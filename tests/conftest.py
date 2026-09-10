import os

import pytest

from app import create_app
from app.cli import bootstrap_admin
from app.config import Config
from app.extensions import db as _db
from app.models import Category, Team, User


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "test.db"

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECRET_KEY = "test-secret"
        ADMIN_USERNAME = "admin"
        ADMIN_EMAIL = "admin@example.com"
        ADMIN_PASSWORD = "adminpass"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SERVER_NAME = "localhost"

    flask_app = create_app(TestConfig)

    # Der instance_path zeigt sonst auf das echte instance/-Verzeichnis des
    # Projekts: Tests, die Anhänge anlegen oder aufräumen (siehe
    # tests/test_cli.py, tests/test_betrieb.py), würden dort echte Dateien
    # schreiben und löschen. Die Datenbank liegt über
    # SQLALCHEMY_DATABASE_URI bereits unter tmp_path, die Uploads folgen
    # hier nach.
    flask_app.instance_path = str(tmp_path / "instance")
    os.makedirs(flask_app.instance_path, exist_ok=True)

    # Setup/Teardown brauchen einen App-Context, aber er darf während der
    # eigentlichen Testausführung NICHT ambient bleiben: der Testclient
    # erkennt sonst pro Request einen bereits aktiven Context derselben
    # App und pusht keinen neuen - Flask-Logins Request-Cache (flask.g)
    # würde dann den zuerst geladenen Nutzer über mehrere Requests hinweg
    # behalten, selbst nach einem Identitätswechsel in der Test-Session.
    ctx = flask_app.app_context()
    ctx.push()
    _db.create_all()
    bootstrap_admin(flask_app)
    ctx.pop()

    yield flask_app

    ctx = flask_app.app_context()
    ctx.push()
    _db.session.remove()
    _db.drop_all()
    ctx.pop()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(app):
    with app.app_context():
        return User.query.filter_by(ist_admin=True).first()


def login_as(client, user_or_id):
    user_id = user_or_id.id if hasattr(user_or_id, "id") else user_or_id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


@pytest.fixture
def make_team(db):
    def _make_team(name="IT", ad_gruppe_agenten="grp-it-agenten", kategorien=("Drucker defekt",)):
        team = Team(name=name, ad_gruppe_agenten=ad_gruppe_agenten)
        db.session.add(team)
        db.session.flush()
        for kat_name in kategorien:
            db.session.add(Category(team_id=team.id, name=kat_name))
        db.session.commit()
        return team

    return _make_team


@pytest.fixture
def make_user(db):
    def _make_user(anzeigename="Test User", email="user@example.local", teams=None, ad_username="tuser"):
        user = User(
            ad_username=ad_username,
            anzeigename=anzeigename,
            email=email,
            aktiv=True,
        )
        if teams:
            user.teams = list(teams)
        db.session.add(user)
        db.session.commit()
        return user

    return _make_user
