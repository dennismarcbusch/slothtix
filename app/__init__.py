import os

from flask import Flask

from app.cli import bootstrap_admin, register_cli
from app.config import Config
from app.extensions import db, migrate


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
        instance_relative_config=True,
    )
    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    register_cli(app)

    from app import models  # noqa: F401  (Modelle für Migrationen registrieren)
    from app.routes import main_bp

    app.register_blueprint(main_bp)

    with app.app_context():
        bootstrap_admin(app)

    return app
