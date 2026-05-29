import csv
import io
import re
from datetime import datetime, timedelta, timezone

# S-15: valida formato de placa (Mercosul ABC1D23 e antigo ABC1234)
_PLACA_RE = re.compile(r'^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$')

from flask import Blueprint, render_template, request, jsonify, Response, abort, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func, extract

from models import db, Viatura, Deteccao, Heartbeat, Hotlist, MotivoHotlist, EventoSistema


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_data(s: str):
    """Converte 'YYYY-MM-DD' → datetime ou None se vazio/inválido."""
    try:
        return datetime.strptime(s, "%Y-%m-%d") if s else None
    except ValueError:
        return None


def _marcar_hotlist_pendente():
    """Sinaliza para todas as viaturas ativas que a hotlist mudou."""
    # P-6: 1 UPDATE bulk em vez de N UPDATEs individuais
    Viatura.query.filter_by(ativa=True).update({"hotlist_pendente": True})


def _verificar_pi_offline():
    """
    Gera/resolve eventos pi_offline para viaturas sem heartbeat há >5 min.
    Chamado ao carregar o dashboard e a tela de eventos.
    """
    agora = _utcnow()
    corte = agora - timedelta(minutes=5)

    viaturas = Viatura.query.filter_by(ativa=True).all()
    if not viaturas:
        return

    ids = [v.viatura_id for v in viaturas]
    # P-3: 2 queries fixas em vez de 2N (uma por viatura)
    ultimos = _ultimos_heartbeats(ids)
    ev_map = {
        ev.viatura_id: ev
        for ev in EventoSistema.query.filter(
            EventoSistema.viatura_id.in_(ids),
            EventoSistema.tipo == "pi_offline",
            EventoSistema.resolvido == False,
        ).all()
    }

    for v in viaturas:
        hb = ultimos.get(v.viatura_id)
        offline = not hb or hb.recebido_em < corte
        ev_aberto = ev_map.get(v.viatura_id)

        if offline and not ev_aberto:
            ultimo = hb.recebido_em.strftime("%d/%m %H:%M") if hb else "nunca"
            db.session.add(EventoSistema(
                viatura_id=v.viatura_id,
                tipo="pi_offline",
                severidade="critico",
                detalhe=f"Último heartbeat: {ultimo}",
            ))
        elif not offline and ev_aberto:
            ev_aberto.resolvido = True
            ev_aberto.resolvido_em = agora

    # S-17: commit removido daqui — responsabilidade do caller
    # Evita double-commit se o caller já tiver transação em andamento


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
    # D-1: filtro "hoje" em BRT (UTC-3) — midnight BRT = 03:00 UTC
    agora_brt = agora - timedelta(hours=3)
    inicio_hoje = datetime.combine(agora_brt.date(), datetime.min.time()) + timedelta(hours=3)

    _verificar_pi_offline()
    db.session.commit()  # persiste eventos pi_offline criados/resolvidos acima

    viaturas_db = Viatura.query.filter_by(ativa=True).all()
    hbs = _ultimos_heartbeats([v.viatura_id for v in viaturas_db])

    # Eventos ativos por viatura para o widget de saúde
    ev_abertos = (
        EventoSistema.query
        .filter_by(resolvido=False)
        .all()
    )
    ev_por_viatura = {}
    for ev in ev_abertos:
        ev_por_viatura.setdefault(ev.viatura_id, []).append(ev)

    viaturas = []
    for v in viaturas_db:
        hb = hbs.get(v.viatura_id)
        online = bool(hb and (agora - hb.recebido_em).total_seconds() < 300)
        evs = ev_por_viatura.get(v.viatura_id, [])
        viaturas.append({
            "viatura_id": v.viatura_id,
            "descricao": v.descricao,
            "online": online,
            "heartbeat": hb,
            "eventos": evs,
            "tem_critico": any(e.severidade == "critico" for e in evs),
            "tem_aviso": any(e.severidade == "aviso" for e in evs),
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
    dt_inicio = _parse_data(data_inicio)
    dt_fim = _parse_data(data_fim)
    if dt_inicio:
        q = q.filter(Deteccao.recebido_em >= dt_inicio)
    if dt_fim:
        q = q.filter(Deteccao.recebido_em < dt_fim + timedelta(days=1))
    if (data_inicio and not dt_inicio) or (data_fim and not dt_fim):
        flash("Data inválida — filtro de data ignorado.", "warning")

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
    dt_inicio = _parse_data(data_inicio)
    dt_fim = _parse_data(data_fim)
    if dt_inicio:
        q = q.filter(Deteccao.recebido_em >= dt_inicio)
    if dt_fim:
        q = q.filter(Deteccao.recebido_em < dt_fim + timedelta(days=1))
    if (data_inicio and not dt_inicio) or (data_fim and not dt_fim):
        flash("Data inválida — filtro de data ignorado.", "warning")

    if request.args.get("export") == "csv":
        return _exportar_csv(q.order_by(Deteccao.recebido_em.desc()).limit(50_000).all(), "leituras")

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


@dashboard_bp.route("/api/mapa/alertas")
@login_required
def api_mapa_alertas():
    """Retorna alertas táticos com GPS para o mapa CSI. ?horas=N (1–72, padrão 24)."""
    try:
        horas = max(1, min(72, int(request.args.get("horas", 24))))
    except (ValueError, TypeError):
        horas = 24

    corte = _utcnow() - timedelta(hours=horas)
    alertas = (
        Deteccao.query
        .filter(
            Deteccao.alerta_tatico == True,
            Deteccao.latitude.isnot(None),
            Deteccao.longitude.isnot(None),
            Deteccao.recebido_em >= corte,
        )
        .order_by(Deteccao.recebido_em.asc())
        .limit(500)
        .all()
    )

    agora = _utcnow()
    resultado = []
    for a in alertas:
        idade_min = (agora - a.recebido_em).total_seconds() / 60
        resultado.append({
            "id": a.id,
            "placa": a.placa,
            "viatura_id": a.viatura_id,
            "latitude": a.latitude,
            "longitude": a.longitude,
            "marca": a.marca or "",
            "modelo": a.modelo or "",
            "cor": a.cor or "",
            "score": round(a.score or 0, 2),
            "recebido_em": (a.recebido_em - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M:%S"),
            "tem_imagem": a.imagem_placa is not None,
            "idade_min": round(idade_min),
        })

    return jsonify({"alertas": resultado, "horas": horas, "total": len(resultado)})


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

# ──────────────────────────────────────────────────────────────────────────────
# Eventos do sistema (Sprint 6)
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/eventos")
@login_required
def eventos():
    _admin_required()
    _verificar_pi_offline()
    db.session.commit()  # persiste eventos pi_offline criados/resolvidos acima

    viatura_id = request.args.get("viatura_id", "")
    tipo = request.args.get("tipo", "")
    severidade = request.args.get("severidade", "")
    apenas_ativos = request.args.get("apenas_ativos", "1")

    q = EventoSistema.query
    if viatura_id:
        q = q.filter_by(viatura_id=viatura_id)
    if tipo:
        q = q.filter_by(tipo=tipo)
    if severidade:
        q = q.filter_by(severidade=severidade)
    if apenas_ativos == "1":
        q = q.filter_by(resolvido=False)

    lista = q.order_by(EventoSistema.criado_em.desc()).limit(300).all()
    viaturas_ativas = Viatura.query.filter_by(ativa=True).order_by(Viatura.viatura_id).all()

    return render_template(
        "eventos.html",
        eventos=lista,
        viaturas_ativas=viaturas_ativas,
        filtros={
            "viatura_id": viatura_id,
            "tipo": tipo,
            "severidade": severidade,
            "apenas_ativos": apenas_ativos,
        },
    )


@dashboard_bp.route("/eventos/<int:evento_id>/resolver", methods=["POST"])
@login_required
def resolver_evento(evento_id):
    _admin_required()
    ev = EventoSistema.query.get_or_404(evento_id)
    ev.resolvido = True
    ev.resolvido_em = _utcnow()
    db.session.commit()
    return redirect(url_for("dashboard.eventos", **{
        k: v for k, v in request.form.items() if k != "csrf_token"
    }))


# ──────────────────────────────────────────────────────────────────────────────
# Hotlist
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/viaturas/saude")
@login_required
def saude_frota():
    _admin_required()
    agora = _utcnow()
    viaturas_db = Viatura.query.filter_by(ativa=True).all()
    hbs = _ultimos_heartbeats([v.viatura_id for v in viaturas_db])
    ev_abertos = EventoSistema.query.filter_by(resolvido=False).all()
    ev_por_viatura = {}
    for ev in ev_abertos:
        ev_por_viatura.setdefault(ev.viatura_id, []).append(ev)

    viaturas = []
    for v in viaturas_db:
        hb = hbs.get(v.viatura_id)
        online = bool(hb and (agora - hb.recebido_em).total_seconds() < 300)
        evs = ev_por_viatura.get(v.viatura_id, [])
        viaturas.append({
            "viatura_id": v.viatura_id,
            "descricao": v.descricao,
            "online": online,
            "heartbeat": hb,
            "eventos": evs,
            "tem_critico": any(e.severidade == "critico" for e in evs),
            "tem_aviso": any(e.severidade == "aviso" for e in evs),
        })
    return render_template("saude_frota.html", viaturas=viaturas)


@dashboard_bp.route("/hotlist", methods=["GET", "POST"])
@login_required
def hotlist():
    _admin_required()

    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "adicionar":
            placa = request.form.get("placa", "").upper().strip()
            descricao = request.form.get("descricao", "").strip()
            motivo = request.form.get("motivo", "").strip()
            observacao = request.form.get("observacao", "").strip()
            try:
                prioridade = int(request.form.get("prioridade", 2))
            except ValueError:
                prioridade = 2
            if placa and _PLACA_RE.match(placa):
                existente = Hotlist.query.filter_by(placa=placa).first()
                if existente:
                    existente.ativa = True
                    existente.descricao = descricao
                    existente.motivo = motivo
                    existente.prioridade = prioridade
                    existente.observacao = observacao
                    flash(f"Placa {placa} atualizada na hotlist.", "success")
                else:
                    db.session.add(Hotlist(
                        placa=placa, descricao=descricao,
                        motivo=motivo, prioridade=prioridade, observacao=observacao,
                    ))
                    flash(f"Placa {placa} adicionada à hotlist.", "success")
                _marcar_hotlist_pendente()
                db.session.commit()
            else:
                flash("Formato de placa inválido. Use AAA1234 (antigo) ou AAA1A23 (Mercosul).", "danger")
            return redirect(url_for("dashboard.hotlist"))

        elif acao == "remover":
            placa = request.form.get("placa", "")
            item = Hotlist.query.filter_by(placa=placa).first()
            if item:
                db.session.delete(item)
                _marcar_hotlist_pendente()
                db.session.commit()
                flash(f"Placa {placa} removida da hotlist.", "warning")
            return redirect(url_for("dashboard.hotlist"))

        elif acao == "importar_csv":
            arquivo = request.files.get("csv_file")
            if arquivo:
                content = arquivo.stream.read()
                if len(content) > 500_000:
                    flash("Arquivo muito grande (máx. 500 KB).", "danger")
                    return redirect(url_for("dashboard.hotlist"))
                stream = io.StringIO(content.decode("utf-8", errors="replace"))
                reader = csv.reader(stream)
                adicionadas = 0
                ignoradas = 0
                invalidas = 0
                for row in reader:
                    if not row:
                        continue
                    placa = row[0].strip().upper()
                    descricao = row[1].strip() if len(row) > 1 else ""
                    motivo = row[2].strip() if len(row) > 2 else ""
                    try:
                        prioridade = int(row[3].strip()) if len(row) > 3 else 2
                    except ValueError:
                        prioridade = 2
                    if not placa or not _PLACA_RE.match(placa):
                        invalidas += 1
                        continue
                    if Hotlist.query.filter_by(placa=placa).first():
                        ignoradas += 1
                        continue
                    db.session.add(Hotlist(
                        placa=placa, descricao=descricao,
                        motivo=motivo, prioridade=prioridade,
                    ))
                    adicionadas += 1
                if adicionadas:
                    _marcar_hotlist_pendente()
                db.session.commit()
                partes = [f"{adicionadas} placa(s) adicionada(s)"]
                if ignoradas:
                    partes.append(f"{ignoradas} já existia(m)")
                if invalidas:
                    partes.append(f"{invalidas} inválida(s) ignorada(s)")
                flash(" · ".join(partes) + ".", "success" if adicionadas else "warning")
                return redirect(url_for("dashboard.hotlist"))

        elif acao == "adicionar_motivo":
            nome = request.form.get("nome_motivo", "").strip()
            if nome and not MotivoHotlist.query.filter_by(nome=nome).first():
                db.session.add(MotivoHotlist(nome=nome))
                db.session.commit()
            return redirect(url_for("dashboard.hotlist"))

        elif acao == "remover_motivo":
            motivo_id = request.form.get("motivo_id")
            item_m = db.session.get(MotivoHotlist, motivo_id)
            if item_m:
                db.session.delete(item_m)
                db.session.commit()
            return redirect(url_for("dashboard.hotlist"))

    if request.args.get("export") == "csv":
        items = Hotlist.query.filter_by(ativa=True).order_by(Hotlist.prioridade, Hotlist.placa).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["placa", "descricao", "motivo", "prioridade"])
        for item in items:
            writer.writerow([item.placa, item.descricao, item.motivo, item.prioridade])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=hotlist.csv"},
        )

    items = Hotlist.query.order_by(Hotlist.prioridade, Hotlist.placa).all()
    motivos = MotivoHotlist.query.order_by(MotivoHotlist.nome).all()
    return render_template("hotlist.html", hotlist=items, motivos=motivos)


@dashboard_bp.route("/hotlist/<placa>/editar", methods=["POST"])
@login_required
def hotlist_editar(placa):
    _admin_required()
    item = Hotlist.query.filter_by(placa=placa.upper()).first_or_404()
    try:
        item.prioridade = int(request.form.get("prioridade", item.prioridade))
    except ValueError:
        pass
    item.motivo = request.form.get("motivo", item.motivo).strip()
    item.descricao = request.form.get("descricao", item.descricao).strip()
    item.observacao = request.form.get("observacao", item.observacao).strip()
    _marcar_hotlist_pendente()
    db.session.commit()
    flash(f"Placa {placa.upper()} atualizada.", "success")
    return redirect(url_for("dashboard.hotlist"))


@dashboard_bp.route("/hotlist/<placa>/toggle", methods=["POST"])
@login_required
def hotlist_toggle(placa):
    _admin_required()
    item = Hotlist.query.filter_by(placa=placa.upper()).first_or_404()
    item.ativa = not item.ativa
    _marcar_hotlist_pendente()
    db.session.commit()
    estado = "ativada" if item.ativa else "desativada"
    flash(f"Placa {placa.upper()} {estado}.", "info")
    return redirect(url_for("dashboard.hotlist"))


@dashboard_bp.route("/leituras/<int:leitura_id>")
@login_required
def detalhe_leitura(leitura_id):
    d = Deteccao.query.get_or_404(leitura_id)
    return render_template("detalhe_leitura.html", d=d)


@dashboard_bp.route("/leituras/<int:leitura_id>/imagem_placa")
@login_required
def imagem_placa(leitura_id):
    """Serve o crop da placa (JPEG binário) para exibição no detalhe do alerta."""
    d = Deteccao.query.get_or_404(leitura_id)
    if not d.imagem_placa:
        abort(404)
    return Response(
        d.imagem_placa,
        mimetype="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@dashboard_bp.route("/leituras/<int:leitura_id>/imagem_veiculo")
@login_required
def imagem_veiculo(leitura_id):
    """Serve o frame completo da câmera (JPEG binário) — disponível apenas em alertas táticos."""
    d = Deteccao.query.get_or_404(leitura_id)
    if not d.imagem_veiculo:
        abort(404)
    return Response(
        d.imagem_veiculo,
        mimetype="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Trajetória Investigativa
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/investigacao")
@login_required
def investigacao():
    viaturas = Viatura.query.filter_by(ativa=True).all()
    return render_template("investigacao.html", viaturas=viaturas)


@dashboard_bp.route("/api/investigacao/trajeto")
@login_required
def api_investigacao_trajeto():
    placa        = request.args.get("placa", "").upper().strip()
    marca        = request.args.get("marca", "").strip()
    modelo       = request.args.get("modelo", "").strip()
    cor          = request.args.get("cor", "").strip()
    tipo_veiculo = request.args.get("tipo_veiculo", "").strip()
    data_inicio  = request.args.get("data_inicio", "")
    data_fim     = request.args.get("data_fim", "")
    hora_inicio  = request.args.get("hora_inicio", "")
    hora_fim     = request.args.get("hora_fim", "")

    q = Deteccao.query.filter(
        Deteccao.latitude.isnot(None),
        Deteccao.longitude.isnot(None),
    )

    if placa:
        q = q.filter(Deteccao.placa.contains(placa))
    if marca:
        q = q.filter(Deteccao.marca.ilike(f"%{marca}%"))
    if modelo:
        q = q.filter(Deteccao.modelo.ilike(f"%{modelo}%"))
    if cor:
        q = q.filter(Deteccao.cor.ilike(f"%{cor}%"))
    if tipo_veiculo:
        q = q.filter(Deteccao.tipo_veiculo.ilike(f"%{tipo_veiculo}%"))
    dt_inicio = _parse_data(data_inicio)
    dt_fim = _parse_data(data_fim)
    if dt_inicio:
        q = q.filter(Deteccao.recebido_em >= dt_inicio)
    if dt_fim:
        q = q.filter(Deteccao.recebido_em < dt_fim + timedelta(days=1))
    if hora_inicio:
        try:
            q = q.filter(extract("hour", Deteccao.recebido_em) >= int(hora_inicio))
        except ValueError:
            pass
    if hora_fim:
        try:
            q = q.filter(extract("hour", Deteccao.recebido_em) <= int(hora_fim))
        except ValueError:
            pass

    deteccoes = q.order_by(Deteccao.recebido_em.asc()).limit(500).all()

    pontos = [
        {
            "lat": d.latitude,
            "lon": d.longitude,
            "id": d.id,
            "placa": d.placa,
            "viatura_id": d.viatura_id,
            "recebido_em": (d.recebido_em - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M:%S"),
            "marca": d.marca,
            "modelo": d.modelo,
            "cor": d.cor,
            "score": round(d.score or 0, 2),
            "velocidade": round(d.velocidade or 0, 1),
            "alerta_tatico": d.alerta_tatico,
        }
        for d in deteccoes
    ]

    return jsonify({"total": len(pontos), "pontos": pontos})


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
    eventos = (EventoSistema.query
               .filter_by(viatura_id=viatura_id)
               .order_by(EventoSistema.criado_em.desc())
               .limit(100).all())
    return render_template("config_viatura.html",
                           viatura_id=viatura.viatura_id,
                           viatura=viatura,
                           cfg=viatura.get_config(),
                           eventos=eventos)


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

@dashboard_bp.route("/admin/retencao")
@login_required
def admin_retencao():
    _admin_required()

    total_det, ant_det, rec_det = db.session.query(
        func.count(Deteccao.id), func.min(Deteccao.recebido_em), func.max(Deteccao.recebido_em)
    ).one()

    total_hb, ant_hb, rec_hb = db.session.query(
        func.count(Heartbeat.id), func.min(Heartbeat.recebido_em), func.max(Heartbeat.recebido_em)
    ).one()

    total_ev, ant_ev, rec_ev = db.session.query(
        func.count(EventoSistema.id), func.min(EventoSistema.criado_em), func.max(EventoSistema.criado_em)
    ).filter(EventoSistema.resolvido == True).one()

    stats = {
        "deteccoes":          {"total": total_det, "mais_antigo": ant_det, "mais_recente": rec_det},
        "heartbeats":         {"total": total_hb,  "mais_antigo": ant_hb,  "mais_recente": rec_hb},
        "eventos_resolvidos": {"total": total_ev,  "mais_antigo": ant_ev,  "mais_recente": rec_ev},
    }
    return render_template("retencao.html", stats=stats)


@dashboard_bp.route("/admin/retencao/limpar", methods=["POST"])
@login_required
def admin_retencao_limpar():
    _admin_required()

    try:
        dias = int(request.form.get("dias", 180))
        dias = max(30, min(730, dias))
    except (ValueError, TypeError):
        flash("Valor de dias inválido.", "danger")
        return redirect(url_for("dashboard.admin_retencao"))

    corte = datetime.utcnow() - timedelta(days=dias)
    total = 0

    if request.form.get("limpar_deteccoes"):
        total += Deteccao.query.filter(Deteccao.recebido_em < corte).delete()
    if request.form.get("limpar_heartbeats"):
        total += Heartbeat.query.filter(Heartbeat.recebido_em < corte).delete()
    if request.form.get("limpar_eventos"):
        total += EventoSistema.query.filter(
            EventoSistema.criado_em < corte,
            EventoSistema.resolvido == True,
        ).delete()

    db.session.commit()
    flash(f"{total} registro(s) deletados (anteriores a {corte.strftime('%d/%m/%Y')}).", "success")
    return redirect(url_for("dashboard.admin_retencao"))


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
