import os
import requests

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user

from models import db, Viatura

api_viaturas_bp = Blueprint("api_viaturas", __name__)

COMANDOS_VALIDOS = {"pause_lpr", "resume_lpr", "restart_lpr", "restart_argos"}


def _headers_pi():
    return {"X-API-Key": current_app.config.get("QG_API_KEY", "argos-secret-2026")}


def _admin_required_json():
    if not current_user.is_admin():
        return jsonify({"erro": "acesso negado"}), 403
    return None


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

    base_url = os.getenv("VIATURA_BASE_URL", "")
    if not base_url:
        return jsonify({"aviso": "VIATURA_BASE_URL não configurada — retornando config padrão",
                        "config": {}}), 200

    try:
        resp = requests.get(f"{base_url}/api/config", headers=_headers_pi(), timeout=10)
        return jsonify(resp.json()), 200
    except requests.exceptions.RequestException as e:
        return jsonify({"erro": str(e)}), 502


@api_viaturas_bp.route("/api/viaturas/<viatura_id>/config", methods=["POST"])
@login_required
def salvar_config(viatura_id):
    err = _admin_required_json()
    if err:
        return err

    config = request.get_json(force=True, silent=True) or {}
    base_url = os.getenv("VIATURA_BASE_URL", "")

    if not base_url:
        return jsonify({"aviso": "VIATURA_BASE_URL não configurada — config simulada", "config": config}), 200

    try:
        resp = requests.post(f"{base_url}/api/config", json=config, headers=_headers_pi(), timeout=10)
        return jsonify({"status": "aplicado", "resposta": resp.status_code}), 200
    except requests.exceptions.RequestException as e:
        return jsonify({"erro": str(e)}), 502


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
