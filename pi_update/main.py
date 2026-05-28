# ==============================================================================
# main.py — ARGOS INTERCEPTOR V2.0 — Ponto de Entrada Principal
# ==============================================================================
import logging
import os
import signal
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, render_template_string, Response

# Adiciona o diretório raiz ao path para imports relativos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    FLASK_HOST,
    FLASK_PORT,
    IS_PRODUCTION,
    SPLASH_HANDOVER_DELAY_S,
    SPLASH_SERVICE_NAME,
    TEMPO_TRAVA_ALERTA_S,
    VIATURA_ID,
)

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("argos.main")

# ──────────────────────────────────────────────────────────────────────────────
# Imports dos módulos ARGOS Refatorados
# ──────────────────────────────────────────────────────────────────────────────
from src.gps_reader import gps
from src.offline_buffer import buffer
from src.ui_template import HTML_TEMPLATE

# Estado global e Hotlist
from src.state import lock_estado, ultima_leitura
from src.hotlist_manager import hotlist_manager
from src.hotlist_sync import hotlist_sync_service
from src.config_polling import config_polling_service
from src.telemetry import telemetry_service
from src.webhook_handler import webhook_bp, gpio
from src.remote_api import remote_bp

# ──────────────────────────────────────────────────────────────────────────────
# Flask App
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.register_blueprint(webhook_bp)
app.register_blueprint(remote_bp)

# ──────────────────────────────────────────────────────────────────────────────
# Rotas Auxiliares (UI e APIs locais)
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/latest")
def get_latest():
    with lock_estado:
        return jsonify(ultima_leitura)

@app.route("/api/hotlist")
def get_hotlist():
    return jsonify({"hotlist": hotlist_manager.get_all(), "total": hotlist_manager.size()})

@app.route("/api/preview")
def get_preview():
    preview_path = "/tmp/argos_preview.jpg"
    try:
        with open(preview_path, "rb") as f:
            data = f.read()
        return Response(data, mimetype="image/jpeg",
                        headers={"Cache-Control": "no-store"})
    except (FileNotFoundError, OSError):
        return Response(status=204)

def _ler_temperatura() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000, 1)
    except OSError:
        return None


@app.route("/api/status")
def get_status():
    """Endpoint de health check para monitoramento externo."""
    pos = gps.get_position()
    return jsonify({
        "viatura_id": VIATURA_ID,
        "uptime": time.time(),
        "gps": pos,
        "buffer_pendente": buffer.pending_count(),
        "online": buffer.is_online(),
        "hotlist_size": hotlist_manager.size(),
        "circuit_breaker": telemetry_service.circuit_breaker.state,
        "cpu_temp_c": _ler_temperatura(),
    })

# ──────────────────────────────────────────────────────────────────────────────
# Serviços em Background
# ──────────────────────────────────────────────────────────────────────────────
def _splash_handover():
    """Mata o serviço mpv quando Flask estiver pronto."""
    if not IS_PRODUCTION:
        return
    logger.info("[SPLASH] Aguardando handover para Flask...")
    time.sleep(SPLASH_HANDOVER_DELAY_S)
    try:
        subprocess.run(
            ["sudo", "systemctl", "stop", SPLASH_SERVICE_NAME],
            timeout=10, check=False
        )
        logger.info("[SPLASH] Vídeo de abertura encerrado. Painel assumiu.")
    except Exception as e:
        logger.warning(f"[SPLASH] {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Inicialização
# ──────────────────────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("🚀  ARGOS INTERCEPTOR V2.0 — INICIANDO")
    logger.info("=" * 60)
    logger.info(f"Viatura ID   : {VIATURA_ID}")
    logger.info(f"Hotlist      : {hotlist_manager.size()} placas carregadas")
    logger.info(f"Trava tática : {TEMPO_TRAVA_ALERTA_S}s")
    logger.info(f"Ambiente     : {'PRODUÇÃO (Raspberry Pi)' if IS_PRODUCTION else 'DESENVOLVIMENTO'}")

    # [HAT] Inicializar hardware HAT Gusbach
    hat_ok = gpio.inicializar()
    logger.info(f"[HAT] Gusbach HAT: {'ATIVO' if hat_ok else 'MODO SIMULADO (sem hardware)'}")

    # Thread 1 — Splash Handover
    threading.Thread(target=_splash_handover, name="splash-handover", daemon=True).start()

    # Thread 2 — GPS Reader
    gps.start()
    logger.info(f"[GPS] Leitura iniciada em /dev/ttyAMA0")

    # Thread 3 — Offline Buffer
    buffer.start()
    logger.info(f"[BUFFER] {buffer.pending_count()} evento(s) pendente(s) no disco.")

    # Thread 4 — Telemetria (com Circuit Breaker)
    telemetry_service.start()
    logger.info(f"[TELEMETRIA] Serviço iniciado. Estado: {telemetry_service.circuit_breaker.state}")

    # Thread 5 — Hotlist Sync (polling QG a cada 30s)
    hotlist_sync_service.start()
    logger.info(f"[HOTLIST-SYNC] Polling QG ativo.")

    # Thread 6 — Config Polling (sinc config LPR a cada 60s)
    config_polling_service.start()
    logger.info(f"[CONFIG-POLLING] Polling QG ativo.")

    # Thread 7 — Flask Server
    flask_thread = threading.Thread(
        target=app.run,
        kwargs={
            "port": FLASK_PORT,
            "host": FLASK_HOST,
            "debug": False,
            "use_reloader": False,
        },
        name="flask-server",
        daemon=True,
    )
    flask_thread.start()

    logger.info(f"🔗  Painel tático: http://localhost:{FLASK_PORT}")
    logger.info(f"🔗  Webhook:       http://localhost:{FLASK_PORT}/alpr-webhook")
    logger.info(f"🔗  API Status:    http://localhost:{FLASK_PORT}/api/status")
    logger.info("=" * 60)

    # Bloqueio da Main Thread
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n[ARGOS] Sinal de encerramento recebido.")
        gps.stop()
        buffer.stop()
        telemetry_service.stop()
        hotlist_sync_service.stop()
        gpio.encerrar()
        logger.info("[ARGOS] Sistema encerrado com segurança.")
        sys.exit(0)

if __name__ == "__main__":
    main()
