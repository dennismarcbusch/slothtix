import functools
from datetime import datetime
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
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

from app import login_throttle
from app.ad_abgleich import ermittle_berechtigung
from app.extensions import db
from app.ldap_service import LdapAuthError
from app.ldap_service import authenticate as ldap_authenticate
from app.models import Settings, Team, User, utcnow

# Zeitpunkt der Anmeldung, als ISO-String in der Session. Grundlage für die
# absolute Sitzungsdauer (Config.SESSION_MAX_ALTER).
ANGEMELDET_SEIT = "angemeldet_seit"

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
    ist_user, agent_teams = ermittle_berechtigung(
        ldap_user.gruppen, settings, Team.query.filter_by(aktiv=True).all()
    )

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


@auth_bp.before_app_request
def sitzung_ablaufen_lassen():
    """Beendet Sitzungen, die älter als Config.SESSION_MAX_ALTER sind.

    Flask allein liefert das nicht: PERMANENT_SESSION_LIFETIME wird bei
    jedem Request neu aufgeschoben (SESSION_REFRESH_EACH_REQUEST), womit
    eine dauerhaft geöffnete Registerkarte die Anmeldung endlos am Leben
    hielte. Der Zeitstempel in der Session macht die Grenze absolut."""
    # Statische Dateien überspringen: current_user auszuwerten lädt den
    # Nutzer aus der Datenbank, und eine Seite zieht ein halbes Dutzend
    # CSS-/Icon-Anfragen nach sich.
    if request.endpoint == "static":
        return

    if not current_user.is_authenticated:
        return

    seit = session.get(ANGEMELDET_SEIT)
    if seit is None:
        # Sitzung aus der Zeit vor dieser Prüfung (oder von Hand gesetzt):
        # ab jetzt mitzählen, statt sie sofort zu beenden.
        session[ANGEMELDET_SEIT] = utcnow().isoformat()
        return

    try:
        angemeldet_seit = datetime.fromisoformat(seit)
    except ValueError:
        angemeldet_seit = None

    if angemeldet_seit is None or utcnow() - angemeldet_seit > current_app.config["SESSION_MAX_ALTER"]:
        logout_user()
        flash("Die Sitzung ist abgelaufen. Bitte melde dich erneut an.", "error")
        return redirect(url_for("auth.login"))


def _ist_sicheres_ziel(ziel):
    """Prüft, ob `ziel` ein anwendungsinterner Pfad ist.

    Der ?next=-Parameter kommt von Flask-Login (Weiterleitung auf die
    ursprünglich angeforderte Seite) und ist damit vom Aufrufer frei
    wählbar. Ohne diese Prüfung wäre ein Link auf die echte SlothTix-
    Domain nach erfolgreichem Login auf eine beliebige fremde Seite
    umleitbar (Open Redirect -> Phishing).

    Abgelehnt wird deshalb alles, was nicht eindeutig ein relativer Pfad
    ist: absolute URLs (http://evil.example), protokollrelative URLs
    (//evil.example) und Backslash-Varianten, die manche Browser wie
    Schrägstriche behandeln."""
    if not ziel or not ziel.startswith("/") or ziel.startswith(("//", "/\\")):
        return False
    zerlegt = urlparse(ziel)
    return not zerlegt.scheme and not zerlegt.netloc


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
        ip = request.remote_addr

        if login_throttle.ist_gesperrt(username, ip):
            current_app.logger.warning(
                "Login für %r von %s wegen zu vieler Fehlversuche abgewiesen.", username, ip
            )
            flash(
                "Zu viele fehlgeschlagene Anmeldeversuche. Bitte in einigen "
                "Minuten erneut versuchen.",
                "error",
            )
            return render_template("login.html", form=form), 429

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
                login_throttle.merke_fehlversuch(username, ip)
                current_app.logger.info(
                    "Login fehlgeschlagen für %r von %s: %s", username, ip, exc
                )
                flash("Benutzername oder Passwort falsch.", "error")
                return render_template("login.html", form=form)

            # Kein Fehlversuch: Die Zugangsdaten waren korrekt, es fehlt
            # nur die Gruppenmitgliedschaft. Das ist kein Rateversuch und
            # darf das Konto deshalb nicht in die Sperre laufen lassen.
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

        login_throttle.loesche_fehlversuche(username)
        user.letzter_login_am = utcnow()
        db.session.commit()
        login_user(user)
        # permanent=True aktiviert das Ablaufdatum am Cookie; der
        # Zeitstempel trägt zusätzlich die absolute Grenze (siehe
        # sitzung_ablaufen_lassen).
        session.permanent = True
        session[ANGEMELDET_SEIT] = utcnow().isoformat()
        next_url = request.args.get("next")
        if not _ist_sicheres_ziel(next_url):
            next_url = None
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
