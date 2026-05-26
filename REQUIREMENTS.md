# ARGOS QG — Plataforma Web de Comando

> **Sub-projeto:** Interface web para o Quartel-General (QG)  
> **Contexto:** O equipamento ARGOS (Raspberry Pi 5 em cada viatura) envia telemetria via 4G para esta plataforma.  
> **Execução local:** `python app.py` — roda em `http://localhost:5000`  
> **Deploy futuro:** servidor Linux com domínio próprio (ex: `http://34.186.146.135`)  
> **IMPORTANTE:** estes arquivos são exclusivos do QG — não devem ser enviados ao Pi.

---

## Contexto do Sistema

Cada viatura policial tem um Raspberry Pi 5 (ARGOS INTERCEPTOR V2.0) que:
- Lê placas de veículos em tempo real pela câmera
- Verifica se a placa está numa hotlist de monitorados
- Envia detecções e heartbeats via 4G para esta plataforma
- Aceita comandos remotos desta plataforma (hotlist, config, controle)

A comunicação é **sempre iniciada pelo equipamento** (push). A plataforma só precisa ter endpoints disponíveis para receber.

Referências técnicas completas: `docs/INTEGRATION_GUIDE.md` e `docs/qg_receiver_reference.py`

---

## Stack Tecnológica

| Componente | Escolha | Motivo |
|---|---|---|
| Backend | Python / Flask | Mesma stack do equipamento, dev já conhece |
| Banco de dados | SQLite (local) → PostgreSQL (produção) | Zero configuração para começar |
| Frontend | Bootstrap 5 + Jinja2 | Simples, sem build step |
| Mapa | Leaflet.js | Open source, sem API key |
| Tempo real | SSE (Server-Sent Events) | Mais simples que WebSocket para este caso |
| Autenticação | Flask-Login + sessão | Login simples para operadores |

---

## Módulos / Telas

### 1. Endpoint de Telemetria (backend — sem tela)

`POST /api/argos/telemetry`

- Recebe eventos de detecção e heartbeats de todas as viaturas
- Autentica via header `X-API-Key`
- Persiste no banco de dados
- Dispara alerta em tempo real se `alerta_tatico = true`
- Responde `200 OK` para confirmar recebimento (remove do buffer do equipamento)

**Campos recebidos — detecção:**
`viatura_id`, `placa`, `score`, `marca`, `modelo`, `cor`, `velocidade`, `direcao`,
`alerta_tatico`, `latitude`, `longitude`, `timestamp`, `bbox_placa`, `bbox_veiculo`

**Campos recebidos — heartbeat:**
`viatura_id`, `tipo=heartbeat`, `gps`, `lpr_health`, `lpr_fps`, `cpu_temp_c`, `buffer_pendente`

---

### 2. Dashboard Principal (`/`)

Visão geral em tempo real de toda a frota.

**Elementos:**
- Cards por viatura: status (online/offline), última placa lida, GPS, temperatura CPU, health LPR
- Contador de alertas táticos hoje
- Contador de leituras totais hoje
- Indicador de viaturas offline (sem heartbeat > 5 min)
- Feed ao vivo das últimas detecções (lista rolante, atualiza via SSE)

---

### 3. Mapa de Frota (`/mapa`)

- Marcadores no mapa para cada viatura ativa (Leaflet.js)
- Posição atualizada a cada heartbeat (60s)
- Clique no marcador: abre popup com status da viatura
- Alertas táticos: marcador pisca em vermelho
- Rastreio de trajeto: linha mostrando últimas N posições

---

### 4. Alertas Táticos (`/alertas`)

Lista de todas as detecções com `alerta_tatico = true`.

**Colunas:** Data/hora, Viatura, Placa, Veículo (marca/modelo/cor), Velocidade, GPS (link Google Maps), Confiança

**Funcionalidades:**
- Filtro por viatura, data, placa
- Exportar CSV
- Notificação sonora + visual no browser quando novo alerta chega (SSE)

---

### 5. Log de Leituras (`/leituras`)

Histórico completo de todas as placas lidas.

**Colunas:** Data/hora, Viatura, Placa, Veículo, Velocidade, Confiança, Alerta?

**Funcionalidades:**
- Filtro por viatura, data, placa, apenas alertas
- Paginação (50 por página)
- Exportar CSV do período filtrado

---

### 6. Gestão de Viaturas (`/viaturas`)

Lista de todas as viaturas cadastradas.

**Por viatura:**
- ID, status atual (online/offline), última comunicação
- Temperatura CPU atual, LPR Health, buffer pendente
- Ações: pausar LPR, retomar LPR, reiniciar LPR, reiniciar ARGOS
- Ver detalhes (abre modal com histórico de 24h)

---

### 7. Gerenciamento da Hotlist (`/hotlist`)

Lista global de placas monitoradas no QG.

**Funcionalidades:**
- Adicionar placa (campo + botão)
- Remover placa
- Importar CSV (lista de placas)
- Exportar CSV
- Botão "Sincronizar com todas as viaturas" → faz `POST /api/hotlist` em cada viatura ativa
- Indicador: quais viaturas já têm a hotlist atualizada

---

### 8. Configuração Remota de Viatura (`/viaturas/<id>/config`)

Painel para ajustar parâmetros do Plate Recognizer de cada viatura.

**Campos editáveis** (via `POST /api/config` no equipamento):

| Campo | Descrição | Valor atual |
|---|---|---|
| `sample` | Frames processados (1=todos, 2=1 de cada 2) | — |
| `min_score` | Confiança mínima para reportar | — |
| `memory_decay` | Segundos antes de repetir mesma placa | — |
| `roi` | Região de interesse (null = desativado) | — |
| `trajectory` | Rastrear velocidade e direção | — |
| `report_static` | Reportar placas estáticas | — |
| `max_dwell_delay` | Delay máximo antes de reportar | — |

- Lê configuração atual via `GET /api/config`
- Salva via `POST /api/config` (reinicia container LPR automaticamente)

---

### 9. Login / Autenticação (`/login`)

- Tela de login simples (usuário + senha)
- Todos os endpoints protegidos (redireciona para login se não autenticado)
- Perfis: `admin` (acesso total) e `operador` (somente leitura + alertas)

**Usuários iniciais:**
- `admin` / `argos2026`
- `operador` / `operador2026`

---

## Banco de Dados — Tabelas

```sql
-- Viaturas registradas
viaturas (id, viatura_id, descricao, ativa, criado_em)

-- Todas as detecções recebidas
deteccoes (id, viatura_id, placa, score, dscore, marca, modelo, cor,
           tipo_veiculo, velocidade, direcao, regiao, alerta_tatico,
           latitude, longitude, altitude, gps_satellites, gps_status,
           camera_id, timestamp, recebido_em)

-- Heartbeats recebidos
heartbeats (id, viatura_id, latitude, longitude, altitude, speed,
            satellites, gps_status, lpr_health, lpr_fps, cpu_temp_c,
            buffer_pendente, timestamp, recebido_em)

-- Hotlist global do QG
hotlist (id, placa, descricao, ativa, criado_em)

-- Usuários do sistema
usuarios (id, username, password_hash, perfil, criado_em)
```

---

## Configuração (`.env`)

```ini
SECRET_KEY=argos-qg-secret-2026
QG_API_KEY=argos-secret-2026
DATABASE_URL=sqlite:///argos_qg.db
PORT=5000
```

---

## Estrutura de Arquivos

```
qg_webapp/
├── REQUIREMENTS.md          ← este arquivo
├── app.py                   ← ponto de entrada Flask
├── models.py                ← modelos SQLAlchemy
├── routes/
│   ├── telemetry.py         ← POST /api/argos/telemetry
│   ├── dashboard.py         ← telas web
│   ├── api_viaturas.py      ← endpoints para controlar viaturas
│   └── auth.py              ← login/logout
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── mapa.html
│   ├── alertas.html
│   ├── leituras.html
│   ├── viaturas.html
│   ├── hotlist.html
│   └── login.html
├── static/
│   ├── css/
│   └── js/
├── requirements.txt
└── .env.example
```

---

## Ordem de Implementação Sugerida

1. `app.py` + `models.py` + banco de dados
2. `POST /api/argos/telemetry` — endpoint que recebe dados do equipamento
3. Login / autenticação
4. Dashboard principal (sem mapa)
5. Log de leituras + alertas táticos
6. Mapa de frota
7. Gestão de viaturas + controle remoto
8. Gerenciamento de hotlist + sincronização
9. Configuração remota por viatura

---

## Integração com o Equipamento

As credenciais já estão configuradas no Pi:

```
QG_URL    = http://34.186.146.135/api/argos/telemetry
QG_API_KEY = argos-secret-2026
VIATURA_ID = VTR-TATICA-01
```

Quando o app estiver rodando localmente, para testar com o Pi real:
- Usar **ngrok** ou similar para expor `localhost:5000` para a internet
- Ou conectar Pi e PC na mesma rede e usar IP local

---

## Como Rodar Localmente

```bash
cd qg_webapp
pip install -r requirements.txt
python app.py
# Acesse http://localhost:5000
```
