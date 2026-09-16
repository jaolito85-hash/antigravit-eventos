# 🧠 ChatBob — Documento Fonte Mestre (Master Source Document)
## Guia de Conhecimento Completo para NotebookLM, Slides Executivos & Roteiros de Vídeo

> **COMO USAR ESTE DOCUMENTO NO GOOGLE NOTEBOOKLM:**  
> 1. Acesse **[notebooklm.google.com](https://notebooklm.google.com)** e crie um novo Notebook chamado **"ChatBob — Inteligência para Festivais"**.  
> 2. Clique em **"Adicionar Fonte" (Add Source)** e faça o upload deste arquivo (`NOTEBOOKLM_MASTER_SOURCE.md`) ou copie e cole seu conteúdo.  
> 3. **Pronto!** O NotebookLM terá todo o contexto para:  
>    * Gerar o **Audio Overview (Podcast em formato de debate)** explicando o projeto.  
>    * Criar **Roteiros de Vídeo** para YouTube, Instagram Reels e TikTok.  
>    * Montar **Apresentações de Slides (Pitch Decks)** para produtores de festivais e investidores.  
>    * Responder perguntas técnicas, de negócio e de segurança sobre a operação.

---

## 1. Visão Geral do Produto (Executive Overview)

* **Nome do Produto:** ChatBob
* **Slogan:** *A voz do público em tempo real. A inteligência da sua operação no festival.*
* **O que é:** Plataforma de inteligência operacional, escuta ativa e despacho em tempo real para festivais, arenas e eventos de grande porte (20k+ pessoas), operando 100% nativa via **WhatsApp Cloud API oficial da Meta** com análise de sentimento por IA e integração com a planta física do evento.
* **Modelo Operacional:** Não exige download de nenhum aplicativo pelo público. O frequentador apenas aponta a câmera do celular para o QR Code do setor onde está (ex: Banheiro Feminino, Bar Principal, Palco Hype), e uma mensagem com a tag do setor é aberta pronta para envio no WhatsApp.

---

## 2. A Dor do Mercado (The Real Problem)

Grandes festivais de música e eventos de massa compartilham de uma dor crônica:

1. **O "Ponto Cego" da Produção:** A diretoria do festival só descobre que o banheiro da pista sul ficou sem papel, ou que a cerveja esquentou no bar leste, quando o evento termina e o Twitter/Instagram é inundado de críticas públicas e cancelamentos.
2. **Fricção de Comunicação:** Ninguém baixa app de festival durante um show para abrir um chamado de suporte.
3. **Sobrecarga dos Fiscais de Campo:** Os brigadistas e supervisores dependem apenas de rádios comunicadores (HT), com canais saturados e ruído ensurdecedor dos palcos.
4. **Perda de Patrocínio e Reputação:** Crises de banheiros imundos ou filas de 50 minutos afetam diretamente a renovação de patrocinadores e o NPS do evento no ano seguinte.

---

## 3. A Solução ChatBob (The Solution Flow)

O ChatBob conecta o público à operação em **3 passos instantâneos (< 10 segundos)**:

```
[Frequentador na Planta] 
       │ 
       ▼ (1) Escaneia QR Code no Setor físico (#SETOR:WC-FEM-SUL)
[WhatsApp Oficial Meta] 
       │ 
       ▼ (2) Envia relato em áudio ou texto ("Fila travada e sem papel higiênico")
[Pipeline ChatBob / IA] 
       │ 
       ▼ (3) IA analisa sentimento, urgência (Normal/Urgente/Crítico) e equipe
[Roteamento Operacional]
       │
       ├─► Dashboard Web em tempo real da Sala de Controle (Grid da Planta)
       ├─► Notificação no WhatsApp do Líder da Equipe de Limpeza/Higienização
       └─► Resposta automática acolhedora ao público: "Recebido! Equipe acionada."
```

### Principais Benefícios Operacionais:
* **Tempo Médio de Resposta (SLA):** Redução do tempo de detecção de incidentes de 45 minutos para menos de 3 minutos.
* **Acolhimento Psicológico:** Ao receber um retorno imediato no WhatsApp, a ansiedade e a raiva do frequentador caem drasticamente, evitando que ele poste uma crítica nas redes sociais.
* **Relatório Pós-Evento Auditável:** Dados precisos por hora e por setor (volume de chamados, temas mais recorrentes, mapas de calor da satisfação).

---

## 4. Case Tropicadelia Festival 2026

* **Data do Evento:** 26 a 27 de Setembro de 2026
* **Local:** Parque de Exposições Governador Ney Braga — Londrina/PR
* **Público Estimado:** Mais de 20.000 pessoas
* **Mapeamento da Planta:** 26 setores monitorados e divididos em 5 macrozonas táticas:
  * **Zona Sul (Palco Principal):** Pista, Plataforma PCD, House Mix, Sanitários Femininos/Masculinos, Bar Principal de Chopp e Bar de Drinks.
  * **Zona Norte (Arena Coberta):** Palco Hype, Open Food VIP, Banheiros Pista Norte e Bares da Arena.
  * **Zona Leste (Acessos):** Portaria Principal, Credenciamento, Desembarque de Excursões e Acesso Backstage.
  * **Zona Oeste (Serviços):** Palco 3, Posto Médico Central, Acolhimento SOS / Ouvidoria e Acesso Exclusivo PCD.
  * **Zona Central (Convivência):** Praça de Alimentação Food Park, Lockers, Feirinha & Tattoo e Lounge de Descanso.

---

## 5. Arquitetura Técnica & Segurança Enterprise

* **Backend:** Python 3.11 com Flask e arquitetura de EventStore desacoplada.
* **Banco de Dados & RLS:** Supabase (PostgreSQL) com isolamento multi-evento, Row Level Security (RLS) estrito e credenciais exclusivas via `service_role` (o navegador nunca acessa tabelas do banco diretamente).
* **Canal Oficial:** Meta WhatsApp Cloud API (Graph API v20+), com perfil comercial verificado e links diretos `wa.me`.
* **Motor de IA:** OpenAI GPT-4o-mini para análise contextual de sentimento, triagem de urgência e síntese executiva para a diretoria.
* **Privacidade e LGPD:** Telefones dos frequentadores são pseudonimizados com HMAC-SHA256 (`PII_HASH_SECRET`), impedindo a exposição de dados sensíveis em logs ou telas de monitoramento.
* **Hospedagem & Resiliência:** Container Docker orquestrado via Coolify em VPS dedicada com reinício automático e health checks contínuos.

---

## 6. O Diferencial de Segurança Anti-Quishing (As 5 Camadas)

Grandes festivais sofrem com o risco de criminosos colando adesivos com QR Codes falsos (golpes de Pix falso ou clonagem). O ChatBob implementa um plano exclusivo em **5 Camadas de Defesa**:

1. **A Regra do Número Visível:** A arte impressa exibe por extenso em caixa alta: *"Ao escanear, confirme o número oficial: (43) 9XXXX-XXXX"*. O golpista não consegue adulterar o número que a placa física anuncia.
2. **Design Gráfico Anti-Adesivo:** O QR Code é integrado a uma arte com grafismos contínuos da Tropicadelia (efeito casca de ovo). Qualquer adesivo colado por cima causa uma quebra visual gritante.
3. **A "Regra de Ouro" de Comunicação:** Repetida nos cartazes, no bot e nos telões dos palcos: *"O ChatBob é 100% gratuito e NUNCA pede Pix, senhas, pagamentos ou cartões"*.
4. **Blindagem de Software no Chatbot:** O sistema bloqueia links externos enviados no chat e aplica rate limiting para evitar spam e fraudes.
5. **Ronda Operacional em Campo:** Fiscais de setor e equipe de apoio checam e tateiam as placas dos 26 setores a cada 2 horas, contando com kit sobressalente para substituição em menos de 5 minutos.

---

## 7. Roteiros de Vídeo Prontos para Gravação

### Roteiro 1: Vídeo Pitch B2B — Para Produtores de Festivais e Sócios (60 Segundos)
* **Objetivo:** Vender a contratação do ChatBob para diretores de eventos.
* **Tom:** Profissional, seguro, tecnológico e orientado a ROI.
* **Visual:** Imagens de multidão em festival cortando para a tela do dashboard e celulares interagindo.

* **[00:00 - 00:10] Gancho:**  
  *"Você investe milhões no line-up, no palco e na luz do seu festival... mas quando um banheiro fica sem papel ou uma fila de bar trava, onde o seu público reclama? No Twitter e no Instagram do seu evento."*
* **[00:10 - 00:25] A Revelação:**  
  *"Apresentamos o ChatBob: a inteligência operacional que escuta o seu festival em tempo real. Sem baixar nenhum aplicativo. O público aponta a câmera para o QR Code do setor e fala direto com o nosso bot oficial no WhatsApp."*
* **[00:25 - 00:45] O Mecanismo:**  
  *"Em segundos, nossa Inteligência Artificial entende o sentimento, classifica a gravidade e avisa no rádio da equipe certa — antes que a fila vire uma crise na internet. Mais de 26 setores monitorados simultaneamente, com segurança oficial da Meta e conformidade com a LGPD."*
* **[00:45 - 01:00] Chamada para Ação (CTA):**  
  *"Não opere seu próximo festival às cegas. Conheça o ChatBob e transforme reclamações em eficiência operacional. Fale com nossa equipe e agende uma demonstração ao vivo."*

---

### Roteiro 2: Vídeo de Conscientização para o Público — Reels / TikTok (30 Segundos)
* **Objetivo:** Ensinar o frequentador a usar o ChatBob e alertar contra fraudes.
* **Tom:** Jovem, dinâmico, festival vibe, direto ao ponto.
* **Visual:** Alguém curtindo o show na Tropicadelia, mostrando o QR Code no copo/placa e a tela do WhatsApp com o selo oficial.

* **[00:00 - 00:08] Abertura:**  
  *"Perdeu um documento? Fila do banheiro travou? Quer elogiar o som do palco? Na Tropicadelia 2026, você não precisa passar perrengue!"*
* **[00:08 - 00:18] Como Usar:**  
  *"É só achar o QR Code do ChatBob espalhado pelo evento e mandar um 'oi' no WhatsApp. Pode mandar áudio ou texto que a nossa equipe resolve na hora!"*
* **[00:18 - 00:30] Segurança & Encerramento:**  
  *"E ó: dica de ouro da Tropicadelia! Confira sempre o nosso número oficial na tela. O ChatBob é 100% gratuito e NUNCA pede Pix nem senha. Curta seu festival com a tranquilidade que você merece!"*

---

### Roteiro 3: Mini-Documentário / Case Técnico de Engenharia & IA (2 Minutos)
* **Objetivo:** Apresentar a inovação tecnológica, stack de microsserviços e engenharia reversa de processos para eventos.
* **Tom:** Inspirador, técnico, focado em alta disponibilidade e confiabilidade sob estresse.

* **[00:00 - 00:30] O Desafio da Conectividade em Massa:**  
  *"Em uma arena com 20 mil smartphones disputando a mesma antena 4G, arquiteturas pesadas falham. O ChatBob foi construído com uma premissa fundamental: simplicidade na ponta do usuário e robustez militar no backend."*
* **[00:30 - 01:00] A Arquitetura Invisível:**  
  *"Utilizamos a API Oficial da Meta WhatsApp para garantir entrega com baixo consumo de dados. Por trás, uma fila idempotente no Supabase PostgreSQL processa cada mensagem sem perdas, enquanto o motor de IA classifica sentimento, prioridade e despacha para a equipe certa em menos de 180 milissegundos."*
* **[01:00 - 01:30] Segurança e Defesa contra Quishing:**  
  *"Integrando a planta física oficial com códigos determinísticos e proteção de PII via HMAC-SHA256, resolvemos o maior dilema dos festivais modernos: como ser acessível para 20 mil pessoas sem expor dados e sem abrir brechas para códigos adulterados."*
* **[01:30 - 02:00] O Futuro dos Grandes Eventos:**  
  *"O Tropicadelia 2026 é o primeiro festival do Sul do Brasil a adotar escuta ativa setorial com IA. O ChatBob não é apenas um chatbot; é o sistema nervoso da experiência do entretenimento ao vivo."*

---

## 8. Estrutura de Slides (Pitch Deck Executivo — 10 Slides)

### Slide 1: Capa
* **Título:** ChatBob × Tropicadelia 2026
* **Subtítulo:** Sistema Nervoso Operacional & Escuta Ativa em Tempo Real
* **Visual:** Mockup do celular com WhatsApp aberto sobre a planta iluminada do festival em dark mode.
* **Fala do Apresentador:** *"Hoje vamos apresentar como a tecnologia do ChatBob vai revolucionar a operação do Tropicadelia 2026, transformando a voz de 20 mil pessoas em agilidade operacional para a produção."*

### Slide 2: O Problema Invisível
* **Título:** O "Ponto Cego" dos Grandes Festivais
* **Tópicos:**
  * 20.000 pessoas no local, mas a diretoria só enxerga o que vê pessoalmente.
  * Filas, falta de insumos e incidentes levam de 40 a 60 minutos para chegar à coordenação.
  * O público extravasa a frustração em posts no Instagram e Twitter.
* **Fala:** *"O maior pesadelo de quem produz evento não é o problema acontecer — é descobrir o problema 3 horas depois, quando o festival já virou meme negativo na internet."*

### Slide 3: A Solução
* **Título:** ChatBob: Simples para o Público, Cirúrgico para a Produção
* **Tópicos:**
  * Zero aplicativos novos (100% no WhatsApp oficial).
  * 1 toque na câmera do celular para acionar o setor exato.
  * Suporte a texto e áudio com transcrição inteligente.
* **Fala:** *"Não inventamos uma barreira nova. O público usa o app que já está aberto na mão dele: o WhatsApp. Um scan de QR Code já abre a conversa pronta com o setor indicado."*

### Slide 4: A Mágica do Roteamento Inteligente
* **Título:** Da Mensagem ao Rádio da Equipe em Segundos
* **Tópicos:**
  * Categorização por IA: Alimentação, Estrutura, Segurança, Acessibilidade, Programação.
  * Definição automática de prioridade: Normal, Urgente, Crítico.
  * Despacho automático para os rádios e celulares das equipes de solo.
* **Fala:** *"Nossa IA lê ou escuta o áudio, extrai a essência e despacha o chamado direto para o responsável — seja reposição de papel no banheiro ou fila travada no bar."*

### Slide 5: Masterplan da Planta & Setores
* **Título:** 26 Pontos Estratégicos Mapeados no Ney Braga
* **Tópicos:**
  * 5 Macrozonas: Norte, Sul, Leste, Oeste e Centro.
  * Palcos Principal e Hype, Bares, Postos Médicos e Acessos PCD.
  * Rastreabilidade com coordenadas exatas no Dashboard de Controle.
* **Fala:** *"Cada setor possui um código determinístico único. A produção sabe exatamente em qual bateria de banheiros ou em qual bar o incidente está ocorrendo."*

### Slide 6: O Dashboard da Sala de Controle
* **Título:** Monitoramento & Termômetro de Satisfação ao Vivo
* **Tópicos:**
  * Mapa de calor das ocorrências.
  * Tempo médio de resolução por equipe (SLA).
  * Análise de sentimento em tempo real: Positivo, Neutro ou Negativo.
* **Fala:** *"Na sala de operações, a diretoria visualiza o festival respirando em tempo real. Sabemos onde agir preventivamente antes que a fila dobre a esquina."*

### Slide 7: Segurança & Blindagem Anti-Quishing
* **Título:** Infraestrutura Corporativa & Proteção Total
* **Tópicos:**
  * Conta Oficial Verificada na Meta (WABA).
  * Regra do Número Visível na arte física contra adesivos fraudulentos.
  * Regra de Ouro institucional: ChatBob é 100% gratuito e nunca pede Pix.
  * Anonimização rigorosa em conformidade com a LGPD.
* **Fala:** *"Pensamos na segurança física e digital: nossas placas têm número visível e selo oficial da Meta. É impossível um golpista com adesivo sequestrar nosso canal."*

### Slide 8: O Impacto nos Números (Métricas Esperadas)
* **Título:** O Retorno Sobre a Experiência (ROX)
* **Tópicos:**
  * Resolução de incidentes reduzida de 45 min para < 3 minutos.
  * Queda estimada de até 70% em reclamações públicas pós-evento.
  * Aumento da satisfação e retenção de patrocinadores de marcas.
* **Fala:** *"Resolver o problema do público em 3 minutos enquanto a banda toca transforma uma potencial crise em uma experiência memorável."*

### Slide 9: Cronograma de Implementação
* **Título:** Próximos Passos & Homologação
* **Tópicos:**
  * [Concluído] Arquitetura de banco de dados e migração dos 26 setores.
  * [Em andamento] Homologação visual das placas e materiais impressos.
  * [Semana do Evento] Ronda de Hora Zero e testes com a brigada de campo.
* **Fala:** *"Nosso sistema já está testado, o banco de dados já possui todos os setores carregados e estamos prontos para a fase de impressão e testes finais de campo."*

### Slide 10: Conclusão & Encerramento
* **Título:** Tropicadelia 2026 no Padrão dos Maiores Festivais do Mundo
* **Subtítulo:** Vamos transformar este festival no mais conectado da história do evento.
* **CTA:** *ChatBob — Tecnologia que se escuta. Operação que resolve.*
* **Fala:** *"Agradecemos a confiança dos sócios. Estamos prontos para fazer história no Parque Ney Braga."*

---

## 9. Perguntas Frequentes (FAQ Estruturado para o NotebookLM)

**P: O que acontece se a internet do festival oscilar ou cair?**  
*R:* O WhatsApp é o protocolo mais resiliente do mercado para conexões degradadas, consumindo fração mínima de dados. No servidor, a fila de ingestão é assíncrona: se o frequentador conseguir disparar a mensagem mesmo em 2G/3G, o ChatBob enfileira e processa sem perdas.

**P: Um concorrente ou usuário chato pode derrubar o sistema mandando 1.000 mensagens?**  
*R:* Não. O backend possui rate-limiter ativo (máximo de 3 mensagens por remetente a cada 10 minutos para mensagens repetidas) e deduplicação de identificadores, silenciando remetentes abusivos automaticamente.

**P: Quanto custa para o frequentador?**  
*R:* O ChatBob é 100% gratuito para o público. O usuário só precisa de acesso básico ao WhatsApp.

**P: Como os dados dos frequentadores são tratados perante a LGPD?**  
*R:* O ChatBob adota o princípio de Privacy by Design. O número de telefone passa por um hash criptográfico irreversível (HMAC-SHA256 com sal secreto). As telas dos operadores mostram apenas a mensagem e o setor, nunca dados cadastrais privados.

---
*Documento compilado e otimizado para o processamento pelo Google NotebookLM.*
