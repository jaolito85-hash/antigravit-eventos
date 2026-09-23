"""Testes do gerador de QR Code dos setores.

Contrato protegido: o desenho do SVG tem que devolver exatamente a matriz que
o codificador produziu, a zona de silêncio nunca fica abaixo dos 4 módulos da
norma, e a URL é a mesma que o webhook espera receber do participante. Um
módulo desenhado no lugar errado não dá erro em lugar nenhum: só aparece como
placa que não lê, com a tiragem já impressa.
"""

import re
import unittest

import segno

from scripts.generate_qrcodes import monta_svg, monta_url

NUMERO = "554367270996"


def matriz_do_svg(svg: str) -> tuple[list[list[bool]], float]:
    """Refaz a matriz a partir do arquivo, do jeito que um leitor a veria.

    Devolve também a borda em módulos, lida do viewBox.
    """

    view = re.search(r'viewBox="(-?[\d.]+) (-?[\d.]+) ([\d.]+) ([\d.]+)"', svg)
    borda = -float(view.group(1))
    total = float(view.group(3))
    modulos = round(total - 2 * borda)

    matriz = [[False] * modulos for _ in range(modulos)]
    d = re.search(r'id="QR-MODULOS"[^>]*d="([^"]*)"', svg).group(1)
    for x, y, largura in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\3z", d):
        for coluna in range(int(x), int(x) + int(largura)):
            matriz[int(y)][coluna] = True
    return matriz, borda


class TestaDesenhoDoSvg(unittest.TestCase):
    def setUp(self):
        self.url = monta_url(NUMERO, "PALCO-TROPICAL")
        self.qr = segno.make(self.url, error="h", boost_error=False)
        self.matriz = [[bool(m) for m in linha] for linha in self.qr.matrix]

    def svg(self, borda=4.0, modulo_mm=2.93):
        return monta_svg(
            self.matriz,
            borda=borda,
            modulo_mm=modulo_mm,
            codigo="PALCO-TROPICAL",
            url=self.url,
        )

    def test_svg_devolve_a_matriz_do_codificador(self):
        lida, _ = matriz_do_svg(self.svg())
        self.assertEqual(lida, self.matriz)

    def test_borda_fracionaria_nao_desloca_os_modulos(self):
        # A zona de silêncio uniforme em mm gera borda quebrada. Ela vive no
        # viewBox justamente para não empurrar o desenho meio módulo de lado.
        lida, borda = matriz_do_svg(self.svg(borda=4.783))
        self.assertEqual(lida, self.matriz)
        self.assertAlmostEqual(borda, 4.783, places=3)

    def test_zona_de_silencio_nunca_abaixo_da_norma(self):
        _, borda = matriz_do_svg(self.svg())
        self.assertGreaterEqual(borda, 4.0)

    def test_fundo_branco_cobre_o_codigo_inteiro(self):
        svg = self.svg(borda=4.0)
        rect = re.search(
            r'id="ZONA-DE-SILENCIO" x="(-?[\d.]+)" y="(-?[\d.]+)" '
            r'width="([\d.]+)" height="([\d.]+)"',
            svg,
        )
        x, y, largura, altura = (float(g) for g in rect.groups())
        self.assertEqual(x, -4.0)
        self.assertEqual(y, -4.0)
        self.assertEqual(largura, len(self.matriz) + 8)
        self.assertEqual(altura, len(self.matriz) + 8)

    def test_tamanho_em_milimetros_bate_com_o_modulo(self):
        svg = self.svg(borda=4.0, modulo_mm=2.93)
        largura = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
        self.assertAlmostEqual(largura, (len(self.matriz) + 8) * 2.93, places=2)


class TestaUrlDoSetor(unittest.TestCase):
    def test_url_leva_a_etiqueta_e_a_frase_da_placa(self):
        from urllib.parse import parse_qs, urlparse

        from server import TEXTO_DA_PLACA

        url = monta_url(NUMERO, "WC-PISTA-NORTE-1")
        self.assertTrue(url.startswith(f"https://wa.me/{NUMERO}?text="))
        texto = parse_qs(urlparse(url).query)["text"][0]
        self.assertIn("#SETOR:WC-PISTA-NORTE-1", texto)
        self.assertIn(TEXTO_DA_PLACA, texto)

    def test_o_servidor_le_de_volta_o_que_o_qr_manda(self):
        """Usa o parser do server, e não uma cópia dele.

        A versão antiga deste teste repetia o regex aqui dentro. Quando o
        server passou a aceitar a etiqueta em qualquer posição da mensagem, a
        cópia continuou exigindo que ela viesse no começo: o teste passava a
        reprovar justamente a mudança que as placas precisavam.
        """

        from urllib.parse import parse_qs, urlparse

        from server import _extract_sector

        texto = parse_qs(urlparse(monta_url(NUMERO, "PCD-PLATAFORMA-TROPICAL")).query)["text"][0]
        codigo, conteudo = _extract_sector(texto)
        self.assertEqual(codigo, "PCD-PLATAFORMA-TROPICAL")
        self.assertEqual(conteudo, "", "a frase da placa não pode virar chamado")

    def test_correcao_h_sobra_folga_para_o_verniz(self):
        # H recupera 30%. Se algum código de setor crescer a ponto de derrubar
        # o nível, o teste avisa antes de a gráfica imprimir.
        qr = segno.make(monta_url(NUMERO, "SAIDA-LOUNGE-EXCURSOES"), error="h", boost_error=False)
        self.assertEqual(qr.error, "H")


if __name__ == "__main__":
    unittest.main()
