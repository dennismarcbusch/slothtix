"""Betriebsnahe Prüfungen: Fehlerseiten, SQLite-Einstellungen, Aufräumen."""

import os

from sqlalchemy import text

from app.extensions import db
from app.models import Attachment, Category, Team, Ticket, TicketPrioritaet, User

from tests.conftest import login_as


def test_sqlite_pragmas_sind_gesetzt(app):
    with app.app_context():
        verbindung = db.session.connection()
        assert verbindung.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert verbindung.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert verbindung.execute(text("PRAGMA busy_timeout")).scalar() == 15000


def test_fremdschluessel_werden_durchgesetzt(app):
    """Ohne PRAGMA foreign_keys=ON wären die ForeignKey-Constraints im
    Schema reine Dokumentation."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    with app.app_context():
        ticket = Ticket(
            titel="Verwaist",
            beschreibung="…",
            team_id=999999,
            category_id=999999,
            ersteller_id=999999,
            prioritaet=TicketPrioritaet.MITTEL,
        )
        db.session.add(ticket)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_404_nutzt_das_anwendungslayout(client):
    response = client.get("/gibt-es-nicht")
    assert response.status_code == 404
    text_ = response.get_data(as_text=True)
    assert "Diese Seite gibt es nicht" in text_
    assert "SlothTix" in text_


def test_403_nutzt_das_anwendungslayout(app, client, make_team, make_user):
    with app.app_context():
        make_team()
        login_as(client, make_user())

    response = client.get("/admin/teams")
    assert response.status_code == 403
    assert "fehlen dir die Rechte" in response.get_data(as_text=True)


def test_413_erklaert_das_upload_limit(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        team_id, kategorie_id = team.id, team.kategorien[0].id

    login_as(client, admin_user)
    zu_gross = b"\x89PNG\r\n\x1a\n" + b"0" * (app.config["MAX_CONTENT_LENGTH"] + 1024)
    response = client.post(
        "/tickets/neu",
        data={
            "titel": "Zu groß",
            "beschreibung": "Text",
            "team_id": str(team_id),
            "category_id": str(kategorie_id),
            "prioritaet": "mittel",
            "anhaenge": (__import__("io").BytesIO(zu_gross), "riesig.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert "Upload ist zu groß" in response.get_data(as_text=True)


def test_geloeschtes_ticket_raeumt_seine_anhaenge_von_der_platte(app, admin_user, make_team):
    """cascade='all, delete-orphan' entfernt nur die DB-Zeile - die Datei
    unter instance/uploads/ bliebe sonst für immer liegen."""
    with app.app_context():
        team = make_team()
        ticket = Ticket(
            titel="Mit Anhang",
            beschreibung="…",
            team_id=team.id,
            category_id=team.kategorien[0].id,
            ersteller_id=admin_user.id,
            prioritaet=TicketPrioritaet.MITTEL,
        )
        db.session.add(ticket)
        db.session.flush()

        verzeichnis = os.path.join(app.instance_path, "uploads", str(ticket.id))
        os.makedirs(verzeichnis, exist_ok=True)
        pfad = os.path.join(verzeichnis, "abc_bild.png")
        with open(pfad, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")

        db.session.add(
            Attachment(
                ticket_id=ticket.id,
                dateiname="bild.png",
                pfad=os.path.relpath(pfad, app.instance_path),
                groesse_bytes=8,
                mime_type="image/png",
                hochgeladen_von_id=admin_user.id,
            )
        )
        db.session.commit()
        assert os.path.exists(pfad)

        db.session.delete(ticket)
        db.session.commit()

        assert not os.path.exists(pfad)


def test_rollback_laesst_die_datei_liegen(app, admin_user, make_team):
    """Gegenprobe: Bei einem Rollback bleibt die Attachment-Zeile bestehen,
    die Datei darf dann nicht gelöscht sein."""
    with app.app_context():
        team = make_team()
        ticket = Ticket(
            titel="Mit Anhang",
            beschreibung="…",
            team_id=team.id,
            category_id=team.kategorien[0].id,
            ersteller_id=admin_user.id,
            prioritaet=TicketPrioritaet.MITTEL,
        )
        db.session.add(ticket)
        db.session.flush()

        verzeichnis = os.path.join(app.instance_path, "uploads", str(ticket.id))
        os.makedirs(verzeichnis, exist_ok=True)
        pfad = os.path.join(verzeichnis, "abc_bild.png")
        with open(pfad, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")

        db.session.add(
            Attachment(
                ticket_id=ticket.id,
                dateiname="bild.png",
                pfad=os.path.relpath(pfad, app.instance_path),
                groesse_bytes=8,
                mime_type="image/png",
                hochgeladen_von_id=admin_user.id,
            )
        )
        db.session.commit()

        db.session.delete(ticket)
        db.session.flush()
        db.session.rollback()

        assert os.path.exists(pfad)
