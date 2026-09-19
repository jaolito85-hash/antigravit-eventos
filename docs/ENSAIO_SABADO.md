# Ensaio do ChatBob na Tropicadelia 2026

Roteiro operacional para o teste com o organizador. Siga na ordem.

---

## 0. Bloqueador: três credenciais da Meta estão vazias

Verificado no `.env` local em 18/09/2026. Sem elas o bot **não funciona**, então
resolva isso antes de qualquer outra coisa:

| Variável | O que quebra se ficar vazia |
|---|---|
| `META_APP_SECRET` | Toda mensagem recebida é rejeitada com HTTP 401. A assinatura do webhook nunca valida, então nada entra na fila. |
| `META_ACCESS_TOKEN` | O worker morre no start (`Configuração da Meta incompleta`) e o Coolify reinicia o container em loop. Nenhuma resposta é enviada. |
| `META_PHONE_NUMBER_ID` | O webhook descarta as mensagens por não reconhecer o número de origem, e o envio não tem remetente. |

Onde pegar cada uma, no [developers.facebook.com](https://developers.facebook.com):

- `META_APP_SECRET`: App → Configurações → Básico → Chave secreta do app.
- `META_ACCESS_TOKEN`: WhatsApp → Configuração da API → token permanente do usuário do sistema.
- `META_PHONE_NUMBER_ID`: WhatsApp → Configuração da API → ID do número de telefone.

Preencha nos dois lugares: no `.env` local e nas variáveis de ambiente do
Coolify (web **e** worker).

### Como confirmar que ficou certo

```bash
curl -s https://app.nodedata.com.br/health
```

Tem que responder `{"status":"ok","configuration":"ok","database":"ok"}` com
HTTP 200. Se vier `configuration: incomplete`, ainda falta variável, e o
Coolify vai tratar o container como doente.

---

## 0.1. Resolvido: o modelo da OpenAI havia saído do ar

Verificado em 18/09/2026: a chave do projeto perdeu acesso ao `gpt-4o-mini`, que
era o modelo fixado no código. Toda a camada de IA estava caindo no fallback, ou
seja, classificação por palavra-chave, resposta padrão e pulso indisponível.

Já corrigido: o modelo agora vem da variável `OPENAI_MODEL`, com padrão
`gpt-5.4-mini`, que é o que a sua chave acessa hoje. A API também passou a exigir
`max_completion_tokens` no lugar de `max_tokens`, e isso foi ajustado nas cinco
chamadas. A transcrição por `whisper-1` segue liberada.

Se um dia a IA voltar a falhar, confira o que a chave acessa:

```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv('.env'); from openai import OpenAI; print([m.id for m in OpenAI(api_key=os.getenv('OPENAI_API_KEY')).models.list().data])"
```

Depois ajuste `OPENAI_MODEL` no `.env` e no Coolify. Nada quebra enquanto isso: sem
IA o sistema classifica por palavras-chave e responde com texto fixo, de propósito.

---

## 1. Webhook apontado para o servidor

No painel da Meta, em WhatsApp → Configuração:

- URL de callback: `https://app.nodedata.com.br/webhook`
- Token de verificação: o mesmo valor de `META_VERIFY_TOKEN`
- Campo assinado: `messages` (obrigatório)

O botão "Verificar e salvar" só passa se o servidor estiver no ar.

---

## 2. Massa de demonstração para o telão não nascer vazio

O banco hoje tem 6 feedbacks antigos, nenhum vinculado a setor, então o mapa
começa apagado. Para o ensaio ficar apresentável:

```bash
python execution/seed_demo_tropicadelia.py
```

Isso cria 28 feedbacks espalhados pelos setores reais nas últimas 5 horas, com
mistura de elogios, urgências e 2 críticos. Cada registro leva
`source=manual` e `metadata.demo = true`.

Para conferir o que existe:

```bash
python execution/seed_demo_tropicadelia.py --status
```

Para apagar **só** a massa de teste, sem tocar em nada real:

```bash
python execution/seed_demo_tropicadelia.py --clear
```

> Limpe a massa de demonstração antes do evento de verdade, senão os números
> do relatório final saem contaminados.

---

## 3. QR Codes dos setores

Abra `/qrcode` e para cada setor:

1. Nome do evento: `Tropicadelia 2026`
2. Número do WhatsApp: o número oficial, formato `5543999999999`
3. Setor da planta: escolha na lista (os 26 vêm do banco, agrupados por zona)
4. Gerar, depois "Baixar Cartaz"

A mensagem sai como `#SETOR:CODIGO`. Essa tag é o contrato com o worker: é ela
que vincula o relato ao setor e acende o pin certo no mapa. Se você editar a
mensagem e tirar a tag, o feedback chega sem setor.

Quando a pessoa escaneia e envia, o bot responde com o nome do setor e o convite
cadastrado. Exemplo real do setor de sanitários:

```
📍 Você está em *Sanitários Femininos • Palco Principal*!
Falta papel, sabonete ou fila travada? Avise nossa equipe.
Pode mandar texto ou áudio 🎤
```

---

## 4. Ensaio no celular, 4 mensagens

Faça este teste com o seu próprio número antes de mostrar para o organizador:

| Envie | Resposta esperada | No dashboard |
|---|---|---|
| `oi` | Boas-vindas do ChatBob com a regra de ouro anti-golpe | Nenhum card (saudação não polui o painel) |
| Escanear um QR e enviar | Convite com o nome do setor | Nenhum card ainda |
| `acabou o papel e a fila tá enorme` | Resposta com jeito de gente, citando o setor | Card Urgente, pin do setor fica laranja |
| Um áudio de 10s reclamando | Começa com "🎤 Ouvi seu áudio!" | Card com o texto transcrito |

Atenção ao limite: o rate limit corta a partir de 4 mensagens do mesmo número em
10 minutos. Para ensaiar à vontade, use dois celulares ou espere a janela passar.

---

## 5. O que mostrar, na ordem

1. **Telão** (`/telao`, tecla `F` para tela cheia). Deixe rodando no projetor.
   É a peça de impacto: a planta aérea do Ney Braga com os pins pulsando, os
   cinco KPIs, o pulso da IA e as macrozonas. **Tudo ali é clicável e opera
   de verdade**, não é um cartaz:
   * Pin ou linha de "Setores em Alerta" abre os chamados daquele ponto, com
     os números e as mensagens.
   * Dentro do chamado você troca o status e clica em "Conversar com quem
     enviou" para falar com a pessoa na hora.
   * Os KPIs abrem a lista que resumem: críticos, elogios e dúvidas.
   * Cada macrozona abre seus setores, e cada mensagem do "Fluxo Ao Vivo"
     abre direto a conversa de quem escreveu.
   * O alerta crítico em tela cheia também é atalho: clicar nele abre a
     conversa de quem mandou o alerta.
2. **Alerta crítico ao vivo**: mande do celular "tem uma briga perto do palco".
   Em segundos o telão é tomado por um alerta vermelho em tela cheia com a
   mensagem e o setor. Esse é o momento que vende o produto.
   Ligue o som antes no chip "Som off" do topo, ou tecla `S`.
3. **Mapa ao Vivo** no dashboard, para mostrar o ranking de setores em alerta e
   a cobertura por zona.
4. **Chamados**, a fila de trabalho. Cada cartão traz o número, a mensagem
   completa, as atualizações e **a resposta que o ChatBob enviou**, com o
   estado de entrega. É aqui que se mostra a troca inteira e a mudança de
   status. Não confunda com **Atendimento**, que é uma linha por pessoa: a
   mesma pessoa pode ter três chamados.
5. **Relatório** (`/relatorio`), o entregável pós-evento: resumo executivo
   escrito pela IA, aprovação por macrozona e a tabela de desempenho por setor,
   que mostra exatamente qual ponto da planta funcionou e qual deu trabalho.

---

## 5.1. Assumir a conversa na frente do organizador

Esse é o momento que mostra que não é só um robô. Depois de mandar um relato do
celular:

1. No painel, abra o chamado (pelo pin do mapa ou pela aba Feedbacks) e clique
   em **Conversar**.
2. Clique em **Assumir atendimento**. O celular recebe na hora: *"Aqui é a
   equipe da Tropicadelia assumindo a conversa. Pode falar direto comigo!"*
3. Escreva do painel e mostre a mensagem chegando no celular. Suas mensagens
   aparecem em laranja, as do bot em azul.
4. Mande outra mensagem do celular e mostre que **o bot não responde mais**:
   o chamado entra no dashboard, mas quem fala é você.
5. Clique em **Devolver ao ChatBob** e mande mais uma do celular. O automático
   volta a responder.

A aba **Atendimento** lista todas as conversas, com as assumidas no topo, e o
contador laranja na barra lateral mostra quantas estão na mão da equipe.

---

## 5.2. Deixar os sócios brincarem com o bot

Abra `/chatbob` e passe o teclado para eles. É a parte que convence sem
precisar de celular, número da Meta ou nada configurado.

À esquerda eles escrevem como um frequentador escreveria. O bot responde igual
ao WhatsApp e, embaixo de cada resposta, aparece o que ele entendeu: urgência,
categoria, setor e se aquilo abre chamado. Os botões de atalho já trazem os
casos que valem mostrar: `oi`, uma pergunta de horário, uma falta de papel, uma
briga, um elogio e um objeto perdido.

À direita eles cadastram as respostas oficiais do festival. Escreva a pergunta,
a resposta e os jeitos de perguntar separados por vírgula. Salve, volte para a
esquerda e pergunte: o bot já responde com a informação nova, no tom dele.

A base já vem com sete perguntas de partida: horário, local, o que pode entrar,
achados e perdidos, acessibilidade, pagamento e line-up. Revise esses textos
com o organizador antes do evento, porque são eles que o público vai receber.

Na aba "Jeito de falar" dá para ajustar o tom e trocar a mensagem de
boas-vindas. Tom é só jeito de falar; informação vai nas perguntas e respostas.

---

## 6. Se algo der errado no meio

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Mensagem enviada e nada aparece | Webhook rejeitado por assinatura | Confira `META_APP_SECRET` e o log do web: procure "assinatura inválida" |
| Card aparece mas o bot não responde | Worker parado ou token vencido | Veja o log do worker: procure "Falha ao enviar resposta" |
| Pin não acende | Mensagem foi enviada sem a tag `#SETOR:` | Gere o QR de novo pelo `/qrcode` com o setor selecionado |
| Telão sem atualizar | Sessão expirou | Recarregue e entre de novo |
| Resposta sem graça, genérica | OpenAI fora do ar ou sem crédito | O sistema cai no texto fixo de propósito, para nunca deixar ninguém sem resposta |
| Bot não responde ninguém | A conversa foi assumida e não devolvida | Abra a aba Atendimento e clique em Devolver ao ChatBob |
| Não consigo enviar pelo painel | Conversa sem mensagem recebida, ou passou de 24h | O painel explica o motivo no próprio campo de escrita |
| Bot responde errado uma pergunta | Falta gatilho na base | Abra `/chatbob`, teste a frase e acrescente o jeito de perguntar que falhou |

Os logs em produção ficam no Coolify, em cada serviço: `web` para recebimento e
`worker` para classificação e envio.
