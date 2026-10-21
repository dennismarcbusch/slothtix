"""Tests für die Benachrichtigungs-Einstellungen der Agenten und die
morgendliche Zusammenfassung (app/benachrichtigungen.py,
app/zusammenfassung.py)."""

from datetime import date, datetime, time, timedelta

import pytest

from app.extensions import db
from app.models import (
    Category,
    Comment,
    MailNeueTickets,
    Sichtbarkeit,
    Ticket,
    TicketPrioritaet,
    TicketStatus,
    User,
)
from app.notifications import notify_assigned, notify_comment_added, notify_ticket_created
from app.zusammenfassung import link_kontext, sende_faellige_zusammenfassungen

from tests.conftest import login_as

# Dienstag, 21.10.2026, 07:05 Uhr in Berlin (MESZ) - als naive UTC-Zeit.
DIENSTAG_0705 = datetime(2026, 10, 21, 5, 5)
SAMSTAG_0705 = datetime(2026, 10, 24, 5, 5)


@pytest.fixture
def mails(monkeypatch):
    gesendet = []
    sammeln = lambda n: gesendet.extend(n)  # noqa: E731
    monkeypatch.setattr("app.notifications.send_mails", sammeln)
    monkeypatch.setattr("app.notifications.send_mail", lambda *m: gesendet.append(m))
    monkeypatch.setattr("app.zusammenfassung.send_mails", sammeln)
    return gesendet


@pytest.fixture
def team_und_leute(app, make_team, make_user):
    with app.app_context():
        team = make_team()
        agent = make_user(anzeigename="Agent", email="agent@x", ad_username="agent", teams=[team])
        kollege = make_user(anzeigename="Kollege", email="kollege@x", ad_username="kollege", teams=[team])
        ersteller = make_user(anzeigename="Ersteller", email="ersteller@x", ad_username="ersteller")
        return team.id, agent.id, kollege.id, ersteller.id


def _ticket(team_id, ersteller_id, prioritaet=TicketPrioritaet.MITTEL, status=TicketStatus.OFFEN,
            zugewiesen_an_id=None, titel="Drucker", erstellt_am=None):
    ticket = Ticket(
        titel=titel,
        beschreibung="Geht nicht",
        team_id=team_id,
        category_id=Category.query.filter_by(team_id=team_id).first().id,
        ersteller_id=ersteller_id,
        zugewiesen_an_id=zugewiesen_an_id,
        prioritaet=prioritaet,
        status=status,
        erstellt_am=erstellt_am or DIENSTAG_0705 - timedelta(days=2),
    )
    db.session.add(ticket)
    db.session.commit()
    return ticket


def _empfaenger(mails):
    return sorted(m[0] for m in mails)


def test_defaults_behalten_bisheriges_verhalten(app, team_und_leute):
    with app.app_context():
        agent = db.session.get(User, team_und_leute[1])
        assert agent.mail_neue_tickets == MailNeueTickets.ALLE
        assert agent.mail_antworten and agent.mail_zuweisung
        assert not agent.zusammenfassung_aktiv
        assert agent.zusammenfassung_uhrzeit == time(7, 0)


@pytest.mark.parametrize(
    "einstellung, prioritaet, bekommt_mail",
    [
        (MailNeueTickets.ALLE, TicketPrioritaet.NIEDRIG, True),
        (MailNeueTickets.AB_MITTEL, TicketPrioritaet.NIEDRIG, False),
        (MailNeueTickets.AB_MITTEL, TicketPrioritaet.MITTEL, True),
        (MailNeueTickets.NUR_HOCH, TicketPrioritaet.MITTEL, False),
        (MailNeueTickets.NUR_HOCH, TicketPrioritaet.HOCH, True),
        (MailNeueTickets.KEINE, TicketPrioritaet.HOCH, False),
    ],
)
def test_neue_tickets_nach_prioritaet(app, team_und_leute, mails, einstellung, prioritaet, bekommt_mail):
    team_id, agent_id, _, ersteller_id = team_und_leute
    with app.test_request_context():
        db.session.get(User, agent_id).mail_neue_tickets = einstellung
        db.session.commit()
        notify_ticket_created(_ticket(team_id, ersteller_id, prioritaet=prioritaet))

    assert ("agent@x" in _empfaenger(mails)) is bekommt_mail
    # Der Kollege hat nichts umgestellt und bekommt weiter alles.
    assert "kollege@x" in _empfaenger(mails)


def test_antworten_abschaltbar(app, team_und_leute, mails):
    team_id, agent_id, _, ersteller_id = team_und_leute
    with app.test_request_context():
        db.session.get(User, agent_id).mail_antworten = False
        ticket = _ticket(team_id, ersteller_id)
        kommentar = Comment(ticket_id=ticket.id, autor_id=ersteller_id, text="Noch da?",
                            sichtbarkeit=Sichtbarkeit.OEFFENTLICH)
        db.session.add(kommentar)
        db.session.commit()
        notify_comment_added(kommentar)

    assert _empfaenger(mails) == ["kollege@x"]


def test_zuweisung_abschaltbar(app, team_und_leute, mails):
    team_id, agent_id, _, ersteller_id = team_und_leute
    with app.test_request_context():
        db.session.get(User, agent_id).mail_zuweisung = False
        db.session.commit()
        notify_assigned(_ticket(team_id, ersteller_id, zugewiesen_an_id=agent_id))

    assert mails == []


def test_einstellungen_seite_speichert(app, client, team_und_leute):
    agent_id = team_und_leute[1]
    login_as(client, agent_id)

    assert client.get("/benachrichtigungen").status_code == 200
    antwort = client.post(
        "/benachrichtigungen",
        data={
            "mail_neue_tickets": "nur_hoch",
            "mail_zuweisung": "y",
            "zusammenfassung_aktiv": "y",
            "zusammenfassung_uhrzeit": "06:45",
        },
    )
    assert antwort.status_code == 302

    with app.app_context():
        agent = db.session.get(User, agent_id)
        assert agent.mail_neue_tickets == MailNeueTickets.NUR_HOCH
        assert agent.mail_antworten is False
        assert agent.mail_zuweisung is True
        assert agent.zusammenfassung_aktiv is True
        assert agent.zusammenfassung_uhrzeit == time(6, 45)
        assert agent.zusammenfassung_nur_werktags is False


def test_einstellungen_seite_nur_fuer_agenten(client, team_und_leute):
    login_as(client, team_und_leute[3])
    assert client.get("/benachrichtigungen").status_code == 403


def _zusammenfassung_einschalten(agent_id, uhrzeit=time(7, 0), nur_werktags=True):
    agent = db.session.get(User, agent_id)
    agent.zusammenfassung_aktiv = True
    agent.zusammenfassung_uhrzeit = uhrzeit
    agent.zusammenfassung_nur_werktags = nur_werktags
    db.session.commit()


def test_zusammenfassung_gruppiert_offene_tickets(app, team_und_leute, mails):
    team_id, agent_id, kollege_id, ersteller_id = team_und_leute
    with link_kontext(app):
        _zusammenfassung_einschalten(agent_id)
        _ticket(team_id, ersteller_id, titel="Beamer", zugewiesen_an_id=agent_id,
                status=TicketStatus.IN_BEARBEITUNG)
        _ticket(team_id, ersteller_id, titel="Drucker", prioritaet=TicketPrioritaet.HOCH)
        _ticket(team_id, ersteller_id, titel="WLAN", zugewiesen_an_id=kollege_id)
        _ticket(team_id, ersteller_id, titel="Erledigt", status=TicketStatus.GELOEST)

        sende_faellige_zusammenfassungen(DIENSTAG_0705)

    assert len(mails) == 1
    empfaenger, betreff, text = mails[0]
    assert empfaenger == "agent@x"
    assert betreff == "[SlothTix] Zusammenfassung: 2 offen, 1 in Bearbeitung"
    assert text.index("Dir zugewiesen (1)") < text.index("Beamer")
    assert text.index("Noch niemandem zugewiesen (1)") < text.index("Drucker")
    assert "bei Kollege" in text
    assert "Erledigt" not in text
    assert "seit 2 Tagen" in text
    assert "/tickets/" in text


def test_zusammenfassung_nur_einmal_pro_tag(app, team_und_leute, mails):
    team_id, agent_id, _, ersteller_id = team_und_leute
    with link_kontext(app):
        _zusammenfassung_einschalten(agent_id)
        _ticket(team_id, ersteller_id)

        sende_faellige_zusammenfassungen(DIENSTAG_0705)
        sende_faellige_zusammenfassungen(DIENSTAG_0705 + timedelta(minutes=1))
        assert db.session.get(User, agent_id).zusammenfassung_gesendet_am == date(2026, 10, 21)

    assert len(mails) == 1


@pytest.mark.parametrize(
    "jetzt, nur_werktags, faellig",
    [
        (DIENSTAG_0705 - timedelta(minutes=10), True, False),  # 06:55 - zu früh
        (DIENSTAG_0705 + timedelta(hours=2), True, True),  # 09:05 - wird nachgeholt
        (DIENSTAG_0705 + timedelta(hours=4), True, False),  # 11:05 - zu spät
        (SAMSTAG_0705, True, False),
        (SAMSTAG_0705, False, True),
    ],
)
def test_zusammenfassung_zeitfenster(app, team_und_leute, mails, jetzt, nur_werktags, faellig):
    team_id, agent_id, _, ersteller_id = team_und_leute
    with link_kontext(app):
        _zusammenfassung_einschalten(agent_id, nur_werktags=nur_werktags)
        _ticket(team_id, ersteller_id)
        sende_faellige_zusammenfassungen(jetzt)

    assert (len(mails) == 1) is faellig


def test_keine_zusammenfassung_ohne_offene_tickets(app, team_und_leute, mails):
    team_id, agent_id, _, ersteller_id = team_und_leute
    with link_kontext(app):
        _zusammenfassung_einschalten(agent_id)
        _ticket(team_id, ersteller_id, status=TicketStatus.GESCHLOSSEN)
        sende_faellige_zusammenfassungen(DIENSTAG_0705)

    assert mails == []


def test_keine_zusammenfassung_fuer_ehemalige_agenten(app, team_und_leute, mails):
    team_id, agent_id, _, ersteller_id = team_und_leute
    with link_kontext(app):
        _zusammenfassung_einschalten(agent_id)
        _ticket(team_id, ersteller_id)
        db.session.get(User, agent_id).teams = []
        db.session.commit()
        sende_faellige_zusammenfassungen(DIENSTAG_0705)

    assert mails == []


def test_cli_einmaliger_lauf(app, team_und_leute, mails):
    # Ohne fällige Zusammenfassung: der Befehl läuft durch und meldet 0.
    ergebnis = app.test_cli_runner().invoke(args=["zusammenfassungen"])
    assert ergebnis.exit_code == 0, ergebnis.output
    assert "0 Zusammenfassung(en) verschickt." in ergebnis.output
