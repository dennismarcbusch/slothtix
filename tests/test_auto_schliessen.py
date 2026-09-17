"""Tests für das automatische Schließen gelöster Tickets (app/auto_schliessen.py)."""

from datetime import timedelta

import pytest

from app.auto_schliessen import _pruefung_uebernehmen, schliesse_faellige_tickets
from app.extensions import db
from app.models import (
    Comment,
    HistorienAktion,
    Settings,
    Sichtbarkeit,
    Ticket,
    TicketHistory,
    TicketPrioritaet,
    TicketStatus,
    utcnow,
)

from tests.conftest import login_as


@pytest.fixture
def mails(monkeypatch):
    gesendet = []
    monkeypatch.setattr("app.auto_schliessen.send_mails", lambda n: gesendet.extend(n))
    return gesendet


@pytest.fixture
def team_und_leute(app, make_team, make_user):
    with app.app_context():
        team = make_team()
        agent = make_user(anzeigename="Agent", email="agent@x", ad_username="agent", teams=[team])
        ersteller = make_user(anzeigename="Ersteller", email="ersteller@x", ad_username="ersteller")
        return team.id, agent.id, ersteller.id


def _ticket(team_id, ersteller_id, status=TicketStatus.GELOEST, geloest_vor_tagen=None, titel="Drucker"):
    team_category = db.session.execute(
        db.text("SELECT id FROM category WHERE team_id = :t"), {"t": team_id}
    ).scalar()
    ticket = Ticket(
        titel=titel,
        beschreibung="geht nicht",
        team_id=team_id,
        category_id=team_category,
        ersteller_id=ersteller_id,
        prioritaet=TicketPrioritaet.MITTEL,
        status=status,
    )
    db.session.add(ticket)
    db.session.flush()
    if geloest_vor_tagen is not None:
        _status_historie(ticket, ersteller_id, TicketStatus.GELOEST, geloest_vor_tagen)
    db.session.commit()
    return ticket


def _status_historie(ticket, user_id, neuer_status, vor_tagen):
    db.session.add(
        TicketHistory(
            ticket_id=ticket.id,
            aktion=HistorienAktion.STATUS_GEAENDERT,
            alter_wert="in_bearbeitung",
            neuer_wert=neuer_status.value,
            ausgefuehrt_von_id=user_id,
            zeitstempel=utcnow() - timedelta(days=vor_tagen),
        )
    )


def _kommentar(ticket, autor_id, vor_tagen, sichtbarkeit=Sichtbarkeit.OEFFENTLICH):
    db.session.add(
        Comment(
            ticket_id=ticket.id,
            autor_id=autor_id,
            text="Geht leider immer noch nicht",
            sichtbarkeit=sichtbarkeit,
            erstellt_am=utcnow() - timedelta(days=vor_tagen),
        )
    )
    db.session.commit()


def test_schliesst_nach_ablauf_der_frist_mit_system_eintrag(app, team_und_leute):
    team_id, agent_id, ersteller_id = team_und_leute
    with app.app_context():
        faellig = _ticket(team_id, ersteller_id, geloest_vor_tagen=15)
        frisch = _ticket(team_id, ersteller_id, geloest_vor_tagen=13)
        offen = _ticket(team_id, ersteller_id, status=TicketStatus.OFFEN)

        geschlossen = schliesse_faellige_tickets(14)

        assert [t.id for t in geschlossen] == [faellig.id]
        assert db.session.get(Ticket, faellig.id).status == TicketStatus.GESCHLOSSEN
        assert db.session.get(Ticket, frisch.id).status == TicketStatus.GELOEST
        assert db.session.get(Ticket, offen.id).status == TicketStatus.OFFEN

        eintrag = (
            TicketHistory.query.filter_by(ticket_id=faellig.id)
            .order_by(TicketHistory.zeitstempel.desc())
            .first()
        )
        assert (eintrag.alter_wert, eintrag.neuer_wert, eintrag.ausgefuehrt_von_id) == (
            "geloest",
            "geschlossen",
            None,
        )


def test_antwort_des_erstellers_startet_frist_neu(app, team_und_leute):
    team_id, agent_id, ersteller_id = team_und_leute
    with app.app_context():
        mit_antwort = _ticket(team_id, ersteller_id, geloest_vor_tagen=20)
        _kommentar(mit_antwort, ersteller_id, vor_tagen=3)
        nur_agent = _ticket(team_id, ersteller_id, geloest_vor_tagen=20)
        _kommentar(nur_agent, agent_id, vor_tagen=3)

        geschlossen = schliesse_faellige_tickets(14)

        assert [t.id for t in geschlossen] == [nur_agent.id]


def test_zaehlt_ab_dem_letzten_wechsel_auf_geloest(app, team_und_leute):
    team_id, agent_id, ersteller_id = team_und_leute
    with app.app_context():
        ticket = _ticket(team_id, ersteller_id, geloest_vor_tagen=30)
        _status_historie(ticket, agent_id, TicketStatus.OFFEN, 25)
        _status_historie(ticket, agent_id, TicketStatus.GELOEST, 2)
        db.session.commit()

        assert schliesse_faellige_tickets(14) == []


def test_pruefung_hoechstens_einmal_pro_stunde_ueber_alle_worker(app):
    with app.app_context():
        Settings.get_or_create()
        jetzt = utcnow()

        assert _pruefung_uebernehmen(jetzt) is True
        assert _pruefung_uebernehmen(jetzt + timedelta(minutes=30)) is False
        assert _pruefung_uebernehmen(jetzt + timedelta(minutes=61)) is True


def test_seitenaufruf_schliesst_und_mailt_nach_der_antwort(
    app, client, admin_user, team_und_leute, mails
):
    team_id, agent_id, ersteller_id = team_und_leute
    with app.app_context():
        ticket_id = _ticket(team_id, ersteller_id, geloest_vor_tagen=15, titel="Beamer").id
    login_as(client, admin_user)

    antwort = client.get("/tickets/")
    assert mails == []
    antwort.close()

    with app.app_context():
        assert db.session.get(Ticket, ticket_id).status == TicketStatus.GESCHLOSSEN
    [(empfaenger, betreff, text)] = mails
    assert empfaenger == "ersteller@x"
    assert betreff == f"[SlothTix] Ticket #{ticket_id} automatisch geschlossen: Beamer"
    assert "seit 14 Tagen als gelöst markiert" in text
    assert f"/tickets/{ticket_id}" in text

    detail = client.get(f"/tickets/{ticket_id}").get_data(as_text=True)
    assert "System:" in detail


def test_frist_null_schaltet_automatisches_schliessen_ab(
    app, client, admin_user, team_und_leute, mails
):
    team_id, agent_id, ersteller_id = team_und_leute
    with app.app_context():
        Settings.get_or_create().auto_schliessen_tage = 0
        db.session.commit()
        ticket_id = _ticket(team_id, ersteller_id, geloest_vor_tagen=100).id
    login_as(client, admin_user)

    client.get("/tickets/").close()

    with app.app_context():
        assert db.session.get(Ticket, ticket_id).status == TicketStatus.GELOEST
    assert mails == []
