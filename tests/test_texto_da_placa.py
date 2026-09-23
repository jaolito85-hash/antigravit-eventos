"""A placa manda uma frase junto com a etiqueta, e nada disso vira chamado.

Pedido do Lucas em 23/09/2026: só a etiqueta na mensagem pronta "fica bem
estranho" para quem escaneia. A frase resolve isso e cria dois riscos que estes
testes existem para segurar:

1. a etiqueta deixou de ser a primeira coisa da mensagem, e o roteamento inteiro
   dependia de ela estar no começo;
2. a frase é texto NOSSO dentro da mensagem da pessoa, e sem limpeza ela viraria
   o conteúdo do chamado, com a triagem classificando o que nós escrevemos.
"""

import unittest

import server
from server import TEXTO_DA_PLACA, _extract_sector, texto_do_qr


class TextoDoQrTests(unittest.TestCase):
    def test_a_etiqueta_esta_na_mensagem_pronta(self):
        texto = texto_do_qr("AMB-CENTRAL-PISTA")
        self.assertIn("#SETOR:AMB-CENTRAL-PISTA", texto)
        self.assertIn(TEXTO_DA_PLACA, texto)

    def test_o_que_a_placa_manda_volta_como_setor_e_nada_mais(self):
        """O caminho que roda 65 vezes no festival: escanear e enviar."""

        code, conteudo = _extract_sector(texto_do_qr("AMB-CENTRAL-PISTA"))
        self.assertEqual(code, "AMB-CENTRAL-PISTA")
        self.assertEqual(conteudo, "")

    def test_todos_os_setores_da_planta_voltam_inteiros(self):
        """Código com número, hífen e nome longo continuam sendo lidos."""

        for codigo in ("WC-FEM-HYPE-PISTA", "BAR-DRINK-TROPICAL-LOUNGE-01",
                       "DESCANSO-DELEGA-HYPE-BACKSTAGE", "LED-NY-LOUNGE"):
            with self.subTest(codigo=codigo):
                lido, conteudo = _extract_sector(texto_do_qr(codigo))
                self.assertEqual(lido, codigo)
                self.assertEqual(conteudo, "")


class ExtracaoTolerantesTests(unittest.TestCase):
    def test_relato_escrito_depois_da_mensagem_pronta(self):
        """A pessoa completa a mensagem sem apagar o que já estava lá."""

        code, conteudo = _extract_sector(
            f"{TEXTO_DA_PLACA} #SETOR:WC-FEM-HYPE-PISTA acabou o papel"
        )
        self.assertEqual(code, "WC-FEM-HYPE-PISTA")
        self.assertEqual(conteudo, "acabou o papel")

    def test_etiqueta_sozinha_continua_valendo(self):
        """Quem apagou a frase, ou escaneou placa antiga, não pode perder o setor."""

        code, conteudo = _extract_sector("#SETOR:BAR-HYPE-PISTA fila enorme")
        self.assertEqual(code, "BAR-HYPE-PISTA")
        self.assertEqual(conteudo, "fila enorme")

    def test_etiqueta_no_fim_da_mensagem(self):
        code, conteudo = _extract_sector("tem uma pessoa passando mal #SETOR:AMB-CENTRAL-PISTA")
        self.assertEqual(code, "AMB-CENTRAL-PISTA")
        self.assertEqual(conteudo, "tem uma pessoa passando mal")

    def test_minusculas_do_teclado_do_celular(self):
        code, _ = _extract_sector("#setor:bar-hype-pista")
        self.assertEqual(code, "BAR-HYPE-PISTA")

    def test_mensagem_sem_etiqueta_fica_intacta(self):
        code, conteudo = _extract_sector("o banheiro tá sem papel")
        self.assertIsNone(code)
        self.assertEqual(conteudo, "o banheiro tá sem papel")

    def test_frase_da_placa_nao_apaga_texto_parecido_da_pessoa(self):
        """Só a frase inteira sai. Uma palavra dela solta é fala da pessoa."""

        code, conteudo = _extract_sector("#SETOR:BAR-HYPE-PISTA envie alguém aqui")
        self.assertEqual(code, "BAR-HYPE-PISTA")
        self.assertEqual(conteudo, "envie alguém aqui")


class NadaDeChamadoFantasmaTests(unittest.TestCase):
    def test_a_frase_nao_chega_na_triagem(self):
        """Sem limpeza, o Tuca abriria chamado com o texto que nós escrevemos."""

        _, conteudo = _extract_sector(texto_do_qr("PRACA-CENTRAL-PISTA"))
        self.assertNotIn("Tuca", conteudo)
        self.assertNotIn("Envie", conteudo)
        self.assertLess(len(conteudo), 3, "conteúdo vazio cai no convite do setor")


if __name__ == "__main__":
    unittest.main()
