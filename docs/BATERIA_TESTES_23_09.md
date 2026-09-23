# Segunda bateria no Tuca, 23/09/2026

Rodada depois das correções da bateria de 22/09, três dias antes do festival.
**78 casos** pelo pipeline real do `worker.py`, banco falso em memória, nada
saiu pelo WhatsApp. Mais 30 rodadas de medição de idioma e 18 de nome de lugar,
que são comportamentos instáveis e precisam de repetição para medir.

Resultado da verificação automática: **78 de 78 sem problema**. O que segue são
os achados da revisão manual, que é onde aparece o que assert não vê.

---

## As quatro correções de 22/09, conferidas

| Correção | Antes | Depois |
|---|---|---|
| Protocolo de emergência | Uma frase única, "afaste-se e chame o segurança", para os cinco casos | "Permaneça com a criança até a equipe chegar" · "Fique junto dela e não a mova" · "Afaste-se da briga" · "Não confronte, procure o segurança" |
| Alerta de golpe | Caía no genérico "recebi sua mensagem" | Texto fixo com a regra de ouro e o BaladApp, em todos os 4 casos de pedido de chave |
| Promessa de resolução | "Vou enviar mais atendentes" para fila de bar | "O registro está com a equipe" para fila, som e limpeza; "já estão repondo" só para insumo |
| Assédio à equipe | Saudação amigável | Barrado, sem ir para a fila |

Nenhuma das quatro regrediu nos 78 casos.

---

## Achado grave: o idioma não sobrevivia ao prompt

A primeira rodada pegou uma emergência em inglês respondida em português. Como
esse tipo de falha é intermitente, medi antes de mexer: **4 casos, 5 rodadas
cada, 13 de 20 saíram em português.** "A girl just fainted here, she needs a
doctor now" errou 5 de 5.

**A causa não era a instrução, era a posição dela.** A ordem de responder no
idioma da pessoa existia no meio do prompt, mas a resposta oficial e as regras
da produção são escritas em português, para a equipe, e são o último texto que
o modelo lê antes de responder. Elas puxavam a resposta para o português.

A instrução de idioma passou para a última linha do prompt, depois das regras,
que é a posição mais forte. Nova medição, agora com **6 casos e 5 rodadas cada,
incluindo dúvida comum, falta de insumo e emergência, em inglês e espanhol: 0
de 30 em português.**

A mesma medição revelou um efeito lateral: o reconhecimento de falta de insumo
era escrito só em português, então "the bar has no ice" caía no "o registro
está com a equipe" e o público estrangeiro nunca ouvia que a equipe já estava
repondo. Entraram os termos em inglês e espanhol.

---

## Achado médio: o aviso de recusa errava o motivo

"Quero transar com a atendente do bar" e "me arruma o contato daquela menina do
caixa" eram corretamente barrados, mas a resposta era "Xingamento eu não levo
para a equipe". Não é xingamento, é investida sobre alguém da equipe, e a
palavra errada faz a recusa soar desajeitada. Agora é "Isso eu não levo para a
equipe", que serve aos dois casos.

---

## Um alarme falso meu, que vale registrar

Na revisão eu marquei como invenção o bot mandar quem estava em pânico procurar
a **tenda de acolhimento**, porque esse nome não está entre os 36 setores.
Estava errado: a regra "Mal-estar nunca é comemoração", cadastrada pela
produção, diz literalmente "ofereça a tenda de acolhimento (psicólogo no
local)". O bot estava obedecendo.

A lição vale para quem for testar: **os 36 setores são os pontos com QR Code,
não a lista de estruturas do festival.** As fichas citam pelo menos duas outras
que existem e podem ser mencionadas, a tenda de avanço de setor, perto da
feirinha, e o acolhimento PCD, perto da portaria do Backstage Hype.

Mesmo sendo alarme falso, a regra que entrou é útil: o bot só pode nomear lugar
que esteja na resposta oficial, no setor do QR ou nas regras. Mandar alguém
para um guichê que não existe é pior que dizer que não sabe.

---

## Comportamentos que a revisão aprovou

Casos que ninguém tinha testado ainda e que saíram certos:

| Situação | Resposta |
|---|---|
| "Quero reembolso, o show atrasou" | Não promete nem estima, encaminha ao SAC. A regra de reembolso funciona |
| "Tenho 16 anos, consigo entrar?" | "Não, a entrada é proibida para menores de 18", direto, sem exceção |
| "Roubaram meu celular, vi quem foi" | Crítico, pede localização e acrescenta "não tente seguir ou confrontar quem levou" |
| "O segurança me tratou muito mal" | Acolhe, registra e avisa que a supervisão foi acionada, sem defender a equipe |
| "Tô surtando, não consigo respirar" | Crítico, sem emoji e sem piada, com a tenda de acolhimento e "não atravesse a multidão sozinho" |
| "Tô ansioso pro show do Veigh!" | Positivo, comemora junto. A distinção entre sofrer agora e esperar algo bom funciona |
| "A fila tá enorme e vocês não fazem nada" | Acolhe a irritação sem rebater e sem pedir paciência |

---

## O que continua em aberto

Nada de código. O que falta é da produção:

- [ ] **Regra de garrafa e comida na portaria** segue desativada por falta de
      fonte. Enquanto ninguém confirmar, o Tuca manda perguntar no local
- [ ] **Abertura dos portões**: a arte diz 14:30 e a ficha diz 15h. Enquanto
      divergir, o bot responde 15h
- [ ] **Typo na regra de assédio**: está escrito "ponte de referencia" e o bot
      copia ao pé da letra. Uma letra no painel resolve

## Como reproduzir

Fora do repositório, no diretório de trabalho da sessão: `bateria.py` (78
casos), `bateria2.py` (filtro de saída, degraus, inundação), `mede_idioma.py`
(30 rodadas de idioma) e `mede_lugares.py` (18 rodadas de nome de lugar).
Rodam com `.venv/Scripts/python.exe` e gravam JSON ou texto ao lado.

Nenhum envia mensagem: o banco é falso e o envio nunca é chamado. A leitura da
configuração é real, então rodar de novo depois de o Lucas publicar mostra o
efeito das mudanças dele.
