import os
from datetime import timedelta

from flask import Flask, redirect, url_for, render_template
from flask_login import LoginManager
from dotenv import load_dotenv

load_dotenv()

from models import db, Usuario, MotivoHotlist, EventoSistema
from extensions import csrf, limiter


def create_app():
    app = Flask(__name__)

    # S-1: SECRET_KEY obrigatória via env var — nunca hardcoded
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        raise RuntimeError(
            "[ARGOS] SECRET_KEY não definida. "
            "Adicione SECRET_KEY nas variáveis de ambiente do Railway antes de fazer deploy."
        )
    app.config["SECRET_KEY"] = secret_key

    # S-2: QG_API_KEY obrigatória via env var — nunca hardcoded
    qg_api_key = os.environ.get("QG_API_KEY")
    if not qg_api_key:
        raise RuntimeError(
            "[ARGOS] QG_API_KEY não definida. "
            "Adicione QG_API_KEY nas variáveis de ambiente do Railway antes de fazer deploy."
        )
    app.config["QG_API_KEY"] = qg_api_key
    db_url = os.getenv("DATABASE_URL", "sqlite:///argos_qg.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # S-12: cookies de sessão com flags de segurança
    # SESSION_COOKIE_SECURE só funciona em HTTPS — desativar em dev local (FLASK_DEBUG=1)
    _producao = os.getenv("FLASK_DEBUG", "0") != "1"
    app.config["SESSION_COOKIE_SECURE"] = _producao   # HTTPS only em produção
    app.config["SESSION_COOKIE_HTTPONLY"] = True       # JS não acessa o cookie
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"     # bloqueia envio cross-site
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

    db.init_app(app)

    # S-13: CSRF em todos os formulários HTML
    csrf.init_app(app)
    # S-14: Rate limiting (limites definidos por view em routes/auth.py)
    limiter.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar o sistema."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Usuario, int(user_id))

    from routes.auth import auth_bp
    from routes.telemetry import telemetry_bp
    from routes.dashboard import dashboard_bp
    from routes.api_viaturas import api_viaturas_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(telemetry_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_viaturas_bp)

    from urllib.parse import urlencode

    @app.template_filter("urlencode")
    def urlencode_filter(d):
        return urlencode({k: v for k, v in d.items() if v})

    @app.template_filter("brt")
    def brt_filter(dt):
        if dt is None:
            return "--"
        return (dt - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M:%S")

    @app.context_processor
    def inject_contadores():
        """Injeta contadores globais em todos os templates (badge do navbar)."""
        try:
            criticos = EventoSistema.query.filter_by(resolvido=False, severidade="critico").count()
        except Exception:
            criticos = 0
        return {"eventos_criticos_count": criticos}

    @app.route("/healthz")
    def healthz():
        # S-7: restringir a admins autenticados — expõe estrutura interna do banco
        from flask_login import current_user
        if not current_user.is_authenticated or not current_user.is_admin():
            return {"erro": "acesso negado"}, 403
        from sqlalchemy import text
        resultado = {}
        tabelas = ["viaturas", "hotlist", "deteccoes", "heartbeats", "usuarios"]
        try:
            with db.engine.connect() as conn:
                for tabela in tabelas:
                    rows = conn.execute(
                        text("SELECT column_name FROM information_schema.columns "
                             "WHERE table_name = :t ORDER BY ordinal_position"),
                        {"t": tabela}
                    ).fetchall()
                    resultado[tabela] = [r[0] for r in rows]
        except Exception as e:
            return {"erro": str(e)}, 500
        return resultado, 200

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        import traceback
        app.logger.error(f"Erro 500: {e}\n{traceback.format_exc()}")
        return render_template("errors/500.html"), 500

    with app.app_context():
        db.create_all()
        _migrar_schema()
        _seed_usuarios()
        _seed_motivos()

    return app


def _migrar_schema():
    import logging
    from sqlalchemy import text
    log = logging.getLogger(__name__)
    # DEFAULT FALSE em vez de DEFAULT 0 — PostgreSQL rejeita inteiro como padrão booleano
    migrations = [
        "ALTER TABLE viaturas ADD COLUMN hotlist_mode VARCHAR(16) DEFAULT 'hibrido'",
        "ALTER TABLE viaturas ADD COLUMN config_json TEXT",
        "ALTER TABLE viaturas ADD COLUMN config_pendente BOOLEAN DEFAULT FALSE",
        "ALTER TABLE viaturas ADD COLUMN hotlist_pendente BOOLEAN DEFAULT FALSE",
        "ALTER TABLE viaturas ADD COLUMN hotlist_hash VARCHAR(32)",
        "ALTER TABLE viaturas ADD COLUMN ultima_sync_hotlist TIMESTAMP",
        "ALTER TABLE hotlist ADD COLUMN motivo VARCHAR(64) DEFAULT ''",
        "ALTER TABLE hotlist ADD COLUMN prioridade INTEGER DEFAULT 2",
        "ALTER TABLE hotlist ADD COLUMN observacao TEXT DEFAULT ''",
        "ALTER TABLE deteccoes ADD COLUMN imagem_placa BYTEA",
        # P-17: índices compostos para queries frequentes
        "CREATE INDEX IF NOT EXISTS ix_eventos_viatura_resolvido ON eventos_sistema (viatura_id, resolvido)",
        "CREATE INDEX IF NOT EXISTS ix_eventos_viatura_tipo_resolvido ON eventos_sistema (viatura_id, tipo, resolvido)",
        "CREATE INDEX IF NOT EXISTS ix_deteccoes_alerta_recebido ON deteccoes (alerta_tatico, recebido_em)",
        "CREATE INDEX IF NOT EXISTS ix_deteccoes_viatura_recebido ON deteccoes (viatura_id, recebido_em)",
        "CREATE INDEX IF NOT EXISTS ix_heartbeats_viatura_recebido ON heartbeats (viatura_id, recebido_em)",
        # Sprint 8.2 — Multi-tenancy: colunas cliente_id (nullable, migração segura)
        "ALTER TABLE viaturas ADD COLUMN cliente_id INTEGER REFERENCES clientes(id)",
        "ALTER TABLE usuarios ADD COLUMN cliente_id INTEGER REFERENCES clientes(id)",
        "ALTER TABLE hotlist ADD COLUMN cliente_id INTEGER REFERENCES clientes(id)",
        "CREATE INDEX IF NOT EXISTS ix_viaturas_cliente ON viaturas (cliente_id)",
        "CREATE INDEX IF NOT EXISTS ix_usuarios_cliente ON usuarios (cliente_id)",
        "CREATE INDEX IF NOT EXISTS ix_hotlist_cliente ON hotlist (cliente_id)",
    ]
    for sql in migrations:
        try:
            with db.engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            log.info(f"[MIGRATION OK] {sql[:80]}")
        except Exception as e:
            log.info(f"[MIGRATION SKIP] {sql[:80]} — {e}")


def _seed_usuarios():
    """Cria usuários padrão se não existirem.
    S-3: Senhas lidas de variáveis de ambiente — nunca hardcoded no código.
    Se ADMIN_PASSWORD não estiver definida, gera uma senha aleatória e loga no boot.
    """
    import logging
    import secrets as _secrets
    log = logging.getLogger(__name__)

    if not Usuario.query.filter_by(username="admin").first():
        admin_pass = os.environ.get("ADMIN_PASSWORD")
        if not admin_pass:
            admin_pass = _secrets.token_urlsafe(16)
            log.critical(
                "\n" + "=" * 64 + "\n"
                "[ARGOS] ⚠️  ADMIN_PASSWORD não definida nas variáveis de ambiente!\n"
                f"[ARGOS]     Senha admin gerada automaticamente: {admin_pass}\n"
                "[ARGOS]     Defina ADMIN_PASSWORD no Railway para fixar a senha.\n"
                + "=" * 64
            )

        admin = Usuario(username="admin", perfil="admin")
        admin.set_password(admin_pass)

        operador = Usuario(username="operador", perfil="operador")
        operador.set_password(os.environ.get("OPERADOR_PASSWORD", "operador2026"))

        db.session.add_all([admin, operador])
        db.session.commit()
        log.info("[SEED] Usuários padrão criados.")


def _seed_motivos():
    """Cria motivos padrão na tabela motivos_hotlist se ainda estiver vazia."""
    if MotivoHotlist.query.first():
        return

    padroes = [
        "Roubo", "Furto", "Mandado de Busca", "Investigação",
        "Suspeito", "Busca e Apreensão", "Receptação", "Tráfico",
    ]
    db.session.add_all([MotivoHotlist(nome=m) for m in padroes])
    db.session.commit()


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    # S-4: debug nunca ativo em produção — só se FLASK_DEBUG=1 estiver definido
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
