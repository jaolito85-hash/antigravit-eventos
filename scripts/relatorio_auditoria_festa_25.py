"""Gera relatório local a partir das evidências desta auditoria."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT/'out/auditoria-festa-25-fallback.json').read_text(encoding='utf-8'))
direct = json.loads((ROOT/'out/auditoria-festa-25-dirigida.json').read_text(encoding='utf-8'))
report = '''# Auditoria do bot Tuca: mensagens durante a festa

Data: 25/09/2026. Código local, motor principal do worker.

## Parecer

Não recomendo considerar o atendimento de emergência aprovado para a festa antes de corrigir os desvios P0 abaixo. A suíte automatizada passa, mas as conversas exploratórias expõem caminhos que ela não cobre. O risco mais importante é um pedido de socorro não virar chamado ou perder a localização ao longo da conversa.

## O que foi executado

* 513 testes automatizados: 513 passaram na última execução isolada, sem testes ignorados.
* 58 mensagens exploratórias: 51 turnos em 27 cenários e sete condições de limite/strikes. Foram executadas sobre o worker real, no modo de reserva sem IA.
* Quatro verificações dirigidas: duas emergências misturadas com pedido de app, uma emergência em legenda de imagem e um controle positivo em texto. Triagem simulada como crítica, para verificar se o fluxo chega a chamá-la.
* Total: 62 entradas exploratórias/dirigidas, além dos 513 testes existentes. Não são 575 usuários nem uma medição de acurácia.
* A suíte inclui um teste local de 2.000 processamentos. Ele usa dependências simuladas e não comprova capacidade de produção, latência de API ou envio simultâneo por WhatsApp.

A primeira execução registrou duas falhas e três erros. Os três erros estavam associados à ausência de chave no ambiente de testes; na execução final foi utilizada chave fictícia, com conexão de rede bloqueada. Os dois testes de contrato de triagem foram alterados externamente durante a auditoria para incluir `continuacao`. Não alterei esses testes nem o código do bot. A reexecução final passou, e a bateria de 58 mensagens foi repetida após essa alteração externa.

## Limites da evidência

O snapshot utilizado é a cópia local `out/revisao-25-snapshot.json`. A base e o motor atualmente publicados não foram consultados. O snapshot indica motor `atual`, mas isso não confirma a seleção atual em produção. Os problemas de conteúdo são comprovados nessa cópia, e precisam ser conferidos na base publicada antes de editar produção.

Nas 58 mensagens, a chave de IA foi desabilitada; nas conversas, o contador global foi colocado acima do limite para exercitar explicitamente o modo de reserva. A moderação usa seu comportamento local sem API. Banco, chamados e respostas ficam em memória. Nenhum WhatsApp foi enviado. URLs de imagens foram enfileiradas no simulador, sem baixar nem validar as artes.

O relógio do snapshot foi fixado em 26/09 às 21h30 de Brasília para representar a festa. Como a bateria foi sem IA, isso não valida a interpretação temporal do modelo real.

A etapa com IA real foi bloqueada pela revisão automática de aprovação por envio externo da base e consumo de API. A autorização foi solicitada e não havia sido recebida na geração deste relatório. Não há avaliação nova do modelo real, de moderação remota, de transcrição de áudio com música, de entrega Meta ou de atendimento da equipe. Respostas de execuções antigas não foram contabilizadas.

## Erros e alterações necessárias

### P0. Pedido de app impede atendimento de emergência

Entrada: “me manda o app, uma pessoa desmaiou aqui”. Também reproduzido com “tem app? socorro estão me assediando”.

Observado: resposta sobre indisponibilidade do app, status `ignored`, zero chamados. Na verificação dirigida, a triagem sequer foi chamada. É um problema da ordem do fluxo e não depende de a IA estar indisponível.

Causa: `worker.py`, função `process_inbox`, retorna em `pergunta_sobre_app(content)` antes de avaliar o risco.

Alteração: dar precedência ao risco em mensagens com múltiplas intenções; só usar a resposta curta de app depois de excluir necessidade de atendimento. Aceite: ambos os casos devem registrar um chamado crítico, pedir localização quando ausente e nunca encerrar apenas com link de app.

### P0. Limites descartam socorro ou deixam de pedir localização

Entrada: “socorro uma pessoa desmaiou”, variando o histórico do remetente.

Observado: na mensagem 10 há protocolo crítico; na 11 há aviso de excesso e chamado; nas mensagens 12 e 30 há chamado crítico sem resposta; nas mensagens 31 e 32 não há chamado; com três strikes também não há chamado nem resposta.

Causa: limites e strikes são aplicados antes da análise do conteúdo. Isso afeta o motor principal e também o caminho do motor enxuto, que compartilha essas barreiras.

Alteração: criar uma exceção limitada para risco explícito, com deduplicação e controle de abuso próprios, preservando o registro crítico e a coleta de localização. Não remover indiscriminadamente todos os limites. Aceite: um novo relato de emergência legítimo deve chegar à equipe mesmo após os limites, sem permitir um número ilimitado de chamados iguais.

### P0. Emergência perde continuidade e GPS vai para outro chamado

Sequência: “uma pessoa desmaiou perto de mim” → “no bar perto do palco Hype” → localização GPS.

Observado sem IA: primeiro chamado crítico sem região; a referência textual abre um segundo chamado neutro e envia uma imagem; o GPS é anexado ao segundo chamado. O crítico permanece sem coordenadas. A sequência com banheiro sem papel apresenta a mesma fragmentação do relato.

Causa: a reserva não usa histórico para interpretar continuação. Cada relato cria novo feedback; `EventStore.attach_location` seleciona o chamado aberto mais recente, sem preservar qual chamado motivou a pergunta de localização. A consulta real foi inspecionada; sua execução em banco não foi testada.

Alteração: guardar `pending_location_feedback_id` ou equivalente por conversa, atualizar o chamado original com a referência e anexar o GPS ao alvo explícito. Aceite: a sequência inteira deve manter um único incidente crítico com referência e coordenadas, sem cardápio ou programação no meio.

### P0. Criança desaparecida é tratada como objeto perdido na reserva

Entrada: “meu filho de 6 anos sumiu perto da entrada”.

Observado: chamado neutro, orientação para Achados e Perdidos e aplicativo.

Alteração: distinguir desaparecimento de pessoa de perda de objeto, abrangendo filho, filha, criança, sumiu e variantes. Encaminhar o relato ao protocolo de segurança com localização, evitando que a ficha de objetos perdidos o substitua. Aceite: crítico para o exemplo; “perdi meu celular” continua no fluxo de objetos.

### P1. Legenda de imagem com socorro é ignorada

Entrada: imagem cuja legenda é “socorro uma pessoa desmaiou”.

Observado: pede reenvio em texto ou áudio; não chama triagem e não registra incidente. O parser da Meta já extrai a legenda, mas o worker retorna antecipadamente para mídia.

Alteração: analisar a legenda textual sem precisar baixar a imagem, com precedência de emergência. Para mídia sem legenda, manter a orientação sobre os formatos aceitos. Aceite: a legenda acima abre chamado crítico. Esse desvio também independe da qualidade do modelo.

### P1. Variações de linguagem rebaixam situações de risco

Entradas e resultados sem IA:

* “nao consigo respira me ajuda pfv”: Urgente, em vez do protocolo crítico já usado para “não consigo respirar”.
* “ele está me seguindo e estou com medo”, após relato de assédio: novo chamado neutro com texto sobre sinalizar o pessoal do palco.
* “o segurança me agrediu, esse filho da puta me bateu”: Urgente, com resposta de reclamação sobre supervisor, sem coleta de localização.

Alteração: cobrir variantes de escrita e relatos de agressão, preservar o estado de risco da conversa e impedir FAQ comum de substituir atendimento de segurança. Aceite: manter prioridade de segurança e coletar o local; palavrão dentro de denúncia não deve virar punição ao denunciante.

### P1. Recuperação de ficha responde sobre o produto errado

Entrada: “quanto custa a água?”. Observado: “Camiseta R$ 89,90 e moletom R$ 139,90, com kit a R$ 199,90, os preços sobem por”.

Sequência “tem seda?” → “onde eu compro?” → “quanto custa?”: responde inicialmente que não sabe, depois sobre copo/tirante e finalmente sobre camiseta/moletom.

Causa: `match_knowledge` soma gatilhos genéricos e escolhe uma ficha mesmo sem confirmar produto e intenção; a reserva não resolve referências pela conversa.

Alteração: exigir compatibilidade de assunto/produto e um mínimo de confiança; em empate ou referência sem contexto, esclarecer em vez de escolher qualquer preço. Aceite: água nunca retorna preço de camiseta; continuação mantém produto ou admite não saber.

### P1. Reclamação de acessibilidade vira resposta informativa

Entrada: “sou cadeirante e a rampa está bloqueada”.

Observado: chamado neutro, região inferida “Apoio PCD Central • Pista”, explicação de área elevada e pulseira PCD. Não reconhece o bloqueio da passagem nem pede qual rampa.

Alteração: separar consulta sobre acessibilidade de barreira concreta de acesso. Registrar urgência operacional e perguntar qual rampa, sem assumir onde o participante está apenas pela palavra “cadeirante”. Aceite: chamado de apoio com referência correta e sem orientação genérica de cadastro como resposta principal.

### P1. GPS enviado antes do relato não é reaproveitado

Sequência: localização GPS → “tem uma pessoa desmaiada aqui”.

Observado: o bot confirma que recebeu a localização; depois abre crítico sem coordenadas e pede a localização novamente.

Alteração: manter a última localização explícita com prazo curto, vinculando-a ao relato imediatamente seguinte e indicando sua origem e idade. Aceite: não repetir a solicitação no caso imediato; localização antiga ou contraditória deve exigir confirmação.

### P2. Negação gera falso chamado crítico

Entrada: “não tem briga aqui, só quero saber onde fica o banheiro”.

Observado sem IA: protocolo crítico e pedido de localização.

Alteração: considerar negação e contexto na reserva, com cautela para não descartar um segundo risco na mesma mensagem. Aceite: este exemplo responde sobre banheiro; “não tem briga, mas alguém desmaiou” continua crítico.

### P2. Base contém resposta truncada e instrução interna

Observado na cópia local: texto de roupas termina em “os preços sobem por”. A resposta para cobrança duplicada mostra “junto. (Regra 12: nunca prometer devolução.)”.

Alteração: revisar campos públicos, separar orientação interna de resposta ao participante e validar publicação para conteúdo incompleto. Aceite: nenhum texto interno ou frase cortada em respostas diretas, inclusive com IA fora do ar.

### P2. Encaminhamento humano é pouco específico

Entrada: “quero falar com uma pessoa”. Observado sem IA: cria chamado neutro e devolve “Não tenho essa informação confirmada”, sem explicar como acessar atendimento humano.

Alteração: reconhecer explicitamente a intenção, informar o canal humano real e definir fila/estado de transferência conforme a operação. Não prometer que alguém responderá no WhatsApp sem esse serviço existir. Aceite: o participante entende o próximo passo e o operador consegue localizar o pedido.

### P2. Conversas e dúvidas geram chamados adicionais na reserva

“Quem é você?” vira chamado neutro; continuações como “quero” geram novo chamado; dúvidas respondidas também criam feedback. Parte disso é intencional para analytics, mas misturar esses registros com incidentes aumenta ruído e contribui para o erro de vínculo de GPS.

Alteração: separar métricas de conversa/FAQ de incidentes que exigem ação, mantendo os dados necessários de satisfação. Aceite: o painel operacional não apresenta simples apresentação do bot como tarefa pendente, e GPS não é capturado por uma FAQ.

## Comportamentos que funcionaram nesta bateria

* Desmaio explícito, assédio explícito, fumaça no gerador e SOS com QR inválido geraram crítico e pedido de localização.
* “Esse show tá pegando fogo, maravilhoso!” foi reconhecido como elogio, sem falso alarme de incêndio.
* “Tô com fome” seguido de “na pista” manteve contexto e orientou para alimentação.
* Reclamação “esse evento tá uma merda”, seguida de “lixo”, foi registrada sem punir a reclamação como ofensa.
* Para comida garantidamente sem glúten, a reserva não inventou garantia.
* O pedido malicioso de aprovação de reembolso não aprovou pagamento. Isso não comprova resistência do modelo real a injeção de instruções.
* Figurinha foi ignorada sem resposta desnecessária.
* A suíte automatizada validou os seus cenários existentes de localização, áudio, webhook, persistência simulada, proteção, laboratório e motores alternativos. São testes de código, sem comprovação de entrega em produção.

## Ordem sugerida para correções

1. Precedência de emergência antes dos atalhos de app, mídia e bloqueios, com proteção específica contra abuso.
2. Identidade persistente do incidente e vínculo explícito da localização, inclusive mensagens complementares.
3. Cobertura de pessoa desaparecida, agressão e grafias de socorro; conservar risco durante a conversa.
4. Recuperação de fichas por assunto, eliminação de preços incompatíveis e reconhecimento de barreiras de acessibilidade.
5. Revisão editorial da base, transferência humana e separação de analytics da fila operacional.
6. Repetir os casos como testes de regressão e executar a bateria com IA real autorizada. Depois validar entrega Meta e o acompanhamento do operador em ambiente de teste.

## Decisões de operação que fazem diferença

* Quem recebe e assume um crítico, e como saber que alguém realmente o viu? “A equipe foi avisada” hoje acompanha o registro, não comprova leitura ou deslocamento.
* Qual o próximo passo se o participante pede ajuda e o operador não assume? Definir responsável e escalonamento antes da festa.
* Se a IA falhar durante pico, o comportamento precisa ser seguro por si só. A reserva testada responde, mas nem sempre interpreta o problema corretamente.
* Uma pessoa pode registrar dois problemas diferentes. O vínculo de GPS deve usar o incidente pendente, com esclarecimento se houver ambiguidade, e não apenas o mais recente ou o mais grave.
* O snapshot e a janela do evento devem vir da mesma versão publicada. Há indicação de abertura às 15h no texto e início às 15h30 na janela do snapshot; verificar se são conceitos distintos ou cadastro divergente antes de tratar como erro.

## Entregáveis e reprodução

* `scripts/auditoria_festa_25.py`: bateria de conversas. Rodar com argumento `fallback` para execução sem IA; `live` só após autorização de envio externo e custo.
* `out/auditoria-festa-25-fallback.json`: mensagens, respostas, estados e chamados simulados.
* `out/auditoria-festa-25-dirigida.json`: verificações dos atalhos e hashes dos arquivos.
* `out/auditoria-festa-25-suite-isolada.log`: resultado final dos 513 testes.

Commit observado ao término da reexecução: `57a174ca72e69bf13081ae1357eec3cf76f2ef71`. Houve mudanças externas durante o trabalho; os hashes abaixo identificam os arquivos inspecionados na etapa dirigida. Não foram aplicadas correções de comportamento nesta auditoria.

## Apêndice: respostas completas observadas

'''

for i,row in enumerate(data['rows'],1):
    result=row.get('result',{})
    report+=f"### Caso {i:02d}: {row['scenario']}\n\n"
    report+=f"Mensagem: {row['message']}\n\n"
    if 'count' in row:
        report+=f"Contagem na janela: {row['count']}. Strikes anteriores: {row['strikes']}.\n\n"
    report+=f"Tipo: {row.get('kind','text')}. Status: {result.get('status')}. Bloqueio: {result.get('blocked') or result.get('notes') or 'nenhum'}.\n\n"
    replies=result.get('messages',[])
    for msg in replies:
        if isinstance(msg,str): text=msg
        elif msg.get('type')=='image': text='[Imagem enfileirada, conteúdo visual não inspecionado] '+msg.get('content','')
        else: text=msg.get('content','')
        report+='Resposta:\n\n'+ '\n'.join('> '+line for line in text.splitlines())+'\n\n'
    if not replies: report+='Resposta: nenhuma.\n\n'
    cards=row.get('cards',[])
    report+=f"Chamados acumulados na conversa: {len(cards)}.\n\n"
    for card in cards:
        report+=f"* {card.get('urgency')}: {card.get('content')}. Região: {card.get('region')}. GPS: {card.get('coords','ausente')}.\n"
    report+='\n'

report+='## Apêndice: identificação dos arquivos\n\n```json\n'+json.dumps(direct['metadata'],indent=2)+'\n```\n'
assert '\u2014' not in report
path=ROOT/'docs/RELATORIO_AUDITORIA_TUCA_FESTA_25_09_2026.md'
path.write_text(report,encoding='utf-8')
print(path)
