# 🛡️ Plano Diretor de Segurança & Mitigação de Riscos
## Tuca × Tropicadelia 2026 — Operação e Proteção Contra Adulteração de QR Codes (Anti-Quishing)

> **Documento Estratégico e Diretriz Operacional**  
> **Evento:** Tropicadelia Festival 2026  
> **Local:** Parque de Exposições Governador Ney Braga — Londrina/PR  
> **Responsáveis:** Coordenação Técnica Tuca & Diretoria de Operações Tropicadelia  
> **Versão:** 1.1, Setembro/2026 (Camada 4 revisada após auditoria de 20/09)  

---

## 1. Contexto & Vetores de Ameaça em Grandes Festivais

Em eventos de grande porte (20k+ pessoas), a interface primária entre o público e o sistema de atendimento em tempo real é o **QR Code físico** espalhado pelos setores da planta (banheiros, bares, palcos, postos médicos e acessos).

O principal risco identificado pela diretoria e sócios é o **Quishing** (*QR Code Phishing*) e a adulteração física: agentes mal-intencionados que tentam colar adesivos impressos por cima do QR Code oficial para:
1. **Golpes Financeiros (Falso Pix / Falso Bar):** Páginas falsas prometendo *"recarga de pulseira"* ou *"créditos de bebida"* com chave Pix fraudulenta.
2. **Engenharia Social & Clonagem:** Tentativas de capturar números de telefone ou códigos de verificação de WhatsApp.
3. **Phishing de Ingressos/Áreas VIP:** Falsas promoções ou promessas de "upgrade de camarote".
4. **Desinformação / Inundação Operacional:** Envio em massa de falsos chamados para dispersar a equipe de segurança.

Como a segurança física absoluta em um espaço aberto é inviável, adotamos o modelo de **Defesa em Profundidade (5 Camadas)**, onde múltiplas barreiras físicas, digitais, operacionais e de comunicação neutralizam o vetor de ataque antes que o frequentador seja lesado.

---

## 2. As 5 Camadas de Mitigação de Riscos

```
┌─────────────────────────────────────────────────────────────┐
│  CAMADA 1: Engenharia Física & Design Anti-Adulteração     │
├─────────────────────────────────────────────────────────────┤
│  CAMADA 2: Arquitetura Digital & Padrão Oficial Meta (WABA) │
├─────────────────────────────────────────────────────────────┤
│  CAMADA 3: Estratégia de Comunicação & "A Regra de Ouro"   │
├─────────────────────────────────────────────────────────────┤
│  CAMADA 4: Blindagem de Software, Backend & IA             │
├─────────────────────────────────────────────────────────────┤
│  CAMADA 5: Procedimento Operacional de Ronda em Campo (SOP) │
└─────────────────────────────────────────────────────────────┘
```

---

### CAMADA 1: Engenharia Física & Design Gráfico Anti-Adulteração

A primeira barreira deve tornar visualmente óbvia qualquer tentativa de adulteração:

1. **A "Regra do Número Visível" (Obrigatória na Arte):**
   * Nenhum cartaz conterá apenas o QR Code isolado. Todo material impresso terá em destaque, no rodapé imediato do código:
     > **"ESCANEOU? CONFIRA O NÚMERO NA SUA TELA: (43) 9XXXX-XXXX"**
   * O criminoso pode trocar o QR Code colando um adesivo por cima, mas **ele não consegue alterar o número oficial que a arte impressa informa ao frequentador**.
2. **Padrão de Fundo Contínuo e Texturizado:**
   * O QR Code não deve ficar isolado em um quadrado branco plano. A arte da Tropicadelia possui elementos visuais, gradientes e texturas que encostam e contornam os cantos do QR Code.
   * Qualquer adesivo colado por cima causará uma quebra gráfica visível de 10 a 20 metros de distância.
3. **Acabamento Físico Dificultador:**
   * **Verniz UV Localizado / Laminação Anti-aderente:** Reduz severamente a aderência de adesivos de papel comum ou vinil barato.
   * **Altura de Instalação:** Em áreas de grande fluxo ou filas (banheiros e bares), as placas de parede serão afixadas a partir de **1,80m a 2,00m de altura**, fora do alcance discreto de quem passa com um adesivo na mão.
4. **Serialização por Placa:**
   * Cada uma das placas distribuídas nos 26 setores da planta terá um identificador único de patrimônio no rodapé (ex: `TROPIC-26 • WC-SUL-04`). Isso permite que fiscais de campo auditem e registrem a integridade física de cada ponto.

---

### CAMADA 2: Arquitetura Digital & Padrão Oficial Meta WhatsApp

O que acontece no smartphone do frequentador no momento em que a câmera escaneia o código:

1. **WhatsApp Cloud API Oficial (WABA):**
   * O Tuca opera sob a infraestrutura oficial da Meta via Cloud API corporativa (Graph API v20+).
   * Não se trata de um chip pré-pago ou número comum: ao abrir a conversa, o próprio WhatsApp exibe a chancela nativa:
     > *"Esta é uma conta comercial oficial da Tropicadelia Festival"*.
   * Perfil comercial completo com logotipo oficial, descrição corporativa, link para o site do evento e horário de atendimento.
2. **Links Diretos Sem Intermediários:**
   * O QR Code apontará diretamente para o protocolo oficial do WhatsApp:
     `https://wa.me/5543XXXXXXXX?text=%23SETOR%3APALCO-PRINCIPAL`
   * **Sem encurtadores genéricos:** É proibido o uso de ferramentas públicas como `bit.ly` ou `tinyurl`. Caso se utilize redirecionamento próprio para telemetria de cliques, o domínio deve ser estritamente institucional com certificado SSL corporativo (ex: `https://chat.tropicadelia.com.br/setor/wc-sul`).

---

### CAMADA 3: Estratégia de Marketing, Comunicação & "A Regra de Ouro"

A conscientização do público transforma 20 mil frequentadores em auditores naturais:

1. **A "Regra de Ouro" Institucional:**
   > **"O Tuca é 100% gratuito e NUNCA pede Pix, dinheiro, senhas, cartões ou códigos de confirmação."**
   * Essa declaração será repetida sistematicamente:
     * No rodapé de 100% das placas de QR Code.
     * Na mensagem automática de boas-vindas do próprio bot no WhatsApp.
     * Na bio e nos destaques do Instagram oficial do evento.
2. **Comunicação Pré-Evento (Redes Sociais):**
   * Publicações informativas 48h e 24h antes da abertura dos portões:
     > *"Salve o número oficial da Tropicadelia na sua agenda: (43) 9XXXX-XXXX. Esse é o único canal de suporte, localização e achados e perdidos dentro do Parque Ney Braga."*
   * Frequentadores que já possuem o contato salvo na agenda abrem a conversa instantaneamente sem risco de desvio.
3. **Comunicação In Loco (Telões de Palco):**
   * Entre as atrações nos telões dos palcos (Principal e Hype), veiculação de vinheta institucional de 15 segundos exibindo o número oficial e reforçando que o serviço é gratuito e seguro.

---

### CAMADA 4: Blindagem Tecnológica do Software & Inteligência Artificial

O que está implementado e testado no código (auditoria e correções de 20/09/2026):

1. **Entrada só pela Meta, com assinatura:** todo webhook é validado por HMAC-SHA256 antes de qualquer leitura, mensagens repetidas são descartadas pelo ID da Meta, e o corpo da requisição tem teto de 1 MB.
2. **Imagem, vídeo, figurinha e documento nunca são baixados nem exibidos:** o bot pede texto ou áudio. Pornografia por imagem não entra no sistema em nenhum ponto.
3. **Moderação de conteúdo em toda mensagem de texto e em toda transcrição de áudio** (modelo `omni-moderation-latest`): conteúdo sexual, discurso de ódio e assédio explícito não viram chamado, não aparecem no telão e recebem um aviso fixo. Violência, drogas e emergência médica passam de propósito, porque são exatamente os relatos que a segurança e a equipe médica precisam ver. Três bloqueios em 10 minutos silenciam o número.
4. **Limite por número em dois degraus:** até 10 mensagens em 10 minutos tudo normal; da 11ª em diante o chamado continua sendo registrado, mas o bot avisa uma única vez e para de responder; acima de 30 a mensagem é descartada. Nenhuma emergência se perde por escrever em rajada, e um spammer não gera centenas de envios pela Meta.
5. **Áudio com cota:** cada áudio tem no máximo 1 minuto (a duração é lida no próprio arquivo antes de pagar a transcrição) e cada número pode mandar 3 áudios por hora. Trechos que o Whisper marca como música ou silêncio são descartados, para show ao fundo não virar chamado. Todo bloqueio explica o motivo ao participante.
6. **Proteção contra inundação geral:** acima de 60 mensagens por minuto somando todos os números, a IA é desligada e o bot cai no caminho determinístico. Os chamados continuam entrando.
7. **Guardrails de IA contra prompt injection:** o texto do público entra no prompt delimitado como dado, com instrução explícita de nunca obedecê-lo, e toda resposta passa por um filtro de saída: link, e-mail, telefone, chave Pix ou instrução de pagamento que não esteja no material oficial da produção derruba a resposta criativa, que é trocada pelo texto fixo. A classificação por IA só aceita categoria e região da lista fechada.
8. **Privacidade e LGPD:** o telefone do participante é pseudonimizado com HMAC-SHA256 (`PII_HASH_SECRET`) e as APIs do painel nunca devolvem identificador pessoal. O relatório e a exportação CSV escapam todo texto vindo do público.

---

### CAMADA 5: Procedimento Operacional Padrão (POP/SOP) em Campo

A equipe humana em solo garantirá a integridade física ao longo de todo o festival:

1. **Ronda de "Hora Zero" (Pré-Abertura):**
   * 2 horas antes da abertura dos portões, a liderança de operações de TI percorre os 26 setores da planta com o checklist oficial, escaneando cada QR Code para validar roteamento e ausência de danos.
2. **Ronda Preventiva Periódica (A cada 2 Horas):**
   * Fiscais de setor, brigadistas e líderes de equipe de higienização recebem no briefing a instrução: *"Ao inspecionar o setor, verifique o cartaz do Tuca. Caso note adesivo sobreposto ou rasura, remova imediatamente ou acione a central via rádio"*.
3. **Kit de Contingência Sobressalente:**
   * A sala de controle de TI manterá um estoque de 20 placas sobressalentes pré-impressas com fita dupla-face industrial de fixação rápida. Tempo máximo de substituição de uma placa danificada: **inferior a 5 minutos**.
4. **Alerta Rápido no Dashboard:**
   * Caso o público reporte no próprio WhatsApp frases como *"QR code falso"*, *"tem adesivo colado"* ou *"código estranho"*, o classificador operacional eleva o ticket automaticamente para prioridade **CRÍTICA**, enviando a equipe de segurança ao setor correspondente.

---

## 3. Matriz de Resposta a Incidentes (Guia Rápido)

| Incidente | Sintoma / Gatilho | Ação Imediata | Tempo de Resolução |
| :--- | :--- | :--- | :---: |
| **Adesivo colado sobre a placa** | Fiscal detecta ou público relata | Remoção manual imediata; troca por placa sobressalente do kit | < 5 min |
| **Tentativa de fazer o Tuca divulgar link ou Pix** | Injeção de prompt no texto ou no áudio | O filtro de saída derruba a resposta e vai o texto fixo; o bot nunca envia link fora do app oficial | Instantâneo (0s) |
| **Pornografia, ódio ou assédio no chat** | Texto ou áudio ofensivo | Moderação bloqueia, avisa o motivo e não cria chamado; 3 bloqueios silenciam o número | Instantâneo (0s) |
| **Tentativa de flooding/spam no bot** | Remetente enviando dezenas de msgs/min | Degraus por número (10 e 30 em 10 min) e teto global por minuto; o bot avisa uma vez e silencia | Automático |
| **Usuário com dúvida de autenticidade** | Frequentador pergunta se o canal é real | Bot envia mensagem institucional com selo oficial e Regra de Ouro | Instantâneo (0s) |

---

## 4. Alinhamento Executivo com os Sócios

Para a reunião de homologação com a diretoria do festival, utilize a seguinte síntese:

> *"A segurança do Tuca foi desenhada sob a premissa de que o ataque físico (colar adesivo) pode até ser tentado, mas é tornado inútil por 4 fatores conjugados:*
> 1. *O nosso canal tem **Selo Oficial de Empresa na Meta**, impossível de ser clonado num WhatsApp comum.*
> 2. *O número oficial estará impresso por extenso na própria arte e anunciado nos telões dos palcos.*
> 3. *Toda a comunicação do evento estabelece a **Regra de Ouro**: o Tuca é gratuito e jamais pede Pix, dinheiro ou senha.*
> 4. *Nossa equipe de campo possui protocolo de ronda a cada 2 horas nos 26 setores da planta física."*

---
*Documento homologado para integração técnica e operacional na infraestrutura do Tropicadelia 2026.*
