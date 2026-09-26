"""Horários são comparados com a grade oficial, inclusive na madrugada."""
import unittest
from datetime import datetime
from tuca_programacao import schedule_reply

GUIDE={'kind':'lineup','active':True,'answer':'''PALCO TROPICAL
20:25 às 21:20 | Luísa Sonza
21:25 às 22:25 | BK
22:30 às 23:25 | Livinho
23:30 às 00:25 | Veigh
00:30 às 01:30 | Matuê
PALCO HYPE
20:30 | D-Nox
22:00 | Illusionize
00:00 | Vegas
04:00 | Fim do evento'''}
START=datetime.fromisoformat('2026-09-26T15:30:00-03:00')

class ProgramacaoTests(unittest.TestCase):
    def reply(self,text,when,entries=None):
        return schedule_reply(text,[{'content':'quem toca agora?'},{'content':text}],entries or [GUIDE],START,datetime.fromisoformat(when))

    def test_agora_nao_inventa_horario(self):
        reply=self.reply('quem toca agora?','2026-09-26T21:30:00-03:00')
        self.assertIn('BK, às 21:25',reply)
        self.assertIn('D-Nox',reply)
        self.assertNotIn('Luísa',reply)

    def test_depois_nunca_e_show_passado(self):
        reply=self.reply('e depois?','2026-09-26T21:30:00-03:00')
        self.assertIn('Livinho, às 22:30',reply)
        self.assertIn('Illusionize, às 22:00',reply)
        self.assertNotIn('Luísa',reply)

    def test_virada_da_meia_noite(self):
        reply=self.reply('quem toca agora?','2026-09-27T00:10:00-03:00')
        self.assertIn('Veigh',reply)
        self.assertIn('Vegas',reply)
        self.assertNotIn('BK',reply)

    def test_proximo_na_madrugada(self):
        reply=self.reply('e depois?','2026-09-27T00:10:00-03:00')
        self.assertIn('Matuê, às 00:30',reply)
        self.assertNotIn('Luísa',reply)

    def test_antes_do_evento_nao_diz_que_esta_tocando(self):
        reply=self.reply('quem toca agora?','2026-09-25T21:30:00-03:00')
        self.assertIn('Próximos shows previstos',reply)
        self.assertIn('Luísa',reply)

    def test_depois_do_evento_nao_reusa_grade_do_dia_seguinte(self):
        reply=self.reply('quem toca agora?','2026-09-28T21:30:00-03:00')
        self.assertIn('sem show neste horário',reply)
        self.assertNotIn('BK',reply)

    def test_grade_conflitante_nao_escolhe_horario(self):
        other=dict(GUIDE,answer=GUIDE['answer'].replace('21:25 às 22:25 | BK','21:25 às 22:25 | Outro'))
        self.assertIn('divergentes',self.reply('quem toca agora?','2026-09-26T21:30:00-03:00',[GUIDE,other]))

    def test_nao_intercepta_conversa_sem_programacao(self):
        self.assertIsNone(schedule_reply('e depois?',[{'content':'tem seda?'},{'content':'e depois?'}],[GUIDE],START,START))

    def test_pergunta_de_artista_nao_vira_agora(self):
        self.assertIsNone(self.reply('que horas toca Matuê?','2026-09-26T21:30:00-03:00'))

    def test_pergunta_de_palco_preserva_banner(self):
        self.assertIsNone(self.reply('quem toca no hype?','2026-09-26T21:30:00-03:00'))

    def test_agora_no_palco_continua_deterministico(self):
        reply=self.reply('quem toca no hype agora?','2026-09-26T21:30:00-03:00')
        self.assertIn('D-Nox',reply)
        self.assertNotIn('BK',reply)
