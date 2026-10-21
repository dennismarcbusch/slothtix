"""Die Alembic-Migrationen gegen eine Datenbank mit verknüpften Daten.

Alle übrigen Tests legen das Schema per create_all() aus den Modellen an
und sehen die Migrationen nie. So ist v1.5 mit einer Migration
ausgeliefert worden, die auf einer leeren Datenbank lief, im Betrieb aber
an den Fremdschlüsseln auf "user" scheiterte - der App-Container kam
danach nicht mehr hoch.
"""

import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app import create_app
from app.config import Config
from app.extensions import db

MIGRATIONS = os.path.join(os.path.dirname(__file__), os.pardir, "migrations")
ERSTE_REVISION = "7b05cfae232c"


@pytest.fixture
def leere_app(tmp_path, monkeypatch):
    # migrations/env.py ruft fileConfig() auf und würde damit die Logger
    # der übrigen Tests abschalten.
    monkeypatch.setattr("logging.config.fileConfig", lambda *a, **k: None)

    class MigrationsConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'migration.db'}"
        ADMIN_USERNAME = None

    app = create_app(MigrationsConfig)
    with app.app_context():
        yield app
        db.session.remove()
        db.engine.dispose()


def _altbestand_anlegen():
    """Daten im Schema der ersten Revision, so verknüpft wie im Betrieb:
    Team-Mitgliedschaft, Ticket mit Ersteller und Zuweisung, Kommentar,
    Historie und Anhang verweisen alle auf "user"."""
    for sql in (
        "INSERT INTO team (id, name, aktiv) VALUES (1, 'IT', 1)",
        "INSERT INTO category (id, team_id, name, aktiv) VALUES (1, 1, 'Drucker', 1)",
        "INSERT INTO user (id, anzeigename, email, ist_admin, aktiv, erstellt_am) "
        "VALUES (1, 'Agentin', 'agentin@x', 0, 1, '2026-09-01 08:00:00')",
        "INSERT INTO user (id, anzeigename, email, ist_admin, aktiv, erstellt_am) "
        "VALUES (2, 'Lehrer', 'lehrer@x', 0, 1, '2026-09-01 08:00:00')",
        "INSERT INTO team_memberships (user_id, team_id) VALUES (1, 1)",
        "INSERT INTO ticket (id, titel, beschreibung, team_id, category_id, ersteller_id, "
        "zugewiesen_an_id, status, prioritaet, erstellt_am, aktualisiert_am) "
        "VALUES (1, 'Drucker', 'Geht nicht', 1, 1, 2, 1, 'GELOEST', 'HOCH', "
        "'2026-09-02 08:00:00', '2026-09-03 08:00:00')",
        "INSERT INTO comment (id, ticket_id, autor_id, text, sichtbarkeit, erstellt_am) "
        "VALUES (1, 1, 2, 'Danke', 'OEFFENTLICH', '2026-09-03 09:00:00')",
        "INSERT INTO ticket_history (id, ticket_id, aktion, alter_wert, neuer_wert, "
        "ausgefuehrt_von_id, zeitstempel) "
        "VALUES (1, 1, 'STATUS_GEAENDERT', 'offen', 'geloest', 1, '2026-09-03 08:00:00')",
        "INSERT INTO attachment (id, ticket_id, dateiname, pfad, groesse_bytes, mime_type, "
        "hochgeladen_von_id, erstellt_am) "
        "VALUES (1, 1, 'foto.png', 'uploads/1/foto.png', 10, 'image/png', 2, '2026-09-02 08:00:00')",
    ):
        db.session.execute(text(sql))
    db.session.commit()


def _pruefe_altbestand():
    zaehlen = lambda tabelle: db.session.execute(text(f"SELECT COUNT(*) FROM {tabelle}")).scalar()  # noqa: E731
    assert zaehlen("user") == 2
    assert zaehlen("team_memberships") == 1
    assert zaehlen("ticket") == 1
    assert zaehlen("comment") == 1
    assert zaehlen("ticket_history") == 1
    assert zaehlen("attachment") == 1
    assert db.session.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    tabellen = db.session.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).scalars()
    assert not [name for name in tabellen if name.startswith("_alembic_tmp")]


def _schema_abweichungen():
    with db.engine.connect() as verbindung:
        return compare_metadata(MigrationContext.configure(verbindung), db.metadata)


def test_migrationen_mit_verknuepften_daten(leere_app):
    upgrade(directory=MIGRATIONS, revision=ERSTE_REVISION)
    # Wie im Betrieb: Die App setzt foreign_keys=ON für jede Verbindung.
    assert db.session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    _altbestand_anlegen()

    upgrade(directory=MIGRATIONS)
    _pruefe_altbestand()
    assert _schema_abweichungen() == []

    # Zurück bis zur ersten Revision und wieder hoch - auch ein Rollback
    # nach einem missglückten Update darf die Daten nicht verlieren.
    downgrade(directory=MIGRATIONS, revision=ERSTE_REVISION)
    _pruefe_altbestand()
    upgrade(directory=MIGRATIONS)
    _pruefe_altbestand()
