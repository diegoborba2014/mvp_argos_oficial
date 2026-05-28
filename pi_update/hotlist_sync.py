# ==============================================================================
# hotlist_sync.py — Sincronização automática da Hotlist com o QG
#
# Fluxo:
#   1. A cada HOTLIST_SYNC_INTERVAL_S, consulta GET /api/viaturas/<id>/hotlist/pending
#   2. Se QG responder {"pendente": true}: baixa lista via GET /api/viaturas/<id>/hotlist_sync
#   3. Aplica no HotlistManager (persiste em disco automaticamente)
#   4. Confirma ao QG via POST /api/viaturas/<id>/hotlist/ack
# ==============================================================================

import logging
import threading

import requests

from config.settings import (
    HOTLIST_SYNC_INTERVAL_S,
    QG_API_KEY,
    QG_TELEMETRY_URL,
    VIATURA_ID,
)
from src.hotlist_manager import hotlist_manager

logger = logging.getLogger("argos.hotlist_sync")


def _qg_base() -> str:
    """Deriva a URL base do QG a partir da URL de telemetria."""
    if "/api/argos/telemetry" in QG_TELEMETRY_URL:
        return QG_TELEMETRY_URL.replace("/api/argos/telemetry", "")
    return QG_TELEMETRY_URL.rsplit("/", 1)[0]


class HotlistSyncService:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="hotlist-sync", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _headers(self):
        return {"X-API-Key": QG_API_KEY}

    def _loop(self):
        logger.info(f"[HOTLIST-SYNC] Iniciado. Polling a cada {HOTLIST_SYNC_INTERVAL_S}s.")
        while not self._stop.is_set():
            try:
                self._verificar_e_sincronizar()
            except Exception as e:
                logger.warning(f"[HOTLIST-SYNC] Erro: {e}")
            self._stop.wait(HOTLIST_SYNC_INTERVAL_S)

    def _verificar_e_sincronizar(self):
        base = _qg_base()

        resp = requests.get(
            f"{base}/api/viaturas/{VIATURA_ID}/hotlist/pending",
            headers=self._headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            logger.debug(f"[HOTLIST-SYNC] /pending retornou {resp.status_code}")
            return

        data = resp.json()
        if not data.get("pendente"):
            return

        logger.info(f"[HOTLIST-SYNC] Atualização detectada ({data.get('total', '?')} placas). Baixando...")

        resp2 = requests.get(
            f"{base}/api/viaturas/{VIATURA_ID}/hotlist_sync",
            headers=self._headers(),
            timeout=15,
        )
        if not resp2.ok:
            logger.warning(f"[HOTLIST-SYNC] Falha ao baixar hotlist: {resp2.status_code}")
            return

        dados = resp2.json()
        placas = dados.get("placas", [])
        hash_qg = dados.get("hash", "")

        hotlist_manager.update(placas)
        logger.info(f"[HOTLIST-SYNC] Hotlist aplicada: {len(placas)} placa(s).")

        requests.post(
            f"{base}/api/viaturas/{VIATURA_ID}/hotlist/ack",
            json={"hash": hash_qg},
            headers=self._headers(),
            timeout=10,
        )
        logger.info("[HOTLIST-SYNC] ACK enviado ao QG.")


hotlist_sync_service = HotlistSyncService()
