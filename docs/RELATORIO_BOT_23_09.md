# Investigação do Tuca, 23/09/2026, três dias antes do festival

Feito na noite de 23/09, depois do ensaio da tarde que mostrou o bot repetindo
as boas-vindas. Três fontes: as conversas reais dos últimos três dias no banco
(mensagens recebidas, respostas enviadas e chamados abertos), o PR #5 aberto por
outro modelo, e uma bateria nova de **147 mensagens em conversas inteiras**,
passando pelo pipeline real do `worker.py` com IA real e banco falso em memória,
sem enviar nada pelo WhatsApp.

Resultado curto: o PR #5 estava certo no diagnóstico e foi integrado, mas
sozinho deixava dois buracos (a placa escaneada sozinha e o simulador). Além do
loop de boas-vindas, a produção mostrou mais cinco defeitos que ninguém tinha
visto. Todos os sete estão corrigidos e cobertos por teste; o que sobra é
conteúdo que só a produção pode cadastrar.

---

## 1. O que as conversas reais mostraram

Tudo abaixo é do banco de produção, 21 a 23/09.

| # | O que aconteceu | Gravidade | Estado |
|---|---|---|---|
| 1 | **Loop de boas-vindas.** "Voce nao gosta de festa? Kd vc?", "Cade voce??" e oito "Oi" seguidos receberam a mesma apresentação até o limite de mensagens cortar | Alta: é o que a pessoa vê primeiro | Corrigido (PR #5 + ajuste) |
| 2 | **Duas perguntas numa mensagem perdem uma.** "Show vai até que horas? Quais bandas vao tocar?" respondeu a hora e disse "sobre as bandas, essa eu não sei", com o line-up cadastrado | Alta: parece que o bot não sabe o line-up | Corrigido |
| 3 | **Relógio antes do festival.** Na terça, "Qual a line up?" voltou com "às 18h20 vem Yago O Próprio? Opa, esse já passou!". A IA olhava o relógio de terça e a grade de sábado | Média: só até sábado, mas é o que os sócios testam agora | Corrigido |
| 4 | **Pergunta de localização em português para estrangeiro.** A linha fixa "📍 Só me diz onde você está?" sai depois da resposta em inglês ou espanhol, e no Crítico duplica o pedido que o protocolo já faz | Média | Corrigido |
| 5 | **Pergunta boba vira chamado no painel.** Com o prompt do PR #5, "cadê você?" e "quem é você?" abriam chamado Neutro na fila de trabalho | Média: polui a fila no dia | Corrigido |
| 6 | **Placa escaneada sozinha ia para a IA com texto vazio.** Com o PR #5, a mensagem vazia caía no caminho de "pergunta" e a resposta dependia do humor do modelo | Alta: é a primeira mensagem de quase todo mundo | Corrigido |
| 7 | **"Tem água grátis?" e "aceita pix no bar?" caíam em "não sei".** A resposta existe nas fichas "Está muito quente" e "Como eu compro bebida?", mas a triagem só via o título da ficha | Média | Corrigido |

Outros pontos vistos nos dados que não são defeito de código:

- "Me manda um link para o app oficial" recebe "não tenho link". O campo
  `appUrl` continua vazio no painel, e os sócios ficaram de mandar.
- A regra de assédio está com "ponte de referencia" e o bot copia: apareceu em
  "Estou em apuros". Uma letra no painel resolve.
- O envio pela Meta está saudável: nos últimos três dias nenhuma resposta
  falhou de entrega; as únicas falhas são de 17 a 20/09, antes da troca de
  número.
- Nenhuma mensagem recebida ficou com erro de processamento na fila.

## 2. Revisão do PR #5

Título: "O Tuca responde pergunta em vez de repetir as boas-vindas". Três
commits, 10 arquivos, 323 testes passando no branch.

**O que ele acerta e ficou:** o modelo que responde dúvida passa a receber as
últimas seis falas da conversa; cumprimento de quem já falou na janela vira uma
linha curta em vez do cartaz; pergunta marcada como conversa vai para o modelo
que responde de verdade; "ajuda" e "help" deixam de ser saudação; no
classificador de reserva (sem IA), Crítico e Urgente passam a valer mais que
elogio, para "bom dia, tem briga" não virar Positivo.

**O que precisou de ajuste ao integrar:**

- O simulador de `/tuca` não foi tocado: mostrava as boas-vindas para "cadê
  você?" enquanto o WhatsApp respondia a pergunta. Passou a espelhar o worker.
- A placa escaneada sozinha (conteúdo vazio) caía no caminho novo de pergunta.
  Agora ela nem passa pela IA: primeira mensagem em 10 minutos recebe as
  boas-vindas cadastradas no painel mais o convite do setor; as seguintes, só o
  convite.
- O prompt da triagem dizia "pergunta nunca é conversa" e mandava "cadê você?"
  abrir chamado. Ficou: pergunta **sobre o evento** é relato; pergunta ou
  brincadeira **dirigida ao Tuca** é conversa respondida, sem chamado.
- O histórico entrava no prompt como texto solto. Passou a ir marcado como
  dado, dentro de `<history>`, com a mesma proteção contra tag fechada que a
  mensagem atual já tinha.

Integrado na `main` com merge commit, sem reescrever o histórico dele.

## 3. Correções feitas hoje, além do PR

| Correção | Onde | Teste |
|---|---|---|
| Triagem devolve `ficha2` quando a mensagem faz duas perguntas; as duas respostas oficiais viram uma, sem imagem, e a IA responde as duas | `triar_mensagem_ia`, `juntar_fichas` | `test_ficha_por_ia.PerguntaDuplaTests` |
| A triagem vê os primeiros 120 caracteres da resposta de cada ficha, não só o título | `triar_mensagem_ia` | bateria |
| Prompt do guia recebe a janela do festival (do banco) e diz se ele ainda não começou, está rolando ou acabou | `_linha_do_relogio`, `EventStore.event_window` | `test_relogio_do_festival` |
| Pergunta fixa de localização em português e inglês, e só no Urgente; no Crítico o protocolo já pede | `worker.py` | bateria |
| Placa sozinha responde sem IA, com boas-vindas na primeira vez | `worker.py` | `test_worker` (2 casos) |
| Simulador espelha o caminho de pergunta ao Tuca | `_simular` | `test_ficha_por_ia.SimuladorTests` |
| Reserva da resposta criativa deixou de prometer "resolver isso AGORA" numa emergência: sem IA vai a ficha oficial ou o texto por urgência | `generate_ai_response` | suíte |
| "O show tá pegando fogo" no classificador de reserva é elogio, não incêndio; "a barraca tá pegando fogo" continua Crítico | `classificar_sentimento` | `test_classificar_sentimento` |
| "socorro" e "sos" sozinhos são Crítico na triagem | prompt | bateria |
| Histórico sanitizado contra `</participant>` | `worker._contexto` | `test_worker` |

Suíte: **338 testes, todos passando** (`python -m unittest discover -s tests`).

## 4. A bateria

Três rodadas com IA real, todas pelo `process_inbox` do worker, com banco falso
que guarda histórico, contador de mensagens e placa escaneada por pessoa.

| Rodada | Código | Casos | Sinalizados pela conferência automática | Defeitos de verdade |
|---|---|---|---|---|
| 1, linha de base | main com o PR #5 | 139 | 21 | 8 (o resto era limite de mensagens estourado pela própria bateria e assert estrito) |
| 2, depois das correções | main corrigida | 143 | 6 | 1 ("tem água grátis?") |
| 3, dirigida | main final | 75 | 4 | 1 (a mesma) |

O que a linha de base mostrou e a rodada 2 confirmou corrigido:

- "Voce nao gosta de festa? Kd vc?" e "Cade voce??" depois do QR: antes, abriam
  chamado Neutro; agora respondem sem chamado e sem apresentação ("Gosto sim,
  ué! Tô aqui nos bastidores...").
- Seis "Oi" da mesma pessoa: nenhum repete "eu sou o Tuca".
- "Show vai até que horas? Quais bandas vao tocar?": antes "essa eu não sei";
  agora dá a hora e os nomes dos três palcos.
- "quem toca agora?" na terça: antes "esse já passou"; agora "o festival ainda
  não começou, a próxima atração é Ricardo Farhat, sábado às 15h30".
- "quanto custa o hambúrguer e que horas toca a Luísa Sonza?": os dois numa
  resposta só (R$ 35 e 20h25).
- Emergência em inglês e espanhol: resposta inteira no idioma da pessoa e sem a
  linha fixa em português.
- "socorro" e "sos" sozinhos: Crítico nas duas rodadas finais.
- Placa sozinha, "É só enviar 👉 #SETOR:...": boas-vindas do painel e convite do
  setor, sem passar pela IA; o relato seguinte ("tá sem papel") herda o setor
  da placa e acende o pino certo.

Comportamentos conferidos e aprovados na leitura manual: áudio (transcrição,
sem fala, longo demais, cota de 3 por hora), localização com e sem chamado
aberto, foto e vídeo, figurinha e reação (silêncio), atendimento humano
(registra e cala), inundação com IA desligada, limite de 10 respostas em 10
minutos, três strikes de ofensa, golpe por chave Pix e por link, injeção de
prompt em duas mensagens seguidas, 3.000 caracteres de "a", só emoji, só
número.

O que sobrou: "tem água grátis?" continua caindo em "não sei" mesmo com a
triagem vendo o começo das respostas. A informação está na ficha "Está muito
quente", e a IA não liga uma coisa à outra de forma confiável. É conteúdo:
uma ficha com esse título resolve.

## 5. O que ainda depende da produção (painel, não código)

- [ ] **Link do app oficial** (`appUrl` na aba Jeito de falar). Sem ele o bot
      responde "não tenho link" para quem pede.
- [ ] **Typo "ponte de referencia"** nas regras "Assédio e discriminação" e
      "Emergência e saúde". O bot copia literalmente.
- [ ] **Abertura dos portões**: a arte e o line-up dizem 14:30, as fichas dizem
      15h. Hoje o bot responde as duas coisas dependendo da pergunta.
- [ ] **Fim do festival**: a ficha diz 4h, o line-up do Palco Tropical vai até
      04:20. Mesma coisa.
- [ ] Fichas que valem a pena existir com o título certo, mesmo que a resposta
      já esteja em outra: "Tem água grátis?", "Aceita pix e cartão?", "Tem
      estacionamento?".
- [ ] Decidir se dúvida (Neutro) deve mesmo abrir chamado em "aberto" na fila.
      Hoje abre, e no dia serão centenas de "que horas toca X" na lista. O
      telão não mostra, mas o painel conta.

## 6. Como repetir a bateria

Fora do repositório, no diretório de trabalho da sessão: `bateria3.py`. Roda
com `.venv/Scripts/python.exe`, lê fichas, regras e setores do banco real, e
grava `bateria3-resultado.json` e `bateria3-leitura.md` ao lado. Cada pessoa
da bateria tem histórico, contador de mensagens e setor escaneado, então dá
para testar conversa de verdade, não só mensagem solta. Nada é gravado no
banco e nada sai pelo WhatsApp.
