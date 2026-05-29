import csv
import io
import re
from datetime import datetime, timedelta, timezone

# S-15: valida formato de placa (Mercosul ABC1D23 e antigo ABC1234)
_PLACA_RE = re.compile(r'^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$')

from flask import Blueprint, g, render_template, request, jsonify, Response, abort, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func, extract
from werkzeug.security import generate_password_hash

from models import db, Cliente, Viatura, Deteccao, Heartbeat, Hotlist, MotivoHotlist, EventoSistema, Usuario


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


# ── 8.3: Guards por perfil ──────────────────────────────────────────────────

def _superadmin_required():
    """Somente superadmin (ou legado 'admin') acessa."""
    if not current_user.is_superadmin():
        abort(403)


def _hotlist_admin_required():
    """superadmin OU admin_cliente podem gerenciar hotlist e ver eventos."""
    if not (current_user.is_superadmin() or current_user.is_admin_cliente()):
        abort(403)


def _equipment_admin_required():
    """Somente superadmin gerencia equipamentos (viaturas, config, retenção)."""
    if not current_user.is_superadmin():
        abort(403)


# ── 8.3: Filtros de visibilidade por cliente ─────────────────────────────────

def _viatura_ids_do_usuario():
    """Retorna lista de viatura_ids visíveis ao usuário atual.
    None = superadmin (sem filtro). [] = cliente sem viaturas cadastradas.
    Usa flask.g como cache para evitar query repetida na mesma request."""
    if hasattr(g, "_viatura_ids_cache"):
        return g._viatura_ids_cache
    if current_user.is_superadmin():
        g._viatura_ids_cache = None
        return None
    cid = current_user.get_cliente_id()
    if cid is None:
        g._viatura_ids_cache = []
        return []
    ids = [v.viatura_id for v in Viatura.query.filter_by(cliente_id=cid, ativa=True).all()]
    g._viatura_ids_cache = ids
    return ids


def _aplicar_filtro_viatura(query, campo):
    """Aplica filtro de viatura_ids em uma query. Campo deve ser coluna viatura_id."""
    ids = _viatura_ids_do_usuario()
    if ids is None:
        return query
    if not ids:
        return query.filter(False)
    return query.filter(campo.in_(ids))


def _cliente_id_do_usuario():
    """Retorna cliente_id do usuário atual, ou None para superadmin."""
    return None if current_user.is_superadmin() else current_user.get_cliente_id()


def _verificar_acesso_viatura(viatura_id):
    """Aborta 403 se o usuário não pode ver dados desta viatura."""
    ids = _viatura_ids_do_usuario()
    if ids is None:
        return
    if viatura_id not in ids:
        abort(403)


def _verificar_acesso_leitura(deteccao):
    """Aborta 403 se o usuário não pode ver esta detecção."""
    _verificar_acesso_viatura(deteccao.viatura_id)


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

    viaturas_db = _aplicar_filtro_viatura(Viatura.query.filter_by(ativa=True), Viatura.viatura_id).all()
    hbs = _ultimos_heartbeats([v.viatura_id for v in viaturas_db])

    # Eventos ativos por viatura para o widget de saúde
    ev_abertos = _aplicar_filtro_viatura(
        EventoSistema.query.filter_by(resolvido=False), EventoSistema.viatura_id
    ).all()
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

    q_alertas = _aplicar_filtro_viatura(
        Deteccao.query.filter(Deteccao.alerta_tatico == True, Deteccao.recebido_em >= inicio_hoje),
        Deteccao.viatura_id,
    )
    alertas_hoje = q_alertas.count()

    q_leituras = _aplicar_filtro_viatura(
        Deteccao.query.filter(Deteccao.recebido_em >= inicio_hoje),
        Deteccao.viatura_id,
    )
    leituras_hoje = q_leituras.count()

    ultimas_deteccoes = (
        _aplicar_filtro_viatura(Deteccao.query, Deteccao.viatura_id)
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

    q = _aplicar_filtro_viatura(Deteccao.query.filter_by(alerta_tatico=True), Deteccao.viatura_id)

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
    viaturas = _aplicar_filtro_viatura(Viatura.query.filter_by(ativa=True), Viatura.viatura_id).all()

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

    q = _aplicar_filtro_viatura(Deteccao.query, Deteccao.viatura_id)
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
    viaturas = _aplicar_filtro_viatura(Viatura.query.filter_by(ativa=True), Viatura.viatura_id).all()

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
    viaturas = _aplicar_filtro_viatura(Viatura.query.filter_by(ativa=True), Viatura.viatura_id).all()
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
            "ultima_atualizacao": (hb.recebido_em - timedelta(hours=3)).strftime("%d/%m %H:%M:%S"),
            "descricao": v.descricao or "",
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
        _aplicar_filtro_viatura(
            Deteccao.query.filter(
                Deteccao.alerta_tatico == True,
                Deteccao.latitude.isnot(None),
                Deteccao.longitude.isnot(None),
                Deteccao.recebido_em >= corte,
            ),
            Deteccao.viatura_id,
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
    _verificar_acesso_viatura(viatura_id)
    heartbeats = (
        Heartbeat.query
        .filter_by(viatura_id=viatura_id)
        .filter(Heartbeat.latitude.isnot(None))
        .order_by(Heartbeat.recebido_em.desc())
        .limit(40)
        .all()
    )
    pontos = [
        {
            "lat": hb.latitude,
            "lon": hb.longitude,
            "ts": (hb.recebido_em - timedelta(hours=3)).strftime("%H:%M"),
            "idade_min": round((_utcnow() - hb.recebido_em).total_seconds() / 60),
        }
        for hb in reversed(heartbeats)
    ]
    return jsonify(pontos)


# ──────────────────────────────────────────────────────────────────────────────
# Gestão de viaturas
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/viaturas")
@login_required
def viaturas():
    _equipment_admin_required()
    todas = Viatura.query.order_by(Viatura.viatura_id).all()
    clientes = Cliente.query.filter_by(ativo=True).order_by(Cliente.nome).all()
    return render_template("viaturas.html", viaturas=todas, clientes=clientes)


@dashboard_bp.route("/viaturas/criar", methods=["POST"])
@login_required
def criar_viatura():
    _equipment_admin_required()
    viatura_id = request.form.get("viatura_id", "").strip()
    descricao = request.form.get("descricao", "").strip()
    try:
        cliente_id = int(request.form.get("cliente_id")) if request.form.get("cliente_id") else None
    except (ValueError, TypeError):
        cliente_id = None
    if viatura_id and not Viatura.query.filter_by(viatura_id=viatura_id).first():
        db.session.add(Viatura(viatura_id=viatura_id, descricao=descricao, cliente_id=cliente_id))
        db.session.commit()
        flash(f"Viatura {viatura_id} cadastrada.", "success")
    return redirect(url_for("dashboard.viaturas"))


@dashboard_bp.route("/api/viaturas/<viatura_id>/historico")
@login_required
def api_historico_viatura(viatura_id):
    _equipment_admin_required()
    _verificar_acesso_viatura(viatura_id)
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
    _hotlist_admin_required()
    _verificar_pi_offline()
    db.session.commit()  # persiste eventos pi_offline criados/resolvidos acima

    viatura_id = request.args.get("viatura_id", "")
    tipo = request.args.get("tipo", "")
    severidade = request.args.get("severidade", "")
    apenas_ativos = request.args.get("apenas_ativos", "1")

    q = _aplicar_filtro_viatura(EventoSistema.query, EventoSistema.viatura_id)
    if viatura_id:
        q = q.filter_by(viatura_id=viatura_id)
    if tipo:
        q = q.filter_by(tipo=tipo)
    if severidade:
        q = q.filter_by(severidade=severidade)
    if apenas_ativos == "1":
        q = q.filter_by(resolvido=False)

    lista = q.order_by(EventoSistema.criado_em.desc()).limit(300).all()
    viaturas_ativas = _aplicar_filtro_viatura(
        Viatura.query.filter_by(ativa=True), Viatura.viatura_id
    ).order_by(Viatura.viatura_id).all()

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
    _hotlist_admin_required()
    ev = EventoSistema.query.get_or_404(evento_id)
    _verificar_acesso_viatura(ev.viatura_id)
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
    _equipment_admin_required()
    agora = _utcnow()
    viaturas_db = _aplicar_filtro_viatura(Viatura.query.filter_by(ativa=True), Viatura.viatura_id).all()
    hbs = _ultimos_heartbeats([v.viatura_id for v in viaturas_db])
    ev_abertos = _aplicar_filtro_viatura(
        EventoSistema.query.filter_by(resolvido=False), EventoSistema.viatura_id
    ).all()
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
    _hotlist_admin_required()
    cid = _cliente_id_do_usuario()  # None = superadmin (sem filtro de cliente)

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
                    # IDOR: admin_cliente só edita placas do seu cliente
                    if cid is not None and existente.cliente_id != cid:
                        abort(403)
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
                        cliente_id=cid,
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
                if cid is not None and item.cliente_id != cid:
                    abort(403)
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
                        cliente_id=cid,
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
            # motivos são globais — apenas superadmin gerencia
            if not current_user.is_superadmin():
                abort(403)
            nome = request.form.get("nome_motivo", "").strip()
            if nome and not MotivoHotlist.query.filter_by(nome=nome).first():
                db.session.add(MotivoHotlist(nome=nome))
                db.session.commit()
            return redirect(url_for("dashboard.hotlist"))

        elif acao == "remover_motivo":
            if not current_user.is_superadmin():
                abort(403)
            motivo_id = request.form.get("motivo_id")
            item_m = db.session.get(MotivoHotlist, motivo_id)
            if item_m:
                db.session.delete(item_m)
                db.session.commit()
            return redirect(url_for("dashboard.hotlist"))

    if request.args.get("export") == "csv":
        q_exp = Hotlist.query.filter_by(ativa=True)
        if cid is not None:
            q_exp = q_exp.filter_by(cliente_id=cid)
        items_exp = q_exp.order_by(Hotlist.prioridade, Hotlist.placa).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["placa", "descricao", "motivo", "prioridade"])
        for item in items_exp:
            writer.writerow([item.placa, item.descricao, item.motivo, item.prioridade])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=hotlist.csv"},
        )

    q_items = Hotlist.query
    if cid is not None:
        q_items = q_items.filter_by(cliente_id=cid)
    items = q_items.order_by(Hotlist.prioridade, Hotlist.placa).all()
    motivos = MotivoHotlist.query.order_by(MotivoHotlist.nome).all()
    return render_template("hotlist.html", hotlist=items, motivos=motivos)


@dashboard_bp.route("/hotlist/<placa>/editar", methods=["POST"])
@login_required
def hotlist_editar(placa):
    _hotlist_admin_required()
    item = Hotlist.query.filter_by(placa=placa.upper()).first_or_404()
    cid = _cliente_id_do_usuario()
    if cid is not None and item.cliente_id != cid:
        abort(403)
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
    _hotlist_admin_required()
    item = Hotlist.query.filter_by(placa=placa.upper()).first_or_404()
    cid = _cliente_id_do_usuario()
    if cid is not None and item.cliente_id != cid:
        abort(403)
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
    _verificar_acesso_leitura(d)
    return render_template("detalhe_leitura.html", d=d)


@dashboard_bp.route("/leituras/<int:leitura_id>/imagem_placa")
@login_required
def imagem_placa(leitura_id):
    """Serve o crop da placa (JPEG binário) para exibição no detalhe do alerta."""
    d = Deteccao.query.get_or_404(leitura_id)
    _verificar_acesso_leitura(d)
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
    _verificar_acesso_leitura(d)
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
    viaturas = _aplicar_filtro_viatura(Viatura.query.filter_by(ativa=True), Viatura.viatura_id).all()
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

    q = _aplicar_filtro_viatura(
        Deteccao.query.filter(Deteccao.latitude.isnot(None), Deteccao.longitude.isnot(None)),
        Deteccao.viatura_id,
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
    cid = _cliente_id_do_usuario()
    q = Hotlist.query.filter_by(ativa=True)
    if cid is not None:
        q = q.filter_by(cliente_id=cid)
    placas = [h.placa for h in q.all()]
    return jsonify({"placas": placas, "total": len(placas)})


@dashboard_bp.route("/viaturas/<viatura_id>/config")
@login_required
def config_viatura(viatura_id):
    _equipment_admin_required()
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
    _equipment_admin_required()
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
    _equipment_admin_required()

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
    _equipment_admin_required()

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


# ──────────────────────────────────────────────────────────────────────────────
# Sprint 8.6 — Gestão de Clientes (superadmin)
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/admin/clientes", methods=["GET", "POST"])
@login_required
def admin_clientes():
    _superadmin_required()

    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "criar":
            nome = request.form.get("nome", "").strip()
            cnpj = request.form.get("cnpj_cpf", "").strip()
            contato = request.form.get("contato", "").strip()
            if nome and not Cliente.query.filter_by(nome=nome).first():
                db.session.add(Cliente(nome=nome, cnpj_cpf=cnpj, contato=contato))
                db.session.commit()
                flash(f"Cliente '{nome}' cadastrado.", "success")
            elif nome:
                flash("Já existe um cliente com esse nome.", "warning")
            return redirect(url_for("dashboard.admin_clientes"))

        elif acao == "editar":
            cliente_id = request.form.get("cliente_id")
            c = db.session.get(Cliente, cliente_id)
            if c:
                c.nome = request.form.get("nome", c.nome).strip() or c.nome
                c.cnpj_cpf = request.form.get("cnpj_cpf", c.cnpj_cpf).strip()
                c.contato = request.form.get("contato", c.contato).strip()
                db.session.commit()
                flash(f"Cliente '{c.nome}' atualizado.", "success")
            return redirect(url_for("dashboard.admin_clientes"))

        elif acao == "toggle":
            cliente_id = request.form.get("cliente_id")
            c = db.session.get(Cliente, cliente_id)
            if c:
                c.ativo = not c.ativo
                db.session.commit()
                flash(f"Cliente '{c.nome}' {'ativado' if c.ativo else 'desativado'}.", "info")
            return redirect(url_for("dashboard.admin_clientes"))

    clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template("clientes.html", clientes=clientes)


# ──────────────────────────────────────────────────────────────────────────────
# Sprint 8.7 — Gestão de Usuários
# ──────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/admin/usuarios", methods=["GET", "POST"])
@login_required
def admin_usuarios():
    _hotlist_admin_required()  # superadmin + admin_cliente

    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "criar":
            username = request.form.get("username", "").strip()
            senha = request.form.get("senha", "").strip()
            perfil = request.form.get("perfil", "operador_cliente").strip()
            try:
                cid_form = int(request.form.get("cliente_id")) if request.form.get("cliente_id") else None
            except (ValueError, TypeError):
                cid_form = None

            # admin_cliente só pode criar operador_cliente para o próprio cliente
            if current_user.is_admin_cliente():
                perfil = "operador_cliente"
                cid_form = current_user.get_cliente_id()

            perfis_validos = {"superadmin", "admin", "admin_cliente", "operador_cliente", "operador"}
            if not username or len(senha) < 8 or perfil not in perfis_validos:
                flash("Dados inválidos. Usuário requer nome + senha ≥8 chars + perfil válido.", "danger")
                return redirect(url_for("dashboard.admin_usuarios"))

            if Usuario.query.filter_by(username=username).first():
                flash(f"Usuário '{username}' já existe.", "warning")
                return redirect(url_for("dashboard.admin_usuarios"))

            u = Usuario(username=username, perfil=perfil, cliente_id=cid_form)
            u.set_password(senha)
            db.session.add(u)
            db.session.commit()
            flash(f"Usuário '{username}' criado.", "success")
            return redirect(url_for("dashboard.admin_usuarios"))

        elif acao == "remover":
            if not current_user.is_superadmin():
                abort(403)
            uid = request.form.get("usuario_id")
            u = db.session.get(Usuario, uid)
            if u and u.id != current_user.id:
                db.session.delete(u)
                db.session.commit()
                flash(f"Usuário '{u.username}' removido.", "warning")
            return redirect(url_for("dashboard.admin_usuarios"))

        elif acao == "senha":
            uid = request.form.get("usuario_id")
            nova_senha = request.form.get("nova_senha", "").strip()
            u = db.session.get(Usuario, uid)
            # admin_cliente só altera senha de usuários do próprio cliente
            if u and current_user.is_admin_cliente() and u.cliente_id != current_user.get_cliente_id():
                abort(403)
            if u and len(nova_senha) >= 8:
                u.set_password(nova_senha)
                db.session.commit()
                flash(f"Senha de '{u.username}' alterada.", "success")
            elif u:
                flash("Senha deve ter ao menos 8 caracteres.", "danger")
            return redirect(url_for("dashboard.admin_usuarios"))

    # Filtra usuários: superadmin vê todos; admin_cliente vê apenas usuários do próprio cliente
    if current_user.is_superadmin():
        usuarios = Usuario.query.order_by(Usuario.username).all()
        clientes = Cliente.query.filter_by(ativo=True).order_by(Cliente.nome).all()
    else:
        cid = current_user.get_cliente_id()
        usuarios = Usuario.query.filter_by(cliente_id=cid).order_by(Usuario.username).all()
        clientes = []

    return render_template("usuarios.html", usuarios=usuarios, clientes=clientes)


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
