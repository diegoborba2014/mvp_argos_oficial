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

## Sprint 6 — Monitoramento de Eventos do Sistema ⏳ PLANEJADA

**Objetivo:** detectar e notificar falhas operacionais em tempo real — perda de comunicação com o Pi, falha da câmera/LPR, perda de sinal GPS, temperatura alta, buffer crescendo.

---

### 6.1 — QG-side (App Web)

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

## Sprint Pi-B — Comandos + Config + Imagens ⏳ PLANEJADA

**Pré-requisito:** Sprint Pi-A Pi-side concluída

### Comandos via polling:
- QG: tabela `ComandoPendente`, endpoints fila + ack
- Pi: `command_polling.py` — thread 30s

### Config via polling (resolve Sincronizar offline):
- QG: `GET /api/viaturas/<id>/config/pending`
- Pi: `config_polling.py` — aplica e confirma ao QG

### Imagens das detecções:
- QG: `imagem_veiculo` / `imagem_placa` (TEXT base64) na `Deteccao`; thumbnails 80×60px em alertas e leituras
- Pi: `qg_sender.py` envia imagens em base64 (max 100KB)

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

### Pendentes ⏳
- [ ] **Revisão em campo com Pi** — RV-1 (detalhe leitura), RV-2 (hotlist), RV-3 (trajetória)
- [ ] Deploy Sprint Pi-A Pi-side (aguardando Pi disponível)
- [ ] Monitoramento de eventos — Pi offline, LPR, GPS, CPU, buffer (Sprint 6.1 QG + 6.2 Pi)
- [ ] Revisão GPS↔Leitura (Sprint 5.2)
- [ ] Trilha de auditoria de ações (Sprint 5.1)
- [ ] Política de retenção de dados históricos (Sprint 5.3)
- [ ] Backup configurado do banco (Sprint 5.4)
- [ ] Comandos polling Pi-side (Sprint Pi-B)
- [ ] Config polling Pi-side (Sprint Pi-B)
- [ ] Imagens das detecções (Sprint Pi-B)
