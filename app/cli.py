import click
from sqlalchemy.exc import OperationalError
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import User


def bootstrap_admin(app):
    """Legt den initialen Admin-User aus den ADMIN_*-Env-Vars an,
    falls noch kein Admin existiert. Wird auch beim App-Start ausgeführt,
    daher robust gegen eine noch nicht migrierte Datenbank (z. B. während
    `flask db init`/`migrate`, bevor die User-Tabelle existiert)."""
    with app.app_context():
        try:
            admin_exists = User.query.filter_by(ist_admin=True).first() is not None
        except OperationalError:
            return
        if admin_exists:
            return

        username = app.config.get("ADMIN_USERNAME")
        email = app.config.get("ADMIN_EMAIL")
        password = app.config.get("ADMIN_PASSWORD")
        if not (username and email and password):
            return

        admin = User(
            anzeigename=username,
            email=email,
            ist_admin=True,
            aktiv=True,
            passwort_hash=generate_password_hash(password),
        )
        db.session.add(admin)
        db.session.commit()
        app.logger.info("Admin-User %r wurde angelegt.", username)


def register_cli(app):
    @app.cli.command("create-admin")
    def create_admin_command():
        """Legt den initialen Admin-User aus den ADMIN_*-Env-Vars an."""
        if User.query.filter_by(ist_admin=True).first() is not None:
            click.echo("Es existiert bereits ein Admin-User.")
            return

        username = app.config.get("ADMIN_USERNAME")
        email = app.config.get("ADMIN_EMAIL")
        password = app.config.get("ADMIN_PASSWORD")
        if not (username and email and password):
            click.echo(
                "ADMIN_USERNAME, ADMIN_EMAIL und ADMIN_PASSWORD müssen "
                "gesetzt sein."
            )
            return

        admin = User(
            anzeigename=username,
            email=email,
            ist_admin=True,
            aktiv=True,
            passwort_hash=generate_password_hash(password),
        )
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Admin-User {username!r} wurde angelegt.")
