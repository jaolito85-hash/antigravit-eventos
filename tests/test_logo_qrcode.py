"""Testes da logo no centro do QR Code das placas.

Contrato protegido, em ordem de gravidade: a janela da logo nunca cobre o que
o leitor usa para achar a grade, o preto da logo continua saindo em K 100%
puro como o resto do arquivo, a janela respeita o teto medido de área, e sem o
arquivo da logo nada muda no que a gráfica recebe.

Nenhum desses defeitos aparece na tela. Aparecem na placa, de noite, com a
tiragem impressa e o público na frente.
"""

import os
import struct
import tempfile
import unittest
import zlib
from unittest import mock

import segno

import logo_qrcode
import pdf_qrcode
import server

# Tabela de alvos de alinhamento do padrão ISO/IEC 18004, para as versões que
# importam aqui mais as duas que costumam quebrar fórmula: a 7, primeira com
# alvo no centro, e a 32, exceção conhecida do passo.
ALVOS_DO_PADRAO = {
    1: [],
    2: [6, 18],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    14: [6, 26, 46, 66],
    15: [6, 26, 48, 70],
    32: [6, 34, 60, 86, 112, 138],
    40: [6, 30, 58, 86, 114, 142, 170],
}


def escreve_png(largura, altura, tipo, pixels, filtro=0, profundidade=8, paleta=None):
    """Monta um PNG mínimo, para testar o leitor contra arquivo de verdade."""

    canais = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[tipo]
    passo = largura * canais
    cru = bytearray()
    anterior = bytearray(passo)
    for y in range(altura):
        linha = bytearray(pixels[y * passo : (y + 1) * passo])
        saida = bytearray(linha)
        for x in range(passo):
            esquerda = linha[x - canais] if x >= canais else 0
            acima = anterior[x]
            diagonal = anterior[x - canais] if x >= canais else 0
            if filtro == 1:
                saida[x] = (linha[x] - esquerda) & 0xFF
            elif filtro == 2:
                saida[x] = (linha[x] - acima) & 0xFF
            elif filtro == 3:
                saida[x] = (linha[x] - ((esquerda + acima) >> 1)) & 0xFF
            elif filtro == 4:
                p = esquerda + acima - diagonal
                pa, pb, pc = abs(p - esquerda), abs(p - acima), abs(p - diagonal)
                if pa <= pb and pa <= pc:
                    perto = esquerda
                elif pb <= pc:
                    perto = acima
                else:
                    perto = diagonal
                saida[x] = (linha[x] - perto) & 0xFF
        cru.append(filtro)
        cru += saida
        anterior = linha

    blocos = logo_qrcode._bloco_png(
        b"IHDR", struct.pack(">IIBBBBB", largura, altura, profundidade, tipo, 0, 0, 0)
    )
    if paleta:
        blocos += logo_qrcode._bloco_png(b"PLTE", paleta)
    blocos += logo_qrcode._bloco_png(b"IDAT", zlib.compress(bytes(cru)))
    return b"\x89PNG\r\n\x1a\n" + blocos + logo_qrcode._bloco_png(b"IEND", b"")


def arquivo_de_logo(dados: bytes) -> str:
    """Grava o PNG num arquivo temporário, porque `prepara` lê do disco."""

    descritor, caminho = tempfile.mkstemp(suffix=".png")
    with os.fdopen(descritor, "wb") as arquivo:
        arquivo.write(dados)
    return caminho


def matriz_de(codigo: str):
    url = f"https://wa.me/554367270996?text=%23SETOR%3A{codigo}"
    qr = segno.make(url, error="h", boost_error=False)
    return [[bool(m) for m in linha] for linha in qr.matrix], qr.version, url


class LeituraDePngTests(unittest.TestCase):
    def test_le_rgb_de_volta_igual_ao_que_entrou(self):
        pixels = bytes([10, 20, 30, 200, 100, 50, 0, 0, 0, 255, 255, 255])
        largura, altura, rgba = logo_qrcode._le_png(escreve_png(2, 2, 2, pixels))
        self.assertEqual((largura, altura), (2, 2))
        self.assertEqual(rgba[0:4], bytes([10, 20, 30, 255]))
        self.assertEqual(rgba[8:12], bytes([0, 0, 0, 255]))

    def test_le_os_cinco_filtros_de_linha(self):
        # Um filtro implementado errado não dá erro: entrega a logo com as
        # linhas deslocadas, e isso passa por decisão de design de quem olhar.
        pixels = bytes(range(4 * 4 * 3))
        for filtro in range(5):
            with self.subTest(filtro=filtro):
                _, _, rgba = logo_qrcode._le_png(
                    escreve_png(4, 4, 2, pixels, filtro=filtro)
                )
                sem_alfa = bytes(
                    valor for n, valor in enumerate(rgba) if n % 4 != 3
                )
                self.assertEqual(sem_alfa, pixels)

    def test_le_cinza_paleta_e_os_dois_com_alfa(self):
        _, _, cinza = logo_qrcode._le_png(escreve_png(2, 1, 0, bytes([7, 200])))
        self.assertEqual(cinza[0:4], bytes([7, 7, 7, 255]))

        _, _, cinza_alfa = logo_qrcode._le_png(
            escreve_png(2, 1, 4, bytes([7, 128, 200, 255]))
        )
        self.assertEqual(cinza_alfa[0:4], bytes([7, 7, 7, 128]))

        paleta = bytes([255, 0, 0, 0, 255, 0])
        _, _, indexada = logo_qrcode._le_png(
            escreve_png(2, 1, 3, bytes([1, 0]), paleta=paleta)
        )
        self.assertEqual(indexada[0:4], bytes([0, 255, 0, 255]))

    def test_recusa_arquivo_que_nao_sabe_ler_em_vez_de_adivinhar(self):
        # Recado claro para a produção vale mais que placa com a logo torta.
        with self.assertRaises(logo_qrcode.LogoInviavel):
            logo_qrcode._le_png(b"nao sou png")
        with self.assertRaises(logo_qrcode.LogoInviavel):
            logo_qrcode._le_png(escreve_png(1, 1, 2, bytes(6), profundidade=16))


class ConversaoParaCmykTests(unittest.TestCase):
    def test_preto_da_logo_sai_em_k_puro(self):
        # É o contrato do arquivo inteiro: preto convertido de RGB vira preto
        # rico, e o desencontro de registro entre as chapas borra a borda.
        cmyk = logo_qrcode._para_cmyk(1, 1, bytearray([0, 0, 0, 255]))
        self.assertEqual(cmyk, bytes([0, 0, 0, 255]))

    def test_branco_nao_leva_tinta_nenhuma(self):
        cmyk = logo_qrcode._para_cmyk(1, 1, bytearray([255, 255, 255, 255]))
        self.assertEqual(cmyk, bytes([0, 0, 0, 0]))

    def test_transparencia_e_resolvida_sobre_branco(self):
        # O arquivo da gráfica não leva transparência: o alfa é resolvido aqui.
        self.assertEqual(
            logo_qrcode._para_cmyk(1, 1, bytearray([0, 0, 0, 0])),
            bytes([0, 0, 0, 0]),
        )
        meio = logo_qrcode._para_cmyk(1, 1, bytearray([0, 0, 0, 128]))
        self.assertEqual(meio[:3], bytes([0, 0, 0]))
        self.assertGreater(meio[3], 100)
        self.assertLess(meio[3], 155)


class AlvosDeAlinhamentoTests(unittest.TestCase):
    def test_bate_com_a_tabela_do_padrao(self):
        for versao, esperado in ALVOS_DO_PADRAO.items():
            with self.subTest(versao=versao):
                self.assertEqual(logo_qrcode._alvos_de_alinhamento(versao), esperado)


class JanelaTests(unittest.TestCase):
    def test_nunca_cobre_alvo_de_canto_trilha_ou_alvo_fora_do_centro(self):
        # O único alvo que a janela pode cobrir é o do centro, e isso está
        # medido. Cobrir qualquer outro é o celular não reconhecer o código.
        for versao in range(2, 21):
            lado = 4 * versao + 17
            with self.subTest(versao=versao):
                janela = logo_qrcode.lado_da_janela(lado, versao, 120.0)
                centro, meio = lado // 2, janela // 2
                for x0, y0, x1, y1 in logo_qrcode._intervalo_proibido(lado, versao):
                    invade = (
                        centro - meio <= x1
                        and centro + meio >= x0
                        and centro - meio <= y1
                        and centro + meio >= y0
                    )
                    self.assertFalse(invade, f"versao {versao} invade {(x0, y0, x1, y1)}")

    def test_e_impar_para_ficar_no_centro_exato(self):
        for versao in range(2, 21):
            lado = 4 * versao + 17
            self.assertEqual(logo_qrcode.lado_da_janela(lado, versao, 120.0) % 2, 1)

    def test_respeita_o_teto_de_area_medido(self):
        for versao in range(2, 21):
            lado = 4 * versao + 17
            janela = logo_qrcode.lado_da_janela(lado, versao, 120.0)
            self.assertLessEqual(janela**2 / lado**2, logo_qrcode.TETO_DE_AREA)

    def test_o_teto_nao_sobe_sem_medicao_nova(self):
        # Medido em 23/09 com leitura real em imagem degradada: até 11% da
        # área a reserva contra mancha ficou igual à do código limpo, e de 14%
        # para cima caiu um terço. Subir esta constante sem repetir a medição
        # entrega placa que lê na mesa e falha no escuro.
        self.assertLessEqual(logo_qrcode.TETO_DE_AREA, 0.11)

    def test_segue_o_alvo_em_milimetros_e_nao_o_numero_de_modulos(self):
        # A logo tem que sair do mesmo tamanho nas 36 placas, que caem em três
        # versões diferentes de QR. Quem monta a arte tem um número só.
        medidas = []
        for codigo in ("LOCKERS", "WC-PISTA-CENTRAL", "PCD-PLATAFORMA-TROPICAL"):
            matriz, versao, _ = matriz_de(codigo)
            lado = len(matriz)
            janela = logo_qrcode.lado_da_janela(lado, versao, 120.0)
            medidas.append(janela * 120.0 / lado)
        for medida in medidas:
            self.assertLessEqual(medida, logo_qrcode.JANELA_ALVO_MM)
            self.assertGreater(medida, logo_qrcode.JANELA_ALVO_MM - 2 * 120.0 / 41)

    def test_placa_grande_demais_recusa_em_vez_de_entregar(self):
        # A janela é medida em milímetros, então numa placa enorme ela não
        # chega a três módulos e a logo sairia menor que a moldura branca.
        # Recusa explicada vale mais que arquivo com a logo do tamanho de um
        # grão, que ninguém percebe olhando o PDF na tela.
        with self.assertRaises(logo_qrcode.LogoInviavel):
            logo_qrcode.lado_da_janela(45, 7, 600.0)
        # E a placa pequena não é caso de recusa: o limite passa a ser a área.
        self.assertGreaterEqual(logo_qrcode.lado_da_janela(45, 7, 40.0), 3)


class AbreJanelaTests(unittest.TestCase):
    def setUp(self):
        self.matriz, self.versao, _ = matriz_de("WC-PISTA-CENTRAL")

    def test_apaga_o_quadrado_central_e_nada_mais(self):
        nova = logo_qrcode.abre_janela(self.matriz, 11)
        lado = len(self.matriz)
        centro = lado // 2
        for y in range(lado):
            for x in range(lado):
                dentro = abs(x - centro) <= 5 and abs(y - centro) <= 5
                if dentro:
                    self.assertFalse(nova[y][x])
                else:
                    self.assertEqual(nova[y][x], self.matriz[y][x])

    def test_nao_mexe_na_matriz_recebida(self):
        antes = [linha[:] for linha in self.matriz]
        logo_qrcode.abre_janela(self.matriz, 11)
        self.assertEqual(self.matriz, antes)


class PdfComLogoTests(unittest.TestCase):
    def setUp(self):
        self.matriz, self.versao, self.url = matriz_de("WC-PISTA-CENTRAL")
        self.modulo = 120 / len(self.matriz)
        self.caminho = arquivo_de_logo(
            escreve_png(2, 2, 2, bytes([0, 0, 0] * 4))
        )
        self.addCleanup(os.unlink, self.caminho)
        self.logo = logo_qrcode.prepara(self.caminho, len(self.matriz), self.versao, 120.0)
        self.com_janela = logo_qrcode.abre_janela(self.matriz, self.logo.lado_modulos)

    def gera(self, logo):
        return pdf_qrcode.pdf_producao(
            self.com_janela if logo else self.matriz,
            self.modulo, 4 * self.modulo, "WC-PISTA-CENTRAL", self.url, "Tuca",
            logo=logo,
        )

    def test_a_imagem_entra_em_cmyk_de_oito_bits_sem_transparencia(self):
        pdf = self.gera(self.logo)
        self.assertIn(b"/ColorSpace /DeviceCMYK", pdf)
        self.assertIn(b"/BitsPerComponent 8", pdf)
        self.assertIn(b"/XObject << /Im1", pdf)
        self.assertNotIn(b"/SMask", pdf)

    def test_os_operadores_de_cor_continuam_so_k_puro_e_branco(self):
        # A logo é imagem, então não pode ter trazido cor nova para o fluxo.
        achadas = {
            c.decode() for c in __import__("re").findall(
                rb"([\d.]+ [\d.]+ [\d.]+ [\d.]+) k", self.gera(self.logo)
            )
        }
        self.assertEqual(achadas, {"0 0 0 1", "0 0 0 0"})

    def test_sem_logo_o_arquivo_nao_ganha_imagem(self):
        pdf = self.gera(None)
        self.assertNotIn(b"/XObject", pdf)
        self.assertNotIn(b"/Image", pdf)

    def prova(self, logo):
        return pdf_qrcode.pdf_prova(
            self.com_janela if logo else self.matriz,
            self.modulo, 4 * self.modulo, "WC-PISTA-CENTRAL",
            "WC Pista Central", self.url, self.versao, "Tuca", logo=logo,
        )

    def test_a_prova_conta_a_janela_para_a_grafica(self):
        prova = self.prova(self.logo)
        self.assertIn("Logo no centro".encode("cp1252"), prova)
        self.assertIn(b"IMPRIMIR EM 100%", prova)

    def test_quem_chama_a_imagem_tambem_a_carrega(self):
        # Este foi um defeito de verdade: a prova desenhava /Im1 sem embutir a
        # imagem. Leitor de PDF ignora referência quebrada sem reclamar, então
        # a gráfica aprovaria a leitura de um código sem logo e imprimiria a
        # tiragem com ela. Vale para todo arquivo que este módulo monta.
        for nome, pdf in (
            ("producao", self.gera(self.logo)),
            ("prova", self.prova(self.logo)),
            ("producao sem logo", self.gera(None)),
            ("prova sem logo", self.prova(None)),
        ):
            with self.subTest(arquivo=nome):
                chama = b"/Im1 Do" in pdf
                declara = b"/XObject << /Im1" in pdf
                embute = b"/Subtype /Image" in pdf
                self.assertEqual(chama, declara, "chamada e recurso divergem")
                self.assertEqual(chama, embute, "chamada sem imagem embutida")

    def test_a_prova_nao_estoura_o_rodape_do_a4(self):
        # O texto cresce conforme o código e o estouro não dá erro nenhum, só
        # corta o rodapé do arquivo que a gráfica recebe.
        prova = pdf_qrcode.pdf_prova(
            self.com_janela, self.modulo, 4 * self.modulo, "WC-PISTA-CENTRAL",
            "WC Pista Central", self.url, self.versao, "Tuca", logo=self.logo,
        )
        alturas = [
            float(c) for c in __import__("re").findall(rb"Tf ([\d.]+) [\d.]+ Td", prova)
        ]
        self.assertTrue(alturas)
        self.assertGreater(min(alturas), 0)


class PreviewDoPainelTests(unittest.TestCase):
    SETORES = [
        {"id": "s1", "code": "WC-PISTA-CENTRAL", "name": "WC Pista Central",
         "metadata": {"zone": "Pista", "group": "Sanitários"}},
    ]

    def setUp(self):
        server.app.config["TESTING"] = True
        self.cliente = server.app.test_client()
        patch = mock.patch.object(server, "_setores_ativos", return_value=self.SETORES)
        patch.start()
        self.addCleanup(patch.stop)
        with self.cliente.session_transaction() as sessao:
            sessao["logged_in"] = True

    def test_sem_login_nao_entrega_preview(self):
        cliente = server.app.test_client()
        resposta = cliente.get("/api/qrcode/WC-PISTA-CENTRAL/preview.png")
        self.assertEqual(resposta.status_code, 302)

    def test_entrega_png_e_nao_deixa_o_navegador_guardar(self):
        # Preview velho em cache é o jeito mais fácil de aprovar a placa
        # errada depois de trocar o arquivo da logo.
        resposta = self.cliente.get("/api/qrcode/WC-PISTA-CENTRAL/preview.png")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.headers["Content-Type"], "image/png")
        self.assertEqual(resposta.headers["Cache-Control"], "no-store")
        self.assertTrue(resposta.data.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_logo_que_nao_cabe_vira_recado_e_nao_arquivo(self):
        with mock.patch.object(
            server, "_logo_do_qr",
            side_effect=logo_qrcode.LogoInviavel("nao cabe"),
        ):
            resposta = self.cliente.get("/api/qrcode/WC-PISTA-CENTRAL/producao.pdf")
        self.assertEqual(resposta.status_code, 422)
        self.assertIn("nao cabe", resposta.get_json()["error"])

    def test_sem_o_arquivo_da_logo_as_placas_saem_como_antes(self):
        with mock.patch.object(server, "ARQUIVO_DA_LOGO", "nao/existe.png"):
            resposta = self.cliente.get("/api/qrcode/WC-PISTA-CENTRAL/producao.pdf")
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn(b"/XObject", resposta.data)


class PngDoPreviewTests(unittest.TestCase):
    def test_desenha_o_codigo_com_a_logo_no_tamanho_da_janela(self):
        matriz, versao, _ = matriz_de("WC-PISTA-CENTRAL")
        caminho = arquivo_de_logo(escreve_png(2, 2, 2, bytes([0, 0, 255] * 4)))
        self.addCleanup(os.unlink, caminho)
        logo = logo_qrcode.prepara(caminho, len(matriz), versao, 120.0)
        png = logo_qrcode.png_do_codigo(
            logo_qrcode.abre_janela(matriz, logo.lado_modulos), logo, px_por_modulo=6
        )
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        largura, altura = struct.unpack(">II", png[16:24])
        esperado = (len(matriz) + 8) * 6
        self.assertEqual((largura, altura), (esperado, esperado))

    def test_sem_logo_desenha_so_o_codigo(self):
        matriz, _, _ = matriz_de("LOCKERS")
        png = logo_qrcode.png_do_codigo(matriz, None, px_por_modulo=4)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
