# Ensaio do agente antes do festival

O Tuca entra pra valer em 26 de setembro de 2026. Até lá, o agente do Telegram
fica no ar avisando e a rotina da nuvem fica **pausada**: nada de PR antes do
ensaio da rodada 3. Este roteiro tem três rodadas. Cada uma termina com uma
lista do que precisa ter acontecido; se algo não aconteceu, é bug ou ajuste, e
se resolve antes de seguir.

Quem participa: João, Lucas e pelo menos uma pessoa da sala de controle, cada
um com o próprio celular e o WhatsApp.

## Rodada 1: o agente responde (feita em 20/09)

O que já passou em 20/09, no grupo do Telegram:

- [x] `/id` respondeu e o grupo entrou em `TELEGRAM_CHAT_IDS`
- [x] `/saude` respondeu com app, worker, Meta e IA
- [x] A varredura achou dois problemas reais e avisou uma vez cada
- [x] Um deles abriu a issue #4 no GitHub (fechada: erro 131047 é a janela de 24h do WhatsApp, não é bug)

O que falta desta rodada, e qualquer um faz sozinho, a qualquer hora:

- [ ] `/resumo`, `/criticos`, `/respostas`, `/erros`, `/alertas` respondem com números do banco
- [ ] Pergunta livre no grupo, mencionando o bot: "@guardiaotuca_bot como está o festival hoje?" e "os últimos 5 chamados foram bem respondidos?"
- [ ] Apertar **Ignorar** em um alerta: ele muda de texto, não volta por 6h, e aparece como ignorado em `/alertas`

## Rodada 2: fogo controlado, com WhatsApp real (terça 22 ou quarta 23, 1 hora)

Três celulares, o painel aberto na sala de controle, o grupo do Telegram na mão.

**Crítico em um minuto.** Alguém escaneia o QR de um setor e manda "tem uma
briga aqui perto do palco". Esperado: 🚨 no grupo em até 1 minuto, com o número
do chamado e o setor, e o card no painel.

**Crítico sem atendimento.** Deixe esse chamado aberto. Em 10 minutos, na
próxima varredura, chega "Chamados críticos sem ninguém atender". Aí alguém
resolve no painel. Na varredura seguinte chega "🟢 Resolvido".

**Áudio.** Alguém manda um áudio contando um problema. `/respostas` mostra a
transcrição e a resposta do Tuca. Peça à IA no grupo: "o Tuca respondeu bem o
áudio?" A avaliação dela precisa fazer sentido para quem leu a resposta.

**Worker parado.** No Coolify, na aba Logs do app, pare só o container `worker`
(botão Stop dele). Mandem duas mensagens pelo WhatsApp. Em uns 4 minutos chega
"Mensagens esperando e o worker não pega", crítico. Religue o worker
(Redeploy ou Start). As mensagens são processadas, as respostas chegam nos
celulares, e a varredura seguinte manda "🟢 Resolvido".

**Correção do catálogo, com o João.** O botão de correção só aparece para
mensagens presas em processamento, esgotadas ou respostas que a Meta nem
aceitou. Isso não se produz pelo celular. O João, com o Claude Code, planta uma
mensagem de teste presa no banco (em modo de atendimento humano, para o Tuca não
responder a ninguém), o alerta "Mensagens presas em processamento" chega com o
botão **Devolver para a fila**, o Lucas aperta, e o resultado aparece na mesma
mensagem com o nome dele. Depois o João apaga o teste do banco.

Ao fim da rodada 2 precisa ter acontecido: um 🚨 em menos de um minuto, um
alerta que resolveu sozinho, um botão apertado com nome registrado, uma
avaliação da IA que fez sentido.

## Rodada 3: a nuvem corrige, uma vez só (quinta 24 ou sexta 25 de manhã)

É o único ensaio do caminho completo até produção. Feito uma vez, fica ligado
para o festival.

1. O João religa a rotina Guardião do Tuca (ela está pausada).
2. O João abre uma issue no GitHub com a label `tuca-alerta`, título
   "Ensaio do Guardião" e o corpo: "Crie o arquivo tests/test_guardiao_ensaio.py
   com um teste que passa. Não toque em nenhum outro arquivo."
3. Esperado em minutos: a rotina roda (o gatilho é a própria issue; se não
   disparar, o João roda à mão e conserta o gatilho). Ela abre um PR com a label
   `tuca-agente`, e o agente do Telegram manda no grupo o resumo com
   **Aprovar e subir** e **Rejeitar**.
4. O Lucas lê o resumo no celular. Precisa entender o que muda sem perguntar a
   ninguém. Se não entender, o texto do PR é o problema, e o João ajusta o prompt.
5. O Lucas aperta **Aprovar e subir**. Esperado: "aprovado por Lucas" no grupo,
   e uns 3 minutos depois "🟢 Versão nova no ar". O `/saude` continua verde.
6. O João apaga o arquivo de teste com um commit normal.

Ao fim da rodada 3 precisa ter acontecido: issue → PR → botão → merge → deploy,
sem ninguém abrir o computador além do João no passo 2.

## Véspera (25/09, fim do dia): checklist de plantão

- [ ] `/saude` com quatro bolinhas verdes
- [ ] Token do GitHub e token da Meta com validade além de 28/09
- [ ] Rotina Guardião do Tuca ligada (painel: https://claude.ai/code/routines/trig_01PErTaSD6iZAnj2bdHARKbj)
- [ ] Todo mundo que pode aprovar PR está no grupo do Telegram, com notificação ligada
- [ ] Combinado quem aprova PR em cada turno do festival (uma pessoa por turno)
- [ ] Regra do plantão: **Ignorar** é para alerta que a sala já sabe; **Aprovar** só depois de ler o "Risco se aprovar" do PR

## O que o agente vai avisar e não é problema

- **131047 nas respostas não entregues**: a Meta recusou porque a pessoa falou
  com o Tuca há mais de 24h. Ignore. A partir de 20/09 esse caso não abre issue.
- **IA fora por alguns minutos**: o Tuca continua respondendo com os textos
  fixos. Só vira problema se durar mais de meia hora.
