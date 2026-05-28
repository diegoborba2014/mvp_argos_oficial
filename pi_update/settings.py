# ==============================================================================
# settings.py — Configurações Globais do ARGOS INTERCEPTOR V2.0
# ==============================================================================

import os
import platform as _platform

# ──────────────────────────────────────────────────────────────────────────────
# DETECÇÃO DE AMBIENTE (primeiro passo — usada para definir paths)
# ──────────────────────────────────────────────────────────────────────────────
_arm          = _platform.machine() in ("aarch64", "armv7l")
_colab        = os.path.exists("/content")
_env_override = os.getenv("ARGOS_ENV", "").lower() == "development"
IS_PRODUCTION = _arm and not _colab and not _env_override

# Diretório de dados: /opt/argos em produção, ./data em desenvolvimento
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = "/opt/argos" if IS_PRODUCTION else os.path.join(_BASE_DIR, "data")

# ──────────────────────────────────────────────────────────────────────────────
# IDENTIFICAÇÃO DA VIATURA
# ──────────────────────────────────────────────────────────────────────────────
VIATURA_ID = os.getenv("VIATURA_ID", "VTR-TATICA-01")

# ──────────────────────────────────────────────────────────────────────────────
# SERVIDOR FLASK
# ──────────────────────────────────────────────────────────────────────────────
FLASK_HOST  = "0.0.0.0"
FLASK_PORT  = 9093
FLASK_DEBUG = False

# ──────────────────────────────────────────────────────────────────────────────
# GPS — NEO-M8N via UART
# ──────────────────────────────────────────────────────────────────────────────
# Porta correta para Raspberry Pi 5: /dev/ttyAMA0
# Raspberry Pi 4 e anteriores: /dev/ttyS0
GPS_PORT            = "/dev/ttyAMA0"
GPS_BAUDRATE        = 9600
GPS_TIMEOUT_S       = 2
GPS_READ_INTERVAL_S = 1

# Coordenadas simuladas usadas no modo desenvolvimento (PC)
# Ajuste para a cidade de operação real da viatura
GPS_SIM_LAT = -27.5954   # Florianópolis, SC
GPS_SIM_LON = -48.5480

# ──────────────────────────────────────────────────────────────────────────────
# HOTLIST
# ──────────────────────────────────────────────────────────────────────────────
HOTLIST_DEFAULT = [
    "ARG0S26",
    "ROUBAD4",
    "PMSC190",
]
HOTLIST_FILE = os.path.join(_DATA_DIR, "hotlist.json")
HOTLIST_SYNC_INTERVAL_S = 30  # Pi consulta QG a cada 30s

# ──────────────────────────────────────────────────────────────────────────────
# TRAVA TÁTICA
# ──────────────────────────────────────────────────────────────────────────────
TEMPO_TRAVA_ALERTA_S = 15

# ──────────────────────────────────────────────────────────────────────────────
# TELEMETRIA (QG via 4G)
# ──────────────────────────────────────────────────────────────────────────────
QG_TELEMETRY_URL      = os.getenv("QG_URL", "https://qg.argos.internal/telemetry")
QG_API_KEY            = os.getenv("QG_API_KEY", "")
TELEMETRIA_INTERVAL_S = 60
TELEMETRIA_TIMEOUT_S  = 25

# ──────────────────────────────────────────────────────────────────────────────
# BUFFER OFFLINE (Store-and-Forward)
# ──────────────────────────────────────────────────────────────────────────────
OFFLINE_BUFFER_FILE    = os.path.join(_DATA_DIR, "offline_buffer.jsonl")
OFFLINE_MAX_RECORDS    = 5000
OFFLINE_RETRY_INTERVAL = 30

# ──────────────────────────────────────────────────────────────────────────────
# SPLASH SCREEN
# ──────────────────────────────────────────────────────────────────────────────
SPLASH_SERVICE_NAME     = "argos-splash.service"
SPLASH_HANDOVER_DELAY_S = 5
