# Laboratório TUCA

Implementado em 24/09/2026. Acesso no painel: **Ferramentas > Testes lado a lado** (também disponível em **Tuca > Comparar os dois Tucas**), rota `/tuca/laboratorio`. Requer o login administrativo existente.

## Como comparar

1. Escolha a configuração publicada ou o rascunho do painel.
2. Envie uma mensagem para receber as duas respostas. Cada lado mantém sua própria memória.
3. Continue a conversa, incluindo localização textual, GPS ou QR quando necessário.
4. Confira resposta, prioridade, localização, fontes e quantidade de chamados simulados.
5. Vote por rodada, acrescente observações e exporte o comparativo em JSON.

A base de regras, fichas e setores fica congelada na abertura da comparação. Os dois lados recebem a mesma mensagem e a mesma base. O identificador da base e a revisão do código acompanham a exportação. O lado atual executa o worker desta versão local do código; isso não comprova equivalência com uma versão diferente ainda instalada no servidor.

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
