"""Gera a apresentação executiva da Planta e Matriz de QR Codes do Tropicadelia 2026 em HTML e PDF."""

import base64
import os
import subprocess
import sys

IMAGE_PATH = os.path.abspath("docs/assets/planta-tropicadelia-2026.jpg")
HTML_OUTPUT = os.path.abspath("docs/tuca-tropicadelia-masterplan-planta.html")
PDF_OUTPUT = os.path.abspath("docs/Tuca-Tropicadelia-Masterplan-Planta.pdf")

with open(IMAGE_PATH, "rb") as f:
    b64_image = base64.b64encode(f.read()).decode("utf-8")

html_content = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tuca × Tropicadelia 2026 — Masterplan Operacional & Matriz da Planta</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800;900&family=Righteous&display=swap');

    :root {{
      --ink: #0a0a0c;
      --paper: #f8f8f5;
      --neon: #f0f400;
      --pink: #d72c72;
      --blue: #1677ff;
      --green: #10b981;
      --dark-card: #141418;
      --border-dark: #27272a;
      --muted: #64748b;
    }}

    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      padding: 0;
      background: #202024;
      color: var(--ink);
      font-family: "Poppins", Arial, sans-serif;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}

    @page {{
      size: A4 portrait;
      margin: 0;
    }}

    .page {{
      position: relative;
      width: 210mm;
      height: 297mm;
      margin: 0 auto 8mm;
      padding: 16mm 16mm 14mm;
      overflow: hidden;
      background: var(--paper);
      page-break-after: always;
      display: flex;
      flex-direction: column;
    }}
    .page:last-child {{ page-break-after: auto; }}

    .dark {{
      background: var(--ink);
      color: #ffffff;
    }}

    /* Top decor & headers */
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 4mm;
      font-size: 7.5pt;
      font-weight: 800;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--pink);
    }}
    .dark .eyebrow {{
      color: var(--neon);
    }}
    .eyebrow::before {{
      content: "";
      width: 20px;
      height: 4px;
      background: currentColor;
    }}

    h1, h2, h3, h4, p {{ margin-top: 0; }}

    h1 {{
      font: 400 38pt/0.95 "Righteous", Impact, sans-serif;
      letter-spacing: -0.5px;
      margin-bottom: 5mm;
    }}
    h2 {{
      font: 400 24pt/1.05 "Righteous", Impact, sans-serif;
      letter-spacing: -0.3px;
      margin-bottom: 4mm;
    }}
    h3 {{
      font-size: 11pt;
      font-weight: 700;
      margin-bottom: 2mm;
    }}

    .pink {{ color: var(--pink); }}
    .neon {{ color: var(--neon); }}
    .blue {{ color: var(--blue); }}

    .lead {{
      font-size: 10.5pt;
      line-height: 1.45;
      font-weight: 500;
      color: #334155;
      margin-bottom: 5mm;
    }}
    .dark .lead {{
      color: #cbd5e1;
    }}

    /* Grid & Cards */
    .grid-2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 5mm;
    }}
    .grid-3 {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 4mm;
    }}
    .grid-4 {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 3.5mm;
    }}

    .card {{
      padding: 4.5mm;
      border: 1px solid #e2e8f0;
      background: #ffffff;
      border-radius: 2mm;
    }}
    .dark .card {{
      background: var(--dark-card);
      border-color: var(--border-dark);
      color: #f1f5f9;
    }}
    .card.accent {{
      background: var(--pink);
      border-color: var(--pink);
      color: #ffffff;
    }}
    .card.neon-accent {{
      background: var(--neon);
      border-color: var(--neon);
      color: #0a0a0c;
    }}

    .tag {{
      display: inline-block;
      padding: 1mm 2.2mm;
      border-radius: 1mm;
      font-size: 6.8pt;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      background: var(--pink);
      color: #ffffff;
      margin-bottom: 1.5mm;
    }}
    .tag.neon-tag {{
      background: var(--neon);
      color: #0a0a0c;
    }}
    .tag.blue-tag {{
      background: var(--blue);
      color: #ffffff;
    }}
    .tag.gray-tag {{
      background: #334155;
      color: #ffffff;
    }}

    /* Tables */
    table.data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 7.6pt;
      margin-top: 2mm;
      background: #ffffff;
      border-radius: 1.5mm;
      overflow: hidden;
      border: 1px solid #e2e8f0;
    }}
    table.data-table th {{
      background: #0f172a;
      color: #ffffff;
      padding: 2.5mm 3mm;
      text-align: left;
      font-size: 6.8pt;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.6px;
    }}
    table.data-table td {{
      padding: 2.2mm 3mm;
      border-bottom: 1px solid #e2e8f0;
      vertical-align: middle;
      line-height: 1.35;
    }}
    table.data-table tr:nth-child(even) td {{
      background: #f8fafc;
    }}
    table.data-table code {{
      font-family: monospace;
      font-weight: 700;
      background: #f1f5f9;
      padding: 0.5mm 1.5mm;
      border-radius: 1mm;
      color: var(--pink);
      font-size: 7.2pt;
    }}

    /* Map presentation */
    .map-container {{
      position: relative;
      width: 100%;
      height: 125mm;
      background: #111;
      border-radius: 2.5mm;
      overflow: hidden;
      border: 2px solid var(--pink);
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4mm 10mm rgba(0,0,0,0.15);
    }}
    .map-container img {{
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
    }}
    .map-badge {{
      position: absolute;
      background: rgba(10, 10, 12, 0.88);
      color: #fff;
      padding: 1.5mm 3mm;
      border-radius: 1mm;
      font-size: 6.8pt;
      font-weight: 700;
      border-left: 3px solid var(--neon);
      backdrop-filter: blur(4px);
    }}

    /* Mock WhatsApp Bubble */
    .chat-bubble {{
      background: #ffffff;
      border-radius: 2.5mm 2.5mm 2.5mm 0.5mm;
      padding: 3mm 3.5mm;
      margin-bottom: 2.5mm;
      box-shadow: 0 1mm 2mm rgba(0,0,0,0.06);
      border-left: 3px solid #22c55e;
      font-size: 7.8pt;
      line-height: 1.35;
    }}
    .chat-bubble .sender {{
      font-size: 6.6pt;
      font-weight: 800;
      color: #16a34a;
      text-transform: uppercase;
      margin-bottom: 1mm;
    }}

    /* Bottom deco bands */
    .bands {{
      position: absolute;
      inset: auto 0 0;
      display: grid;
      grid-template-columns: 3fr 1fr 2fr;
      height: 6mm;
    }}
    .bands i:nth-child(1) {{ background: var(--pink); }}
    .bands i:nth-child(2) {{ background: var(--neon); }}
    .bands i:nth-child(3) {{ background: var(--blue); }}

    /* Footer */
    .footer {{
      margin-top: auto;
      padding-top: 3mm;
      border-top: 1px solid #cbd5e1;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 6.8pt;
      font-weight: 700;
      letter-spacing: 0.8px;
      text-transform: uppercase;
      color: #64748b;
    }}
    .dark .footer {{
      border-color: #27272a;
      color: #94a3b8;
    }}

    /* Cover specific */
    .cover-decor {{
      position: absolute;
      right: -35mm;
      top: 25mm;
      width: 130mm;
      height: 130mm;
      border: 18mm dotted rgba(240, 244, 0, 0.85);
      border-radius: 50%;
      transform: rotate(15deg);
      pointer-events: none;
    }}
    .cover-box {{
      position: relative;
      z-index: 2;
      margin-top: 32mm;
      max-width: 155mm;
    }}
    .meta-list {{
      display: grid;
      grid-template-columns: 35mm 1fr;
      gap: 2mm 4mm;
      margin-top: 8mm;
      font-size: 8.5pt;
    }}
    .meta-list dt {{
      font-size: 7.2pt;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: var(--neon);
    }}
    .meta-list dd {{
      margin: 0;
      font-weight: 600;
      color: #f1f5f9;
    }}

    @media print {{
      html, body {{ background: #ffffff; }}
      .page {{ margin: 0; }}
    }}
  </style>
</head>
<body>

  <!-- PÁGINA 1: CAPA EXECUTIVA -->
  <section class="page dark">
    <div class="cover-decor"></div>
    <div class="eyebrow">Documento Executivo • Node Data & Tropicadelia</div>
    
    <div class="cover-box">
      <h1>MASTERPLAN<br>DA PLANTA &<br><span class="neon">MATRIZ DE ESCUTA.</span></h1>
      <p class="lead">Mapeamento operacional da planta física, distribuição estratégica de QR Codes determinísticos e arquitetura de resposta em tempo real para o Tropicadelia 2026.</p>

      <dl class="meta-list">
        <dt>Evento</dt><dd>Tropicadelia 2026 — O Despertar</dd>
        <dt>Data</dt><dd>26 de setembro de 2026 (12h de duração)</dd>
        <dt>Local</dt><dd>Parque de Exposições Governador Ney Braga • Londrina-PR</dd>
        <dt>Público Estimado</dt><dd>30.000 participantes projetados</dd>
        <dt>Solução</dt><dd>Tuca — Anfitrião Digital & Radar Operacional</dd>
        <dt>Tecnologia</dt><dd>Node Data Tecnologia (WhatsApp Cloud API + Supabase)</dd>
        <dt>Apresentação</dt><dd>Diretoria, Produção Executiva e Coordenação Operacional</dd>
      </dl>
    </div>

    <div style="margin-top: 25mm; max-width: 160mm; position: relative; z-index: 2;">
      <div class="card" style="background: rgba(20,20,24,0.9); border: 1.5px solid var(--neon);">
        <p style="margin: 0; font-size: 8.4pt; line-height: 1.45; color: #f8fafc;">
          <strong class="neon">Objetivo deste documento:</strong> Apresentar a leitura técnica da planta aprovada da edição 2026, convertendo cada setor físico em um sensor inteligente de dados, filas e ocorrências através de QR Codes contextuais, sem necessidade de download de aplicativo.
        </p>
      </div>
    </div>

    <div class="footer">
      <span>Tuca × Tropicadelia 2026</span>
      <span>01 • Masterplan Operacional</span>
    </div>
    <div class="bands"><i></i><i></i><i></i></div>
  </section>

  <!-- PÁGINA 2: A PLANTA E ANÁLISE TERRITORIAL -->
  <section class="page">
    <div class="eyebrow">Análise Territorial • Parque Ney Braga</div>
    <h2>A PLANTA DO FESTIVAL CONECTADA EM TEMPO REAL</h2>
    <p class="lead" style="margin-bottom: 3.5mm;">A planta recebida organiza os 3 palcos, 4 praças de consumo, serviços centrais e fluxos perimetrais. Cada área terá atendimento direcionado.</p>

    <!-- Visualização da planta oficial -->
    <div class="map-container">
      <img src="data:image/jpeg;base64,{b64_image}" alt="Planta Oficial Tropicadelia 2026">
      <div class="map-badge" style="top: 3mm; left: 3mm;">📍 Setor Norte: Arena Palco Hype + Open Food</div>
      <div class="map-badge" style="bottom: 3mm; left: 3mm;">📍 Setor Sul: Palco Principal + PCD + Descanso</div>
      <div class="map-badge" style="top: 45%; right: 3mm;">📍 Setor Leste: Acesso Excursões & Bares Food</div>
    </div>

    <!-- Macrozonas da planta -->
    <div class="grid-3" style="margin-top: 4mm;">
      <div class="card">
        <span class="tag">Zona Sul</span>
        <h3 style="font-size: 9pt; margin-bottom: 1.5mm;">Palco Principal & Apoio</h3>
        <p style="font-size: 7.4pt; margin: 0; color: #475569; line-height: 1.4;">
          Maior concentração de público. Abriga Palco Principal, House Mix, Plataforma PCD reservada, Bateria WC Feminino, Bar 02, Bar 03 e Lounge Bamboo's Pallet.
        </p>
      </div>

      <div class="card">
        <span class="tag neon-tag">Zona Norte</span>
        <h3 style="font-size: 9pt; margin-bottom: 1.5mm;">Arena Hype & Open Food</h3>
        <p style="font-size: 7.4pt; margin: 0; color: #475569; line-height: 1.4;">
          Espaço coberto e VIP com Palco Hype, Open Food contínuo, Bar 06, Caixa 05 e sanitários próprios. Exige monitoramento rigoroso de reposição gastronômica.
        </p>
      </div>

      <div class="card">
        <span class="tag blue-tag">Zona Oeste & Central</span>
        <h3 style="font-size: 9pt; margin-bottom: 1.5mm;">Palco 3, Praça & CCO</h3>
        <p style="font-size: 7.4pt; margin: 0; color: #475569; line-height: 1.4;">
          Palco 3, Praça de Alimentação no gramado oval, Bar Celeiro, Bares de Destilados P1/P2, Lockers, Feirinha, Tattoo e o posto operacional CCO / L&P (Achados e Perdidos).
        </p>
      </div>
    </div>

    <div class="footer">
      <span>Leitura Territorial da Planta</span>
      <span>02 • Masterplan Operacional</span>
    </div>
    <div class="bands"><i></i><i></i><i></i></div>
  </section>

  <!-- PÁGINA 3: MATRIZ DE QR CODES E PONTOS OPERACIONAIS -->
  <section class="page">
    <div class="eyebrow">Sensoriamento Sem Aplicativo • Engenharia de QR</div>
    <h2>MATRIZ DE IMPLANTAÇÃO DE QR CODES</h2>
    <p class="lead" style="margin-bottom: 2mm;">
      Ao escanear a placa física, o link abre o WhatsApp com a tag <code>#SETOR:CODIGO</code> pré-preenchida. A inteligência do backend identifica onde o visitante está e encaminha sem burocracia.
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th style="width: 26%;">Setor & Código</th>
          <th style="width: 25%;">Local na Planta</th>
          <th style="width: 31%;">Mensagem da Placa (CTA)</th>
          <th style="width: 18%;">Equipe & SLA</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>PALCO-PRINCIPAL-PCD</code></td>
          <td>Plataforma PCD em frente à House Mix</td>
          <td>“Precisa de apoio ou acessibilidade? Chame o Tuca.”</td>
          <td><strong>Acessibilidade</strong><br><span style="color:var(--pink); font-weight:700;">Urgência • &lt; 3 min</span></td>
        </tr>
        <tr>
          <td><code>WC-FEM-PRINCIPAL</code></td>
          <td>Bateria feminina ao lado do Palco Principal</td>
          <td>“Falta papel ou fila travada? Avise nossa equipe em 1 toque.”</td>
          <td><strong>Limpeza & WC</strong><br>SLA &lt; 5 min</td>
        </tr>
        <tr>
          <td><code>WC-MASC-CENTRAL</code></td>
          <td>Bateria masculina central (próx. Lockers)</td>
          <td>“Banheiro precisa de limpeza? Avise o Tuca agora.”</td>
          <td><strong>Limpeza & WC</strong><br>SLA &lt; 5 min</td>
        </tr>
        <tr>
          <td><code>PALCO-HYPE-OPENFOOD</code></td>
          <td>Bancadas de alimentação na Arena Hype</td>
          <td>“Reposição ou atendimento no Open Food? Fale conosco.”</td>
          <td><strong>Alimentação VIP</strong><br>SLA &lt; 4 min</td>
        </tr>
        <tr>
          <td><code>PRACA-ALIMENTACAO</code></td>
          <td>Gramado oval central (Praça Aliment.)</td>
          <td>“Fila longa ou falta de fichas? Avise a coordenação.”</td>
          <td><strong>F&B / Alimentos</strong><br>SLA &lt; 5 min</td>
        </tr>
        <tr>
          <td><code>BAR-CELEIRO-01</code></td>
          <td>Bar Celeiro central e tendas Destilados</td>
          <td>“Acabou gelo ou bebida? Relate direto ao suporte do bar.”</td>
          <td><strong>Bar & Insumos</strong><br>SLA &lt; 4 min</td>
        </tr>
        <tr>
          <td><code>CCO-ACHADOS-PERDIDOS</code></td>
          <td>Posto CCO / L&P (próx. à Feirinha)</td>
          <td>“Perdeu documento ou chave? Consulte itens encontrados.”</td>
          <td><strong>Segurança & CCO</strong><br>SLA &lt; 5 min</td>
        </tr>
        <tr>
          <td><code>LOCKERS-CENTRAL</code></td>
          <td>Ala de guarda-volumes no centro</td>
          <td>“Dúvidas sobre o armário ou chave? Tire sua dúvida aqui.”</td>
          <td><strong>Atendimento</strong><br>SLA &lt; 5 min</td>
        </tr>
        <tr>
          <td><code>PALCO-3-GERAL</code></td>
          <td>Frente de palco e Bar 05 / Caixa 04</td>
          <td>“Curtiu o show? Dê sua nota ou avise sobre o espaço.”</td>
          <td><strong>Experiência / Som</strong><br>SLA Monitoramento</td>
        </tr>
        <tr>
          <td><code>ACESSO-CREDENCIAMENTO</code></td>
          <td>Portões leste / Entrada principal</td>
          <td>“Dúvida com ingresso ou fila? Chame o Tuca.”</td>
          <td><strong>Portaria & Acesso</strong><br>SLA &lt; 3 min</td>
        </tr>
        <tr>
          <td><code>DESCANSO-BAMBOO</code></td>
          <td>Lounge Bamboo's Pallet / Água</td>
          <td>“Hidrate-se! Quer ver os horários dos próximos shows?”</td>
          <td><strong>Engajamento</strong><br>Interação Digital</td>
        </tr>
      </tbody>
    </table>

    <div class="card" style="margin-top: 3.5mm; background: #f1f5f9; border-left: 4px solid var(--pink);">
      <p style="margin: 0; font-size: 7.5pt; line-height: 1.4; color: #1e293b;">
        <strong>Eliminação do Rastreamento Invasivo:</strong> A metodologia de QR Code respeita 100% a LGPD. O público não é monitorado por GPS contra a vontade; a localização é declarada voluntariamente através do escaneamento do ponto físico de atendimento.
      </p>
    </div>

    <div class="footer">
      <span>Inventário Operacional de Pontos</span>
      <span>03 • Masterplan Operacional</span>
    </div>
    <div class="bands"><i></i><i></i><i></i></div>
  </section>

  <!-- PÁGINA 4: JORNADA DO PARTICIPANTE E CASOS PRÁTICOS -->
  <section class="page">
    <div class="eyebrow">Experiência Real • Campo e Operação</div>
    <h2>CASOS PRÁTICOS: A DIFERENÇA NA OPERAÇÃO</h2>
    <p class="lead" style="margin-bottom: 4mm;">Como a triagem automática do Tuca age nos gargalos mais comuns de grandes festivais.</p>

    <div class="grid-2">
      <!-- Caso 1 -->
      <div class="card">
        <span class="tag">Caso 01 • Bares & Bebidas</span>
        <h3 style="font-size: 9.5pt;">Fila travada ou falta de insumo no Bar Celeiro</h3>
        <div class="chat-bubble">
          <div class="sender">Participante (via QR Bar Celeiro)</div>
          “#SETOR:BAR-CELEIRO-01 Acabou o gelo no balcão 2 e a fila tá parada faz 20 min!”
        </div>
        <div class="chat-bubble" style="border-left-color: var(--blue);">
          <div class="sender">Tuca • Sistema Operacional</div>
          “Obrigado pelo aviso! O CCO já acionou o reabastecimento de gelo para o Bar Celeiro. Se preferir, os bares de Destilados P1 logo ao lado estão com fila rápida!”
        </div>
        <p style="font-size: 7.2pt; color: #475569; margin: 0;">
          <strong>Impacto:</strong> A equipe do bar reabastece o insumo 15 minutos antes de gerar desistência de compra e dispersa a fila para bares adjacentes.
        </p>
      </div>

      <!-- Caso 2 -->
      <div class="card">
        <span class="tag neon-tag">Caso 02 • Sanitários & Higiene</span>
        <h3 style="font-size: 9.5pt;">Banheiro sem papel ou com fluxo saturado</h3>
        <div class="chat-bubble">
          <div class="sender">Participante (via QR WC Feminino)</div>
          “#SETOR:WC-FEM-PRINCIPAL As cabines 4 e 5 estão sem papel e com torneira vazando.”
        </div>
        <div class="chat-bubble" style="border-left-color: var(--pink);">
          <div class="sender">Tuca • Limpeza & Manutenção</div>
          “Recebido! A equipe volante de limpeza e reposição já está a caminho desta bateria. Agradecemos por cuidar do nosso festival!”
        </div>
        <p style="font-size: 7.2pt; color: #475569; margin: 0;">
          <strong>Impacto:</strong> Reduz em 80% as reclamações públicas nas redes sociais sobre banheiros, mantendo nota de satisfação elevada.
        </p>
      </div>

      <!-- Caso 3 -->
      <div class="card">
        <span class="tag" style="background:#dc2626;">Caso 03 • Acolhimento PCD</span>
        <h3 style="font-size: 9.5pt;">Apoio dedicado na Plataforma de Acessibilidade</h3>
        <div class="chat-bubble">
          <div class="sender">Participante (via QR Plataforma PCD)</div>
          “#SETOR:PALCO-PRINCIPAL-PCD Sou cadeirante e a rampa de saída está bloqueada por pedestres.”
        </div>
        <div class="chat-bubble" style="border-left-color: #dc2626;">
          <div class="sender">Tuca • Central de Acessibilidade</div>
          “🚨 Alerta prioritário recebido! Nossos monitores de acessibilidade foram acionados para liberação imediata do acesso. Estamos com você!”
        </div>
        <p style="font-size: 7.2pt; color: #475569; margin: 0;">
          <strong>Impacto:</strong> Ocorrência classificada automaticamente como <code>Crítico</code>, gerando ação imediata e evitando incidentes de segurança.
        </p>
      </div>

      <!-- Caso 4 -->
      <div class="card">
        <span class="tag blue-tag">Caso 04 • Achados e Perdidos</span>
        <h3 style="font-size: 9.5pt;">Resolução ágil de pertences no CCO</h3>
        <div class="chat-bubble">
          <div class="sender">Participante (via QR Geral / Praça)</div>
          “Perdi minha CNH e o cartão de crédito perto da praça de alimentação!”
        </div>
        <div class="chat-bubble" style="border-left-color: var(--blue);">
          <div class="sender">Tuca • Achados & Perdidos</div>
          “Não se preocupe! Documentos encontrados estão sendo centralizados no posto <strong>CCO / L&P</strong> (em frente à Feirinha). Vá até lá com uma foto sua para conferência.”
        </div>
        <p style="font-size: 7.2pt; color: #475569; margin: 0;">
          <strong>Impacto:</strong> Desafoga os seguranças na pista e organiza o fluxo até o container oficial de Achados e Perdidos.
        </p>
      </div>
    </div>

    <div class="footer">
      <span>Jornada de Resposta em Campo</span>
      <span>04 • Masterplan Operacional</span>
    </div>
    <div class="bands"><i></i><i></i><i></i></div>
  </section>

  <!-- PÁGINA 5: CENTRO DE COMANDO, GOVERNANÇA E PRÓXIMOS PASSOS -->
  <section class="page dark">
    <div class="eyebrow">Centro de Controle • CCO & Governança</div>
    <h2>PAINEL EM TEMPO REAL & PRÓXIMOS PASSOS</h2>
    <p class="lead" style="margin-bottom: 4.5mm;">
      Toda a inteligência do festival converge para um painel operacional intuitivo, permitindo à diretoria tomar decisões preventivas antes que os problemas escalem.
    </p>

    <div class="grid-3" style="margin-bottom: 5mm;">
      <div class="card">
        <span class="tag neon-tag">Recurso 01</span>
        <h3 style="font-size: 9.5pt; color: #fff;">Mapa de Calor da Planta</h3>
        <p style="font-size: 7.3pt; color: #cbd5e1; margin: 0; line-height: 1.4;">
          A planta do Parque Ney Braga é exibida no painel com pins coloridos (Verde = Normal, Amarelo = Atenção, Vermelho = Crítico), revelando manchas de calor e gargalos em tempo real.
        </p>
      </div>

      <div class="card">
        <span class="tag">Recurso 02</span>
        <h3 style="font-size: 9.5pt; color: #fff;">Triagem Semântica por IA</h3>
        <p style="font-size: 7.3pt; color: #cbd5e1; margin: 0; line-height: 1.4;">
          Cada mensagem é classificada automaticamente por sentimento (Positivo, Neutro, Crítico) e categoria (Bar, Limpeza, Som, Segurança), disparando notificações para os rádios certos.
        </p>
      </div>

      <div class="card">
        <span class="tag blue-tag">Recurso 03</span>
        <h3 style="font-size: 9.5pt; color: #fff;">Relatório Pós-Evento</h3>
        <p style="font-size: 7.3pt; color: #cbd5e1; margin: 0; line-height: 1.4;">
          Auditoria completa de dados: tempos de resposta por setor, notas dos patrocinadores, produtos mais demandados e índice de satisfação geral para as marcas apoiadoras.
        </p>
      </div>
    </div>

    <div class="card" style="background: rgba(255,255,255,0.03); border: 1.5px solid var(--border-dark); margin-bottom: 6mm;">
      <h3 style="color: var(--neon); font-size: 10pt; margin-bottom: 2mm;">ROTEIRO DE HOMOLOGAÇÃO COM A PRODUÇÃO:</h3>
      <div class="grid-4" style="font-size: 7.2pt; color: #cbd5e1;">
        <div>
          <strong style="color: #fff; display:block; margin-bottom: 1mm;">1. Aprovação dos Pontos</strong>
          Validação final dos ~15 locais físicos onde serão afixadas as placas e totens com QR Code.
        </div>
        <div>
          <strong style="color: #fff; display:block; margin-bottom: 1mm;">2. Geração dos Vetores</strong>
          Entrega dos arquivos gráficos em alta resolução prontos para impressão gráfica de teste.
        </div>
        <div>
          <strong style="color: #fff; display:block; margin-bottom: 1mm;">3. Teste em Campo</strong>
          Simulação de leitura e disparo no ensaio geral pré-festival com a equipe de coordenação.
        </div>
        <div>
          <strong style="color: #fff; display:block; margin-bottom: 1mm;">4. Operação Assistida</strong>
          Equipe técnica Node Data acompanhando a telemetria e o CCO durante as 12h de evento.
        </div>
      </div>
    </div>

    <!-- Bloco de assinaturas -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15mm; margin-top: 4mm;">
      <div style="border-top: 1px solid #475569; padding-top: 2.5mm; font-size: 7.5pt; color: #cbd5e1;">
        <strong style="color: #fff;">Node Data Tecnologia</strong><br>
        Engenharia e Inteligência de Dados
      </div>
      <div style="border-top: 1px solid #475569; padding-top: 2.5mm; font-size: 7.5pt; color: #cbd5e1;">
        <strong style="color: #fff;">Tropicadelia 2026</strong><br>
        Diretoria Executiva & Produção Geral
      </div>
    </div>

    <div class="footer">
      <span>Próximos Passos & Homologação</span>
      <span>05 • Masterplan Operacional</span>
    </div>
    <div class="bands"><i></i><i></i><i></i></div>
  </section>

</body>
</html>
"""

with open(HTML_OUTPUT, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"HTML gerado: {HTML_OUTPUT}")

# Executa o Chrome Headless para compilar o PDF
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
cmd = [
    chrome_path,
    "--headless=new",
    "--disable-gpu",
    "--no-pdf-header-footer",
    f"--print-to-pdf={PDF_OUTPUT}",
    HTML_OUTPUT,
]

print("Compilando PDF via Chrome Headless...")
result = subprocess.run(cmd, capture_output=True, text=True)
if os.path.exists(PDF_OUTPUT):
    size_kb = os.path.getsize(PDF_OUTPUT) / 1024
    print(f"Sucesso! PDF gerado: {PDF_OUTPUT} ({size_kb:.1f} KB)")
else:
    print(f"Erro ao gerar PDF: {result.stderr}")
    sys.exit(1)
