# ==============================================================================
# config_polling.py — Sincronização de configuração LPR com o QG via polling
#
# Fluxo:
#   1. A cada CONFIG_POLL_INTERVAL_S, consulta GET /api/viaturas/<id>/config/pending
#   2. Se QG responder {"pendente": true}: compara hash com última config aplicada
#   3. Se hash diferente: aplica no config.ini e reinicia container LPR
#   4. Se hash igual: config já estava aplicada — pula restart (evita loop de reinicializações)
#   5. Confirma ao QG via POST /api/viaturas/<id>/config/ack (3 tentativas)
# ==============================================================================

import hashlib
import logging
import os
import subprocess
import threading
import time

import requests

from config.settings import QG_API_KEY, QG_TELEMETRY_URL, VIATURA_ID
from src.remote_api import _CAMPOS, _escrever_config_ini

logger = logging.getLogger("argos.config_polling")

CONFIG_POLL_INTERVAL_S = 60
_LAST_HASH_FILE = "/opt/argos/last_config_hash"


def _qg_base() -> str:
    if "/api/argos/telemetry" in QG_TELEMETRY_URL:
        return QG_TELEMETRY_URL.replace("/api/argos/telemetry", "")
    return QG_TELEMETRY_URL.rstrip("/")


def _config_hash(campos: dict) -> str:
    s = ",".join(f"{k}={v}" for k, v in sorted(campos.items()))
    return hashlib.md5(s.encode()).hexdigest()


def _load_last_hash() -> str:
    try:
        with open(_LAST_HASH_FILE, "r") as f:
            return f.read().strip()
    except OSError:
        return ""


def _save_last_hash(h: str):
    try:
        with open(_LAST_HASH_FILE, "w") as f:
            f.write(h)
    except OSError as e:
        logger.warning(f"[CONFIG POLLING] Falha ao salvar hash local: {e}")


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
            novo_hash = _config_hash(campos_validos)
            ultimo_hash = _load_last_hash()

            if novo_hash == ultimo_hash:
                # Config já foi aplicada — só reenvia ack sem reiniciar o LPR
                logger.info("[CONFIG POLLING] Config já aplicada (hash idêntico) — enviando ack sem reiniciar.")
            else:
                ok, motivo = _escrever_config_ini(campos_validos)
                if not ok:
                    logger.error(f"[CONFIG POLLING] Falha ao escrever config.ini: {motivo}")
                    return
                _save_last_hash(novo_hash)
                logger.info(f"[CONFIG POLLING] Config aplicada: {campos_validos}")
                subprocess.Popen(["docker", "restart", "stream"])
        else:
            logger.warning("[CONFIG POLLING] Pendente mas sem campos válidos — enviando ack sem aplicar.")

        # Ack com 3 tentativas para garantir que o QG limpe o flag
        for tentativa in range(3):
            try:
                resp = requests.post(
                    f"{base}/api/viaturas/{VIATURA_ID}/config/ack",
                    headers=headers,
                    timeout=10,
                )
                if resp.ok:
                    logger.info("[CONFIG POLLING] Ack enviado ao QG.")
                    return
            except Exception as exc:
                logger.warning(f"[CONFIG POLLING] Tentativa {tentativa+1}/3 falhou: {exc}")
                if tentativa < 2:
                    time.sleep(5)

        logger.error("[CONFIG POLLING] Ack falhou em 3 tentativas — QG reenviará na próxima sync.")


config_polling_service = ConfigPollingService()
