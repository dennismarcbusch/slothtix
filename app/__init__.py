import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.cli import bootstrap_admin, register_cli
from app.config import UNSICHERE_SECRET_KEYS, Config
from app.database import registriere_sqlite_pragmas
from app.errors import registriere_fehlerseiten
from app.extensions import csrf, db, migrate
from app.security import registriere_security_header


def _pruefe_secret_key(app):
    """Verhindert den Start mit fehlendem oder allgemein bekanntem
    SECRET_KEY.

    Ein Fallback-Default wäre hier gefährlich bequem: Die App liefe
    unauffällig weiter, obwohl jeder mit Kenntnis des Schlüssels ein
    gültiges Session-Cookie (z. B. für die Admin-ID) signieren könnte.
    Im Debug-/Testbetrieb ist ein fester Entwicklungsschlüssel dagegen
    unkritisch und praktisch, deshalb wird dort nur gewarnt."""
    key = app.config.get("SECRET_KEY")
    if key and key not in UNSICHERE_SECRET_KEYS:
        return

    if app.debug or app.testing:
        app.config["SECRET_KEY"] = key or "dev-secret-key-change-me"
        app.logger.warning(
            "Es wird ein unsicherer Entwicklungs-SECRET_KEY verwendet - "
            "nur im Debug-/Testbetrieb zulässig."
        )
        return

    raise RuntimeError(
        "SECRET_KEY ist nicht oder nur mit einem Platzhalterwert gesetzt. "
        "Einen zufälligen Wert erzeugen (z. B. 'openssl rand -hex 32') und "
        "in der .env unter SECRET_KEY eintragen."
    )


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
        instance_relative_config=True,
    )
    app.config.from_object(config_class)
    _pruefe_secret_key(app)
    os.makedirs(app.instance_path, exist_ok=True)

    # Vertraut X-Forwarded-For/-Proto/-Host von genau einem vorgeschalteten
    # Reverse-Proxy (Caddy in docker-compose.yml) - dadurch erkennt Flask
    # HTTPS-Requests korrekt (wichtig fürs Secure-Cookie und für
    # url_for(..., _external=True) in den Benachrichtigungs-Mails). Sicher,
    # weil die App im Compose-Setup nur noch über den Proxy erreichbar ist,
    # nicht mehr direkt vom Host aus.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    registriere_sqlite_pragmas(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    registriere_security_header(app)
    registriere_fehlerseiten(app)
    register_cli(app)

    from app import models  # noqa: F401  (Modelle für Migrationen registrieren)
    from app.admin import admin_bp
    from app.auth import auth_bp, login_manager
    from app.routes import main_bp
    from app.tickets import tickets_bp

    login_manager.init_app(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        bootstrap_admin(app)

    return app
