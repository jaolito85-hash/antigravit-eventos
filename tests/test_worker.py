"""Testes do worker da API oficial da Meta."""

import unittest
from unittest import mock

import protecao
import server
import worker
from meta_whatsapp import Media
from worker import _extract_sector, process_inbox


class FakeStore:
    def __init__(self, mode="bot", count=1, audios=0, blocked=0, per_minute=0):
        self.feedback = None
        self.response = None
        self.responses = []
        self.finished = None
        self.failed = None
        self.blocked_reason = None
        self.mode = mode
        self.count = count
        self.audios = audios
        self.blocked = blocked
        self.per_minute = per_minute
        self.rate_checked = False

    def claim_inbox(self, _message):
        return True

    def conversation_mode(self, _sender_hash):
        return self.mode

    def recent_sender_count(self, _sender_hash, minutes=10):
        self.rate_checked = True
        return self.count

    def recent_sender_audio_count(self, _sender_hash, minutes=60):
        return self.audios

    def recent_blocked_count(self, _sender_hash, minutes=10):
        return self.blocked

    def recent_event_count(self, minutes=1):
        return self.per_minute

    def sector_by_code(self, code):
        if code == "PALCO":
            return {
                "id": "sector-id",
                "name": "Palco Tropical",
                "metadata": {"cta": "Como está o som por aí?"},
            }
        return None

    def create_feedback(self, **kwargs):
        self.feedback = kwargs
        return 42

    def enqueue_text(self, message, content, feedback_id=None):
        self.response = (message, content, feedback_id)
        self.responses.append(content)

    def finish_inbox(self, _message_id, status="processed"):
        self.finished = status

    def block_inbox(self, _message_id, reason):
        self.finished = "ignored"
        self.blocked_reason = reason

    def fail_inbox(self, message, error):
        self.failed = (message, error)


def _message(**overrides):
    """Mensagem de entrada padrão com os campos que o worker consome."""

    base = {
        "id": "inbox-id",
        "sender": "5543999999999",
        "sender_hash": "hash",
        "channel_account_id": "phone-id",
        "message_type": "text",
        "content": "#SETOR:PALCO\nBanheiro está sujo",
        "media_id": None,
        "attempts": 0,
    }
    base.update(overrides)
    return base


LIBERADO = {"bloquear": False, "motivo": None, "origem": "teste"}
BLOQUEADO = {"bloquear": True, "motivo": "sexual", "origem": "teste"}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        # Nenhum teste toca a rede. A decisão do bot mora no server, então é
        # lá que a resposta criativa e o enriquecimento de categoria ficam
        # desligados, sobrando o texto determinístico.
        for target in ("generate_ai_response", "classificar_com_ia"):
            patcher = mock.patch.object(server, target, lambda *a, **k: None)
            patcher.start()
            self.addCleanup(patcher.stop)

        # A conversa por IA também sai do caminho. O patch vai no worker, que é
        # quem chama a função: o nome foi importado para o namespace dele.
        smalltalk = mock.patch.object(
            worker, "compose_smalltalk", lambda _c: "BOAS-VINDAS DO TUCA"
        )
        smalltalk.start()
        self.addCleanup(smalltalk.stop)

        # A moderação da OpenAI libera tudo por padrão; cada teste de bloqueio
        # troca isso. O .env tem chave real, então sem o patch iria à rede.
        moderacao = mock.patch.object(worker, "moderar_texto", return_value=LIBERADO)
        self.moderar = moderacao.start()
        self.addCleanup(moderacao.stop)

    def test_extract_sector_marker(self):
        code, content = _extract_sector("#SETOR:PALCO\nBanheiro sujo")
        self.assertEqual(code, "PALCO")
        self.assertEqual(content, "Banheiro sujo")

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_falta_de_estoque_vai_para_a_ia(self, mock_ia):
        store = FakeStore()

        process_inbox(store, _message(content="Falta cerveja no bar do camarote"))

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        mock_ia.assert_called_once()
        self.assertEqual(mock_ia.call_args.args[0], "Falta cerveja no bar do camarote")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.feedback["category"], "Alimentação & Bebidas")
        self.assertIn("destacamos", store.response[1])

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_frase_incomum_ainda_passa_pela_ia(self, mock_ia):
        store = FakeStore()
        content = "no camarote ninguem consegue mais beber o que pediu"

        process_inbox(store, _message(content=content))

        mock_ia.assert_called_once()
        self.assertEqual(mock_ia.call_args.args[0], content)
        self.assertEqual(store.feedback["urgency"], "Urgente")

    @mock.patch("server.triar_mensagem_ia", return_value=None)
    def test_palavras_chave_assumem_quando_a_ia_cai(self, _mock_ia):
        """Com a OpenAI fora do ar, um relato de falta não pode virar Neutro."""

        store = FakeStore()

        process_inbox(store, _message(content="Falta cerveja no bar do camarote"))

        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["urgency"], "Urgente")

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_processa_texto_com_setor(self, _mock_ia):
        store = FakeStore()

        process_inbox(store, _message())

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["region"], "Palco Tropical")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.response[2], 42)

    def test_audio_sem_media_id_pede_texto(self):
        store = FakeStore()

        process_inbox(store, _message(message_type="audio", content=None))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("texto", store.response[1])

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_audio_com_media_id_e_transcrito(self, _mock_ia):
        store = FakeStore()

        with mock.patch.object(
            worker, "_transcribe_inbox_audio",
            lambda _m: {"texto": "fila enorme no bar", "motivo": None},
        ):
            process_inbox(
                store,
                _message(message_type="audio", content=None, media_id="media-1"),
            )

        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertIn("áudio", store.response[1])

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "conversa", "urgencia": "Neutro"})
    def test_conversa_recebe_resposta_sem_criar_card(self, _mock_ia):
        """A IA disse que e conversa: responde e nao entra na fila de trabalho."""

        store = FakeStore()

        process_inbox(store, _message(content="Oi!"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("TUCA", store.response[1])

    @mock.patch("server.triar_mensagem_ia", return_value=None)
    def test_scan_de_qr_sem_texto_responde_o_convite_do_setor(self, _mock_ia):
        store = FakeStore()

        process_inbox(store, _message(content="#SETOR:PALCO\n"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("Palco Tropical", store.response[1])
        self.assertIn("som", store.response[1])

    # ------------------------------------------------------------------
    # Atendimento humano: o bot registra e cala a boca
    # ------------------------------------------------------------------

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_operador_no_comando_registra_sem_responder(self, _mock_ia):
        """Com o operador na conversa, o chamado entra mas nada e enviado."""

        store = FakeStore(mode="human")

        process_inbox(store, _message(content="a fila do bar travou de novo"))

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        self.assertIsNotNone(store.feedback)
        self.assertEqual(store.feedback["urgency"], "Urgente")
        # O participante esta falando com uma pessoa: nada de resposta do bot.
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "conversa", "urgencia": "Neutro"})
    def test_operador_no_comando_nao_manda_boas_vindas(self, _mock_ia):
        store = FakeStore(mode="human")

        process_inbox(store, _message(content="oi"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia", return_value=None)
    def test_operador_no_comando_nao_manda_convite_do_setor(self, _mock_ia):
        store = FakeStore(mode="human")

        conteudo = "#SETOR:PALCO" + chr(10)
        process_inbox(store, _message(content=conteudo))

        self.assertIsNone(store.feedback)
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Positivo"})
    def test_operador_no_comando_ignora_o_limite_de_mensagens(self, _mock_ia):
        """Quem esta conversando com a equipe pode escrever a vontade."""

        store = FakeStore(mode="human", count=99)

        process_inbox(store, _message(content="obrigado pela ajuda de voces"))

        self.assertEqual(store.finished, "processed")
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_bot_volta_a_responder_quando_devolvem_a_conversa(self, _mock_ia):
        store = FakeStore(mode="bot")

        process_inbox(store, _message(content="a fila do bar travou de novo"))

        self.assertEqual(store.finished, "processed")
        self.assertIsNotNone(store.response)
        self.assertIn("destacamos", store.response[1])

    def test_video_pede_texto_ou_audio(self):
        store = FakeStore()

        process_inbox(store, _message(message_type="video", content=None))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("texto", store.response[1])

    # ------------------------------------------------------------------
    # Proteções: tipo, degraus por número, áudio, moderação e inundação
    # ------------------------------------------------------------------

    def test_reacao_e_tipo_desconhecido_ficam_em_silencio(self):
        """Joinha na resposta do Tuca nao pode voltar como bronca."""

        store = FakeStore()

        process_inbox(store, _message(message_type="unknown", content=None))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertEqual(store.responses, [])

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_mensagem_11_avisa_uma_vez_e_registra_sem_responder(self, _mock_ia):
        store = FakeStore(count=protecao.LIMITE_RESPONDER + 1)

        process_inbox(store, _message(content="Falta cerveja no bar"))

        self.assertEqual(store.finished, "processed")
        self.assertIsNotNone(store.feedback)
        self.assertEqual(store.responses, [protecao.AVISO_MUITAS_MENSAGENS])

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_mensagem_12_registra_em_silencio(self, _mock_ia):
        store = FakeStore(count=protecao.LIMITE_RESPONDER + 2)

        process_inbox(store, _message(content="Falta cerveja no bar"))

        self.assertIsNotNone(store.feedback)
        self.assertEqual(store.responses, [])

    def test_mensagem_31_avisa_o_limite_e_descarta(self):
        store = FakeStore(count=protecao.LIMITE_REGISTRAR + 1)

        process_inbox(store, _message(content="Falta cerveja no bar"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.blocked_reason, "limite de mensagens")
        self.assertEqual(store.responses, [protecao.AVISO_LIMITE_ATINGIDO])
        self.moderar.assert_not_called()

    def test_mensagem_32_descarta_em_silencio(self):
        store = FakeStore(count=protecao.LIMITE_REGISTRAR + 2)

        process_inbox(store, _message(content="Falta cerveja no bar"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.responses, [])

    def test_quarto_audio_na_hora_e_recusado_com_motivo(self):
        store = FakeStore(audios=protecao.AUDIO_MAX_POR_JANELA + 1)

        with mock.patch.object(worker, "_transcribe_inbox_audio") as transcrever:
            process_inbox(store, _message(message_type="audio", content=None, media_id="m"))

        transcrever.assert_not_called()
        self.assertEqual(store.blocked_reason, "cota de audio")
        self.assertEqual(store.responses, [protecao.AVISO_COTA_AUDIO])

    def test_audio_longo_avisa_o_limite_de_1_minuto(self):
        store = FakeStore(audios=1)

        with mock.patch.object(
            worker, "_transcribe_inbox_audio",
            lambda _m: {"texto": None, "motivo": "muito_longo"},
        ):
            process_inbox(store, _message(message_type="audio", content=None, media_id="m"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.blocked_reason, "audio muito_longo")
        self.assertEqual(store.responses, [protecao.AVISO_AUDIO_LONGO])

    def test_audio_so_com_musica_pede_de_novo(self):
        store = FakeStore(audios=1)

        with mock.patch.object(
            worker, "_transcribe_inbox_audio",
            lambda _m: {"texto": None, "motivo": "sem_fala"},
        ):
            process_inbox(store, _message(message_type="audio", content=None, media_id="m"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertEqual(store.responses, [protecao.AVISO_SEM_FALA])

    def test_duracao_e_medida_antes_de_pagar_a_transcricao(self):
        """Audio de 70s nao chega ao Whisper: o proprio arquivo diz a duracao."""

        media = Media(content=b"OggS...", mime_type="audio/ogg", file_size=10, status="ok")
        with mock.patch.object(worker, "fetch_media", return_value=media), \
                mock.patch.object(worker, "duracao_ogg_opus", return_value=70.0), \
                mock.patch.object(worker, "transcribe_audio") as whisper:
            resultado = worker._transcribe_inbox_audio(_message(media_id="m"))

        whisper.assert_not_called()
        self.assertEqual(resultado["motivo"], "muito_longo")

    def test_audio_grande_demais_nem_e_baixado(self):
        media = Media(content=None, mime_type="audio/ogg", file_size=9_000_000, status="muito_grande")
        store = FakeStore(audios=1)

        with mock.patch.object(worker, "fetch_media", return_value=media):
            process_inbox(store, _message(message_type="audio", content=None, media_id="m"))

        self.assertEqual(store.blocked_reason, "audio muito_grande")
        self.assertEqual(store.responses, [protecao.AVISO_AUDIO_GRANDE])

    def test_conteudo_ofensivo_nao_vira_chamado(self):
        store = FakeStore()
        self.moderar.return_value = BLOQUEADO

        with mock.patch("server.triar_mensagem_ia") as triagem:
            process_inbox(store, _message(content="texto que a moderacao reprova"))

        triagem.assert_not_called()
        self.assertIsNone(store.feedback)
        self.assertEqual(store.blocked_reason, "conteudo sexual")
        self.assertEqual(store.responses, [protecao.AVISO_CONTEUDO_BLOQUEADO])

    def test_terceiro_strike_avisa_que_silenciou(self):
        store = FakeStore(blocked=protecao.STRIKES_PARA_SILENCIAR - 1)
        self.moderar.return_value = BLOQUEADO

        process_inbox(store, _message(content="de novo"))

        self.assertEqual(store.responses, [protecao.AVISO_SILENCIADO])

    def test_remetente_silenciado_nao_gera_nada(self):
        store = FakeStore(blocked=protecao.STRIKES_PARA_SILENCIAR)

        process_inbox(store, _message(content="Falta cerveja no bar"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.blocked_reason, "silenciado por strikes")
        self.assertEqual(store.responses, [])
        self.moderar.assert_not_called()

    def test_atendimento_humano_tambem_bloqueia_conteudo_ofensivo(self):
        """O operador continua vendo a conversa, mas nao nasce chamado."""

        store = FakeStore(mode="human")
        self.moderar.return_value = BLOQUEADO

        process_inbox(store, _message(content="texto que a moderacao reprova"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.responses, [])

    def test_inundacao_desliga_a_ia_mas_registra_o_chamado(self):
        store = FakeStore(per_minute=protecao.FLOOD_GLOBAL_POR_MINUTO + 1)

        with mock.patch("server.triar_mensagem_ia") as triagem, \
                mock.patch.object(server, "generate_ai_response") as criativa:
            process_inbox(store, _message(content="Falta cerveja no bar"))

        triagem.assert_not_called()
        criativa.assert_not_called()
        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertIn("destacamos", store.response[1])


if __name__ == "__main__":
    unittest.main()
