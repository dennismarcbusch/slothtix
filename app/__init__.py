import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.cli import bootstrap_admin, register_cli
from app.config import Config
from app.extensions import csrf, db, migrate


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
        instance_relative_config=True,
    )
    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)

    # Vertraut X-Forwarded-For/-Proto/-Host von genau einem vorgeschalteten
    # Reverse-Proxy (Caddy in docker-compose.yml) - dadurch erkennt Flask
    # HTTPS-Requests korrekt (wichtig fürs Secure-Cookie und für
    # url_for(..., _external=True) in den Benachrichtigungs-Mails). Sicher,
    # weil die App im Compose-Setup nur noch über den Proxy erreichbar ist,
    # nicht mehr direkt vom Host aus.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
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
