# Plano: ARGOS QG — Status das Sprints e Pendências

---

## Sprint 1 — QG→Pi Comunicação ✅ CONCLUÍDA
**Commits:** `aa58f14`
- Fix endpoint `/api/command` → `/api/control`, campo `command` → `acao`, header `X-API-Key`

---

## Sprint 2 — Correções Pós-Dados Reais ✅ CONCLUÍDA
**Commits:** `61a951f`, `3a1678f`, `5075008`, `1fbac02`

| Bug | Status |
|---|---|
| Erro 500 em Alertas (`**filtros` Jinja2) | ✅ |
| Feed duplicado | ✅ deduplicação `viatura_id + timestamp` |
| Coluna "Status" sempre "OK" | ✅ → "Situação" / "NORMAL" |
| Data/Hora UTC em vez de BRT | ✅ filtro `brt` |
| Log de Leituras vazio (SQLite efêmero) | ✅ resolvido na Sprint 3 |
| Hotlist sem match | ✅ `_salvar_deteccao` com `hotlist_mode` |
| Sem cadastro manual de viatura | ✅ form + rota `POST /viaturas/criar` |
| Login sem fullscreen | ✅ vídeo fullscreen |
| Páginas de erro sem template | ✅ `templates/errors/` 403/404/500 |

---

## Sprint 2.5 — Config Remota do Equipamento ✅ CONCLUÍDA
**Commits:** `8e2745a`
- `models.py`: `config_json` + `config_pendente` na Viatura; `get_config()` / `set_config()`
- `api_viaturas.py`: GET/POST `/config` + POST `/config/sync`
- `config_viatura.html`: badge Pendente/Sincronizado + botão Sincronizar

---

## Sprint 3 — PostgreSQL + Config LPR Expandida ✅ CONCLUÍDA
**Commits:** `efa2ff1`, `d75eb07`

- `requirements.txt`: `psycopg2-binary` adicionado
- `app.py`: rewrite `postgres://` → `postgresql://`
- Railway: plugin Postgres + `DATABASE_URL=${{Postgres.DATABASE_URL}}`
- `config_viatura.html`: todos os params PlateRecognizer Stream em 4 abas

---

## Sprint 3.5 — Login HUD Tático "Argos Vision" ✅ CONCLUÍDA
**Commits:** `c44a605` → `9e30939`

- Boot sequence animada (6 linhas), congelada até card aparecer (`body.anims-go`)
- Título "ARGOS VISION" — gradiente branco→teal + glow pulsante + glitch único ao carregar
- Subtítulo: "Monitoramento · Reconhecimento · Interceptação"
- Scan line, grid animado, vinheta, cantos HUD, clock em tempo real
- Card glassmorphism + status bar "SISTEMA ONLINE · CRIPTOGRAFIA ATIVA"

---

## Sprint Pi-A QG-side — Hotlist Sync via Polling ✅ CONCLUÍDA
**Commit:** `75296d0`

- `models.py`: campos `hotlist_pendente`, `hotlist_hash`, `ultima_sync_hotlist` na Viatura
- `dashboard.py`: `_marcar_hotlist_pendente()` — chamada ao adicionar/remover/importar placa
- `api_viaturas.py`: 3 endpoints autenticados por API Key:
  - `GET /api/viaturas/<id>/hotlist/pending` — Pi consulta se há atualização
  - `GET /api/viaturas/<id>/hotlist_sync` — Pi baixa lista completa + hash MD5
  - `POST /api/viaturas/<id>/hotlist/ack` — Pi confirma; QG limpa flag

---

## Revisão em Campo ⏳ AGUARDANDO PI DISPONÍVEL

Executar quando o Pi estiver disponível e conectado ao sistema.

### RV-1 — Validar tela de detalhes da leitura (Sprint 4.2)
- [ ] Confirmar que `latitude` / `longitude` exibidos no detalhe correspondem à posição da viatura **no momento da leitura** (não do heartbeat anterior)
- [ ] Confirmar que `marca`, `modelo`, `cor`, `tipo_veiculo` chegam preenchidos do Pi
- [ ] Confirmar que `velocidade`, `direção` e `score` aparecem com valores reais
- [ ] Verificar mini-mapa: pin cai no local correto da leitura

### RV-2 — Validar hotlist com prioridade/motivo (Sprint 4.4)
- [ ] Cadastrar uma placa de teste na hotlist com prioridade **Alta** e motivo **Roubo**
- [ ] Passar o veículo em frente à câmera e confirmar que o alerta tático é gerado
- [ ] Confirmar badge de prioridade 🔴 ALTA visível na tela de Hotlist
- [ ] Confirmar observação e motivo aparecem corretamente na listagem

### RV-3 — Validar trajetória investigativa (Sprint 4.1)
- [ ] Gerar ao menos 3 leituras com GPS em locais diferentes
- [ ] Acessar `/investigacao`, filtrar pela placa de teste
- [ ] Confirmar polyline teal conectando os pontos na ordem correta
- [ ] Confirmar marcador ▶ verde no primeiro avistamento e ■ laranja no último
- [ ] Clicar em item da lista e confirmar que abre popup no mapa

### RV-4 — Validar alerta sonoro e motivos dinâmicos (Sprint 4.3 + 4.5)
- [ ] Cadastrar uma placa de teste na hotlist
- [ ] Passar o veículo em frente à câmera e confirmar que o beep tático (triplo 880→1100→880 Hz) dispara no navegador
- [ ] Confirmar que leituras normais (sem match na hotlist) **não** disparam som
- [ ] Testar botão mudo (🔇) na navbar: verificar que silencia o beep e persiste após recarregar página
- [ ] Confirmar que o badge de alertas pisca na navbar ao receber alerta tático
- [ ] Validar toast de alerta: exibe placa, viatura e horário corretamente
- [ ] Cadastrar motivo personalizado (ex: "Foragido") na tela Hotlist
- [ ] Confirmar que o motivo aparece no datalist ao adicionar nova placa
- [ ] Remover motivo personalizado e confirmar que desaparece da lista

---

## Sprint Pi-A Pi-side — Deploy no Pi ⏳ AGUARDANDO PI DISPONÍVEL

Arquivos prontos em `RASPBERRY/src/` e `RASPBERRY/config/`. Deploy via SCP:

```bash
scp RASPBERRY/src/hotlist_sync.py diego@100.127.61.22:~/argos/src/
scp RASPBERRY/src/main.py diego@100.127.61.22:~/argos/src/
scp RASPBERRY/config/settings.py diego@100.127.61.22:~/argos/config/
ssh diego@100.127.61.22 "sudo systemctl restart argos"
```

---

## Sprint 4 — Investigação + Melhorias Operacionais ⏳ PLANEJADA

### 4.1 — Trajetória Investigativa ✅ CONCLUÍDA
**Commit:** pendente push

**Objetivo:** dado um conjunto de filtros (placa, marca, modelo, cor, tipo, intervalo de datas e horas), exibir no mapa o caminho percorrido por um veículo com base nas coordenadas GPS de cada leitura registrada. Ferramenta para apoio a investigações.

**Arquivos a criar/modificar:**
- `routes/dashboard.py` — 2 novas rotas
- `templates/investigacao.html` — nova tela (estende `base.html`)

**Rota de página:**
```
GET /investigacao
```
Renderiza `investigacao.html` com lista de viaturas para o filtro.

**API de dados:**
```
GET /api/investigacao/trajeto
```
Parâmetros query (todos opcionais):
- `placa` — substring (ex: `ABC`)
- `marca`, `modelo`, `cor`, `tipo_veiculo` — ilike substring
- `data_inicio`, `data_fim` — formato `YYYY-MM-DD`
- `hora_inicio`, `hora_fim` — inteiro 0–23 (filtra pela hora do dia)

Query SQLAlchemy:
```python
from sqlalchemy import extract
q = Deteccao.query.filter(
    Deteccao.latitude.isnot(None),
    Deteccao.longitude.isnot(None)
)
# aplicar filtros opcionais...
# extract('hour', Deteccao.recebido_em) para filtro de hora
q = q.order_by(Deteccao.recebido_em.asc()).limit(500)
```

Retorno JSON:
```json
{
  "total": 12,
  "pontos": [
    {
      "lat": -23.55, "lon": -46.63,
      "placa": "ABC1234", "viatura_id": "VTR-TATICA-01",
      "recebido_em": "26/05/2026 14:30:00",
      "marca": "Toyota", "modelo": "Corolla", "cor": "Prata",
      "score": 0.92, "velocidade": 45.0, "alerta_tatico": false
    }
  ]
}
```

**Layout `investigacao.html`:**
- Topo: formulário de filtros (placa, marca, modelo, cor, tipo, data_inicio, data_fim, hora_inicio, hora_fim)
- Lado esquerdo (35%): lista de detecções com numeração, data/hora BRT, placa em destaque, viatura
- Lado direito (65%): mapa Leaflet (dark) — polyline teal (`#00c8dc`) + marcadores numerados
- Popup de cada marcador: placa, data/hora, viatura, velocidade, score
- Marcador inicial = verde (primeiro avistamento), final = vermelho (último)
- Reutilizar o tileset CartoDB Dark Matter já usado em `templates/mapa.html`
- Mensagem "Nenhum resultado com coordenada GPS" se total = 0

**Sidebar ARGOS:** adicionar link "Investigação" na navegação em `templates/base.html`

---

### 4.2 — Tela de Detalhes de uma Leitura ✅ CONCLUÍDA
**Commit:** `34de6fc`

- `routes/dashboard.py`: rota `GET /leituras/<id>` → `detalhe_leitura()`
- `templates/detalhe_leitura.html`: cabeçalho (placa/viatura/situação), card veículo, card confiança (score + dscore), card GPS (lat/lon/alt/satélites/status + mini-mapa Leaflet dark), card timestamps
- `templates/leituras.html` e `alertas.html`: linhas clicáveis (cursor:pointer) para abrir detalhe

**⚠️ REVISÃO PENDENTE COM PI (campo):**
- Validar que coordenada GPS exibida no detalhe é a posição da viatura no momento da leitura (não do heartbeat)
- Confirmar campos marca/modelo/cor/tipo chegando preenchidos do equipamento
- Ver também item 4.4: validar prioridade/motivo na hotlist com placa real

---

### 4.3 — Alerta Sonoro no Painel ✅ CONCLUÍDA

- `templates/base.html`: beep tático triplo (880→1100→880 Hz) via Web Audio API — sem arquivo externo
- Som dispara **somente** em `alerta_tatico: true` (match na hotlist)
- Botão mudo/ativo na navbar (ícone 🔊/🔇) com estado persistido em `localStorage`
- Toast e badge navbar já existentes — mantidos

---

### 4.6 — UX Review da Tela Hotlist ⏳ PLANEJADA

**Objetivo:** revisar a tela `/hotlist` sob a perspectiva de um operador policial que usa o sistema em campo, com foco em usabilidade, clareza visual e eficiência operacional.

**Problemas identificados:**

| # | Problema | Impacto | Solução proposta |
|---|---|---|---|
| 1 | Sem busca na tabela | Difícil achar placa quando lista cresce | Campo de filtro instantâneo em JS (sem recarregar) |
| 2 | Sem edição inline | Alterar motivo/prioridade exige remover e re-adicionar | Modal ou linha expansível com form de edição |
| 3 | Sem toggle ativo/inativo | Só tem "remover" — sem desativar temporariamente | Botão toggle (ativa/inativa) separado do botão excluir |
| 4 | Coluna direita sobrecarregada | 4 cards empilhados geram muito scroll em telas menores | Reorganizar: tabs ou accordion na coluna direita |
| 5 | Sem flash messages de confirmação | Após adicionar/remover, nenhum feedback visual | `flash()` do Flask com categoria success/danger |
| 6 | Validação de placa fraca | Aceita qualquer 7 chars; não valida Mercosul/formato antigo | Regex no cliente e servidor (AAA1234 ou AAA1A23) |
| 7 | Sem contador por prioridade | Não dá para ver rapidamente "quantas Alta?" | Mini-badges no cabeçalho: 🔴 3 🟡 12 ⚪ 5 |
| 8 | Botão excluir muito exposto | Fácil clicar por acidente na operação | Confirm dialog já existe, mas mover para ícone menor |
| 9 | Sem paginação ou virtualização | Com >200 placas, tabela fica pesada | Paginação ou scroll virtual no front |
| 10 | Importação CSV sem feedback de linha | Ao importar, não mostra quantas foram adicionadas vs ignoradas | Retornar contagem: N adicionadas, N duplicatas ignoradas |

**Critérios de aceite:**
- [ ] Operador consegue encontrar uma placa em <5s em lista com 100 entradas
- [ ] Operador consegue alterar prioridade de uma placa sem remover e re-adicionar
- [ ] Feedback visual imediato após qualquer ação (adicionar/remover/editar/importar)
- [ ] Validação de formato de placa no formulário impede entradas inválidas
- [ ] Contadores por prioridade visíveis no cabeçalho sem rolar a página

---

### 4.5 — Motivos Dinâmicos na Hotlist ✅ CONCLUÍDA
**Commit:** pendente push

- `models.py`: novo modelo `MotivoHotlist` (tabela `motivos_hotlist`, campo `nome` único)
- `app.py`: `_seed_motivos()` — popula 8 motivos padrão (Roubo, Furto, Mandado de Busca, Investigação, Suspeito, Busca e Apreensão, Receptação, Tráfico)
- `routes/dashboard.py`: importa `MotivoHotlist`; trata `acao == "adicionar_motivo"` e `acao == "remover_motivo"`; passa `motivos` ao template
- `templates/hotlist.html`: datalist `motivos-sugeridos` gerado dinamicamente via `{% for m in motivos %}`; novo card "Motivos Cadastrados" com lista + botão remover + campo para adicionar novo motivo

---

### 4.4 — Hotlist com Prioridade, Motivo e Observação ✅ CONCLUÍDA
**Commits:** `75296d0`, `d5ea804`, `0785d70`

- `models.py`: `motivo` (String 64), `prioridade` (Integer 1/2/3), `observacao` (Text) na Hotlist
- `_migrar_schema()` em `app.py`: migrations com `DEFAULT FALSE` (não `DEFAULT 0`) para colunas BOOLEAN
- `routes/dashboard.py`: form lê prioridade/motivo/observacao; hotlist ordenada por prioridade
- `templates/hotlist.html`: badge prioridade (🔴Alta/🟡Média/⚪Baixa), datalist de motivos sugeridos
- `/healthz` endpoint temporário adicionado para diagnóstico de schema

**Bug crítico descoberto:** `BOOLEAN DEFAULT 0` é rejeitado pelo PostgreSQL (aceita só `FALSE`/`TRUE`).
Ver seção de lições aprendidas em `feedback_tecnico.md`.

---

## Sprint 5 — Auditoria e Produção ⏳ PLANEJADA

### 5.1 — Trilha de Auditoria

**Objetivo:** registrar quem fez o quê e quando — alterações na hotlist e ações de usuários.

**Novo modelo `LogAuditoria`:**
```python
class LogAuditoria(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    usuario     = db.Column(db.String(64))
    acao        = db.Column(db.String(128))   # ex: "hotlist:adicionar:ABC1234"
    detalhe     = db.Column(db.Text)
    criado_em   = db.Column(db.DateTime, default=_utcnow)
```

Registrar em: adicionar/remover/importar hotlist, sync de config, comandos enviados ao Pi.
Tela `/auditoria` (só admin) com filtro de período e usuário.

---

### 5.2 — Revisão GPS↔Leitura (pendência registrada na memória)

**Objetivo:** garantir que a coordenada GPS salva na detecção é a posição da viatura **no momento da leitura**, não do último heartbeat.

**Pontos a revisar (Pi-side):**
1. `webhook_handler.py` — lê `gps.get_position()` no momento do webhook e inclui lat/lon no payload
2. `telemetry.py` / payload de detecção — campos `latitude/longitude` chegam preenchidos no `POST /api/argos/telemetry`

**Pontos a revisar (QG-side):**
3. `_salvar_deteccao()` em `telemetry.py` — salva `latitude/longitude` do payload (não do heartbeat)
4. Mapa — pin da detecção usa coordenada da detecção, não da viatura
5. Validação em campo: cadastrar placa na hotlist, passar com carro, confirmar pin correto no mapa

---

### 5.3 — Política de Retenção de Dados

**Objetivo:** evitar crescimento ilimitado do banco em produção.

- Tarefa agendada (cron ou endpoint admin): deletar `Deteccao` e `Heartbeat` com mais de N dias (configurável, ex: 180 dias)
- Tela de admin com contagem de registros por tabela e botão "Limpar dados antigos"

---

### 5.4 — Backup do Banco

**Objetivo:** garantir que dados não sejam perdidos.

- Railway PostgreSQL tem backup automático no plano pago (verificar se está ativo)
- Documentar procedimento de restore
- Alternativa: endpoint `/admin/backup` que exporta dump CSV de todas as tabelas

---

## Sprint 6 — Monitoramento de Eventos do Sistema

**Objetivo:** detectar e notificar falhas operacionais em tempo real — perda de comunicação com o Pi, falha da câmera/LPR, perda de sinal GPS, temperatura alta, buffer crescendo.

---

### 6.1 — QG-side (App Web) ✅ CONCLUÍDA
**Commit:** pendente push

**Modelo `EventoSistema`** (nova tabela):
```python
class EventoSistema(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    viatura_id  = db.Column(db.String(64), index=True)
    tipo        = db.Column(db.String(32))   # ver tabela abaixo
    severidade  = db.Column(db.String(8))    # "critico" | "aviso" | "info"
    detalhe     = db.Column(db.Text)
    resolvido   = db.Column(db.Boolean, default=False)
    criado_em   = db.Column(db.DateTime, default=_utcnow)
```

**Tipos de evento e thresholds:**

| Tipo | Condição | Severidade |
|---|---|---|
| `pi_offline` | Sem heartbeat há >5 min | Crítico |
| `pi_reconectado` | Heartbeat após offline | Info |
| `lpr_offline` | `lpr_health = 0` ou `None` | Crítico |
| `lpr_degradado` | `lpr_health < 70%` | Aviso |
| `gps_sem_sinal` | `satellites < 4` ou `gps_status` ≠ "3D Fix" | Aviso |
| `gps_restaurado` | GPS volta ao normal após sem sinal | Info |
| `buffer_crescendo` | `buffer_pendente > 50` detecções | Aviso |
| `cpu_quente` | `cpu_temp_c > 80°C` | Aviso |
| `camera_erro` | Enviado explicitamente pelo Pi | Crítico |

**Detecção automática no QG** (via análise dos heartbeats recebidos em `telemetry.py`):
- `_verificar_eventos(viatura_id, payload)` — chamada após `_salvar_heartbeat()`
- Compara valores do heartbeat com thresholds
- Gera `EventoSistema` se condição nova (não gera duplicata enquanto evento não resolvido)
- Broadcast SSE `system_event` para todos os clientes conectados

**Tela `/eventos`** (admin):
- Filtros: viatura, tipo, severidade, período
- Tabela com ícone de severidade, tipo, detalhe, data, status (resolvido/ativo)
- Badge na navbar com contagem de eventos críticos ativos (não resolvidos)

**Widget no Dashboard** (card "Saúde da Frota"):
- Linha por viatura: ícones de status para Pi, LPR, GPS, Temp, Buffer
- Verde = OK, amarelo = aviso, vermelho = crítico, cinza = sem dados

---

### 6.2 — Pi-side (ajustes no código)

Os campos já enviados nos heartbeats cobrem a maioria dos eventos. Ajustes necessários:

**Enviar eventos explícitos** (novo tipo de payload `tipo: "evento"`):
- **Falha de câmera**: quando `camera_server.py` ou o stream HTTP cair → enviar `tipo: "evento"`, `subtipo: "camera_erro"`
- **GPS fix perdido/recuperado**: quando `gps_status` muda de/para "3D Fix" → enviar evento de transição
- **LPR parou**: quando Health Score cai para 0 por >30s (camera travada) → enviar `subtipo: "lpr_offline"`

**Heartbeat — campos a confirmar:**
- `lpr_health`: já enviado (0.0–1.0)
- `cpu_temp_c`: já enviado
- `buffer_pendente`: já enviado (contagem de eventos no OfflineBuffer)
- `gps_status`: já enviado (`""`, `"2D Fix"`, `"3D Fix"`)
- `satellites`: já enviado

**Arquivos a modificar no Pi:**
- `src/main.py` — `_salvar_heartbeat()` + nova thread `EventMonitor`
- `src/qg_sender.py` — suporte a `tipo: "evento"` no payload enviado ao QG

---

## Sprint 7 — Correções de Segurança, Qualidade e Performance ⏳ PLANEJADA

> Originada da revisão técnica completa realizada em 27/05/2026 (três agentes paralelos: backend, frontend/UX, segurança/arquitetura). Todos os itens abaixo são bugs reais encontrados em código de produção.

---

### 7.1 — Segurança Crítica 🔴 PRIORIDADE MÁXIMA

Deve ser feita **antes** de qualquer operação em campo ou exposição da URL pública a terceiros.

**Lição aprendida (S-1/S-2/S-3):** Sempre configurar as env vars no Railway **antes** de fazer push do código que remove fallbacks. O `.env` local é gitignored — Railway não o lê. O `QG_API_KEY` deve manter o mesmo valor que o Pi usa. Grep em todos os arquivos para encontrar todos os usos do secret antes de declarar concluído (estava em 3 arquivos: `app.py`, `telemetry.py`, `api_viaturas.py`).

| # | Problema | Arquivo | Solução |
|---|---|---|---|
| S-1 | `SECRET_KEY` hardcoded com fallback público `"dev-secret-key-mude-em-prod"` | `app.py` | `os.environ["SECRET_KEY"]` — levantar `ValueError` se ausente |
| S-2 | `QG_API_KEY` hardcoded com fallback `"argos-key-dev"` | `app.py`, `api_viaturas.py` | Idem — somente via env var |
| S-3 | Senha admin padrão `"admin123"` hardcoded no seed | `app.py` | Ler de `ADMIN_PASSWORD` env var; gerar aleatória se ausente e logar no boot |
| S-4 | `debug=True` hardcoded no `app.run()` | `app.py` | `debug=os.getenv("FLASK_DEBUG","0")=="1"` |
| S-5 | Open Redirect no login — parâmetro `next` não é validado | `routes/dashboard.py` | Validar com `is_safe_url()` (checar que começa com `/` e não tem `//`) |
| S-6 | `/api/stream` (SSE) sem autenticação — qualquer pessoa na internet ouve alertas táticos | `routes/api_stream.py` | Adicionar `@login_required` |
| S-7 | `/healthz` expõe estrutura do banco sem autenticação | `app.py` | Restringir a `127.0.0.1` OU adicionar `@login_required` OU remover |
| S-8 | XSS via `innerHTML` no feed SSE do dashboard — `d.placa`, `d.marca`, `d.modelo`, `d.cor`, `d.viatura_id` não são escapados | `templates/dashboard.html` | Criar `escapeHtml()` em JS e aplicar em todos os campos interpolados via `innerHTML` |
| S-9 | XSS nos popups Leaflet de `investigacao.html` — dados da detecção concatenados diretamente no HTML do popup | `templates/investigacao.html` | Aplicar `escapeHtml()` em todos os campos antes de montar o popup |
| S-10 | XSS em `confirm()` na hotlist — `'${placa}'` sem escape, placa pode conter aspas simples | `templates/hotlist.html` | Usar atributo `data-placa` no botão e ler via `dataset` em JS |
| S-11 | Logout via GET (`/logout`) — vulnerável a CSRF (link externo pode deslogar usuário) | `routes/dashboard.py`, `templates/base.html` | Mudar para `POST` com form; adicionar CSRF token |
| S-12 | Cookies de sessão sem flags de segurança | `app.py` | Adicionar: `SESSION_COOKIE_SECURE=True`, `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"`, `PERMANENT_SESSION_LIFETIME=timedelta(hours=8)` |
| S-13 | Sem proteção CSRF em nenhum formulário POST (Flask-WTF não instalado) | todos os templates | Instalar `Flask-WTF`, habilitar `CSRFProtect(app)`, adicionar `{{ form.hidden_tag() }}` ou meta tag + JS |
| S-14 | Sem rate limiting no login — brute force ilimitado | `routes/dashboard.py` | Instalar `Flask-Limiter`; aplicar `@limiter.limit("5/minute")` na rota `/login` |
| S-15 | CSV import sem limite de tamanho — DoS: upload de arquivo de 100 MB trava o servidor | `routes/dashboard.py` | Verificar `len(content) > 500_000` antes de processar; validar formato de placa com regex |
| S-16 | SSE broadcast ANTES do `db.session.commit()` em `telemetry.py` — cliente recebe dado que pode não ter sido gravado | `routes/telemetry.py` | Mover `_broadcast()` para DEPOIS do `db.session.commit()` |
| S-17 | `_verificar_pi_offline()` chama `db.session.commit()` dentro de rota que pode já ter transação em andamento — risco de double-commit ou rollback silencioso | `routes/dashboard.py` | Remover `db.session.commit()` da função; deixar o commit para o caller da rota |
| S-18 | Links com `target="_blank"` sem `rel="noopener noreferrer"` — tab-napping | vários templates | Adicionar `rel="noopener noreferrer"` em todos os `target="_blank"` |

---

### 7.2 — Performance, Qualidade e UX Técnico 🟡

| # | Problema | Arquivo | Solução |
|---|---|---|---|
| P-1 | Leaflet (~143 KB) + ApexCharts (~1,1 MB) carregados em **todas** as páginas via `base.html` — páginas sem mapa pagam 1,2 MB desnecessários | `templates/base.html` | Mover para `{% block extra_css/js %}` — incluir apenas em `mapa.html`, `investigacao.html`, `detalhe_leitura.html` e `viaturas.html` |
| P-2 | 3 conexões SSE simultâneas abertas pelo mesmo navegador — `base.html` + `dashboard.html` + `mapa.html` criam cada um seu `EventSource` | `templates/base.html`, `dashboard.html`, `mapa.html` | Centralizar **uma** conexão em `base.html`; `dashboard.html` e `mapa.html` escutam evento JS customizado em vez de criar novo `EventSource` |
| P-3 | N+1 queries em `_verificar_pi_offline()` — faz `v.ultimo_heartbeat()` (1 query) para cada viatura em loop | `routes/dashboard.py` | Carregar todos os últimos heartbeats em uma única query com `GROUP BY viatura_id` antes do loop |
| P-4 | Hotlist carregada inteira na memória a cada detecção — `Hotlist.query.filter_by(ativa=True).all()` para fazer match de uma placa | `routes/telemetry.py` | Usar `db.session.query(db.exists().where(...)).scalar()` — retorna bool sem trazer registros |
| P-5 | N queries em `_verificar_eventos()` — para cada tipo de evento, faz uma query separada no banco | `routes/telemetry.py` | Carregar todos eventos abertos da viatura de uma vez: `EventoSistema.query.filter_by(viatura_id=vid, resolvido=False).all()` e fazer lookup em memória |
| P-6 | `_marcar_hotlist_pendente()` atualiza cada viatura em loop individual — N UPDATEs separados | `routes/dashboard.py` | Usar `Viatura.query.filter_by(ativa=True).update({"hotlist_pendente": True})` — 1 UPDATE bulk |
| P-7 | `strptime` sem try/except em filtros de data — crash 500 se operador digitar data inválida | `routes/dashboard.py` | Envolver em `try/except ValueError` e ignorar filtro inválido com flash de aviso |
| P-8 | Mapa crasha quando viatura não tem GPS — `L.marker([null, null])` lança exceção | `templates/mapa.html` | Adicionar `if (!v.latitude || !v.longitude) return;` antes de criar o marcador |
| P-9 | Macro `icone()` definida **dentro** do `{% for v in viaturas %}` — redefinida a cada iteração | `templates/dashboard.html` | Mover a definição `{% macro icone(...) %}` para fora do loop `{% for %}` |
| P-10 | CSV export sem LIMIT — exportar 500 mil registros pode travar o servidor | `routes/dashboard.py` | Adicionar `.limit(50_000)` na query de export OU implementar export paginado com aviso |
| P-11 | `fetch()` do botão Sincronizar Config e do histórico sem `.catch()` — erros de rede silenciosos para o operador | `templates/config_viatura.html`, `templates/investigacao.html` | Adicionar `.catch(err => ...)` com mensagem visual de erro |
| P-12 | Badge "OK" no feed SSE do dashboard (JavaScript) vs "NORMAL" no template Jinja2 — inconsistência visual | `templates/dashboard.html` | Padronizar para "NORMAL" no JS também |
| P-13 | `lazy="dynamic"` depreciado no SQLAlchemy 2.x — gera `LegacyAPIWarning` nos logs | `models.py` | Substituir por `lazy="write_only"` (ou `lazy="select"` se a relação for lida) |
| P-14 | `.query.get(id)` depreciado no SQLAlchemy 2.x — quebra na versão 3.x | vários arquivos em `routes/` | Substituir por `db.session.get(Model, id)` em todos os usos |
| P-15 | Sem PRG (Post/Redirect/Get) nas ações da hotlist — F5 repete a última ação POST | `routes/dashboard.py` | Adicionar `return redirect(url_for("dashboard.hotlist"))` após toda ação POST bem-sucedida |
| P-16 | Sem SRI (Subresource Integrity) nos assets CDN — CDN comprometido = XSS universal | `templates/base.html` | Adicionar `integrity="sha384-..."` e `crossorigin="anonymous"` nas tags `<link>` e `<script>` dos CDNs |
| P-17 | Sem índices compostos no banco para queries frequentes | `models.py` | Adicionar `Index("ix_evento_resolvido_sev", "resolvido", "severidade")` em `EventoSistema`; `Index("ix_deteccao_viatura_ts", "viatura_id", "recebido_em")` em `Deteccao` |
| P-18 | Card-footer das viaturas com `background: #f8f9fa` (branco) — destoante do tema escuro do sistema | `templates/viaturas.html` | Substituir por `background: #1a1d23; color: #adb5bd` |

---

## Sprint Pi-B — Comandos + Config + Imagens

**Pré-requisito:** Sprint Pi-A Pi-side concluída

### Comandos via polling: ⏳ PLANEJADO
- QG: tabela `ComandoPendente`, endpoints fila + ack
- Pi: `command_polling.py` — thread 30s

### Config via polling (resolve Sincronizar offline): ⏳ PLANEJADO
- QG: `GET /api/viaturas/<id>/config/pending`
- Pi: `config_polling.py` — aplica e confirma ao QG

---

### Pi-B.1 — Imagens em Alertas Táticos (estrutura BYTEA) ✅ QG CONCLUÍDO
**Commit QG:** `ef3961d`

**Decisão arquitetural:**
- Somente o **crop da placa** é enviado ao QG (nunca o frame completo do veículo)
- Redimensionamento para max 300px de largura via Pillow (JPEG 75%, limite 60 KB)
- Armazenado como **BYTEA** no PostgreSQL (`LargeBinary` no SQLAlchemy) — não TEXT base64

| Arquivo | Alteração |
|---|---|
| `APP_WEB/models.py` | `imagem_placa = LargeBinary` na `Deteccao` |
| `APP_WEB/app.py` | Migration `ALTER TABLE deteccoes ADD COLUMN imagem_placa BYTEA` |
| `APP_WEB/routes/telemetry.py` | `_salvar_deteccao()`: decodifica base64 → bytes e salva |
| `APP_WEB/routes/dashboard.py` | Rota `GET /leituras/<id>/imagem_placa` serve JPEG binário (`Cache-Control: private, max-age=86400`) |
| `APP_WEB/templates/alertas.html` | Thumbnail 36px na listagem; ícone câmera-slash quando sem imagem |
| `APP_WEB/templates/detalhe_leitura.html` | Card "Imagem da Placa" com borda vermelha |
| `RASPBERRY/src/webhook_handler.py` | Função `_thumbnail_placa_b64()` com Pillow; crop só enviado em alertas (Pi-B.1) |

---

### Pi-B.2 — Imagens em TODAS as Detecções + Thumbnails Dashboard/Leituras ✅ QG CONCLUÍDO
**Commit QG:** `7e5cd99` — 27/05/2026

**Decisão revisada:** imagem enviada em **todas** as detecções, independente de hotlist match e do modo de operação (Híbrido, Nuvem/Online, Local/Offline).

**Mudanças em relação ao Pi-B.1:**

| Arquivo | Alteração |
|---|---|
| `RASPBERRY/src/webhook_handler.py` | Remove condição `if not e_alerta` — `imagem_placa` sempre incluída no buffer |
| `RASPBERRY/src/offline_buffer.py` | `_persist_to_disk()` exclui `imagem_placa` do disco (~50 MB economizados com 5.000 registros); imagem fica só em memória — se Pi reiniciar offline, evento é reenviado sem foto |
| `APP_WEB/models.py` | `to_dict()` agora inclui `"tem_imagem": self.imagem_placa is not None` para SSE JS |
| `APP_WEB/routes/telemetry.py` | **Fix S-16:** `db.session.commit()` movido para ANTES de `_broadcast()` — garante imagem no banco quando browser requisitar |
| `APP_WEB/templates/dashboard.html` | Nova coluna thumbnail (50px sem header) no Feed ao Vivo: thead + Jinja2 + JS SSE handler com `d.tem_imagem`; linhas clicáveis → detalhe |
| `APP_WEB/templates/leituras.html` | Nova coluna thumbnail (50px sem header) no Log de Leituras; colspan atualizado para 8 |

**Retrocompatibilidade:** `onerror="this.style.display='none'"` em todos os `<img>` — detecções antigas sem imagem não quebram o layout.

**Impacto de storage:** ~10 KB/detecção × 1.000 leituras/dia = **~10 MB/dia** no PostgreSQL. Sprint 5.3 (retenção de dados) torna-se prioritária.

**Deploy Pi-B (ambos Pi-B.1 e Pi-B.2):** ⏳ PENDENTE — aguardando Pi disponível.
```bash
scp RASPBERRY/src/webhook_handler.py diego@100.127.61.22:~/argos/src/
scp RASPBERRY/src/offline_buffer.py diego@100.127.61.22:~/argos/src/
ssh diego@100.127.61.22 "sudo systemctl restart argos"
```
Sem isso, o Pi usa o código antigo e **não envia imagens** ao QG.

---

## Checklist Geral

### Concluídos ✅
- [x] Endpoint `/api/argos/telemetry` com validação X-API-Key
- [x] Banco PostgreSQL em produção no Railway
- [x] `/alertas` e `/leituras` com filtros e exportação CSV
- [x] Dashboard tempo real (SSE) com viaturas online/offline
- [x] Cadastro manual de viatura
- [x] Config LPR completa (todos os params PlateRecognizer) com legendas em 4 abas
- [x] Botão Sincronizar config com badge Pendente/Sincronizado
- [x] Login HUD tático Argos Vision (boot, glitch, gradiente teal)
- [x] Páginas 404/403/500 tema ARGOS
- [x] Hotlist híbrida (Pi OU QG fazem match)
- [x] Hotlist sync QG-side: flag automática + 3 endpoints Pi
- [x] Mapa com posição das viaturas em tempo real + trajetória por heartbeat
- [x] Filtros histórico: viatura, placa, data, só alertas
- [x] Hotlist com prioridade (Alta/Média/Baixa), motivo e observação (Sprint 4.4)
- [x] Trajetória investigativa — GPS path por placa/marca/modelo/cor/hora (Sprint 4.1)
- [x] Tela de detalhes individual de leitura (Sprint 4.2)
- [x] Alerta sonoro tático (beep triplo, botão mudo, somente match hotlist) (Sprint 4.3)
- [x] Motivos dinâmicos na hotlist — CRUD via UI, sem deploy (Sprint 4.5)
- [x] Imagens da placa (BYTEA) — estrutura QG + rota servir JPEG + thumbnail alertas + card detalhe (Sprint Pi-B.1) — `ef3961d`
- [x] Imagens em TODAS as detecções + thumbnails Dashboard e Log de Leituras (Sprint Pi-B.2) — `7e5cd99`
- [x] Fix S-16: `db.session.commit()` antes de `_broadcast()` SSE — `7e5cd99`

### Pendentes ⏳

#### 🔴 Segurança — Sprint 7.1 (fazer antes de ir ao campo)
- [x] S-1/S-2/S-3: Secrets e senhas hardcoded → variáveis de ambiente obrigatórias ✅ `4e6f4f8`
- [x] S-4: `debug=True` hardcoded → `os.getenv("FLASK_DEBUG","0")=="1"` ✅ `495d9b6`
- [ ] S-5: Open Redirect no login → validar parâmetro `next`
- [x] S-6: `/api/stream` SSE sem autenticação → `@login_required` ✅ `495d9b6`
- [ ] S-7: `/healthz` exposto publicamente → restringir ou remover
- [ ] S-8/S-9: XSS via `innerHTML` no feed SSE e popups Leaflet → `escapeHtml()`
- [ ] S-10: XSS no `confirm()` da hotlist → `data-placa` + `dataset`
- [ ] S-11: Logout via GET → mudar para POST + CSRF token
- [ ] S-12: Cookies de sessão sem flags SECURE/HTTPONLY/SAMESITE
- [ ] S-13: Sem CSRF em formulários → instalar Flask-WTF
- [ ] S-14: Login sem rate limiting → instalar Flask-Limiter
- [ ] S-15: CSV import sem limite de tamanho → limitar a 500 KB + validar placa
- [x] S-16: SSE broadcast antes do commit → movido para depois ✅ `7e5cd99`
- [ ] S-17: Double-commit em `_verificar_pi_offline()` → remover commit interno
- [ ] S-18: `target="_blank"` sem `rel="noopener noreferrer"`

#### 🟡 Performance e Qualidade — Sprint 7.2
- [ ] P-1: Leaflet + ApexCharts carregados globalmente → mover para páginas específicas
- [ ] P-2: 3 conexões SSE simultâneas → centralizar 1 conexão em `base.html`
- [ ] P-3: N+1 queries em `_verificar_pi_offline()` → bulk query
- [ ] P-4: Hotlist carregada inteira por detecção → query EXISTS no banco
- [ ] P-5: N queries em `_verificar_eventos()` → carregar de uma vez
- [ ] P-6: `_marcar_hotlist_pendente()` N UPDATEs → 1 UPDATE bulk
- [ ] P-7: `strptime` sem try/except → tratar data inválida com flash
- [ ] P-8: Mapa crasha sem GPS → guard `if (!v.latitude || !v.longitude)`
- [ ] P-9: Macro `icone()` dentro do loop → mover para fora do `{% for %}`
- [ ] P-10: CSV export sem LIMIT → limitar a 50.000 registros
- [ ] P-11: `fetch()` sem `.catch()` no Sincronizar e histórico
- [ ] P-12: Badge "OK" vs "NORMAL" inconsistente → padronizar para "NORMAL"
- [ ] P-13: `lazy="dynamic"` depreciado → `lazy="write_only"`
- [ ] P-14: `.query.get()` depreciado → `db.session.get()`
- [ ] P-15: Sem PRG nas ações da hotlist → `redirect()` após POST
- [ ] P-16: Sem SRI nos assets CDN → adicionar `integrity=` hash
- [ ] P-17: Sem índices compostos → adicionar em `EventoSistema` e `Deteccao`
- [ ] P-18: Card-footer das viaturas branco → tema escuro

#### ⏳ Outros pendentes
- [ ] **Revisão em campo com Pi** — RV-1 (detalhe leitura), RV-2 (hotlist), RV-3 (trajetória), RV-4 (alerta sonoro + motivos)
- [ ] Deploy Sprint Pi-A Pi-side (aguardando Pi disponível)
- [ ] Monitoramento de eventos Pi-side — eventos explícitos câmera/GPS/LPR (Sprint 6.2)
- [ ] UX Review da tela Hotlist — busca, edição inline, toggle ativo/inativo (Sprint 4.6)
- [ ] Revisão GPS↔Leitura (Sprint 5.2)
- [ ] Trilha de auditoria de ações (Sprint 5.1)
- [ ] Política de retenção de dados históricos (Sprint 5.3)
- [ ] Backup configurado do banco (Sprint 5.4)
- [ ] Comandos polling Pi-side (Sprint Pi-B)
- [ ] Config polling Pi-side (Sprint Pi-B)
- [ ] Imagens da placa no Pi — **QG deployado** (`ef3961d` + `7e5cd99`), **Pi pendente SCP** (Sprint Pi-B.1 + Pi-B.2)
