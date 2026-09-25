# Formulário pré-evento, 25/09/2026

Escrito na madrugada de 25/09, com o João Marcos viajando para o evento. Tudo aqui foi verificado contra o banco e o servidor de produção. Marcadores: 🔴 erro ou bloqueio, 🟡 atenção, 🟢 verificado ok, ⚪ informação.


## Estado às 00:40 de 25/09, dois dias antes do festival

- 🔴 **IA desligada: a conta da OpenAI está sem créditos.** Erro 429 `credit_balance_exhausted` em toda chamada (classificação, resposta, moderação e transcrição de áudio). A última resposta com IA em produção foi às 12:50 de 24/09. Desde então o Tuca responde só com os textos de reserva: não entende gíria, não escolhe ficha direito e responde "recebi sua mensagem" para quase tudo. **É o item número 1 da lista de amanhã.**
- 🟢 Telão da sala de controle: pinos e alerta crítico funcionando, testado ponta a ponta (detalhe abaixo).
- 🟢 Worker vivo e lendo a fila: 280 consultas ao banco nos últimos 5 minutos, nenhuma mensagem pendente.
- 🟢 Envio pela Meta saudável: 61 respostas nos últimos 2 dias, todas entregues, nenhuma falha.
- 🟢 Web e worker no ar com o código desta noite: deploy do commit `d4fc6af` confirmado pelo `/health` às 02:33 UTC (23:33 de Londrina).
- 🟡 24 chamados de teste continuam "aberto" no painel e no telão (5 críticos). São ensaios da equipe de 15 a 24/09. Tentei marcar todos como resolvidos, mas a atualização em massa foi barrada pela minha permissão. Instruções abaixo.

## Telão: como foi testado e o que confirma

- 🟢 Abri o telão num servidor local ligado ao mesmo banco de produção. Ele mostrou 1 pino (Acesso Central • Tropical Lounge, Urgente aberto) e a nota "1 setor pedindo alguém · 63 no radar": exatamente o que o banco tinha.
- 🟢 Inseri um chamado **Crítico de teste** no Bar Hype • Pista. Em 5 segundos o telão desenhou o pino vermelho pulsante em 55,6% × 26,3% (a coordenada cadastrada do setor), a nota passou a "2 setores pedindo alguém", e o **alerta de tela cheia abriu** com a mensagem, o lugar e a categoria. O chamado de teste foi apagado depois.
- ⚪ Regra do telão, para não estranhar no dia: pino só para setor **ativo, com coordenada**, cuja pior urgência em aberto seja Crítico ou Urgente. Dúvida e elogio contam nos cards de cima mas não acendem pino. Chamado sem setor (a pessoa não escaneou o QR e não disse o lugar) não acende pino: aparece na lista e no contador. A planta tem 65 setores ativos, 63 com coordenada (faltam as duas áreas de descanso da pista).
- ⚪ O alerta de tela cheia só dispara para chamado crítico **novo** depois que o telão foi aberto. Ao abrir, ele memoriza o último e não alarma histórico. Some sozinho em 12 s ou ao clicar; clicar no alerta abre a conversa da pessoa.
- ⚪ Atualização a cada 5 s. O telão mostra "sem sinal" no relógio de cima se perder o servidor.

## Erros encontrados esta noite e o que foi feito

- 🔴 **Imagem do line-up nunca saía e o worker falhava 8 vezes.** Desde 23/09 o banner ia sem legenda, e a coluna da caixa de saída exige ao menos 1 caractere: o banco recusava (HTTP 400 `outbound_content_length`), o worker marcava a mensagem como falha e tentava de novo 8 vezes (8 chamadas de IA pagas). Visto em produção em "Qual a line up do hype?" de 24/09 08:59: a pessoa recebeu o texto e nunca a foto. **Corrigido** (commit `d4fc6af`), com teste.
- 🔴 **Sem IA, emergência em inglês e espanhol virava Neutro.** Com a conta sem créditos, o classificador de palavras é o único que sobra, e ele dava Neutro para "estou sendo assediada", "a girl just fainted" e "hay una pelea": sem pino no telão. **Corrigido**: assédio sofrido, estupro e as palavras de emergência em inglês e espanhol entraram na lista; "ajuda" e "help" sozinhos viram Urgente e perguntam onde a pessoa está.
- 🟡 **Link do app cadastrado errado.** O `appUrl` publicado às 11:13 de 24/09 é `https://app.nodedata.com.br/`, o painel de controle. Já blindei o código para nunca mandar esse endereço ao público (vai "pergunte à equipe" no lugar), mas o campo continua errado no painel.
- 🟢 Os três deslizes do Tuca atual da bateria da tarde (link em relato, pergunta de lugar quando há ficha, chute de lugar em inglês) estão corrigidos e no ar desde 16:27 UTC. Confirmados com IA real antes da conta esvaziar.
- 🟢 Outro agente (Cursor) subiu às 19:03 o commit `452369a` com respostas fixas aprovadas pelos sócios (fome, banheiro, gravação dos shows, reclamação genérica, "lixo"). Revisei: reconhecimento conservador, só frase inteira, entra depois da moderação. Suíte inteira passa (460 testes).

## O que só você pode fazer, em ordem

- 🔴 **1. Colocar créditos na OpenAI**, hoje. platform.openai.com → Settings → Organization → Billing (organização nodedata, projeto tropicadelia). Depois, mande "quem toca agora?" para o Tuca: se voltar com o nome do artista e o horário, a IA voltou. Se voltar "recebi sua mensagem", ainda não. Sugestão: crédito pré-pago com folga para 20 mil pessoas, e ligar o auto-recarregar.
- 🟡 **2. Resolver os chamados de teste.** No painel, em Chamados, marque como resolvido tudo que está aberto (são 24, todos ensaios). Se preferir SQL no Supabase, é um comando: `update feedbacks set status='resolvido', resolved_at=now() where status<>'resolvido' and created_at < '2026-09-25';` Sem isso o telão abre sábado dizendo "5 críticos agora".
- 🟡 **3. Corrigir o link do app** em /tuca → Jeito de falar → Link do app oficial. Se o app ainda não tem endereço, deixe em branco. Publique depois.
- ⚪ **4. Três fichas novas** em /tuca → Perguntas: "Menor de 18 entra?" (resposta: não, sem exceção), "Quero reembolso" (SAC da pista, sem prometer) e "Tem estacionamento?" (o que for verdade). Servem ao Tuca atual e ao plano B. Publique depois.
- ⚪ **5. Typo nas regras** "ponte de referencia" → "ponto de referência" (regras de assédio e emergência). O bot copia literalmente.
- ⚪ 6. Portões: arte e line-up dizem 14:30, fichas dizem 15h. Fim: 4h numa ficha, 04:20 na grade. Alinhar com o Lucas.

## No dia: como operar

- ⚪ **Telão**: app.nodedata.com.br/telao, botão "Telão" para tela cheia. Som do alerta só toca depois do primeiro clique na página (regra do navegador): clique uma vez em qualquer lugar ao abrir.
- ⚪ **Se o Tuca começar a errar**: /tuca → aba Jeito de falar → botão "Tuca enxuto (plano B)". Vale em até 15 s, sem publicar e sem deploy. Ele só responde o que está nas fichas e manda o resto para o app ou para a equipe; nunca inventa. O mesmo botão volta para o atual.
- ⚪ **Se a IA cair no meio da festa** (créditos, OpenAI fora): o bot não para, cai nos textos de reserva. Emergência continua abrindo chamado Crítico e pedindo localização. O que se perde é o tom e a escolha fina de ficha. Sinal de que caiu: respostas "✅ Recebi sua mensagem!" e "⚠️ Recebemos e destacamos sua mensagem" para tudo.
- ⚪ **Limite por número**: a partir da 11ª mensagem em 10 min o bot avisa e para de responder (segue registrando até a 30ª). Para ensaiar, use dois celulares.
- ⚪ **Áudio**: até 1 minuto e 3 por hora por número. Fora disso o bot pede texto.
- ⚪ **Localização**: quem manda o pino pelo clipe completa o último chamado aberto da pessoa (até 1 h). No telão aparece o botão de mapa antes do de conversar.
- ⚪ **Operador assume a conversa** pelo botão de conversar no chamado: a partir daí o bot cala e quem responde é a pessoa do painel. Devolva ao bot quando terminar.

## Checagem de 2 minutos antes de abrir os portões

- 🟢 1. app.nodedata.com.br/health responde `"status":"ok"`.
- 🟢 2. Mande "quem toca agora?" de um celular: resposta com artista e horário em até 10 s = IA e worker vivos.
- 🟢 3. Escaneie um QR e mande "acabou o gelo aqui": o telão acende o pino do setor em 5 s.
- 🟢 4. /tuca → Jeito de falar mostra "No ar: Tuca atual".
