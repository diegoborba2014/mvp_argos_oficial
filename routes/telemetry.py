import base64
import json
import queue
import threading
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify, Response, current_app

from models import db, Viatura, Deteccao, Heartbeat, Hotlist, EventoSistema

# Eventos gerados há mais de 2 horas são aceitos (200 OK, Pi remove do buffer)
# mas descartados silenciosamente — não salvos no banco.
BUFFER_MAX_AGE_HORAS = 2

telemetry_bp = Blueprint("telemetry", __name__)

# Fila global para SSE — broadcast para todos os clientes conectados
_sse_listeners: list[queue.Queue] = []
_sse_lock = threading.Lock()


def _broadcast(event: str, data: dict):
    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_listeners:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_listeners.remove(q)


def _garantir_viatura(viatura_id: str) -> Viatura:
    v = Viatura.query.filter_by(viatura_id=viatura_id).first()
    if not v:
        v = Viatura(viatura_id=viatura_id)
        db.session.add(v)
        db.session.flush()
    return v


def _evento_antigo(payload: dict) -> bool:
    """
    Retorna True se o evento foi gerado há mais de BUFFER_MAX_AGE_HORAS.
    Usa _queued_at (timestamp de enfileiramento no Pi) como referência.
    Se o campo não existir, usa o timestamp da detecção.
    """
    agora = datetime.now(timezone.utc)
    corte = agora - timedelta(hours=BUFFER_MAX_AGE_HORAS)

    # Tenta _queued_at primeiro (campo adicionado pelo OfflineBuffer do Pi)
    queued_at = payload.get("_queued_at")
    if queued_at:
        try:
            dt = datetime.fromisoformat(queued_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt < corte
        except (ValueError, AttributeError):
            pass

    # Fallback: usa timestamp da detecção
    ts = payload.get("timestamp")
    if ts:
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            return dt < corte
        except (ValueError, OSError):
            pass

    return False  # Se não conseguir determinar a idade, aceita o evento


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/argos/telemetry — recebe eventos do equipamento ARGOS
# ──────────────────────────────────────────────────────────────────────────────

@telemetry_bp.route("/api/argos/telemetry", methods=["POST"])
def receber_telemetria():
    api_key = current_app.config.get("QG_API_KEY")
    if request.headers.get("X-API-Key", "") != api_key:
        return jsonify({"erro": "nao autorizado"}), 401

    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"erro": "body JSON invalido"}), 400

    viatura_id = payload.get("viatura_id", "desconhecido")
    tipo = payload.get("tipo", "deteccao")

    if _evento_antigo(payload):
        current_app.logger.debug(
            f"[BUFFER] Evento antigo descartado — {viatura_id} | "
            f"queued_at: {payload.get('_queued_at', '?')}"
        )
        return jsonify({"status": "ok", "descartado": True}), 200

    # Deduplicação: ignora detecções com mesmo viatura_id+timestamp já salvas
    if tipo != "heartbeat":
        ts = payload.get("timestamp")
        if ts is not None:
            try:
                ts_float = float(ts)
                if Deteccao.query.filter_by(viatura_id=viatura_id, timestamp=ts_float).first():
                    return jsonify({"status": "ok", "duplicado": True}), 200
            except (ValueError, TypeError):
                pass

    viatura = _garantir_viatura(viatura_id)

    if tipo == "heartbeat":
        _salvar_heartbeat(viatura_id, payload)
        db.session.commit()
    else:
        deteccao = _salvar_deteccao(viatura_id, payload, viatura)
        db.session.commit()  # commit antes do broadcast — garante que imagem já está no banco
        _broadcast("new_detection", deteccao.to_dict())

    return jsonify({"status": "ok"}), 200


def _salvar_deteccao(viatura_id: str, p: dict, viatura: Viatura) -> Deteccao:
    placa = (p.get("placa") or "").upper().strip()
    pi_alerta = bool(p.get("alerta_tatico", False))

    # Hotlist match: verifica no QG quando modo é híbrido ou nuvem
    alerta = pi_alerta
    if viatura.hotlist_mode in ("hibrido", "nuvem"):
        hotlist_placas = {h.placa for h in Hotlist.query.filter_by(ativa=True).all()}
        alerta = pi_alerta or (placa in hotlist_placas)

    # Decode imagem_placa (base64 → bytes) — presente apenas em alertas táticos
    imagem_placa_bytes = None
    imagem_b64 = p.get("imagem_placa")
    if imagem_b64:
        try:
            imagem_placa_bytes = base64.b64decode(imagem_b64)
        except Exception:
            pass

    d = Deteccao(
        viatura_id=viatura_id,
        placa=placa,
        score=p.get("score") or 0.0,
        dscore=p.get("dscore") or 0.0,
        marca=p.get("marca") or "",
        modelo=p.get("modelo") or "",
        cor=p.get("cor") or "",
        tipo_veiculo=p.get("tipo_veiculo") or "",
        velocidade=p.get("velocidade") or 0.0,
        direcao=p.get("direcao") or 0.0,
        regiao=p.get("regiao") or "",
        alerta_tatico=alerta,
        camera_id=p.get("camera_id") or "",
        imagem_placa=imagem_placa_bytes,
        latitude=p.get("latitude"),
        longitude=p.get("longitude"),
        altitude=p.get("altitude"),
        gps_satellites=p.get("gps_satellites"),
        gps_status=p.get("gps_status") or "",
        timestamp=float(p["timestamp"]) if p.get("timestamp") else None,
    )
    db.session.add(d)
    return d


def _resolver_evento(viatura_id: str, tipo: str):
    """Marca como resolvido o evento aberto (se existir) daquele tipo/viatura."""
    ev = EventoSistema.query.filter_by(viatura_id=viatura_id, tipo=tipo, resolvido=False).first()
    if ev:
        ev.resolvido = True
        ev.resolvido_em = datetime.now(timezone.utc).replace(tzinfo=None)


def _verificar_eventos(viatura_id: str, hb: Heartbeat):
    """Gera e resolve EventoSistema automaticamente a cada heartbeat recebido."""

    def _abrir(tipo, severidade, detalhe):
        if not EventoSistema.query.filter_by(viatura_id=viatura_id, tipo=tipo, resolvido=False).first():
            db.session.add(EventoSistema(
                viatura_id=viatura_id, tipo=tipo,
                severidade=severidade, detalhe=detalhe,
            ))
            _broadcast("system_event", {
                "viatura_id": viatura_id, "tipo": tipo,
                "severidade": severidade, "detalhe": detalhe,
            })

    # Pi reconectado: se havia evento pi_offline aberto, resolve-o
    _resolver_evento(viatura_id, "pi_offline")

    # ── LPR ──────────────────────────────────────────────────────────────────
    if hb.lpr_health is not None:
        if hb.lpr_health == 0.0:
            _abrir("lpr_offline", "critico", "LPR Health = 0% — câmera pode estar travada")
            _resolver_evento(viatura_id, "lpr_degradado")
        elif hb.lpr_health < 0.70:
            _resolver_evento(viatura_id, "lpr_offline")
            _abrir("lpr_degradado", "aviso", f"LPR Health = {hb.lpr_health * 100:.0f}%")
        else:
            _resolver_evento(viatura_id, "lpr_offline")
            _resolver_evento(viatura_id, "lpr_degradado")

    # ── GPS ───────────────────────────────────────────────────────────────────
    if hb.satellites is not None:
        if hb.satellites < 4:
            _abrir("gps_sem_sinal", "aviso", f"Apenas {hb.satellites} satélite(s) visível(is)")
        else:
            _resolver_evento(viatura_id, "gps_sem_sinal")

    # ── Buffer crescendo ──────────────────────────────────────────────────────
    if hb.buffer_pendente is not None:
        if hb.buffer_pendente > 50:
            _abrir("buffer_crescendo", "aviso", f"{hb.buffer_pendente} eventos aguardando envio")
        else:
            _resolver_evento(viatura_id, "buffer_crescendo")

    # ── CPU quente ────────────────────────────────────────────────────────────
    if hb.cpu_temp_c is not None:
        if hb.cpu_temp_c > 80:
            _abrir("cpu_quente", "aviso", f"Temperatura CPU: {hb.cpu_temp_c:.1f}°C")
        else:
            _resolver_evento(viatura_id, "cpu_quente")


def _salvar_heartbeat(viatura_id: str, p: dict):
    gps = p.get("gps", {})
    hb = Heartbeat(
        viatura_id=viatura_id,
        latitude=gps.get("latitude"),
        longitude=gps.get("longitude"),
        altitude=gps.get("altitude"),
        speed=gps.get("speed"),
        satellites=gps.get("satellites"),
        gps_status=gps.get("status", ""),
        lpr_health=p.get("lpr_health"),
        lpr_fps=p.get("lpr_fps"),
        cpu_temp_c=p.get("cpu_temp_c"),
        buffer_pendente=p.get("buffer_pendente", 0),
        timestamp=float(p["timestamp"]) if p.get("timestamp") else None,
    )
    db.session.add(hb)

    _broadcast("heartbeat", {
        "viatura_id": viatura_id,
        "latitude": gps.get("latitude"),
        "longitude": gps.get("longitude"),
        "lpr_health": p.get("lpr_health"),
        "cpu_temp_c": p.get("cpu_temp_c"),
        "buffer_pendente": p.get("buffer_pendente", 0),
    })

    # Verifica eventos operacionais com base nos dados do heartbeat
    _verificar_eventos(viatura_id, hb)


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/stream — SSE (Server-Sent Events)
# ──────────────────────────────────────────────────────────────────────────────

@telemetry_bp.route("/api/stream")
def sse_stream():
    def event_stream(q: queue.Queue):
        yield "data: {\"status\": \"connected\"}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            # Remove a fila ao desconectar — evita vazamento de memória
            with _sse_lock:
                try:
                    _sse_listeners.remove(q)
                except ValueError:
                    pass

    q: queue.Queue = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_listeners.append(q)

    return Response(
        event_stream(q),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/argos/status — health check
# ──────────────────────────────────────────────────────────────────────────────

@telemetry_bp.route("/api/argos/status")
def status_qg():
    return jsonify({"status": "online", "servico": "ARGOS QG"}), 200
