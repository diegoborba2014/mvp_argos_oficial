# ARGOS QG — Plano de Design / UX + Backend

> Skills instaladas: `frontend-design` · `web-design-guidelines` · `ui-ux-pro-max` · `ckm-design-system`

---

## Identidade Visual Extraída do Logo

O logo "ARGOS — De olho em tudo" define a linguagem visual:

| Token | Valor | Uso |
|---|---|---|
| `--teal` | `#00c8dc` | Accent principal — ativo, online, destaque |
| `--teal-dim` | `rgba(0,200,220,.12)` | Fundos de elementos ativos |
| `--teal-glow` | `rgba(0,200,220,.35)` | Sombras e halos |
| `--red` | `#c0392b` | Alertas táticos, ações destrutivas |
| `--red-glow` | `rgba(192,57,43,.4)` | Sombra de alertas |
| `--bg-deep` | `#0a0c11` | Fundo da página |
| `--bg-surface` | `#12151c` | Sidebar, navbar |
| `--bg-card` | `#1a1d26` | Cards e painéis |
| `--bg-card-2` | `#22263a` | Hover, linhas alternadas |
| `--text` | `#f0f2f5` | Texto principal |
| `--text-dim` | `rgba(240,242,245,.55)` | Labels, meta-dados |
| `--text-muted` | `rgba(240,242,245,.28)` | Placeholders, bordas sutis |
| `--border` | `rgba(0,200,220,.1)` | Bordas de cards |
| `--online` | `#2ecc71` | Viatura online |
| `--offline` | `#636e72` | Viatura offline |

**Direção estética:** Industrial / Centro de Comando Tático  
Não é um painel administrativo genérico — é uma interface de vigilância operacional.  
Cada elemento deve parecer parte de um sistema real de monitoramento de frota policial.

---

## Tipografia

| Papel | Fonte | CDN |
|---|---|---|
| Display / IDs / Placas | `Share Tech Mono` | Google Fonts |
| Headings e nav | `Exo 2` (600–700) | Google Fonts |
| Body / labels | `Exo 2` (400) | Google Fonts |

**Racional:** "Share Tech Mono" reforça a natureza técnica/vigilância para placas e IDs de viatura.  
"Exo 2" é geométrico, de leitura clara, com caráter tecnológico — evita a aparência genérica de Inter/Roboto.

---

## Skills Instaladas

| Skill | Localização | Uso |
|---|---|---|
| `frontend-design` | `.agents/skills/frontend-design/` | Guia de design distintivo, evita "AI slop" |
| `web-design-guidelines` | `.agents/skills/web-design-guidelines/` | Auditoria UX/acessibilidade Vercel |
| `ui-ux-pro-max` | `.agents/skills/ui-ux-pro-max/` | 50+ estilos, 161 paletas, suporta HTML/CSS puro |
| `ckm-design-system` | `.agents/skills/ckm-design-system/` | Tokens CSS (3 camadas), sistema de componentes |

---

## ORDEM DE EXECUÇÃO

**Backend primeiro** — corrigir bugs críticos antes de mexer em templates evita que mudanças de design quebrem código Python.

```
B1 (bugs críticos) → B2 (melhorias médias) → D1 (tokens CSS) → D2 (componentes) → D3 (tabelas/mapa) → D4 (auditoria UX)
```

---

## Sprint B1 — Backend: Correções Críticas

**Objetivo:** Eliminar bugs que causam falhas em produção ou corrupção de dados.  
**Arquivos afetados:** `models.py`, `routes/telemetry.py`, `routes/dashboard.py`, `routes/api_viaturas.py`, `requirements.txt`

### Tarefas

#### B1.1 — `requests` ausente em requirements.txt
- [ ] Adicionar `requests` ao `requirements.txt`
- [ ] **Arquivo:** `qg_webapp/requirements.txt`
- [ ] **Risco sem correção:** `ImportError` na inicialização → app não sobe em ambiente limpo

#### B1.2 — `datetime.utcnow()` depreciado (Python 3.12+)
- [ ] Substituir TODOS os `datetime.utcnow()` por `datetime.now(timezone.utc)` nos arquivos:
  - `models.py` (métodos `online()`, `to_dict()`, defaults de coluna)
  - `routes/dashboard.py` (filtros de data `inicio_hoje`, comparações)
  - `routes/telemetry.py` (já usa `timezone.utc` — verificar consistência)
- [ ] Garantir que comparações entre datetimes naive e aware não quebrem (`.replace(tzinfo=timezone.utc)` onde necessário)
- [ ] **Risco sem correção:** `DeprecationWarning` vira `RuntimeError` em versões futuras do Python; comparações aware vs naive já lançam `TypeError`

#### B1.3 — Vazamento de memória no SSE (`_sse_listeners`)
- [ ] **Arquivo:** `routes/telemetry.py`
- [ ] Substituir `list` por sistema com limpeza de clientes desconectados:
  ```python
  # Padrão: usar try/except no broadcast para remover clientes mortos
  def _broadcast(event: str, data: dict):
      msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
      dead = []
      for q in _sse_listeners:
          try:
              q.put_nowait(msg)
          except Exception:
              dead.append(q)
      for q in dead:
          _sse_listeners.remove(q)
  ```
- [ ] Adicionar timeout no gerador SSE (fecha conexão após 5min de inatividade se cliente não lê)
- [ ] **Risco sem correção:** cada tab aberta do dashboard acumula uma fila em memória — servidor trava após horas/dias de uso contínuo

#### B1.4 — N+1 queries em `api_mapa_viaturas()` e `dashboard`
- [ ] **Arquivo:** `routes/dashboard.py`
- [ ] Substituir loop que chama `v.ultimo_heartbeat()` por uma única query com subquery:
  ```python
  from sqlalchemy import func
  
  # Busca o último heartbeat de cada viatura em uma query só
  subq = (db.session.query(
      Heartbeat.viatura_id,
      func.max(Heartbeat.recebido_em).label("max_rec")
  ).group_by(Heartbeat.viatura_id).subquery())
  
  heartbeats = {
      hb.viatura_id: hb
      for hb in Heartbeat.query.join(
          subq,
          (Heartbeat.viatura_id == subq.c.viatura_id) &
          (Heartbeat.recebido_em == subq.c.max_rec)
      ).all()
  }
  ```
- [ ] Aplicar o mesmo padrão em todas as rotas que iteram viaturas
- [ ] **Risco sem correção:** com 10 viaturas = 10 queries extras por request; com 100 viaturas = 100 queries → dashboard trava

---

## Sprint B2 — Backend: Melhorias de Robustez

**Objetivo:** Preparar o app para uso em produção real — segurança, estabilidade e observabilidade.

### Tarefas

#### B2.1 — CSRF em formulários POST
- [ ] Adicionar `flask-wtf` ao `requirements.txt`
- [ ] Inicializar `CSRFProtect(app)` em `app.py`
- [ ] Adicionar `{{ csrf_token() }}` (campo hidden) em todos os `<form method="POST">`:
  - `login.html`, `hotlist.html`, `viaturas.html` (formulários de comando)
- [ ] Alternativa simples sem Flask-WTF: gerar token na sessão e validar manualmente
- [ ] **Risco sem correção:** formulários podem ser disparados por sites externos (CSRF attack)

#### B2.2 — Handlers de erro HTTP
- [ ] **Arquivo:** `app.py`
- [ ] Adicionar handlers para 403, 404, 500:
  ```python
  @app.errorhandler(404)
  def not_found(e):
      return render_template("errors/404.html"), 404
  
  @app.errorhandler(500)
  def server_error(e):
      app.logger.error(f"500: {e}")
      return render_template("errors/500.html"), 500
  ```
- [ ] Criar templates `templates/errors/404.html` e `500.html` com estilo ARGOS (fundo escuro, texto teal)
- [ ] **Risco sem correção:** erros expõem stack trace Python em produção (vazamento de informação)

#### B2.3 — Rate limit no endpoint de telemetria
- [ ] Adicionar `flask-limiter` ao `requirements.txt`
- [ ] Aplicar `@limiter.limit("600/minute")` em `POST /api/argos/telemetry`
- [ ] **Risco sem correção:** Pi com bug de loop pode enviar milhares de requests/min e derrubar o servidor

#### B2.4 — Gunicorn com workers compatíveis com SSE
- [ ] **Arquivo:** `Procfile` e `requirements.txt`
- [ ] Adicionar `gevent` ao `requirements.txt`
- [ ] Atualizar `Procfile`:
  ```
  web: gunicorn app:app --worker-class gevent --workers 1 --bind 0.0.0.0:$PORT --timeout 300
  ```
- [ ] Ou usar `--worker-class gthread --threads 4` (alternativa sem gevent)
- [ ] **Risco sem correção:** Gunicorn com worker sync bloqueia no SSE stream — segundo cliente não consegue conectar

#### B2.5 — Logging estruturado
- [ ] Configurar `app.logger` com nível INFO em produção
- [ ] Logar: recebimento de detecções (viatura_id, placa, alerta), heartbeats descartados (antigos), erros de API de viatura
- [ ] **Não é crítico** mas essencial para debug em produção

---

## Sprint D1 — Design: Sistema de Tokens CSS

**Objetivo:** Criar `static/css/argos-theme.css` — fonte única de verdade visual. AdminLTE fica invisível sob os overrides.

### Tarefas

#### D1.1 — Arquivo `argos-theme.css` com tokens e reset
- [ ] **Arquivo novo:** `qg_webapp/static/css/argos-theme.css`
- [ ] Estrutura (seguindo ckm-design-system — 3 camadas):
  ```css
  /* === PRIMITIVOS === */
  :root {
    --primitive-teal: #00c8dc;
    --primitive-red: #c0392b;
    --primitive-dark-900: #0a0c11;
    --primitive-dark-800: #12151c;
    --primitive-dark-700: #1a1d26;
    --primitive-dark-600: #22263a;
    --primitive-green: #2ecc71;
    --primitive-gray: #636e72;
  }

  /* === SEMÂNTICOS === */
  :root {
    --teal: var(--primitive-teal);
    --teal-dim: rgba(0,200,220,.12);
    --teal-glow: rgba(0,200,220,.35);
    --red: var(--primitive-red);
    --red-dim: rgba(192,57,43,.1);
    --red-glow: rgba(192,57,43,.4);
    --bg-deep: var(--primitive-dark-900);
    --bg-surface: var(--primitive-dark-800);
    --bg-card: var(--primitive-dark-700);
    --bg-card-2: var(--primitive-dark-600);
    --text: #f0f2f5;
    --text-dim: rgba(240,242,245,.55);
    --text-muted: rgba(240,242,245,.28);
    --border: rgba(0,200,220,.1);
    --online: var(--primitive-green);
    --offline: var(--primitive-gray);
    --font-mono: 'Share Tech Mono', monospace;
    --font-ui: 'Exo 2', sans-serif;
  }
  ```
- [ ] Override global AdminLTE: body, wrappers, navbar, footer
- [ ] Importar fonts Google no início do arquivo:
  ```css
  @import url('https://fonts.googleapis.com/css2?family=Exo+2:wght@400;600;700&family=Share+Tech+Mono&display=swap');
  ```

#### D1.2 — Carregar `argos-theme.css` nos templates
- [ ] **Arquivo:** `templates/base.html` — adicionar após AdminLTE CSS:
  ```html
  <link rel="stylesheet" href="{{ url_for('static', filename='css/argos-theme.css') }}">
  ```
- [ ] **Arquivo:** `templates/login.html` — verificar que já carrega ou adicionar
- [ ] Testar que nenhum elemento "explode" visualmente (AdminLTE ainda funciona como base)

#### D1.3 — Override sidebar e navbar
- [ ] Sidebar: `--bg-surface` como fundo, borda direita `1px solid var(--border)`
- [ ] Item ativo: `background: var(--teal-dim)`, `border-left: 3px solid var(--teal)`
- [ ] Item hover: `background: rgba(0,200,220,.06)`, transição `0.15s`
- [ ] Separadores de seção com `border-top: 1px solid var(--border)`
- [ ] Navbar: fundo `--bg-surface`, borda inferior `var(--border)`

---

## Sprint D2 — Design: Componentes Principais

**Objetivo:** Redesenhar os elementos de maior impacto visual — o que o operador vê primeiro.

### Tarefas

#### D2.1 — KPI cards (contadores do dashboard)
- [ ] **Template:** `templates/dashboard.html` — substituir `.info-box` por design glassmorphism:
  ```css
  .argos-kpi {
    background: rgba(255,255,255,.03);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
  }
  .argos-kpi .number {
    font-family: var(--font-ui);
    font-weight: 700;
    font-size: 2.5rem;
    color: var(--teal);
  }
  .argos-kpi.alerta .number { color: var(--red); }
  .argos-kpi.alerta { border-color: rgba(192,57,43,.3); }
  ```
- [ ] Card de alertas: pulse animation quando contador > 0
- [ ] Ícones com `filter: drop-shadow(0 0 6px var(--teal-glow))`

#### D2.2 — Cards de viatura no dashboard
- [ ] Borda esquerda `3px solid var(--teal)` (online) ou `var(--offline)` (offline)
- [ ] Fundo `--bg-card`, hover `--bg-card-2`
- [ ] Badge "ONLINE" com `animation: pulse 2s infinite`
- [ ] Placa lida: `font-family: var(--font-mono)`, fundo `rgba(0,0,0,.4)`, padding, borda sutil
- [ ] Temperatura com cor dinâmica (verde < 65°C, laranja 65–80°C, vermelho > 80°C)

#### D2.3 — Feed ao vivo (últimas detecções)
- [ ] Contêiner com `background: var(--bg-deep)`, `border: 1px solid var(--border)`
- [ ] Linha normal: sem fundo, hover `--bg-card-2`
- [ ] Linha de alerta: `background: var(--red-dim)`, `border-left: 3px solid var(--red)`
- [ ] Animação `fadeInDown` em novas linhas inseridas via SSE
- [ ] Efeito "scan": `::before` pseudo-elemento com linha teal `height: 2px` passando do topo para baixo (`animation: scan 4s linear infinite`)
- [ ] Placas em `var(--font-mono)` com `background: rgba(0,0,0,.3)`, `padding: 2px 6px`

#### D2.4 — Notificações de alerta (toast)
- [ ] `border-left: 4px solid var(--red)`, fundo `--bg-card`, sombra `var(--red-glow)`
- [ ] Slide-in animation da direita (`transform: translateX(110%)` → `translateX(0)`)
- [ ] Ícone de sino/alerta animado (tremble keyframe)
- [ ] Auto-dismiss após 8s com barra de progresso que encolhe

---

## Sprint D3 — Design: Tabelas, Mapa e Páginas Secundárias

**Objetivo:** Completar a cobertura visual em todas as telas do sistema.

### Tarefas

#### D3.1 — Tabelas de alertas e leituras
- [ ] Remover `table-striped` Bootstrap (linhas brancas)
- [ ] Cabeçalho: `background: var(--bg-surface)`, `color: var(--text-dim)`, `font-family: var(--font-ui)`, `font-weight: 600`, `text-transform: uppercase`, `font-size: .75rem`, `letter-spacing: 1px`
- [ ] Linha: `background: var(--bg-card)`, hover `var(--bg-card-2)`
- [ ] Linha de alerta: `background: rgba(192,57,43,.08)`, `border-left: 3px solid var(--red)`
- [ ] Placas: `font-family: var(--font-mono)`, badge escuro
- [ ] Barra de confiança LPR: `height: 4px`, teal (>80%), laranja (60–80%), vermelho (<60%)
- [ ] Paginação: estilo escuro matching o tema

#### D3.2 — Mapa Leaflet
- [ ] Alterar tile layer para CartoDB Dark Matter:
  ```javascript
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '© CartoDB',
    maxZoom: 19
  }).addTo(map);
  ```
- [ ] Marcadores online: círculo teal `#00c8dc` com `animation: pulse-map 2s infinite`
- [ ] Marcadores offline: círculo cinza `#636e72` sem animação
- [ ] Marcadores de alerta: círculo vermelho `#c0392b` com pulse forte + `box-shadow: 0 0 12px var(--red-glow)`
- [ ] Popup escuro: `background: var(--bg-card)`, `color: var(--text)`, `border: 1px solid var(--border)`
  ```javascript
  const popup = L.popup({ className: 'argos-popup' })
  ```
  ```css
  .argos-popup .leaflet-popup-content-wrapper {
    background: var(--bg-card);
    color: var(--text);
    border: 1px solid var(--border);
  }
  ```

#### D3.3 — Páginas de viaturas e hotlist
- [ ] Tabela de viaturas: seguir padrão D3.1
- [ ] Botões de comando: `background: transparent`, `border: 1px solid var(--teal)`, `color: var(--teal)`, hover `background: var(--teal-dim)`
- [ ] Botões destrutivos (reiniciar ARGOS): borda e texto vermelho
- [ ] Hotlist: badge da placa em `font-mono`, botão remover vermelho outline
- [ ] Upload CSV: drop zone com borda dashed `--border`, hover `--teal-dim`

#### D3.4 — Página de login (refinamentos)
- [ ] Aplicar `font-family: var(--font-ui)` no formulário
- [ ] Campo input: `background: rgba(255,255,255,.05)`, `border: 1px solid var(--border)`, focus `border-color: var(--teal)`, `box-shadow: 0 0 0 3px var(--teal-dim)`
- [ ] Botão "Entrar": `background: var(--red)`, hover brightness 110%, transição 0.2s
- [ ] Placeholder em `var(--text-muted)`

#### D3.5 — Templates de erro (404/500)
- [ ] Criar `templates/errors/404.html` e `500.html`
- [ ] Fundo `--bg-deep`, código de erro em `font-mono` tamanho grande com cor `--teal`
- [ ] Mensagem em `--text-dim`, link de volta ao dashboard

---

## Sprint D4 — Auditoria UX e Acessibilidade

**Objetivo:** Validar que o design é acessível, consistente e funcional antes de considerar completo.

### Tarefas

#### D4.1 — Auditoria com web-design-guidelines skill
- [ ] Rodar a skill contra cada template principal:
  ```
  /web-design-guidelines qg_webapp/templates/dashboard.html
  /web-design-guidelines qg_webapp/templates/alertas.html
  /web-design-guidelines qg_webapp/templates/leituras.html
  /web-design-guidelines qg_webapp/templates/mapa.html
  ```

#### D4.2 — Checklist de acessibilidade (WCAG AA)
- [ ] Contraste de texto ≥ 4.5:1 — especialmente `--text-dim` sobre `--bg-card`
- [ ] Foco visível em todos os inputs e botões (`outline: 2px solid var(--teal)`)
- [ ] Labels HTML em todos os campos de formulário (`<label for="...">`)
- [ ] Alt text na imagem do logo (`alt="ARGOS — De olho em tudo"`)
- [ ] Tabelas com `<thead>`, `<th scope="col">` adequado
- [ ] Botões de ação com feedback de loading state (spinner inline ao clicar)
- [ ] Toast de alerta com `role="alert"` para leitores de tela

#### D4.3 — Teste de responsividade
- [ ] Dashboard legível em 1366×768 (resolução mínima de monitores táticos)
- [ ] Sidebar colapsada em telas < 768px (AdminLTE já faz, verificar com tema)
- [ ] Tabelas com scroll horizontal em mobile

#### D4.4 — Validação visual final
- [ ] Testar com `python app.py` e navegar em todas as telas
- [ ] Simular payload de detecção → verificar feed ao vivo + toast
- [ ] Abrir mapa → verificar tiles CartoDB Dark Matter
- [ ] Verificar que fontes Exo 2 e Share Tech Mono carregam (network tab)

---

## Componentes (Referência Visual Completa)

### P1 — Sistema de cor e tipografia global
`static/css/argos-theme.css` — tokens + tipografia + reset AdminLTE

### P2 — Cards de viatura
Borda esquerda colorida · glow teal online · placa em mono · temperatura dinâmica

### P3 — KPI cards
Glassmorphism · número grande Exo 2 · pulse em alertas

### P4 — Feed ao vivo
Fundo terminal · fadeInDown em novas linhas · scan animation · alerta borda vermelha

### P5 — Sidebar
Item ativo: teal-dim + borda esquerda · hover suave · separadores com linha teal

### P6 — Tabelas
Sem stripe claro · hover card-2 · cabeçalho uppercase · barra de confiança colorida

### P7 — Mapa
CartoDB Dark Matter · marcadores pulse · popup escuro matching tema

### P8 — Login
Fontes aplicadas · inputs com focus teal · botão vermelho hover

### P9 — Toast de alerta
Slide-in · borda vermelha · ícone animado · auto-dismiss com barra de progresso

---

## Arquivo de Implementação

**Um único arquivo:** `qg_webapp/static/css/argos-theme.css`  
Carregado no `base.html` e `login.html` após o AdminLTE CSS.  
Zero mudança de HTML nas rotas Python — só CSS custom properties e overrides.

---

## Resumo das Sprints

| Sprint | Escopo | Arquivos Principais | Risco se Pulada |
|---|---|---|---|
| **B1** | Bugs críticos | `models.py`, `telemetry.py`, `dashboard.py`, `api_viaturas.py`, `requirements.txt` | App trava em produção |
| **B2** | Robustez produção | `app.py`, `requirements.txt`, `Procfile` | Segurança e estabilidade |
| **D1** | Token CSS + tipografia | `argos-theme.css`, `base.html` | Identidade visual ausente |
| **D2** | Componentes principais | `argos-theme.css`, `dashboard.html` | Dashboard genérico |
| **D3** | Tabelas, mapa, secundárias | `argos-theme.css`, `mapa.html`, `alertas.html` | Inconsistência visual |
| **D4** | Auditoria UX | Todos os templates | Inacessível / contraste ruim |
