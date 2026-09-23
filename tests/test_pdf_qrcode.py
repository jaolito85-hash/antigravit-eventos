"""Testes do arquivo de QR Code que vai para a gráfica.

Contrato protegido: o preto é K 100% puro, a página tem o tamanho real em
milímetros e o endpoint do painel não entrega arquivo para quem não está
logado. Preto convertido de RGB vira preto rico, com tinta nos quatro canais,
e em QR Code qualquer desencontro de registro entre as chapas borra a borda do
módulo e o leitor perde o código. Isso não aparece na tela: aparece na placa,
com a tiragem já impressa.
"""

import re
import unittest
from unittest import mock

import segno

import pdf_qrcode
import server

SETORES = [
    {"id": "s1", "code": "PALCO-TROPICAL", "name": "Palco Tropical • Principal",
     "metadata": {"zone": "Pista", "group": "Palcos"}},
    {"id": "s2", "code": "SAIDA-LOUNGE-EXCURSOES", "name": "Saída • Excursões",
     "metadata": {"zone": "Tropical Lounge", "group": "Entradas e Acessos"}},
]
URL = "https://wa.me/554367270996?text=%23SETOR%3APALCO-TROPICAL"


def matriz(url=URL):
    qr = segno.make(url, error="h", boost_error=False)
    return [[bool(m) for m in linha] for linha in qr.matrix], qr.version


def cores(pdf: bytes) -> set[str]:
    """Operadores de cor CMYK usados no arquivo."""

    return {c.decode() for c in re.findall(rb"([\d.]+ [\d.]+ [\d.]+ [\d.]+) k", pdf)}


def pagina_mm(pdf: bytes) -> tuple[float, float]:
    achado = re.search(rb"/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", pdf)
    return (
        float(achado.group(1)) / 72 * 25.4,
        float(achado.group(2)) / 72 * 25.4,
    )


class PdfDeProducaoTests(unittest.TestCase):
    def setUp(self):
        self.matriz, self.versao = matriz()
        self.modulo = 120 / len(self.matriz)
        self.zona = 4 * self.modulo
        self.pdf = pdf_qrcode.pdf_producao(
            self.matriz, self.modulo, self.zona, "PALCO-TROPICAL", URL, "Tuca"
        )

    def test_e_um_pdf_valido(self):
        self.assertTrue(self.pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", self.pdf)
        self.assertIn(b"xref", self.pdf)

    def test_preto_e_k_puro_e_nao_preto_rico(self):
        # Esta é a razão de o arquivo não ser gerado no navegador.
        self.assertEqual(cores(self.pdf), {"0 0 0 1", "0 0 0 0"})

    def test_pagina_tem_o_tamanho_real_do_bloco(self):
        largura, altura = pagina_mm(self.pdf)
        esperado = len(self.matriz) * self.modulo + 2 * self.zona
        self.assertAlmostEqual(largura, esperado, places=2)
        self.assertAlmostEqual(altura, esperado, places=2)

    def test_nao_desenha_texto(self):
        # Arquivo de produção não leva nada além do código: qualquer texto
        # aqui acabaria impresso dentro da arte.
        self.assertNotIn(b" Tj", self.pdf)

    def test_um_retangulo_por_faixa_de_modulos_vizinhos(self):
        # Faixa em vez de quadrado solto elimina a fresta de um micron que o
        # RIP às vezes deixa entre dois módulos apenas encostados.
        faixas = list(pdf_qrcode._faixas(self.matriz))
        escuros = sum(largura for _, _, largura in faixas)
        self.assertEqual(escuros, sum(sum(linha) for linha in self.matriz))
        self.assertLess(len(faixas), escuros)


class PdfDeProvaTests(unittest.TestCase):
    def setUp(self):
        self.matriz, self.versao = matriz()
        self.modulo = 120 / len(self.matriz)
        self.pdf = pdf_qrcode.pdf_prova(
            self.matriz, self.modulo, 4 * self.modulo, "PALCO-TROPICAL",
            "Palco Tropical • Principal", URL, self.versao, "Tuca",
        )

    def test_sai_em_a4_para_imprimir_em_qualquer_lugar(self):
        largura, altura = pagina_mm(self.pdf)
        self.assertAlmostEqual(largura, 210, places=0)
        self.assertAlmostEqual(altura, 297, places=0)

    def test_avisa_para_nao_ajustar_a_pagina(self):
        # O erro mais comum não é de arquivo: é imprimir com "ajustar à
        # página" e o código sair fora de escala.
        self.assertIn(b"IMPRIMIR EM 100%", self.pdf)
        self.assertIn(b"100 mm exatos", self.pdf)

    def test_usa_fonte_base_que_existe_em_qualquer_rip(self):
        self.assertIn(b"/BaseFont /Helvetica", self.pdf)
        self.assertNotIn(b"/FontFile", self.pdf)

    def test_acento_nao_vira_lixo(self):
        # WinAnsi, como a fonte declara: "IMPRESSÃO" com Ã de verdade.
        self.assertIn("IMPRESSÃO".encode("cp1252"), self.pdf)


class EndpointDoPainelTests(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.cliente = server.app.test_client()
        self.patch = mock.patch.object(server, "_setores_ativos", return_value=SETORES)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        # Sem logo, à força: o que esta classe protege é o arquivo base da
        # gráfica, e ele não pode passar a depender de alguém ter deixado ou
        # não um PNG na pasta static. A logo tem os testes dela em
        # test_logo_qrcode.py.
        sem_logo = mock.patch.object(server, "ARQUIVO_DA_LOGO", "")
        sem_logo.start()
        self.addCleanup(sem_logo.stop)

    def logado(self):
        with self.cliente.session_transaction() as sessao:
            sessao["logged_in"] = True

    def test_sem_login_nao_entrega_arquivo(self):
        resposta = self.cliente.get("/api/qrcode/PALCO-TROPICAL/producao.pdf")
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login", resposta.headers["Location"])

    def test_entrega_o_pdf_de_producao_com_nome_do_setor(self):
        self.logado()
        resposta = self.cliente.get("/api/qrcode/PALCO-TROPICAL/producao.pdf")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.headers["Content-Type"], "application/pdf")
        # O nome do arquivo carrega o código porque trocar duas placas de
        # lugar na instalação não dá erro visível em lugar nenhum.
        self.assertIn("TUCA_QR_PALCO-TROPICAL_PRODUCAO.pdf", resposta.headers["Content-Disposition"])
        self.assertEqual(cores(resposta.data), {"0 0 0 1", "0 0 0 0"})

    def test_margem_branca_e_a_mesma_para_todos_os_setores(self):
        # Os códigos têm comprimentos diferentes e caem em versões diferentes
        # de QR. Se cada placa saísse com um total diferente, o designer teria
        # 36 medidas para montar a arte.
        self.logado()
        medidas = set()
        for setor in SETORES:
            resposta = self.cliente.get(f"/api/qrcode/{setor['code']}/producao.pdf")
            medidas.add(round(pagina_mm(resposta.data)[0], 2))
        self.assertEqual(len(medidas), 1, f"medidas divergentes: {medidas}")

    def test_setor_inativo_nao_gera_arquivo(self):
        self.logado()
        resposta = self.cliente.get("/api/qrcode/NAO-EXISTE/producao.pdf")
        self.assertEqual(resposta.status_code, 404)

    def test_tipo_desconhecido_nao_gera_arquivo(self):
        self.logado()
        self.assertEqual(
            self.cliente.get("/api/qrcode/PALCO-TROPICAL/qualquer.pdf").status_code, 404
        )

    def test_sem_segno_o_painel_avisa_em_vez_de_quebrar(self):
        # Se a dependência faltar no container, o botão para de funcionar mas
        # o webhook do festival continua de pé.
        self.logado()
        with mock.patch.object(server, "segno", None):
            resposta = self.cliente.get("/api/qrcode/PALCO-TROPICAL/producao.pdf")
        self.assertEqual(resposta.status_code, 503)


if __name__ == "__main__":
    unittest.main()
