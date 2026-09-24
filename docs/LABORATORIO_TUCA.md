# Laboratório TUCA

Implementado em 24/09/2026. Acesso no painel: **Ferramentas > Testes lado a lado** (também disponível em **Tuca > Comparar os três Tucas**), rota `/tuca/laboratorio`. Requer o login administrativo existente.

## Como comparar

1. Escolha a configuração publicada ou o rascunho do painel.
2. Envie uma mensagem para receber as três respostas. Cada lado mantém sua própria memória.
3. Continue a conversa, incluindo localização textual, GPS ou QR quando necessário.
4. Confira resposta, prioridade, localização, fontes e quantidade de chamados simulados.
5. Vote por rodada, acrescente observações e exporte o comparativo em JSON.

A base de regras, fichas e setores fica congelada na abertura da comparação. Os três motores recebem a mesma mensagem e a mesma base. O identificador da base e a revisão do código acompanham a exportação. O lado atual executa o worker desta versão local do código; isso não comprova equivalência com uma versão diferente ainda instalada no servidor.

## Minha versão experimental

- Atendimento acolhedor, com respostas positivas e humor nos elogios.
- Protocolo direto para emergências explícitas, sem depender de uma classificação da IA para reconhecer esses casos.
- Respostas informativas com trechos oficiais verificáveis e fontes exibidas.
- Encaminhamento simulado quando falta informação confiável.
- Detecção de divergências nos horários de abertura dos portões e término do evento.
- Localização associada ao chamado pendente específico, inclusive após uma pergunta intermediária.
- Elogios e agradecimentos não abrem chamados operacionais no experimental. Uma futura integração deve tratar métricas de satisfação separadamente.

## Isolamento e limites

O laboratório usa a API de IA configurada e consome tokens. Chamados, mensagens de saída e anexação de localização usam armazenamento simulado. Não envia WhatsApp, não publica regras e não promove o experimental para produção.

A sessão pertence ao login que a criou, tem estado assinado, expira após 30 minutos e permite até 60 rodadas. Atualizar a página inicia uma nova comparação; exporte antes para preservar suas avaliações. O JSON exportado contém as conversas e avaliações, mas não os tokens de sessão.

O teste cobre texto, QR e GPS. Não mede entrega real de WhatsApp, áudio, disponibilidade da equipe ou capacidade do ambiente de produção. A seleção de informações ainda pode errar a relevância, e a detecção de contradições não é universal. Trechos verificáveis reduzem invenções, mas não garantem que a base oficial esteja correta.

## Validação realizada

- 396 testes automatizados aprovados, incluindo 32 testes novos do laboratório.
- Ensaio com IA real de 9 mensagens sequenciais, enviadas aos dois motores: 18 processamentos.
- Cenários: água, horário conflitante, elogio, emergência, dúvida desconhecida, localização textual, GPS, incidente e agradecimento.
- Interface conferida em desktop e celular. Voto, observação e exportação verificados pelo navegador.
- No teste final de portões, o atual respondeu 15h; o experimental identificou divergência e encaminhou para confirmação.

Durante o ensaio, corrigimos dois problemas do experimental: escolha de uma informação oficial pouco relevante para a pergunta sobre água; e criação duplicada de chamado ao receber uma localização depois de uma emergência. Foram adicionadas regressões para ambos.

## Arquivos e publicação

- `tuca_experimental.py`: protocolos, seleção de fontes e memória do experimental.
- `tuca_lab.py`: isolamento da configuração e armazenamento simulado, execução dos motores.
- `tuca_lab_routes.py`: endpoints autenticados e validação de sessões.
- `templates/tuca_lab.html`, `static/tuca_lab.js`, `static/tuca_lab.css`: interface.
- `tests/test_tuca_lab.py`: regressões e isolamento.

A prévia local está em `http://127.0.0.1:5057/tuca/laboratorio`, enquanto o processo local estiver em execução. Essa prévia usa uma cópia das informações consultadas, sem acesso ao banco de produção. Login exclusivo da prévia: `lab`, senha `TesteLocalTuca2026`.

O código ainda precisa ser publicado no servidor para que a nova tela apareça no painel remoto. Publicar a tela não altera automaticamente o motor de atendimento de produção. A adoção do experimental exige integração com persistência e envio reais, além de validação ponta a ponta.

Antes do evento, a equipe precisa resolver os horários oficiais conflitantes. Nenhum motor pode garantir uma resposta correta quando a própria base contém respostas diferentes.


## Terceiro motor: TUCA JEV + LLM (24/09/2026)

A comparação agora inclui atual, experimental e JEV + LLM. Uma mensagem alimenta os três motores, com memória independente. Votos e exportação incluem a terceira opção.

O JEV avalia intenção, risco, localização, conflito e relevância de cada fonte. O código aplica limites; a LLM recebe somente as fontes aprovadas para selecionar trechos literais. Ela não pode mudar a intenção, prioridade ou localização decididas nessa etapa. A busca local também não pode reintroduzir uma fonte rejeitada pelo JEV.

Emergências explícitas e GPS usam protocolos diretos. A interface identifica essas rodadas como sem consulta ao JEV. Em falta de chave, timeout ou resposta inválida, o terceiro motor informa nos detalhes que usou a reserva e encaminha a dúvida simulada sem inventar fatos. Isso não é contabilizado como uma decisão bem-sucedida do JEV.

### Configurações no painel

Abra **Configurar JEV** na própria aba de testes:

- Chave TypeSafe: campo de senha. Em branco preserva a configuração existente.
- Modelo inicial: `jev-1.13.0`, verificado na API real. A versão fixa facilita reproduzir comparações.
- Confiança mínima de intenção: `0.75`.
- Limite de localização: `0.90`, aplicado tanto à confiança do setor quanto à probabilidade de a pessoa ter informado sua localização atual.
- Probabilidade mínima de relevância da fonte: `0.85`.
- Tempo limite de leitura da API: `12` segundos, configurável entre 3 e 20.
- Testar conexão: consulta uma saudação fictícia usando a configuração já salva.

Esses valores são iniciais, não limites calibrados para todos os participantes. Risco físico usa política conservadora fixa: probabilidade a partir de `0.35` aciona protocolo crítico. Confiança do Choice é um resumo da distribuição, não percentual de acerto. Os detalhes mostram as probabilidades separadamente.

Salvar os limites não modifica uma comparação em andamento. Inicie **Iniciar nova conversa** para aplicá-los. Trocar a chave vale para a chamada seguinte. Exporte os resultados antes de iniciar outra comparação.

### Chave e publicação

A chave local autorizada foi importada para `.env`, ignorado pelo Git. Ela não é enviada no commit, nos tokens de sessão ou na exportação. O ambiente remoto precisa receber sua própria configuração: cole a chave no campo do painel e salve, ou configure `TYPESAFE_API_KEY` no servidor.

A chave salva pelo painel tem prioridade sobre a variável de ambiente. Remover a chave do painel volta a usar a variável, se ela existir. O sistema nunca devolve a chave em respostas HTTP.

Configurações privadas ficam em `instance/tuca-jev.json`, fora do Git e da imagem Docker, com gravação atômica e permissão restrita no sistema de arquivos. Esse arquivo contém o segredo e deve permanecer acessível apenas ao usuário do serviço e aos administradores do servidor. O Compose monta o volume persistente `tuca_lab_private` em `/app/instance`. Em outra plataforma, monte armazenamento privado persistente nesse caminho ou configure `TUCA_JEV_CONFIG_FILE`; sem persistência, configurações salvas na tela podem ser perdidas na recriação do container. A variável `TYPESAFE_API_KEY` evita depender do arquivo para a chave.

Nenhuma mensagem real de participante foi usada para validar esta integração. A bateria autorizada enviou regras, fichas, setores e histórico fictício à TypeSafe e à OpenAI. Continuam simulados banco e WhatsApp.

### Validação da integração

- 416 testes automatizados aprovados, incluindo 20 novos testes do JEV.
- Conexão real com `jev-1.13.0` confirmada.
- 10 mensagens sequenciais nos três motores: 30 processamentos com IA real onde aplicável.
- Casos: água gratuita, horário conflitante, elogio metafórico, emergência, Wi-Fi desconhecido, localização posterior à emergência, GPS, falta de gelo, agradecimento e tentativa de impor instruções.
- JEV: água com fonte, conflito encaminhado, elogio sem chamado, localização no chamado pendente e nenhum chamado duplicado nessa sequência.

Arquivos principais: `tuca_jev.py` e `tuca_jev_config.py`. Regressões em `tests/test_tuca_jev.py`.


A interface também foi validada em desktop e celular: salvar configurações, testar conexão, votar no JEV e exportar as três respostas com probabilidades. Foi repetida a pergunta de água pela interface, além da bateria de 30 processamentos. Nessa repetição, o motor atual acrescentou caracteres em outro idioma, ausentes da base oficial; experimental e JEV mantiveram o trecho da fonte. Essa ocorrência foi preservada no comparativo local e não é evidência suficiente para estimar uma taxa de falha.

A caixa de mensagem informa explicitamente que envios sucessivos continuam a mesma conversa, com contador da próxima mensagem. O botão Iniciar nova conversa zera os três históricos. Atualizar a página ou trocar a base também reinicia.
