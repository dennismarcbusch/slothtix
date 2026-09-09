from flask import Blueprint, redirect, url_for
from flask_login import current_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("tickets.list_view"))
    return redirect(url_for("auth.login"))


@main_bp.route("/favicon.ico")
def favicon():
    # Browser fragen diesen Pfad oft direkt ab, unabhängig vom
    # <link rel="icon"> im <head>.
    return redirect(url_for("static", filename="favicon.ico"))
