import functools

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf import FlaskForm
from werkzeug.security import check_password_hash
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired

from app.extensions import db
from app.ldap_service import LdapAuthError
from app.ldap_service import authenticate as ldap_authenticate
from app.models import Settings, Team, User, utcnow

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Bitte melde dich an, um fortzufahren."

auth_bp = Blueprint("auth", __name__)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class LoginForm(FlaskForm):
    username = StringField("Benutzername", validators=[DataRequired()])
    password = PasswordField("Passwort", validators=[DataRequired()])


def sync_user_from_ldap(username, ldap_user, settings):
    """JIT-Sync: legt den Nutzer bei Bedarf an/aktualisiert ihn und prüft,
    ob er Zugriff hat (Mitglied der User-Gruppe oder einer
    Team-Agenten-Gruppe). Gibt den synchronisierten User zurück, oder
    None, wenn keine der konfigurierten Gruppen zutrifft (kein Zugriff)."""
    ist_user = bool(settings.ad_gruppe_user) and settings.ad_gruppe_user in ldap_user.gruppen
    agent_teams = [
        team
        for team in Team.query.filter_by(aktiv=True).all()
        if team.ad_gruppe_agenten and team.ad_gruppe_agenten in ldap_user.gruppen
    ]

    if not ist_user and not agent_teams:
        return None

    user = User.query.filter_by(ad_username=username).first()
    if user is None:
        user = User(ad_username=username)
        db.session.add(user)

    user.anzeigename = ldap_user.anzeigename or username
    user.email = ldap_user.email
    user.aktiv = True
    user.teams = agent_teams
    user.letzter_login_am = utcnow()
    db.session.commit()
    return user


def _authenticate_local_admin(username, password):
    """Lokaler Admin-Account: einziger User mit ad_username=NULL, meldet
    sich mit Passwort statt LDAP-Bind an (siehe REQUIREMENTS.md 3.1)."""
    admin = User.query.filter_by(ad_username=None, anzeigename=username).first()
    if admin is None or not admin.passwort_hash:
        return None
    if not check_password_hash(admin.passwort_hash, password):
        return None
    return admin


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data

        user = _authenticate_local_admin(username, password)

        if user is None:
            settings = Settings.get_or_create()
            try:
                ldap_user = ldap_authenticate(
                    settings,
                    current_app.config.get("LDAP_BIND_PASSWORD"),
                    username,
                    password,
                )
            except LdapAuthError as exc:
                current_app.logger.info("Login fehlgeschlagen für %r: %s", username, exc)
                flash("Benutzername oder Passwort falsch.", "error")
                return render_template("login.html", form=form)

            user = sync_user_from_ldap(username, ldap_user, settings)
            if user is None:
                flash(
                    "Anmeldung erfolgreich, aber kein Zugriff auf SlothTix "
                    "(keine berechtigte Gruppenmitgliedschaft).",
                    "error",
                )
                return render_template("login.html", form=form)

        if not user.aktiv:
            flash("Dieses Konto ist deaktiviert.", "error")
            return render_template("login.html", form=form)

        user.letzter_login_am = utcnow()
        db.session.commit()
        login_user(user)
        next_url = request.args.get("next")
        return redirect(next_url or url_for("main.index"))

    return render_template("login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


def admin_required(view):
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.ist_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def agent_required(view):
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not (current_user.ist_admin or current_user.ist_agent):
            abort(403)
        return view(*args, **kwargs)

    return wrapped
