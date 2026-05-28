# ==============================================================================
# offline_buffer.py — Store-and-Forward para falha de 4G
# ==============================================================================
# Quando o modem 4G cair, salva os eventos em disco (JSONL).
# Quando a conexão voltar, reenvia automaticamente em background.
# ==============================================================================

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime

import requests

from config.settings import (
    OFFLINE_BUFFER_FILE,
    OFFLINE_MAX_RECORDS,
    OFFLINE_RETRY_INTERVAL,
    QG_TELEMETRY_URL,
    QG_API_KEY,
    TELEMETRIA_TIMEOUT_S,
)

logger = logging.getLogger("argos.buffer")


class OfflineBuffer:
    """
    Fila persistente de eventos com retry automático.

    Fluxo:
    1. enqueue(evento) — sempre disponível, mesmo sem 4G
    2. Thread interna tenta enviar a fila ao QG periodicamente
    3. Eventos enviados com sucesso são removidos do disco
    4. Eventos falhos permanecem na fila para próxima tentativa
    """

    def __init__(self):
        self._queue: deque = deque()
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._conectado = False

        # Garante que o diretório do buffer existe
        # Protege contra o caso onde dirname retorna string vazia
        buffer_dir = os.path.dirname(OFFLINE_BUFFER_FILE)
        if buffer_dir:
            os.makedirs(buffer_dir, exist_ok=True)

        # Recarrega eventos pendentes do disco (crash recovery)
        self._load_from_disk()

    # ──────────────────────────────────────────────────────────────────────────
    # API Pública
    # ──────────────────────────────────────────────────────────────────────────

    def start(self):
        """Inicia thread de retry em background."""
        self._running = True
        self._thread = threading.Thread(
            target=self._retry_loop,
            name="offline-buffer",
            daemon=True
        )
        self._thread.start()
        logger.info(f"[BUFFER] Iniciado. {len(self._queue)} evento(s) pendente(s) no disco.")

    def stop(self):
        self._running = False

    def enqueue(self, evento: dict):
        """
        Adiciona um evento à fila. Thread-safe.
        O evento é imediatamente persistido em disco.
        """
        evento["_queued_at"] = datetime.utcnow().isoformat()

        with self._lock:
            if len(self._queue) >= OFFLINE_MAX_RECORDS:
                descartado = self._queue.popleft()
                logger.warning(f"[BUFFER] Fila cheia. Descartando evento mais antigo: {descartado.get('placa')}")

            self._queue.append(evento)
            self._persist_to_disk()

        logger.debug(f"[BUFFER] Evento enfileirado: {evento.get('placa')} | Fila: {len(self._queue)}")

    def is_online(self) -> bool:
        return self._conectado

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    # ──────────────────────────────────────────────────────────────────────────
    # Loop de Retry
    # ──────────────────────────────────────────────────────────────────────────

    def _retry_loop(self):
        """Tenta enviar eventos pendentes periodicamente."""
        while self._running:
            time.sleep(OFFLINE_RETRY_INTERVAL)

            with self._lock:
                if not self._queue:
                    continue
                pendentes = list(self._queue)

            enviados = 0
            try:
                for evento in pendentes:
                    resultado = self._enviar_evento(evento)
                    if resultado is True:
                        with self._lock:
                            try:
                                self._queue.remove(evento)
                                enviados += 1
                            except ValueError:
                                pass
                    elif resultado is None:
                        # 4xx — descartar sem bloquear a fila
                        with self._lock:
                            try:
                                self._queue.remove(evento)
                            except ValueError:
                                pass
                    else:
                        # False — falha de rede, parar e tentar no próximo ciclo
                        break
            except Exception as e:
                logger.error(f"[BUFFER] Erro inesperado no loop de retry: {e}")

            if enviados > 0:
                logger.info(f"[BUFFER] {enviados} evento(s) enviados ao QG.")
                with self._lock:
                    self._persist_to_disk()

    def _enviar_evento(self, evento: dict):
        """Tenta enviar um único evento ao QG.
        Retorna True (sucesso), False (falha de rede — retriable), None (erro 4xx — descartar).
        """
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": QG_API_KEY,
            "X-Viatura-ID": evento.get("viatura_id", ""),
        }
        try:
            resp = requests.post(
                QG_TELEMETRY_URL,
                json=evento,
                headers=headers,
                timeout=TELEMETRIA_TIMEOUT_S,
            )
            if resp.status_code in (200, 201, 202):
                self._conectado = True
                return True
            if 400 <= resp.status_code < 500:
                # Erro do cliente (payload inválido, API key errada, etc.) — não adianta retentar
                logger.warning(f"[BUFFER] HTTP {resp.status_code} — evento descartado (não-retriable).")
                self._conectado = True  # rede ok; só o payload é problemático
                return None
            # 5xx ou outros — falha do servidor, tentar de novo depois
            self._conectado = False
            logger.debug(f"[BUFFER] HTTP {resp.status_code} do QG — tentará novamente.")
            return False
        except requests.exceptions.RequestException as e:
            self._conectado = False
            logger.debug(f"[BUFFER] Falha de rede ({type(e).__name__}): {str(e)[:120]}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Persistência em Disco
    # ──────────────────────────────────────────────────────────────────────────

    def _persist_to_disk(self):
        """Salva a fila inteira no arquivo JSONL. Chamado com lock adquirido."""
        try:
            with open(OFFLINE_BUFFER_FILE, "w", encoding="utf-8") as f:
                for evento in self._queue:
                    # Não serializa imagens base64 no disco (economiza espaço no cartão SD)
                    # imagem_placa fica só em memória — se o Pi reiniciar offline, o evento
                    # é reenviado sem imagem (dados textuais e GPS são preservados)
                    evento_slim = {k: v for k, v in evento.items()
                                   if k not in ("imagem_veiculo", "imagem_placa")}
                    f.write(json.dumps(evento_slim, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error(f"[BUFFER] Erro ao salvar buffer em disco: {e}")

    def _load_from_disk(self):
        """Recarrega eventos pendentes do disco após reinício."""
        if not os.path.exists(OFFLINE_BUFFER_FILE):
            return
        try:
            with open(OFFLINE_BUFFER_FILE, "r", encoding="utf-8") as f:
                for linha in f:
                    linha = linha.strip()
                    if linha:
                        self._queue.append(json.loads(linha))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"[BUFFER] Erro ao carregar buffer do disco: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Instância global
# ──────────────────────────────────────────────────────────────────────────────
buffer = OfflineBuffer()
