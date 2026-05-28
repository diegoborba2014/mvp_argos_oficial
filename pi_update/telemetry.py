# ==============================================================================
# telemetry.py — Telemetria de background e Circuit Breaker
# ==============================================================================
import time
import logging
import threading
import requests as req

from config.settings import (
    QG_TELEMETRY_URL,
    QG_API_KEY,
    TELEMETRIA_TIMEOUT_S,
    TELEMETRIA_INTERVAL_S,
    VIATURA_ID
)
from src.gps_reader import gps
from src.offline_buffer import buffer

logger = logging.getLogger("argos.telemetry")


def _ler_temperatura() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000, 1)
    except OSError:
        return None

class CircuitBreaker:
    """Implementa o padrão de Circuit Breaker para evitar sobrecarga em falhas."""
    def __init__(self, failure_threshold=3, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED (Online), OPEN (Bloqueado), HALF_OPEN (Testando)

    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        return True  # HALF_OPEN

    def record_success(self):
        self.failures = 0
        if self.state != "CLOSED":
            logger.info("[CIRCUIT BREAKER] Conexão reestabelecida. Circuito CLOSED.")
        self.state = "CLOSED"

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.state == "HALF_OPEN" or self.failures >= self.failure_threshold:
            if self.state != "OPEN":
                logger.warning(f"[CIRCUIT BREAKER] Limite de falhas atingido ({self.failures}). Circuito OPEN.")
            self.state = "OPEN"

class TelemetryService:
    def __init__(self):
        self._running = False
        self._thread = None
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="telemetria", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            if self.circuit_breaker.can_execute():
                self._enviar_heartbeat()
            else:
                logger.debug("[TELEMETRIA] Circuito OPEN: Heartbeat pulado para evitar timeout excessivo.")
            
            time.sleep(TELEMETRIA_INTERVAL_S)

    def _enviar_heartbeat(self):
        try:
            pos = gps.get_position()
            
            # Consulta saúde do Plate Recognizer Stream via Heartbeat API (porta 8001)
            lpr_health = -1
            lpr_fps = -1.0
            try:
                r = req.get("http://localhost:8001/status/", timeout=2)
                if r.status_code in (200, 500):
                    data = r.json()
                    cam_data = next(iter(data.get("cameras", {}).values()), {})
                    lpr_health = cam_data.get("health", -1)
                    lpr_fps = cam_data.get("received_fps", -1.0)
            except Exception:
                pass

            payload = {
                "viatura_id": VIATURA_ID,
                "timestamp": time.time(),
                "gps": pos,
                "buffer_pendente": buffer.pending_count(),
                "tipo": "heartbeat",
                "lpr_health": lpr_health,
                "lpr_fps": lpr_fps,
                "cpu_temp_c": _ler_temperatura(),
            }
            
            resp = req.post(
                QG_TELEMETRY_URL,
                json=payload,
                headers={"X-API-Key": QG_API_KEY},
                timeout=TELEMETRIA_TIMEOUT_S,
            )
            
            # Se não falhou por rede, conta como sucesso pro Circuit Breaker
            if resp.status_code < 500:
                self.circuit_breaker.record_success()
                logger.debug(f"[TELEMETRIA] Heartbeat enviado. HTTP {resp.status_code}")
            else:
                # Erros de servidor contam como falha
                self.circuit_breaker.record_failure()
                logger.warning(f"[TELEMETRIA] Falha no servidor QG: HTTP {resp.status_code}")

        except req.exceptions.RequestException as e:
            self.circuit_breaker.record_failure()
            logger.debug(f"[TELEMETRIA] Erro de rede no heartbeat: {e}")
        except Exception as e:
            logger.error(f"[TELEMETRIA] Erro interno: {e}")

telemetry_service = TelemetryService()
