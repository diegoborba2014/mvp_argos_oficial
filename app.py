import os
from datetime import timedelta

from flask import Flask, redirect, url_for, render_template
from flask_login import LoginManager
from dotenv import load_dotenv

load_dotenv()

from models import db, Usuario


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "argos-qg-secret-2026")
    app.config["QG_API_KEY"] = os.getenv("QG_API_KEY", "argos-secret-2026")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///argos_qg.db")
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

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(f"Erro 500: {e}")
        return render_template("errors/500.html"), 500

    with app.app_context():
        db.create_all()
        _migrar_schema()
        _seed_usuarios()

    return app


def _migrar_schema():
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE viaturas ADD COLUMN hotlist_mode VARCHAR(16) DEFAULT 'hibrido'",
    ]
    with db.engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass


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


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
