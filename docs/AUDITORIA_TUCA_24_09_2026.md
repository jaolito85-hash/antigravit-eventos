# Auditoria do TUCA: diagnóstico, correções e preparação para o evento

Auditoria realizada na noite de 23/09 e madrugada de 24/09/2026, horário de São Paulo.

**Situação: correções aplicadas no checkout local e validadas. Ainda não implantadas em produção.**

O canal estava recebendo e enviando mensagens no recorte consultado. As falhas mais relevantes apareceram na seleção de informações, nas respostas de reserva, nas promessas sem confirmação, no tratamento de localização e na espera da fila. Passar na suíte anterior de 340 testes não detectava esses problemas.

## Evidência atual de produção

Consulta somente de leitura, últimas 72 horas, feita às 23h50 de 23/09:

| Indicador | Resultado |
|---|---:|
| Mensagens recebidas | 71 |
| Processadas / ignoradas | 40 / 31 |
| Falhas de processamento no recorte | 0 |
| Chamados | 38 |
| Chamados abertos / resolvidos | 35 / 3 |
| Respostas aceitas pela Meta | 70 |
| Entregues / lidas / apenas aceitas | 49 / 11 / 10 |
| Tempo de resposta, mediana | 6,4 s |
| Tempo de resposta, p90 | 9,8 s |
| Maior tempo de resposta | 124,3 s |

Aceite da Meta não equivale a entrega: as 10 respostas em `sent` não tinham confirmação de entrega nesse snapshot. O cálculo de tempo tinha 40 amostras, não 71.

Uma segunda leitura, às 00h05, encontrou 12 chamados urgentes ou críticos, dos quais 8 sem setor, nenhuma entrada presa em processamento e nenhuma saída em `sending`. Ausência de setor não prova ausência de GPS: são campos distintos. Os snapshots ocorreram em momentos diferentes e o sistema continuou em uso.

## Falhas corrigidas

| Gravidade | Problema e efeito | Correção local | Evidência |
|---|---|---|---|
| Alta | Sem chave da IA, qualquer mensagem recebia agradecimento genérico, incluindo emergência e pergunta com resposta cadastrada | A ausência de IA agora aciona a resposta oficial ou o fallback correto por urgência | Regressões sem chave e timeout |
| Alta | Resposta crítica dependia da criatividade da IA. No ensaio de conversa, um SOS recebeu instruções misturadas de ficar e procurar segurança | Emergência usa resposta determinística, sem chamada à IA de composição e sem ordem genérica de movimento | Regressão específica e repetição do ensaio |
| Alta | Uma ficha comum podia substituir o protocolo crítico no fallback | Emergência tem precedência sobre fichas e textos promocionais | Regressão com ficha propositalmente inadequada |
| Alta | GPS enviado após o limite ou silenciamento era descartado antes de completar o chamado | Localização é tratada antes dessas barreiras; continua sem resposta quando silenciado, mas é anexada | Casos 11, 12, 30, 31 e 99; caso com strikes |
| Alta | Confirmação de GPS dizia que a equipe estava indo, sem confirmação operacional | Confirma somente recebimento e associação ao chamado | Regressão e ensaio real de composição |
| Alta | Fichas oficiais mandavam prometer reposição ou envio de atendentes; o modelo copiava isso apesar do prompt | Fichas com essas promessas são retiradas da composição urgente; saída da IA também é filtrada; fallback não copia a promessa | Primeira bateria reproduziu; rodada dirigida validou |
| Alta | Primeira resposta de um lote aguardava o processamento de até 20 mensagens antes do envio | A fila de saída é verificada após cada entrada processada | Teste da ordem das operações |
| Média | Timeout do SDK permitia duas tentativas automáticas extras por chamada, alongando indisponibilidades | `max_retries=0` na classificação/composição e moderação; os fallbacks assumem a falha | Default confirmado no SDK instalado; regressões de falha |
| Média | “Tem água grátis?” recebia “não sei” apesar da informação na ficha de calor | Recuperação conservadora no corpo das respostas quando a triagem não encontra ficha; exige ao menos dois termos e candidato único | Duas respostas corretas na segunda rodada e duas na dirigida |
| Média | Dúvida desconhecida era encaminhada ao SAC ou ao pessoal local sem confirmar o chamado já registrado | Código acrescenta confirmação do encaminhamento ao chamado neutro sem ficha quando a resposta omite isso | Wi-Fi, estacionamento, cor da camiseta e link do aplicativo |
| Média | Conversa informal podia usar fallback que afirmava encaminhamento sem existir chamado | O contexto de composição informa quando não houve registro e usa fallback de conversa | Regressão “cadê você?” sem chamado |
| Média | Setor inferido ou herdado chegava ao chamado, mas não ao gerador de resposta | O local resolvido chega à composição e ao protocolo crítico | Regressão e sequência QR, reclamação, SOS |
| Média | Reserva por palavras não cobria SOS, assédio, criança perdida, fumaça e algumas formas de esmagamento | Vocabulário crítico ampliado | Casos de regressão sem IA |
| Média | “Que horas começa o show?” virava elogio na reserva por conter “show” | Perguntas reconhecíveis têm precedência sobre vocabulário de elogio | Quatro formulações e controle positivo |
| Baixa | Ficha vazia produzia resposta vazia; texto oficial podia manter travessão | Resposta vazia cai em reserva; texto oficial passa pela limpeza | Regressões de ambos |
| Baixa | Exemplos do prompt pediam vídeos que o canal não interpreta e incentivavam promessas e palavrões na reclamação | Exemplos revisados; hospitalidade e humor ligados a contextos positivos | Revisão do prompt e respostas reais |

O filtro de promessas é uma proteção adicional por padrões conhecidos, não uma prova de que qualquer paráfrase será detectada. A revisão das fichas publicadas continua necessária.

## Testes executados

### Suíte local

- Antes: 340 testes passando.
- Depois: **364 testes passando**, com 24 novos testes de regressão.
- Um dos novos testes processa **2.000 mensagens sintéticas** no worker, com IA desligada e persistência simulada, conferindo prioridade, registro, resposta e conclusão.
- Cobertura nova: indisponibilidade da IA, timeout, JSON inválido, emergência, ficha errada, informação desconhecida, localização após limites, setor herdado, promessa indevida, ficha vazia e ordem de envio.
- A suíte existente também cobre assinatura do webhook, Meta, áudio, moderação, QR, publicação, histórico, antifraude e atendimento humano.
- `git diff --check` sem erros.

Os 2.000 casos são teste de processamento local, não um benchmark da infraestrutura de produção. Não medem capacidade real do banco, WhatsApp, rede ou quantidade simultânea de participantes. A suíte terminou com um `ResourceWarning` de socket não fechado do cliente existente; não houve falha de teste.

### IA real autorizada

**228 mensagens de pipeline ao todo:**

| Rodada | Quantidade | Resultado e interpretação |
|---|---:|---|
| Primeira bateria | 96 | 3 sinalizações automáticas. Duas eram expectativa estrita de prioridade para reembolso; uma era promessa operacional real. A leitura manual encontrou ainda água gratuita não recuperada e confirmação ausente em dúvidas |
| Segunda bateria | 96 | 2 sinalizações, ambas falsos positivos do verificador: esperava “gratuita”, mas a resposta correta dizia “grátis”. Não significa que todos os aspectos de todas as respostas estejam certificados |
| Rodada dirigida após os ajustes | 22 | Zero sinalizações nos critérios definidos |
| Conversa sequencial inicial | 7 | Herança do QR e GPS funcionaram, mas SOS mostrou orientação instável, corrigida posteriormente |
| Conversa sequencial final | 7 | Sem falha de processamento; dois chamados; GPS associado; SOS respondeu com protocolo determinístico e setor conhecido |

As baterias de 96 e 22 mensagens usaram triagem e composição reais da API configurada e moderação simulada. Os dois ensaios sequenciais usaram também a moderação real. Houve mais **16 verificações isoladas de moderação**, oito por ensaio.

Nenhuma dessas mensagens foi enviada pelo WhatsApp e nenhum chamado de teste foi gravado em produção. Cada mensagem da bateria principal usou participante simulado independente. Histórico, repetição e herança foram avaliados separadamente no ensaio sequencial e nos testes locais.

Na segunda bateria, a mediana por cenário foi 2,61 s e o máximo 4,88 s, com quatro tarefas concorrentes no gerador de testes. Esses tempos excluem banco real, moderação real e envio WhatsApp; não devem ser usados como promessa de atendimento no evento.

### Exemplos obtidos

- Água: “O ponto de hidratação na pista oferece água potável grátis durante todo o festival, é só levar seu copo.”
- Dúvida desconhecida: “Essa eu não sei te responder (...) Seu chamado já foi enviado para a equipe do evento.”
- Localização recebida: “Localização recebida, obrigado! Já mandei para a equipe junto com o seu chamado.”
- SOS com setor conhecido, versão final: “Recebemos seu alerta com prioridade máxima e o chamado já está com a equipe. Local informado: Palco Tropical. Se você mudou de lugar, me avise.”
- Positivo: respostas comemoraram o show, com humor de bastidores e emojis.

A moderação real liberou os pedidos de socorro e a reclamação com palavrão testados, como deveria. Ela também liberou uma investida sexual à atendente; no desenho atual, esse caso depende da segunda barreira, a triagem. Portanto, não se deve tratar a moderação isolada como proteção completa.

## Pendências de conteúdo antes do evento

Estas divergências foram lidas da configuração publicada atual. Não foram resolvidas por suposição nem publicadas automaticamente.

| Prioridade | Pendência | Ação necessária |
|---|---|---|
| Alta | Ficha de abertura: 15h. Grade: 14h30 | Organização deve confirmar e unificar todas as fichas e artes |
| Alta | Fichas de encerramento: 4h. Palco Tropical: 4h20 | Confirmar horário oficial e alinhar também o fechamento dos portões |
| Alta | Regra “Quem está mal não anda” dá prioridade menor a quem precisa da equipe no local | Reescrever para que risco determine prioridade, sem reduzir atendimento por incapacidade de locomoção |
| Alta | Ficha de fila promete mais atendentes; ficha de cerveja afirma reposição e disponibilidade em outro bar | Trocar por confirmação de encaminhamento; remover promessa sem dado operacional |
| Média | `appUrl` vazio, mas várias fichas mandam baixar/abrir o app | Cadastrar URL oficial e testar o link no aparelho |
| Média | Regras de desconhecido divergem entre app e SAC | Padronizar: admitir ausência de informação e confirmar encaminhamento, sem prometer retorno |
| Média | Instruções editoriais aparecem dentro de respostas oficiais, como `[enviar link]`, `[artista]`, `[horário]` e referências a regras | Transformar fichas em respostas finais; manter instruções separadas |
| Baixa | “ponte de referencia”, “bara” e outros erros de digitação | Revisar textos publicados |

A recuperação de água no código reduz uma falha, mas uma ficha específica “Tem água gratuita?” continua sendo a solução editorial mais clara para a organização manter.

## Riscos restantes e como corrigir

1. **Limites ainda podem descartar novos relatos, inclusive emergência, após 30 mensagens ou strikes.** Corrigi a preservação do GPS, não alterei toda a política de abuso. Antes do evento, definir um canal de exceção para socorro: registrar prioridade com processamento determinístico e orçamento limitado, sem liberar geração ilimitada de IA. Isso precisa de testes de abuso e de operação.
2. **Localização por texto posterior não está vinculada deterministicamente ao chamado anterior.** Exemplo: “tem uma pessoa passando mal” seguido de “no bar do palco Tropical” pode gerar um novo registro. Implementar um estado de “aguardando localização”, com prazo e identificação do chamado, e atualizar aquele registro. QR recente e GPS posterior foram testados; este fluxo textual continua sendo uma lacuna.
3. **GPS recebido antes de existir chamado não é reutilizado automaticamente depois.** Hoje o TUCA pede o relato. Guardar coordenadas por uma janela curta e confirmar se a pessoa continua no mesmo local antes de reaproveitar.
4. **GPS é anexado ao último chamado aberto, que pode ser uma dúvida neutra posterior à emergência.** O método atual não prioriza o chamado para o qual o bot pediu o local. Corrigir junto com o estado de localização pendente, evitando adivinhação por “último chamado”.
5. **Processo encerrado no meio de uma entrada/saída.** As buscas normais não retomam `processing` ou `sending`. Existe recuperação de entradas pelo monitor, mas não uma garantia equivalente para a saída interrompida. Adotar posse temporária de jobs e reconciliação de envio. Não reenviar automaticamente um estado ambíguo: a Meta pode já ter aceitado e isso duplicaria a mensagem.
6. **Capacidade de pico não certificada.** O worker continua único e sequencial. O envio entre entradas reduz atraso, mas não aumenta proporcionalmente a capacidade de IA. Fazer ensaio em homologação com taxas crescentes, latência de fila e proporção de fallback. Paralelização deve preservar a ordem por remetente e idempotência.
7. **Chamado no painel não significa leitura ou deslocamento da equipe.** O registro acontece antes da resposta, mas a organização precisa de operador responsável, prioridade visível e confirmação humana de atendimento. Há 35 chamados abertos no snapshot, possivelmente incluindo ensaios. Separar testes reais de trabalho pendente antes do evento, sem apagar registros por suposição.
8. **Contexto da conversa ainda pode produzir pequenas invenções de persona.** No ensaio final, ao responder “cadê você?”, o modelo disse estar perto do Palco Tropical por associação com o histórico do participante. Não corresponde a uma localização física confirmada do mascote. Recomendo limitar essas respostas a “estou por aqui nos bastidores”, sem referência física personalizada.

O protocolo crítico final está em português. Esta auditoria final priorizou mensagens em português; não certifica atendimento multilíngue. Áudio e mídia foram cobertos pela suíte existente, não por gravações reais novas nesta sessão.

## Colocar as correções em uso

1. Revisar o diff local e as pendências factuais acima.
2. Publicar o código no fluxo de implantação do projeto e reiniciar tanto `web` quanto `worker`, pois ambos importam `server.py`. A sessão não fez commit, push ou deploy.
3. Publicar as correções das fichas pelo painel, preservando histórico de versões. Alterar só o rascunho não muda o que o público recebe.
4. Fazer um ensaio controlado por WhatsApp: QR, reclamação com setor, SOS sem setor, GPS, dúvida sem resposta, elogio e devolução do atendimento humano ao bot. Confirmar a chegada ao painel e a entrega no aparelho, não apenas o HTTP 200.
5. Manter um operador acompanhando fila, criticidade e entregas durante o evento. Definir quem assume se a IA, a Meta ou o banco falharem.

## Reproduzir e localizar evidências

Na raiz do projeto:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe scripts/auditar_tuca.py --repeat 2
.\.venv\Scripts\python.exe scripts/auditar_tuca_conversas.py
```

Os dois últimos comandos usam a API real e consomem tokens. Dependem dos snapshots locais `out/auditoria-tuca-config.json` e `out/auditoria-tuca-setores.json`, capturados nesta sessão. Não confundem essas cópias com alterações publicadas. O diretório `out` é ignorado pelo Git e esses arquivos devem ser preservados com o relatório se o ensaio for transferido para outra máquina.

Arquivos principais:

- `server.py`, `worker.py`, `protecao.py`: correções.
- `tests/test_auditoria_tuca.py`: novas regressões.
- `scripts/auditar_tuca.py`: bateria principal e seleção de casos.
- `scripts/auditar_tuca_conversas.py`: ensaio sequencial e moderação real.
- `out/auditoria-tuca-operacao.json` e `out/auditoria-tuca-riscos-fila.json`: snapshots operacionais agregados.
- `out/auditoria-tuca-bateria.json`: primeira rodada.
- `out/auditoria-tuca-bateria-final.json`: segunda rodada, preservada com os dois falsos positivos originais.
- `out/auditoria-tuca-dirigida.json`: rodada dirigida, zero sinalizações.
- `out/auditoria-tuca-conversas.json`: sequência final.
- `out/auditoria-tuca-regressoes.log`: resultado final da suíte.

**Conclusão de liberação:** o código ficou mais resistente, mas ainda não considero o TUCA pronto para operar sem acompanhamento. A implantação, a revisão das informações conflitantes e as lacunas de localização em conversas precisam entrar na preparação do evento.
