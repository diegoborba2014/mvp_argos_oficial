from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import Usuario
from extensions import limiter

auth_bp = Blueprint("auth", __name__)


def _redirect_seguro(next_url: str | None) -> str:
    """S-5: valida parâmetro 'next' para evitar Open Redirect.
    Aceita apenas URLs relativas que começam com '/' e não com '//'.
    Qualquer outra coisa (http://evil.com, //evil.com, javascript:) é descartada.
    """
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return url_for("dashboard.index")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", exempt_when=lambda: request.method != "POST")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        senha = request.form.get("senha", "")
        usuario = Usuario.query.filter_by(username=username).first()

        if usuario and usuario.check_password(senha):
            login_user(usuario, remember=True)
            return redirect(_redirect_seguro(request.args.get("next")))

        flash("Usuário ou senha inválidos.", "danger")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    # S-11: logout via POST — evita que links externos façam logout via GET
    logout_user()
    return redirect(url_for("auth.login"))
