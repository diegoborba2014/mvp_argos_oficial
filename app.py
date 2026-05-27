import os
from datetime import timedelta

from flask import Flask, redirect, url_for, render_template
from flask_login import LoginManager
from dotenv import load_dotenv

load_dotenv()

from models import db, Usuario, MotivoHotlist, EventoSistema


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "argos-qg-secret-2026")
    app.config["QG_API_KEY"] = os.getenv("QG_API_KEY", "argos-secret-2026")
    db_url = os.getenv("DATABASE_URL", "sqlite:///argos_qg.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar o sistema."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return Usuario.query.get(int(user_id))

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
    """Cria usuários padrão se não existirem."""
    if Usuario.query.filter_by(username="admin").first():
        return

    admin = Usuario(username="admin", perfil="admin")
    admin.set_password("argos2026")

    operador = Usuario(username="operador", perfil="operador")
    operador.set_password("operador2026")

    db.session.add_all([admin, operador])
    db.session.commit()


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
    app.run(host="0.0.0.0", port=port, debug=True)
