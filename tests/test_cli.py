"""Tests für die Flask-CLI-Kommandos, insbesondere das Aufräumen der
Testdaten vor dem Produktivstart (`flask tickets-purge`)."""

import os
from datetime import datetime

from app.extensions import db
from app.models import (
    Attachment,
    Category,
    Comment,
    Sichtbarkeit,
    Team,
    Ticket,
    TicketHistory,
    TicketPrioritaet,
    HistorienAktion,
    User,
)


def _ticket(team, ersteller, titel="Testticket", erstellt_am=None):
    ticket = Ticket(
        titel=titel,
        beschreibung="Beschreibung",
        team_id=team.id,
        category_id=team.kategorien[0].id,
        ersteller_id=ersteller.id,
        prioritaet=TicketPrioritaet.MITTEL,
    )
    if erstellt_am is not None:
        ticket.erstellt_am = erstellt_am
    db.session.add(ticket)
    db.session.commit()
    return ticket


def _anhang(app, ticket, ersteller, dateiname="bild.png", comment=None):
    verzeichnis = os.path.join(app.instance_path, "uploads", str(ticket.id))
    os.makedirs(verzeichnis, exist_ok=True)
    pfad = os.path.join(verzeichnis, f"abc_{dateiname}")
    with open(pfad, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")

    db.session.add(
        Attachment(
            ticket_id=None if comment else ticket.id,
            comment_id=comment.id if comment else None,
            dateiname=dateiname,
            pfad=os.path.relpath(pfad, app.instance_path),
            groesse_bytes=8,
            mime_type="image/png",
            hochgeladen_von_id=ersteller.id,
        )
    )
    db.session.commit()
    return pfad


def test_probelauf_loescht_nichts(app, admin_user, make_team):
    with app.app_context():
        team = make_team()
        _ticket(team, admin_user)

        ergebnis = app.test_cli_runner().invoke(args=["tickets-purge", "--alle"])

        assert ergebnis.exit_code == 0
        assert "Probelauf" in ergebnis.output
        assert "Tickets:     1" in ergebnis.output
        assert Ticket.query.count() == 1


def test_alle_loescht_tickets_samt_anhaengen(app, admin_user, make_team):
    with app.app_context():
        team = make_team()
        ticket = _ticket(team, admin_user)
        kommentar = Comment(
            ticket_id=ticket.id,
            autor_id=admin_user.id,
            text="Ein Kommentar",
            sichtbarkeit=Sichtbarkeit.OEFFENTLICH,
        )
        db.session.add(kommentar)
        db.session.add(
            TicketHistory(
                ticket_id=ticket.id,
                aktion=HistorienAktion.ZUGEWIESEN,
                alter_wert=None,
                neuer_wert="admin",
                ausgefuehrt_von_id=admin_user.id,
            )
        )
        db.session.commit()

        ticket_datei = _anhang(app, ticket, admin_user)
        kommentar_datei = _anhang(
            app, ticket, admin_user, dateiname="intern.png", comment=kommentar
        )

        ergebnis = app.test_cli_runner().invoke(args=["tickets-purge", "--alle", "--ja"])

        assert ergebnis.exit_code == 0
        assert Ticket.query.count() == 0
        assert Comment.query.count() == 0
        assert TicketHistory.query.count() == 0
        assert Attachment.query.count() == 0
        assert not os.path.exists(ticket_datei)
        assert not os.path.exists(kommentar_datei)
        # Der jetzt leere uploads/<ticket_id>-Ordner bleibt sonst stehen.
        assert not os.path.exists(os.path.dirname(ticket_datei))


def test_stammdaten_bleiben_erhalten(app, admin_user, make_team):
    """Der Zweck des Kommandos: Testtickets weg, Konfiguration bleibt."""
    with app.app_context():
        team = make_team()
        _ticket(team, admin_user)

        app.test_cli_runner().invoke(args=["tickets-purge", "--alle", "--ja"])

        assert Team.query.count() == 1
        assert Category.query.count() == 1
        assert User.query.count() == 1


def test_vor_datum_loescht_nur_aeltere_tickets(app, admin_user, make_team):
    with app.app_context():
        team = make_team()
        alt = _ticket(team, admin_user, titel="Alt", erstellt_am=datetime(2026, 1, 1))
        neu = _ticket(team, admin_user, titel="Neu", erstellt_am=datetime(2026, 6, 1))

        ergebnis = app.test_cli_runner().invoke(
            args=["tickets-purge", "--vor", "2026-03-01", "--ja"]
        )

        assert ergebnis.exit_code == 0
        verbleibend = Ticket.query.all()
        assert [t.titel for t in verbleibend] == ["Neu"]
        assert neu.id in {t.id for t in verbleibend}
        assert alt.id not in {t.id for t in verbleibend}


def test_verwaiste_dateien_werden_entfernt(app, admin_user, make_team):
    """Altlasten aus früheren Resets: Datei auf der Platte, aber keine
    Attachment-Zeile mehr."""
    with app.app_context():
        team = make_team()
        ticket = _ticket(team, admin_user)
        referenziert = _anhang(app, ticket, admin_user)

        verwaist = os.path.join(
            app.instance_path, "uploads", "999", "xyz_altlast.png"
        )
        os.makedirs(os.path.dirname(verwaist), exist_ok=True)
        with open(verwaist, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")

        ergebnis = app.test_cli_runner().invoke(
            args=["tickets-purge", "--verwaiste-dateien", "--ja"]
        )

        assert ergebnis.exit_code == 0
        assert not os.path.exists(verwaist)
        # Ohne --alle/--vor bleiben Tickets und ihre Anhänge unangetastet.
        assert Ticket.query.count() == 1
        assert os.path.exists(referenziert)


def test_ohne_umfang_bricht_ab(app):
    ergebnis = app.test_cli_runner().invoke(args=["tickets-purge"])
    assert ergebnis.exit_code != 0
    assert "--alle" in ergebnis.output


def test_alle_und_vor_schliessen_sich_aus(app):
    ergebnis = app.test_cli_runner().invoke(
        args=["tickets-purge", "--alle", "--vor", "2026-01-01"]
    )
    assert ergebnis.exit_code != 0
    assert "schließen sich gegenseitig aus" in ergebnis.output


def test_ungueltiges_datum_bricht_ab(app):
    ergebnis = app.test_cli_runner().invoke(args=["tickets-purge", "--vor", "01.03.2026"])
    assert ergebnis.exit_code != 0
    assert "JJJJ-MM-TT" in ergebnis.output
