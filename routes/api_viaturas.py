import hashlib
import os
import requests

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user

from models import db, Viatura
from extensions import csrf

api_viaturas_bp = Blueprint("api_viaturas", __name__)

COMANDOS_VALIDOS = {"pause_lpr", "resume_lpr", "restart_lpr", "restart_argos"}


def _headers_pi():
    return {"X-API-Key": current_app.config.get("QG_API_KEY")}


def _admin_required_json():
    if not current_user.is_admin():
        return jsonify({"erro": "acesso negado"}), 403
    return None


def _api_key_required():
    api_key = current_app.config.get("QG_API_KEY")
    if request.headers.get("X-API-Key", "") != api_key:
        return jsonify({"erro": "nao autorizado"}), 401
    return None


def _hotlist_hash(placas: list) -> str:
    return hashlib.md5(",".join(sorted(placas)).encode()).hexdigest()


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/comando", methods=["POST"])
@login_required
def enviar_comando(viatura_id):
    err = _admin_required_json()
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    comando = data.get("comando", "")

    if comando not in COMANDOS_VALIDOS:
        return jsonify({"erro": f"comando inválido: {comando}"}), 400

    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first()
    if not viatura:
        return jsonify({"erro": "viatura não encontrada"}), 404

    if not viatura.online():
        return jsonify({"erro": "viatura offline — comando não enviado"}), 503

    # A URL de cada viatura é derivada da configuração (para produção, salvar no banco)
    # Por ora usa variável de ambiente VIATURA_BASE_URL ou padrão de desenvolvimento
    base_url = os.getenv("VIATURA_BASE_URL", "")
    if not base_url:
        return jsonify({"aviso": "VIATURA_BASE_URL não configurada — comando simulado", "comando": comando}), 200

    try:
        resp = requests.post(
            f"{base_url}/api/control",
            json={"acao": comando},
            headers=_headers_pi(),
            timeout=10,
        )
        return jsonify({"status": "enviado", "resposta": resp.status_code}), 200
    except requests.exceptions.RequestException as e:
        return jsonify({"erro": f"falha ao contatar viatura: {str(e)}"}), 502


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/config", methods=["GET"])
@login_required
def obter_config(viatura_id):
    err = _admin_required_json()
    if err:
        return err
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first()
    if not viatura:
        return jsonify({"erro": "viatura não encontrada"}), 404
    return jsonify(viatura.get_config()), 200


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/config", methods=["POST"])
@login_required
def salvar_config(viatura_id):
    err = _admin_required_json()
    if err:
        return err
    config = request.get_json(force=True, silent=True) or {}
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first()
    if not viatura:
        return jsonify({"erro": "viatura não encontrada"}), 404
    viatura.set_config(config)
    db.session.commit()
    return jsonify({"status": "salvo", "pendente": True}), 200


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/config/sync", methods=["POST"])
@login_required
def sincronizar_config(viatura_id):
    err = _admin_required_json()
    if err:
        return err
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first()
    if not viatura:
        return jsonify({"erro": "viatura não encontrada"}), 404
    if not viatura.get_config():
        return jsonify({"erro": "nenhuma configuração salva para sincronizar"}), 400
    viatura.config_pendente = True
    db.session.commit()
    return jsonify({"status": "pendente", "aviso": "Config enfileirada — Pi aplicará em até 60 s via polling"}), 200


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/config/pending", methods=["GET"])
def config_pending_get(viatura_id):
    """Pi polls: tem config nova para mim?"""
    err = _api_key_required()
    if err:
        return err
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first()
    if not viatura:
        return jsonify({"erro": "viatura não encontrada"}), 404
    pendente = bool(viatura.config_pendente)
    config = viatura.get_config() if pendente else {}
    return jsonify({"pendente": pendente, "config": config}), 200


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/config/ack", methods=["POST"])
@csrf.exempt
def config_ack(viatura_id):
    """Pi confirma que aplicou a config; QG limpa flag pendente."""
    err = _api_key_required()
    if err:
        return err
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first()
    if not viatura:
        return jsonify({"erro": "viatura não encontrada"}), 404
    viatura.config_pendente = False
    db.session.commit()
    return jsonify({"status": "ok"}), 200


# ──────────────────────────────────────────────────────────────────────────────
# Hotlist sync — autenticados por API Key (chamados pelo Pi, não pelo browser)
# ──────────────────────────────────────────────────────────────────────────────

@api_viaturas_bp.route("/api/viaturas/<viatura_id>/hotlist/pending", methods=["GET"])
def hotlist_pendente(viatura_id):
    """Pi consulta: há atualização de hotlist para mim?"""
    err = _api_key_required()
    if err:
        return err
    from models import Hotlist
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first()
    placas = [h.placa for h in Hotlist.query.filter_by(ativa=True).all()]
    h = _hotlist_hash(placas)
    pendente = bool(viatura.hotlist_pendente) if viatura else False
    return jsonify({"pendente": pendente, "hash": h, "total": len(placas)}), 200


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/hotlist_sync", methods=["GET"])
def hotlist_sync_get(viatura_id):
    """Pi baixa a hotlist completa."""
    err = _api_key_required()
    if err:
        return err
    from models import Hotlist
    placas = [h.placa for h in Hotlist.query.filter_by(ativa=True).all()]
    h = _hotlist_hash(placas)
    return jsonify({"placas": placas, "hash": h, "total": len(placas)}), 200


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/hotlist/ack", methods=["POST"])
@csrf.exempt  # S-13: Pi autentica via X-API-Key, não via sessão de browser
def hotlist_ack(viatura_id):
    """Pi confirma que aplicou a hotlist; QG limpa flag pendente."""
    err = _api_key_required()
    if err:
        return err
    from datetime import datetime, timezone
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first()
    if not viatura:
        return jsonify({"erro": "viatura não encontrada"}), 404
    data = request.get_json(force=True, silent=True) or {}
    viatura.hotlist_pendente = False
    viatura.hotlist_hash = data.get("hash", "")
    viatura.ultima_sync_hotlist = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    return jsonify({"status": "ok"}), 200


@api_viaturas_bp.route("/api/hotlist/sync/<viatura_id>", methods=["POST"])
@login_required
def sincronizar_hotlist(viatura_id):
    err = _admin_required_json()
    if err:
        return err

    from models import Hotlist
    placas = [h.placa for h in Hotlist.query.filter_by(ativa=True).all()]

    base_url = os.getenv("VIATURA_BASE_URL", "")
    if not base_url:
        return jsonify({"aviso": "VIATURA_BASE_URL não configurada — sync simulado",
                        "placas_enviadas": len(placas)}), 200

    try:
        resp = requests.post(f"{base_url}/api/hotlist", json={"placas": placas}, headers=_headers_pi(), timeout=15)
        return jsonify({"status": "sincronizado", "placas": len(placas), "resposta": resp.status_code}), 200
    except requests.exceptions.RequestException as e:
        return jsonify({"erro": str(e)}), 502
