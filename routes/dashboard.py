import csv
import io
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, jsonify, Response, abort, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from models import db, Viatura, Deteccao, Heartbeat, Hotlist


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _marcar_hotlist_pendente():
    """Sinaliza para todas as viaturas ativas que a hotlist mudou."""
    for v in Viatura.query.filter_by(ativa=True).all():
        v.hotlist_pendente = True


def _ultimos_heartbeats(viatura_ids=None):
    """Retorna {viatura_id: Heartbeat} com o último heartbeat de cada viatura em uma query."""
    subq = (
        db.session.query(
            Heartbeat.viatura_id,
            func.max(Heartbeat.recebido_em).label("max_rec"),
        )
        .group_by(Heartbeat.viatura_id)
        .subquery()
    )
    q = Heartbeat.query.join(
        subq,
        (Heartbeat.viatura_id == subq.c.viatura_id)
        & (Heartbeat.recebido_em == subq.c.max_rec),
    )
    if viatura_ids is not None:
        q = q.filter(Heartbeat.viatura_id.in_(viatura_ids))
    return {hb.viatura_id: hb for hb in q.all()}

dashboard_bp = Blueprint("dashboard", __name__)


def _admin_required():
    if not current_user.is_admin():
        abort(403)


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard principal
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/")
@login_required
def index():
    agora = _utcnow()
    inicio_hoje = datetime.combine(agora.date(), datetime.min.time())

    viaturas_db = Viatura.query.filter_by(ativa=True).all()
    hbs = _ultimos_heartbeats([v.viatura_id for v in viaturas_db])

    viaturas = []
    for v in viaturas_db:
        hb = hbs.get(v.viatura_id)
        online = bool(hb and (agora - hb.recebido_em).total_seconds() < 300)
        viaturas.append({
            "viatura_id": v.viatura_id,
            "descricao": v.descricao,
            "online": online,
            "heartbeat": hb,
        })

    alertas_hoje = Deteccao.query.filter(
        Deteccao.alerta_tatico == True,
        Deteccao.recebido_em >= inicio_hoje,
    ).count()

    leituras_hoje = Deteccao.query.filter(
        Deteccao.recebido_em >= inicio_hoje,
    ).count()

    ultimas_deteccoes = (
        Deteccao.query
        .order_by(Deteccao.recebido_em.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "dashboard.html",
        viaturas=viaturas,
        alertas_hoje=alertas_hoje,
        leituras_hoje=leituras_hoje,
        ultimas_deteccoes=ultimas_deteccoes,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Alertas táticos
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/alertas")
@login_required
def alertas():
    viatura_id = request.args.get("viatura_id", "")
    placa = request.args.get("placa", "").upper().strip()
    data_inicio = request.args.get("data_inicio", "")
    data_fim = request.args.get("data_fim", "")

    q = Deteccao.query.filter_by(alerta_tatico=True)

    if viatura_id:
        q = q.filter_by(viatura_id=viatura_id)
    if placa:
        q = q.filter(Deteccao.placa.contains(placa))
    if data_inicio:
        q = q.filter(Deteccao.recebido_em >= datetime.strptime(data_inicio, "%Y-%m-%d"))
    if data_fim:
        q = q.filter(Deteccao.recebido_em < datetime.strptime(data_fim, "%Y-%m-%d") + timedelta(days=1))

    resultados = q.order_by(Deteccao.recebido_em.desc()).limit(500).all()
    viaturas = Viatura.query.filter_by(ativa=True).all()

    if request.args.get("export") == "csv":
        return _exportar_csv(resultados, "alertas")

    return render_template(
        "alertas.html",
        deteccoes=resultados,
        viaturas=viaturas,
        filtros={"viatura_id": viatura_id, "placa": placa, "data_inicio": data_inicio, "data_fim": data_fim},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Log de leituras
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/leituras")
@login_required
def leituras():
    viatura_id = request.args.get("viatura_id", "")
    placa = request.args.get("placa", "").upper().strip()
    data_inicio = request.args.get("data_inicio", "")
    data_fim = request.args.get("data_fim", "")
    so_alertas = request.args.get("so_alertas") == "1"
    page = request.args.get("page", 1, type=int)

    q = Deteccao.query
    if viatura_id:
        q = q.filter_by(viatura_id=viatura_id)
    if placa:
        q = q.filter(Deteccao.placa.contains(placa))
    if so_alertas:
        q = q.filter_by(alerta_tatico=True)
    if data_inicio:
        q = q.filter(Deteccao.recebido_em >= datetime.strptime(data_inicio, "%Y-%m-%d"))
    if data_fim:
        q = q.filter(Deteccao.recebido_em < datetime.strptime(data_fim, "%Y-%m-%d") + timedelta(days=1))

    if request.args.get("export") == "csv":
        return _exportar_csv(q.order_by(Deteccao.recebido_em.desc()).all(), "leituras")

    paginacao = q.order_by(Deteccao.recebido_em.desc()).paginate(page=page, per_page=50, error_out=False)
    viaturas = Viatura.query.filter_by(ativa=True).all()

    return render_template(
        "leituras.html",
        paginacao=paginacao,
        viaturas=viaturas,
        filtros={"viatura_id": viatura_id, "placa": placa, "data_inicio": data_inicio,
                 "data_fim": data_fim, "so_alertas": so_alertas},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Mapa de frota
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/mapa")
@login_required
def mapa():
    return render_template("mapa.html")


@dashboard_bp.route("/api/mapa/viaturas")
@login_required
def api_mapa_viaturas():
    agora = _utcnow()
    viaturas = Viatura.query.filter_by(ativa=True).all()
    hbs = _ultimos_heartbeats([v.viatura_id for v in viaturas])
    resultado = []
    for v in viaturas:
        hb = hbs.get(v.viatura_id)
        if not hb or not hb.latitude:
            continue
        online = (agora - hb.recebido_em).total_seconds() < 300
        resultado.append({
            "viatura_id": v.viatura_id,
            "online": online,
            "latitude": hb.latitude,
            "longitude": hb.longitude,
            "cpu_temp_c": hb.cpu_temp_c,
            "lpr_health": hb.lpr_health,
            "buffer_pendente": hb.buffer_pendente,
            "ultima_atualizacao": hb.recebido_em.strftime("%d/%m/%Y %H:%M:%S"),
        })

    # Últimos alertas táticos recentes para marcadores vermelhos
    alertas = (
        Deteccao.query
        .filter_by(alerta_tatico=True)
        .filter(Deteccao.latitude.isnot(None))
        .order_by(Deteccao.recebido_em.desc())
        .limit(50)
        .all()
    )
    alertas_geo = [
        {
            "placa": a.placa,
            "viatura_id": a.viatura_id,
            "latitude": a.latitude,
            "longitude": a.longitude,
            "recebido_em": a.recebido_em.strftime("%d/%m/%Y %H:%M:%S"),
        }
        for a in alertas
    ]

    return jsonify({"viaturas": resultado, "alertas": alertas_geo})


@dashboard_bp.route("/api/mapa/trajeto/<viatura_id>")
@login_required
def api_trajeto(viatura_id):
    heartbeats = (
        Heartbeat.query
        .filter_by(viatura_id=viatura_id)
        .filter(Heartbeat.latitude.isnot(None))
        .order_by(Heartbeat.recebido_em.desc())
        .limit(20)
        .all()
    )
    pontos = [{"lat": hb.latitude, "lon": hb.longitude} for hb in reversed(heartbeats)]
    return jsonify(pontos)


# ──────────────────────────────────────────────────────────────────────────────
# Gestão de viaturas
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/viaturas")
@login_required
def viaturas():
    _admin_required()
    todas = Viatura.query.all()
    return render_template("viaturas.html", viaturas=todas)


@dashboard_bp.route("/viaturas/criar", methods=["POST"])
@login_required
def criar_viatura():
    _admin_required()
    viatura_id = request.form.get("viatura_id", "").strip()
    descricao = request.form.get("descricao", "").strip()
    if viatura_id and not Viatura.query.filter_by(viatura_id=viatura_id).first():
        db.session.add(Viatura(viatura_id=viatura_id, descricao=descricao))
        db.session.commit()
    return redirect(url_for("dashboard.viaturas"))


@dashboard_bp.route("/api/viaturas/<viatura_id>/historico")
@login_required
def api_historico_viatura(viatura_id):
    _admin_required()
    inicio = _utcnow() - timedelta(hours=24)
    heartbeats = (
        Heartbeat.query
        .filter_by(viatura_id=viatura_id)
        .filter(Heartbeat.recebido_em >= inicio)
        .order_by(Heartbeat.recebido_em.asc())
        .all()
    )
    return jsonify([
        {
            "ts": hb.recebido_em.strftime("%H:%M"),
            "cpu_temp_c": hb.cpu_temp_c,
            "lpr_health": hb.lpr_health,
        }
        for hb in heartbeats
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Hotlist
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/hotlist", methods=["GET", "POST"])
@login_required
def hotlist():
    _admin_required()

    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "adicionar":
            placa = request.form.get("placa", "").upper().strip()
            descricao = request.form.get("descricao", "").strip()
            if placa:
                existente = Hotlist.query.filter_by(placa=placa).first()
                if existente:
                    existente.ativa = True
                    existente.descricao = descricao
                else:
                    db.session.add(Hotlist(placa=placa, descricao=descricao))
                _marcar_hotlist_pendente()
                db.session.commit()

        elif acao == "remover":
            placa = request.form.get("placa", "")
            item = Hotlist.query.filter_by(placa=placa).first()
            if item:
                db.session.delete(item)
                _marcar_hotlist_pendente()
                db.session.commit()

        elif acao == "importar_csv":
            arquivo = request.files.get("csv_file")
            if arquivo:
                stream = io.StringIO(arquivo.stream.read().decode("utf-8"))
                reader = csv.reader(stream)
                for row in reader:
                    if not row:
                        continue
                    placa = row[0].strip().upper()
                    descricao = row[1].strip() if len(row) > 1 else ""
                    if placa:
                        existente = Hotlist.query.filter_by(placa=placa).first()
                        if not existente:
                            db.session.add(Hotlist(placa=placa, descricao=descricao))
                _marcar_hotlist_pendente()
                db.session.commit()

    if request.args.get("export") == "csv":
        items = Hotlist.query.filter_by(ativa=True).order_by(Hotlist.placa).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["placa", "descricao"])
        for item in items:
            writer.writerow([item.placa, item.descricao])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=hotlist.csv"},
        )

    items = Hotlist.query.order_by(Hotlist.placa).all()
    return render_template("hotlist.html", hotlist=items)


@dashboard_bp.route("/api/hotlist")
@login_required
def api_hotlist():
    placas = [h.placa for h in Hotlist.query.filter_by(ativa=True).all()]
    return jsonify({"placas": placas, "total": len(placas)})


@dashboard_bp.route("/viaturas/<viatura_id>/config")
@login_required
def config_viatura(viatura_id):
    _admin_required()
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first_or_404()
    return render_template("config_viatura.html", viatura_id=viatura.viatura_id, viatura=viatura, cfg=viatura.get_config())


@dashboard_bp.route("/viaturas/<viatura_id>/hotlist_mode", methods=["POST"])
@login_required
def salvar_hotlist_mode(viatura_id):
    _admin_required()
    viatura = Viatura.query.filter_by(viatura_id=viatura_id).first_or_404()
    modo = request.form.get("hotlist_mode", "hibrido")
    if modo in ("hibrido", "nuvem", "local"):
        viatura.hotlist_mode = modo
        db.session.commit()
    return redirect(url_for("dashboard.config_viatura", viatura_id=viatura_id))


# ──────────────────────────────────────────────────────────────────────────────
# Utilitário
# ──────────────────────────────────────────────────────────────────────────────

def _exportar_csv(deteccoes: list, nome: str) -> Response:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "data_hora", "viatura_id", "placa", "marca", "modelo", "cor",
        "velocidade_kmh", "score", "alerta_tatico", "latitude", "longitude",
    ])
    for d in deteccoes:
        writer.writerow([
            d.recebido_em.strftime("%d/%m/%Y %H:%M:%S"),
            d.viatura_id, d.placa, d.marca, d.modelo, d.cor,
            f"{d.velocidade:.1f}", f"{d.score:.2f}",
            "SIM" if d.alerta_tatico else "NAO",
            d.latitude or "", d.longitude or "",
        ])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome}.csv"},
    )
