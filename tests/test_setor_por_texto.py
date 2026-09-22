"""Testes da localização do chamado quando o QR não veio junto.

Contrato protegido: o QR manda sempre que existir, o texto assume quando ele
falta, e nenhum dos dois inventa lugar. O setor decide para onde a operação
anda no meio de 20 mil pessoas, então pino deduzido precisa vir marcado como
deduzido, e empate tem que devolver nada.

O QR só acompanha a primeira mensagem de quem escaneou: áudio nunca carrega a
tag e ninguém volta na placa para escanear de novo. Por isso o texto é o que
localiza a maior parte dos chamados.
"""

import unittest
from unittest import mock

import server
import worker
from worker import process_inbox

from tests.test_worker import FakeStore

SETORES = [
    {"id": "s1", "code": "PALCO-TROPICAL", "name": "Palco Tropical • Principal",
     "metadata": {"zone": "Pista", "group": "Palcos"}},
    {"id": "s2", "code": "WC-FEM-PALCO", "name": "Sanitários Femininos • Palco Tropical",
     "metadata": {"zone": "Pista", "group": "Sanitários"}},
    {"id": "s3", "code": "WC-MASC-PALCO", "name": "Sanitários Masculinos • Palco Tropical",
     "metadata": {"zone": "Pista", "group": "Sanitários"}},
    {"id": "s4", "code": "LOCKERS", "name": "Lockers • Guarda-volumes",
     "metadata": {"zone": "Tropical Lounge", "group": "Atendimento ao Público"}},
    {"id": "s5", "code": "ALAMEDA-GASTRONOMICA", "name": "Alameda Gastronômica • Gramado",
     "metadata": {"zone": "Pista", "group": "Alimentação"}},
]


class IdentificaSetorPorTextoTests(unittest.TestCase):
    """Caminho determinístico, que assume quando a IA está fora do ar."""

    def test_acha_o_setor_citado_pelo_nome(self):
        setor = server.identificar_setor_por_texto(
            "a alameda gastronomica ta com o chao escorregadio", SETORES
        )
        self.assertEqual(setor["code"], "ALAMEDA-GASTRONOMICA")

    def test_apelido_do_publico_chega_no_nome_oficial(self):
        # Ninguém escreve "sanitários": escreve banheiro, e no feminino sem s.
        setor = server.identificar_setor_por_texto(
            "o banheiro feminino do palco tropical ta sem papel", SETORES
        )
        self.assertEqual(setor["code"], "WC-FEM-PALCO")

    def test_armario_acha_os_lockers(self):
        setor = server.identificar_setor_por_texto("o armario nao abre", SETORES)
        self.assertEqual(setor["code"], "LOCKERS")

    def test_empate_devolve_nada_em_vez_de_chutar(self):
        # "banheiro" sozinho cabe em dois setores. Mandar a equipe para o
        # masculino quando o problema é no feminino é pior que não saber.
        self.assertIsNone(
            server.identificar_setor_por_texto("o banheiro ta sem papel", SETORES)
        )

    def test_mensagem_sem_lugar_nenhum_nao_localiza(self):
        self.assertIsNone(server.identificar_setor_por_texto("show incrivel!!!", SETORES))

    def test_sem_setores_cadastrados_nao_quebra(self):
        self.assertIsNone(server.identificar_setor_por_texto("qualquer coisa", []))


class TriagemLocalizaTests(unittest.TestCase):
    def test_setor_sai_por_numero_da_lista(self):
        resposta = mock.MagicMock()
        resposta.choices = [mock.MagicMock()]
        resposta.choices[0].message.content = (
            '{"tipo": "relato", "urgencia": "Urgente", "setor": 4}'
        )
        cliente = mock.MagicMock()
        cliente.chat.completions.create.return_value = resposta
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
            r = server.triar_mensagem_ia("o armario nao abre", setores=SETORES)

        self.assertEqual(r["setor"]["code"], "LOCKERS")

    def test_lista_de_setores_nao_entra_no_prompt_sem_pedir(self):
        # Quem escaneou o QR já está localizado. Mandar os 36 setores no
        # prompt de toda mensagem seria pagar tokens para descobrir o que a
        # placa já disse.
        resposta = mock.MagicMock()
        resposta.choices = [mock.MagicMock()]
        resposta.choices[0].message.content = '{"tipo": "relato", "urgencia": "Urgente"}'
        cliente = mock.MagicMock()
        cliente.chat.completions.create.return_value = resposta
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
            server.triar_mensagem_ia("o armario nao abre", setores=[])

        enviado = cliente.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertNotIn("SETORES DA PLANTA", enviado)


class GrupoDeLugarTests(unittest.TestCase):
    """O corte que o relatório usa: "287 chamados em Sanitários"."""

    def test_empate_entre_banheiros_ainda_diz_que_e_banheiro(self):
        # O caso que motiva o campo existir: não dá para saber QUAL banheiro,
        # mas a reclamação não pode sumir da conta de banheiros.
        texto = "o banheiro ta sem papel"
        self.assertIsNone(server.identificar_setor_por_texto(texto, SETORES))
        self.assertEqual(server.identificar_grupo_por_texto(texto, SETORES), "Sanitários")

    def test_empate_entre_grupos_diferentes_nao_inventa_grupo(self):
        # "Tropical" sozinho cabe no palco e nos dois banheiros dele: tipos de
        # lugar diferentes, então nem o setor nem o grupo dá para cravar.
        texto = "to aqui no tropical"
        self.assertIsNone(server.identificar_setor_por_texto(texto, SETORES))
        self.assertIsNone(server.identificar_grupo_por_texto(texto, SETORES))

    def test_lugar_mais_especifico_ganha_de_quem_so_encosta(self):
        # Citou os dois, mas descreveu um deles inteiro: não é empate.
        texto = "sai do palco tropical e fui pra alameda gastronomica"
        self.assertEqual(server.identificar_grupo_por_texto(texto, SETORES), "Alimentação")

    def test_setor_conhecido_carrega_o_grupo_dele(self):
        self.assertEqual(server.grupo_do_setor(SETORES[3]), "Atendimento ao Público")
        self.assertIsNone(server.grupo_do_setor(None))
        self.assertIsNone(server.grupo_do_setor({"metadata": {}}))

    def test_grupos_saem_da_planta_em_ordem_estavel(self):
        # A IA escolhe por número: lista embaralhada entre duas chamadas faria
        # a mesma mensagem cair em grupos diferentes.
        self.assertEqual(
            server._grupos_ativos(SETORES),
            ["Alimentação", "Atendimento ao Público", "Palcos", "Sanitários"],
        )

    def test_grupo_do_chamado_com_setor_sai_da_planta(self):
        # Não do que foi gravado: mudar a planta tem que corrigir o histórico
        # inteiro, não metade dele.
        with mock.patch.object(server, "_setores_ativos", return_value=SETORES):
            grupo = server.grupo_do_feedback(
                {"sector_id": "s2", "metadata": {"place_group": "Coisa Velha"}}
            )
        self.assertEqual(grupo, "Sanitários")

    def test_grupo_do_chamado_sem_setor_usa_o_que_a_triagem_guardou(self):
        with mock.patch.object(server, "_setores_ativos", return_value=SETORES):
            grupo = server.grupo_do_feedback(
                {"sector_id": None, "metadata": {"place_group": "Sanitários"}}
            )
        self.assertEqual(grupo, "Sanitários")

    def test_chamado_sem_lugar_nenhum_fica_fora_da_conta(self):
        with mock.patch.object(server, "_setores_ativos", return_value=SETORES):
            self.assertIsNone(server.grupo_do_feedback({"sector_id": None, "metadata": {}}))


class WorkerLocalizaTests(unittest.TestCase):
    """O chamado que chega sem QR precisa acender o pino do mesmo jeito."""

    def setUp(self):
        self.mensagem = {
            "id": "m1",
            "provider_message_id": "wamid.1",
            "sender_hash": "hash",
            "content": "o armario que aluguei nao abre",
            "message_type": "text",
        }

    def _processa(self, store, triagem):
        with mock.patch.object(worker, "triar_mensagem", return_value=triagem), \
                mock.patch.object(worker, "_setores_ativos", return_value=SETORES), \
                mock.patch.object(worker, "moderar_texto", return_value={"bloquear": False}), \
                mock.patch.object(worker, "_classify", return_value=("Urgente", "Estrutura & Espaço", "Lockers • Guarda-volumes")), \
                mock.patch.object(worker, "_compose_reply", return_value="ok"):
            process_inbox(store, self.mensagem)

    def test_setor_do_texto_vira_pino_no_mapa(self):
        store = FakeStore()
        self._processa(store, {
            "tipo": "relato", "urgencia": "Urgente", "ficha": None,
            "setor": SETORES[3], "setor_por": "ia", "lugar": "Atendimento ao Público",
        })
        self.assertEqual(store.feedback["sector_id"], "s4")
        self.assertEqual(store.feedback["sector_source"], "ia")
        # Com setor, o grupo sai da planta na hora de somar e não fica
        # congelado no chamado.
        self.assertIsNone(store.feedback["place_group"])

    def test_sem_lugar_nenhum_o_chamado_entra_sem_setor(self):
        store = FakeStore()
        self._processa(store, {
            "tipo": "relato", "urgencia": "Urgente", "ficha": None,
            "setor": None, "setor_por": None, "lugar": None,
        })
        self.assertIsNone(store.feedback["sector_id"])
        self.assertIsNone(store.feedback["sector_source"])
        self.assertIsNone(store.feedback["place_group"])

    def test_sem_setor_mas_com_tipo_de_lugar_entra_na_conta(self):
        # "O banheiro tá sem papel": pino apagado, mas o relatório conta.
        store = FakeStore()
        self._processa(store, {
            "tipo": "relato", "urgencia": "Urgente", "ficha": None,
            "setor": None, "setor_por": None, "lugar": "Sanitários",
        })
        self.assertIsNone(store.feedback["sector_id"])
        self.assertEqual(store.feedback["place_group"], "Sanitários")

    def test_qr_manda_mais_que_a_deducao_do_texto(self):
        # A pessoa escaneou a placa do palco e escreveu sobre o armário. O
        # lugar lido da placa é fato; o do texto é dedução, e não sobrescreve.
        store = FakeStore()
        self.mensagem["content"] = "#SETOR:PALCO\no armario nao abre"
        self._processa(store, {
            "tipo": "relato", "urgencia": "Urgente", "ficha": None,
            "setor": SETORES[3], "setor_por": "ia", "lugar": "Atendimento ao Público",
        })
        self.assertEqual(store.feedback["sector_id"], "sector-id")
        self.assertEqual(store.feedback["sector_source"], "qr")


if __name__ == "__main__":
    unittest.main()
