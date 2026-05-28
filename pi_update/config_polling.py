# ==============================================================================
# config_polling.py — Sincronização de configuração LPR com o QG via polling
#
# Fluxo:
#   1. A cada CONFIG_POLL_INTERVAL_S, consulta GET /api/viaturas/<id>/config/pending
#   2. Se QG responder {"pendente": true}: baixa a config do campo "config"
#   3. Aplica escrevendo no /opt/stream/config.ini (mesma lógica do remote_api.py)
#   4. Reinicia container Docker LPR para aplicar as mudanças
#   5. Confirma ao QG via POST /api/viaturas/<id>/config/ack
# ==============================================================================

import logging
import subprocess
import threading
import time

import requests

from config.settings import QG_API_KEY, QG_TELEMETRY_URL, VIATURA_ID
from src.remote_api import _CAMPOS, _escrever_config_ini

logger = logging.getLogger("argos.config_polling")

CONFIG_POLL_INTERVAL_S = 60


def _qg_base() -> str:
    if "/api/argos/telemetry" in QG_TELEMETRY_URL:
        return QG_TELEMETRY_URL.replace("/api/argos/telemetry", "")
    return QG_TELEMETRY_URL.rstrip("/")


class ConfigPollingService:
    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="config_polling", daemon=True)
        self._thread.start()
        logger.info("[CONFIG POLLING] Serviço iniciado.")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._verificar()
            except Exception as exc:
                logger.error(f"[CONFIG POLLING] Erro no loop: {exc}")
            time.sleep(CONFIG_POLL_INTERVAL_S)

    def _verificar(self):
        base = _qg_base()
        headers = {"X-API-Key": QG_API_KEY}
        try:
            resp = requests.get(
                f"{base}/api/viaturas/{VIATURA_ID}/config/pending",
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return
            data = resp.json()
        except Exception as exc:
            logger.debug(f"[CONFIG POLLING] Falha ao consultar QG: {exc}")
            return

        if not data.get("pendente"):
            return

        config = data.get("config", {})
        campos_validos = {k: v for k, v in config.items() if k in _CAMPOS and v is not None}

        if campos_validos:
            ok, motivo = _escrever_config_ini(campos_validos)
            if not ok:
                logger.error(f"[CONFIG POLLING] Falha ao escrever config.ini: {motivo}")
                return
            logger.info(f"[CONFIG POLLING] Config aplicada: {campos_validos}")
            subprocess.Popen(["docker", "restart", "stream"])
        else:
            logger.warning("[CONFIG POLLING] Pendente mas sem campos válidos — enviando ack sem aplicar.")

        try:
            requests.post(
                f"{base}/api/viaturas/{VIATURA_ID}/config/ack",
                headers=headers,
                timeout=10,
            )
            logger.info("[CONFIG POLLING] Ack enviado ao QG.")
        except Exception as exc:
            logger.warning(f"[CONFIG POLLING] Falha ao enviar ack: {exc}")


config_polling_service = ConfigPollingService()
