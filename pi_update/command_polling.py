# ==============================================================================
# command_polling.py — Execução de comandos remotos do QG via polling
#
# Fluxo:
#   1. A cada COMMAND_POLL_INTERVAL_S, consulta GET /api/viaturas/<id>/comando/pending
#   2. Se QG responder {"pendente": true, "comando": "restart_lpr"}: executa o comando
#   3. Confirma ao QG via POST /api/viaturas/<id>/comando/ack
#
# Nota sobre restart_argos: envia ack ANTES de executar — o restart mata este processo.
# ==============================================================================

import logging
import subprocess
import threading
import time

import requests

from config.settings import QG_API_KEY, QG_TELEMETRY_URL, VIATURA_ID

logger = logging.getLogger("argos.command_polling")

COMMAND_POLL_INTERVAL_S = 30

_ACOES = {
    "pause_lpr":     ["docker", "stop",      "stream"],
    "resume_lpr":    ["docker", "start",     "stream"],
    "restart_lpr":   ["docker", "restart",   "stream"],
    "restart_argos": ["sudo",   "systemctl", "restart", "argos"],
}


def _qg_base() -> str:
    if "/api/argos/telemetry" in QG_TELEMETRY_URL:
        return QG_TELEMETRY_URL.replace("/api/argos/telemetry", "")
    return QG_TELEMETRY_URL.rstrip("/")


class CommandPollingService:
    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="command_polling", daemon=True)
        self._thread.start()
        logger.info("[COMMAND POLLING] Serviço iniciado.")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._verificar()
            except Exception as exc:
                logger.error(f"[COMMAND POLLING] Erro no loop: {exc}")
            time.sleep(COMMAND_POLL_INTERVAL_S)

    def _verificar(self):
        base = _qg_base()
        headers = {"X-API-Key": QG_API_KEY}

        try:
            resp = requests.get(
                f"{base}/api/viaturas/{VIATURA_ID}/comando/pending",
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return
            data = resp.json()
        except Exception as exc:
            logger.debug(f"[COMMAND POLLING] Falha ao consultar QG: {exc}")
            return

        if not data.get("pendente"):
            return

        comando = data.get("comando", "")
        if comando not in _ACOES:
            logger.warning(f"[COMMAND POLLING] Comando desconhecido: '{comando}' — descartando")
            self._enviar_ack(base, headers)
            return

        logger.info(f"[COMMAND POLLING] Executando: '{comando}'")

        if comando == "restart_argos":
            # Envia ack ANTES de reiniciar — o restart mata este processo
            self._enviar_ack(base, headers)
            time.sleep(0.3)
            subprocess.Popen(_ACOES[comando])
            return

        try:
            subprocess.run(_ACOES[comando], timeout=30, check=False)
            logger.info(f"[COMMAND POLLING] '{comando}' concluído.")
        except Exception as exc:
            logger.error(f"[COMMAND POLLING] Falha ao executar '{comando}': {exc}")

        self._enviar_ack(base, headers)

    def _enviar_ack(self, base: str, headers: dict):
        try:
            requests.post(
                f"{base}/api/viaturas/{VIATURA_ID}/comando/ack",
                headers=headers,
                timeout=10,
            )
            logger.info("[COMMAND POLLING] Ack enviado ao QG.")
        except Exception as exc:
            logger.warning(f"[COMMAND POLLING] Falha ao enviar ack: {exc}")


command_polling_service = CommandPollingService()
