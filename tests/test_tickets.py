import io
import re

from app.extensions import db
from app.models import (
    Attachment,
    Comment,
    Settings,
    Sichtbarkeit,
    Team,
    Ticket,
    TicketPrioritaet,
    TicketStatus,
)

from tests.conftest import login_as


def _create_ticket(db, team, category, ersteller, titel="Testticket"):
    ticket = Ticket(
        titel=titel,
        beschreibung="Beschreibung",
        team_id=team.id,
        category_id=category.id,
        ersteller_id=ersteller.id,
        prioritaet=TicketPrioritaet.MITTEL,
    )
    db.session.add(ticket)
    db.session.commit()
    return ticket


def test_create_ticket_via_form(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        login_as(client, admin_user)

        response = client.post(
            "/tickets/neu",
            data={
                "titel": "Drucker kaputt",
                "beschreibung": "Druckt nicht mehr.",
                "team_id": str(team.id),
                "category_id": str(category.id),
                "prioritaet": "mittel",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        ticket = Ticket.query.filter_by(titel="Drucker kaputt").first()
        assert ticket is not None
        assert ticket.status == TicketStatus.OFFEN


def test_create_ticket_rejects_category_from_other_team(app, client, admin_user, make_team):
    with app.app_context():
        team_a = make_team(name="IT", ad_gruppe_agenten="grp-it")
        team_b = make_team(name="Hausmeister", ad_gruppe_agenten="grp-hm", kategorien=("Heizung",))
        login_as(client, admin_user)

        response = client.post(
            "/tickets/neu",
            data={
                "titel": "Falsche Kategorie",
                "beschreibung": "Test",
                "team_id": str(team_a.id),
                "category_id": str(team_b.kategorien[0].id),
                "prioritaet": "niedrig",
            },
            follow_redirects=True,
        )

        assert b"geh\xc3\xb6rt nicht zu diesem Team" in response.data
        assert Ticket.query.filter_by(titel="Falsche Kategorie").first() is None


def test_create_ticket_with_valid_attachment(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        login_as(client, admin_user)

        response = client.post(
            "/tickets/neu",
            data={
                "titel": "Mit Anhang",
                "beschreibung": "Siehe Screenshot",
                "team_id": str(team.id),
                "category_id": str(category.id),
                "prioritaet": "niedrig",
                "anhaenge": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 100), "screenshot.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        assert response.status_code == 200
        ticket = Ticket.query.filter_by(titel="Mit Anhang").first()
        assert ticket is not None
        assert len(ticket.anhaenge) == 1
        assert ticket.anhaenge[0].dateiname == "screenshot.png"


def test_create_ticket_rejects_oversized_attachment(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        settings = Settings.get_or_create()
        settings.anhang_max_groesse_mb = 1
        db.session.commit()
        login_as(client, admin_user)

        too_big = b"0" * (2 * 1024 * 1024)
        response = client.post(
            "/tickets/neu",
            data={
                "titel": "Zu gross",
                "beschreibung": "Test",
                "team_id": str(team.id),
                "category_id": str(category.id),
                "prioritaet": "niedrig",
                "anhaenge": (io.BytesIO(too_big), "riesig.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        assert b"berschreitet das Limit" in response.data
        assert Ticket.query.filter_by(titel="Zu gross").first() is None


def test_create_ticket_rejects_disallowed_file_type(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        login_as(client, admin_user)

        response = client.post(
            "/tickets/neu",
            data={
                "titel": "Falscher Typ",
                "beschreibung": "Test",
                "team_id": str(team.id),
                "category_id": str(category.id),
                "prioritaet": "niedrig",
                "anhaenge": (io.BytesIO(b"#!/bin/sh\necho hi"), "script.sh"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        assert b"ist nicht erlaubt" in response.data
        assert Ticket.query.filter_by(titel="Falscher Typ").first() is None


def test_pure_user_cannot_see_others_ticket(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        anderer = make_user(anzeigename="Anderer", email="a@example.local", ad_username="anderer")
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, anderer)
        response = client.get(f"/tickets/{ticket.id}")

        assert response.status_code == 403


def test_agent_can_see_team_ticket(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, agent)
        response = client.get(f"/tickets/{ticket.id}")

        assert response.status_code == 200


def test_user_comment_is_forced_public(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, ersteller)
        client.post(
            f"/tickets/{ticket.id}/kommentar",
            data={"text": "Mein Kommentar", "sichtbarkeit": "intern"},
            follow_redirects=True,
        )

        comment = Comment.query.filter_by(ticket_id=ticket.id).first()
        assert comment is not None
        assert comment.sichtbarkeit == Sichtbarkeit.OEFFENTLICH


def test_internal_comment_hidden_from_ticket_creator(app, client, make_team, make_user):
    # Bewusst KEIN gemeinsamer app_context über die Client-Requests hinweg:
    # der Testclient pusht sonst denselben App-Context wieder (Flask
    # erkennt einen bereits aktiven Context für dieselbe App und pusht
    # keinen neuen), wodurch Flask-Logins Request-Cache (flask.g) den
    # zuerst geladenen Nutzer über den Identitätswechsel hinweg behält.
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        ticket = _create_ticket(db, team, category, ersteller)
        ticket_id, agent_id, ersteller_id = ticket.id, agent.id, ersteller.id

    login_as(client, agent_id)
    client.post(
        f"/tickets/{ticket_id}/kommentar",
        data={"text": "Interne Notiz", "sichtbarkeit": "intern"},
        follow_redirects=True,
    )

    login_as(client, ersteller_id)
    response = client.get(f"/tickets/{ticket_id}")

    assert b"Interne Notiz" not in response.data


def test_non_agent_cannot_change_status(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, ersteller)
        response = client.post(
            f"/tickets/{ticket.id}/aktualisieren",
            data={
                "status": "geschlossen",
                "prioritaet": "mittel",
                "category_id": str(category.id),
                "zugewiesen_an_id": "",
            },
        )

        assert response.status_code == 403
        assert db.session.get(Ticket, ticket.id).status == TicketStatus.OFFEN


def test_agent_can_change_status_and_history_is_recorded(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, agent)
        response = client.post(
            f"/tickets/{ticket.id}/aktualisieren",
            data={
                "status": "in_bearbeitung",
                "prioritaet": "mittel",
                "category_id": str(category.id),
                "zugewiesen_an_id": "",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        updated = db.session.get(Ticket, ticket.id)
        assert updated.status.value == "in_bearbeitung"
        assert len(updated.historie) == 1
        assert updated.historie[0].alter_wert == "offen"
        assert updated.historie[0].neuer_wert == "in_bearbeitung"


def test_assign_rejects_non_team_member(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        outsider = make_user(anzeigename="Outsider", email="o@example.local", ad_username="outsider")
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, agent)
        response = client.post(
            f"/tickets/{ticket.id}/aktualisieren",
            data={
                "status": "offen",
                "prioritaet": "mittel",
                "category_id": str(category.id),
                "zugewiesen_an_id": str(outsider.id),
            },
            follow_redirects=True,
        )

        assert b"Ung\xc3\xbcltige Zuweisung" in response.data
        assert db.session.get(Ticket, ticket.id).zugewiesen_an_id is None


def test_closed_tickets_hidden_by_default_in_overview(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        _create_ticket(db, team, category, admin_user, titel="Offenes Ticket")
        geschlossen = _create_ticket(db, team, category, admin_user, titel="Geschlossenes Ticket")
        geschlossen.status = TicketStatus.GESCHLOSSEN
        db.session.commit()

        login_as(client, admin_user)
        response = client.get("/tickets/")

        assert b"Offenes Ticket" in response.data
        assert b"Geschlossenes Ticket" not in response.data

        client.post("/tickets/geschlossene-umschalten", follow_redirects=False)
        response = client.get("/tickets/")
        assert b"Geschlossenes Ticket" in response.data


def test_internal_comment_attachment_hidden_from_creator_but_visible_to_agent(
    app, client, make_team, make_user
):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        ticket = _create_ticket(db, team, category, ersteller)
        ticket_id, agent_id, ersteller_id = ticket.id, agent.id, ersteller.id

    login_as(client, agent_id)
    client.post(
        f"/tickets/{ticket_id}/kommentar",
        data={
            "text": "Interne Notiz mit Anhang",
            "sichtbarkeit": "intern",
            "anhaenge": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 50), "intern.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    with app.app_context():
        attachment_id = Attachment.query.filter_by(dateiname="intern.png").first().id

    login_as(client, ersteller_id)
    response = client.get(f"/tickets/anhaenge/{attachment_id}")
    assert response.status_code == 403

    login_as(client, agent_id)
    response = client.get(f"/tickets/anhaenge/{attachment_id}")
    assert response.status_code == 200


def test_old_open_ticket_is_highlighted_in_overview(app, client, admin_user, make_team):
    from datetime import timedelta

    from app.models import utcnow

    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        alt = _create_ticket(db, team, category, admin_user, titel="Altes Ticket")
        alt.erstellt_am = utcnow() - timedelta(days=30)
        _create_ticket(db, team, category, admin_user, titel="Neues Ticket")
        db.session.commit()

    login_as(client, admin_user)
    response = client.get("/tickets/").get_data(as_text=True)

    assert 'ticket-alt' in response
    alt_row_start = response.index("Altes Ticket")
    neu_row_start = response.index("Neues Ticket")
    alt_row = response[max(0, alt_row_start - 400) : alt_row_start]
    neu_row = response[max(0, neu_row_start - 400) : neu_row_start]
    assert "ticket-alt" in alt_row
    assert "ticket-alt" not in neu_row


def test_search_and_filters_narrow_overview(app, client, admin_user, make_team):
    with app.app_context():
        team_a = make_team(name="IT", ad_gruppe_agenten="grp-it")
        team_b = make_team(name="Hausmeister", ad_gruppe_agenten="grp-hm", kategorien=("Heizung",))
        _create_ticket(db, team_a, team_a.kategorien[0], admin_user, titel="Drucker streikt")
        _create_ticket(db, team_b, team_b.kategorien[0], admin_user, titel="Heizung kalt")

    login_as(client, admin_user)

    response = client.get("/tickets/?q=Drucker").get_data(as_text=True)
    assert "Drucker streikt" in response
    assert "Heizung kalt" not in response

    with app.app_context():
        team_b_id = Team.query.filter_by(name="Hausmeister").first().id
    response = client.get(f"/tickets/?team={team_b_id}").get_data(as_text=True)
    assert "Heizung kalt" in response
    assert "Drucker streikt" not in response


def test_attachment_extension_wins_over_spoofed_content_type(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        login_as(client, admin_user)

        response = client.post(
            "/tickets/neu",
            data={
                "titel": "Gespoofter Typ",
                "beschreibung": "Test",
                "team_id": str(team.id),
                "category_id": str(category.id),
                "prioritaet": "niedrig",
                "anhaenge": (io.BytesIO(b"#!/bin/sh\necho hi"), "evil.sh", "image/png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        assert b"ist nicht erlaubt" in response.data
        assert Ticket.query.filter_by(titel="Gespoofter Typ").first() is None


def test_ersteller_filter_narrows_overview(app, client, admin_user, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        anderer = make_user(anzeigename="Anderer Ersteller", email="a@example.local", ad_username="anderer")
        _create_ticket(db, team, category, admin_user, titel="Ticket von Admin")
        _create_ticket(db, team, category, anderer, titel="Ticket von Anderer")
        anderer_id = anderer.id

        login_as(client, admin_user)
        response = client.get(f"/tickets/?ersteller={anderer_id}").get_data(as_text=True)

        assert "Ticket von Anderer" in response
        assert "Ticket von Admin" not in response


def test_non_agent_cannot_change_priority(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, ersteller)
        response = client.post(
            f"/tickets/{ticket.id}/aktualisieren",
            data={
                "status": "offen",
                "prioritaet": "hoch",
                "category_id": str(category.id),
                "zugewiesen_an_id": "",
            },
        )

        assert response.status_code == 403
        assert db.session.get(Ticket, ticket.id).prioritaet == TicketPrioritaet.MITTEL


def test_agent_can_change_priority_and_history_is_recorded(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, agent)
        response = client.post(
            f"/tickets/{ticket.id}/aktualisieren",
            data={
                "status": "offen",
                "prioritaet": "niedrig",
                "category_id": str(category.id),
                "zugewiesen_an_id": "",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        updated = db.session.get(Ticket, ticket.id)
        assert updated.prioritaet == TicketPrioritaet.NIEDRIG
        assert len(updated.historie) == 1
        assert updated.historie[0].alter_wert == "mittel"
        assert updated.historie[0].neuer_wert == "niedrig"


def test_update_details_changes_all_four_fields_in_one_request(app, client, make_team, make_user):
    with app.app_context():
        team = make_team(kategorien=("Drucker defekt", "Heizung"))
        category = next(k for k in team.kategorien if k.name == "Drucker defekt")
        andere_category = next(k for k in team.kategorien if k.name == "Heizung")
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, agent)
        response = client.post(
            f"/tickets/{ticket.id}/aktualisieren",
            data={
                "status": "in_bearbeitung",
                "prioritaet": "hoch",
                "category_id": str(andere_category.id),
                "zugewiesen_an_id": str(agent.id),
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert "Ticket aktualisiert" in response.get_data(as_text=True)
        updated = db.session.get(Ticket, ticket.id)
        assert updated.status == TicketStatus.IN_BEARBEITUNG
        assert updated.prioritaet == TicketPrioritaet.HOCH
        assert updated.category_id == andere_category.id
        assert updated.zugewiesen_an_id == agent.id
        assert len(updated.historie) == 4


def test_update_details_with_unchanged_values_flashes_no_changes(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        ticket = _create_ticket(db, team, category, ersteller)

        login_as(client, agent)
        response = client.post(
            f"/tickets/{ticket.id}/aktualisieren",
            data={
                "status": "offen",
                "prioritaet": "mittel",
                "category_id": str(category.id),
                "zugewiesen_an_id": "",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert "Keine Änderungen" in response.get_data(as_text=True)
        assert len(db.session.get(Ticket, ticket.id).historie) == 0


def test_change_team_redirects_to_overview_not_detail(app, client, make_team, make_user):
    # Verschiebt ein Ticket in ein Team, in dem der ausführende Agent kein
    # Mitglied ist. Ein Redirect auf die Detailseite würde dort an
    # _kann_ticket_sehen scheitern (403), da der Agent das Ticket im neuen
    # Team nicht mehr sehen darf - deshalb muss auf die Übersicht
    # umgeleitet werden.
    with app.app_context():
        team_a = make_team(name="IT", ad_gruppe_agenten="grp-it")
        team_b = make_team(name="Hausmeister", ad_gruppe_agenten="grp-hm", kategorien=("Heizung",))
        kategorie_b = team_b.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(
            anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team_a]
        )
        ticket = _create_ticket(db, team_a, team_a.kategorien[0], ersteller)

        login_as(client, agent)
        response = client.post(
            f"/tickets/{ticket.id}/team",
            data={"team_id": str(team_b.id), "category_id": str(kategorie_b.id)},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/tickets/")

        follow_up = client.get(response.headers["Location"])
        assert follow_up.status_code == 200
        assert db.session.get(Ticket, ticket.id).team_id == team_b.id


def test_sort_by_titel_ascending_and_descending(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        _create_ticket(db, team, category, admin_user, titel="Zebra-Ticket")
        _create_ticket(db, team, category, admin_user, titel="Apfel-Ticket")

    login_as(client, admin_user)

    response = client.get("/tickets/?sort=titel&dir=asc").get_data(as_text=True)
    apfel_pos = response.index("Apfel-Ticket")
    zebra_pos = response.index("Zebra-Ticket")
    assert apfel_pos < zebra_pos

    response = client.get("/tickets/?sort=titel&dir=desc").get_data(as_text=True)
    apfel_pos = response.index("Apfel-Ticket")
    zebra_pos = response.index("Zebra-Ticket")
    assert zebra_pos < apfel_pos


def test_sort_by_prioritaet_uses_severity_order_not_alphabetical(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        hoch = _create_ticket(db, team, category, admin_user, titel="Hohes Ticket")
        hoch.prioritaet = TicketPrioritaet.HOCH
        niedrig = _create_ticket(db, team, category, admin_user, titel="Niedriges Ticket")
        niedrig.prioritaet = TicketPrioritaet.NIEDRIG
        db.session.commit()

    login_as(client, admin_user)

    response = client.get("/tickets/?sort=prioritaet&dir=asc").get_data(as_text=True)
    niedrig_pos = response.index("Niedriges Ticket")
    hoch_pos = response.index("Hohes Ticket")
    # Aufsteigend nach Dringlichkeit: niedrig vor hoch (nicht alphabetisch,
    # da "hoch" < "niedrig" waere).
    assert niedrig_pos < hoch_pos


def test_sort_link_toggles_direction_and_preserves_filters(app, client, admin_user, make_team):
    with app.app_context():
        team_id = make_team().id

    login_as(client, admin_user)
    response = client.get(f"/tickets/?team={team_id}&sort=titel&dir=asc").get_data(as_text=True)

    assert "sort=titel" in response
    assert "dir=desc" in response
    assert f"team={team_id}" in response


def test_new_ticket_form_has_no_team_preselected(app, client, admin_user, make_team):
    with app.app_context():
        make_team()
        login_as(client, admin_user)

        response = client.get("/tickets/neu").get_data(as_text=True)

        # Nur der leere Platzhalter traegt "selected" - kein echtes Team.
        assert '<option selected value="">Bitte wählen</option>' in response
        assert 'value="1" selected' not in response


def test_new_ticket_missing_team_shows_error_and_does_not_create(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        login_as(client, admin_user)

        response = client.post(
            "/tickets/neu",
            data={
                "titel": "Ohne Team",
                "beschreibung": "Test",
                "team_id": "",
                "category_id": str(category.id),
                "prioritaet": "niedrig",
            },
            follow_redirects=True,
        ).get_data(as_text=True)

        assert "Bitte ein Team auswählen" in response
        assert "Bitte die markierten Pflichtfelder" in response
        assert Ticket.query.filter_by(titel="Ohne Team").first() is None


def test_new_ticket_missing_all_required_fields_shows_error(app, client, admin_user, make_team):
    with app.app_context():
        make_team()
        login_as(client, admin_user)

        response = client.post("/tickets/neu", data={}, follow_redirects=True).get_data(as_text=True)

        assert "Bitte die markierten Pflichtfelder korrekt ausfüllen" in response


def test_only_mine_assigned_toggle_filters_overview(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        agent = make_user(anzeigename="Agent", email="agent@example.local", ad_username="agent", teams=[team])
        agent_id = agent.id

        mir_zugewiesen = _create_ticket(db, team, category, ersteller, titel="Mir zugewiesen")
        mir_zugewiesen.zugewiesen_an_id = agent_id
        _create_ticket(db, team, category, ersteller, titel="Anderes Ticket")
        db.session.commit()

        login_as(client, agent_id)

        response = client.get("/tickets/").get_data(as_text=True)
        assert "Mir zugewiesen" in response
        assert "Anderes Ticket" in response

        client.post("/tickets/mir-zugewiesen-umschalten", follow_redirects=False)
        response = client.get("/tickets/").get_data(as_text=True)
        assert "Mir zugewiesen" in response
        assert "Anderes Ticket" not in response


def test_only_mine_toggle_not_shown_for_pure_user(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        category = team.kategorien[0]
        ersteller = make_user(anzeigename="Ersteller", email="e@example.local", ad_username="ersteller")
        _create_ticket(db, team, category, ersteller)

        login_as(client, ersteller)
        response = client.get("/tickets/").get_data(as_text=True)

        assert "Nur mir zugewiesene anzeigen" not in response


def test_kategoriename_kann_nicht_aus_dem_script_block_ausbrechen(
    app, client, admin_user, make_team
):
    """Die Team->Kategorien-Struktur landet in einem <script>-Block. Ein
    Kategoriename mit '</script>' darf ihn nicht beenden können."""
    with app.app_context():
        make_team(name="IT", kategorien=("</script><img src=x onerror=alert(1)>",))

    login_as(client, admin_user)
    response = client.get("/tickets/neu")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "</script><img" not in html
    assert "\u003c/script\u003e" in html


def test_sortier_links_ignorieren_fremde_query_parameter(app, client, admin_user, make_team):
    """?_method=DELETE landete früher per ** in url_for() und riss die
    gesamte Übersicht mit einem BuildError (HTTP 500) ab."""
    with app.app_context():
        make_team()

    login_as(client, admin_user)
    for parameter in ("_method=DELETE", "_scheme=javascript", "_external=1", "beliebig=x"):
        response = client.get(f"/tickets/?{parameter}")
        assert response.status_code == 200, parameter


def test_sortier_links_behalten_die_aktiven_filter(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team()
        team_id = team.id

    login_as(client, admin_user)
    response = client.get(f"/tickets/?q=drucker&team={team_id}&status=offen")
    html = response.get_data(as_text=True)

    assert "q=drucker" in html
    assert f"team={team_id}" in html
    assert "status=offen" in html


def test_sicherheitsheader_auf_jeder_antwort(client):
    response = client.get("/login")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp


def test_inline_skript_traegt_das_nonce_aus_der_csp(app, client, admin_user, make_team):
    with app.app_context():
        make_team()

    login_as(client, admin_user)
    response = client.get("/tickets/neu")
    html = response.get_data(as_text=True)

    nonce = re.search(r'<script nonce="([^"]+)">', html).group(1)
    assert f"'nonce-{nonce}'" in response.headers["Content-Security-Policy"]


def test_bild_anhang_wird_inline_mit_geprueftem_typ_ausgeliefert(
    app, client, admin_user, make_team
):
    with app.app_context():
        ticket = _ticket_mit_anhang(make_team, admin_user, "screenshot.png", "image/png")
        anhang_id = ticket.anhaenge[0].id

    login_as(client, admin_user)
    response = client.get(f"/tickets/anhaenge/{anhang_id}")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert response.headers["Content-Disposition"].startswith("inline")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_pdf_anhang_wird_zum_download_gezwungen(app, client, admin_user, make_team):
    with app.app_context():
        ticket = _ticket_mit_anhang(make_team, admin_user, "handbuch.pdf", "application/pdf")
        anhang_id = ticket.anhaenge[0].id

    login_as(client, admin_user)
    response = client.get(f"/tickets/anhaenge/{anhang_id}")

    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment")


def _ticket_mit_anhang(make_team, uploader, dateiname, mime_type):
    """Legt ein Ticket mit genau einem Anhang an (Datei auf der Platte
    inklusive) und gibt das Ticket zurück."""
    import os

    from flask import current_app

    team = make_team()
    ticket = Ticket(
        titel="Mit Anhang",
        beschreibung="…",
        team_id=team.id,
        category_id=team.kategorien[0].id,
        ersteller_id=uploader.id,
        prioritaet=TicketPrioritaet.MITTEL,
    )
    db.session.add(ticket)
    db.session.flush()

    verzeichnis = os.path.join(current_app.instance_path, "uploads", str(ticket.id))
    os.makedirs(verzeichnis, exist_ok=True)
    pfad = os.path.join(verzeichnis, f"abc123_{dateiname}")
    with open(pfad, "wb") as f:
        f.write(b"inhalt")

    db.session.add(
        Attachment(
            ticket_id=ticket.id,
            dateiname=dateiname,
            pfad=os.path.relpath(pfad, current_app.instance_path),
            groesse_bytes=6,
            mime_type=mime_type,
            hochgeladen_von_id=uploader.id,
        )
    )
    db.session.commit()
    return ticket


def _ticket_anlegen_mit_datei(client, team_id, kategorie_id, dateiname, inhalt, content_type=None):
    datei = (io.BytesIO(inhalt), dateiname) if content_type is None else (
        io.BytesIO(inhalt),
        dateiname,
        content_type,
    )
    return client.post(
        "/tickets/neu",
        data={
            "titel": "Mit Anhang",
            "beschreibung": "Text",
            "team_id": str(team_id),
            "category_id": str(kategorie_id),
            "prioritaet": "mittel",
            "anhaenge": datei,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_unbekannte_endung_wird_trotz_vorgetaeuschtem_content_type_abgelehnt(
    app, client, admin_user, make_team
):
    """mimetypes.guess_type() lieferte für unbekannte Endungen None, worauf
    der frei wählbare Content-Type des Clients den Ausschlag gab."""
    with app.app_context():
        team = make_team()
        team_id, kategorie_id = team.id, team.kategorien[0].id

    login_as(client, admin_user)
    response = _ticket_anlegen_mit_datei(
        client, team_id, kategorie_id, "nutzlast.blah", b"\x89PNG\r\n\x1a\nirgendwas", "image/png"
    )

    assert "nicht erlaubt" in response.get_data(as_text=True)
    with app.app_context():
        assert Attachment.query.count() == 0


def test_inhalt_muss_zur_endung_passen(app, client, admin_user, make_team):
    """Eine in .png umbenannte Datei darf nicht als Bild durchgehen -
    sonst läge beliebiger Inhalt unter einem Bild-Content-Type."""
    with app.app_context():
        team = make_team()
        team_id, kategorie_id = team.id, team.kategorien[0].id

    login_as(client, admin_user)
    response = _ticket_anlegen_mit_datei(
        client, team_id, kategorie_id, "getarnt.png", b"<html><script>alert(1)</script>"
    )

    assert "passt nicht zur Dateiendung" in response.get_data(as_text=True)
    with app.app_context():
        assert Attachment.query.count() == 0


def test_alle_erlaubten_typen_werden_mit_korrektem_mime_gespeichert(
    app, client, admin_user, make_team
):
    from app.attachments import ERLAUBTE_ENDUNGEN

    beispiele = {
        "bild.png": b"\x89PNG\r\n\x1a\n" + b"0" * 20,
        "foto.jpg": b"\xff\xd8\xff" + b"0" * 20,
        "anim.gif": b"GIF89a" + b"0" * 20,
        "doku.pdf": b"%PDF-1.7" + b"0" * 20,
    }
    with app.app_context():
        team = make_team()
        team_id, kategorie_id = team.id, team.kategorien[0].id

    login_as(client, admin_user)
    for dateiname, inhalt in beispiele.items():
        _ticket_anlegen_mit_datei(client, team_id, kategorie_id, dateiname, inhalt)
        with app.app_context():
            anhang = Attachment.query.filter_by(dateiname=dateiname).first()
            assert anhang is not None, dateiname
            endung = "." + dateiname.rsplit(".", 1)[1]
            assert anhang.mime_type == ERLAUBTE_ENDUNGEN[endung]


def test_dateiname_ohne_lateinische_zeichen_behaelt_die_endung(app, client, admin_user, make_team):
    """secure_filename() verschluckt bei rein nicht-lateinischen Namen die
    Endung - gespeicherter Name und Content-Type müssen trotzdem passen."""
    with app.app_context():
        team = make_team()
        team_id, kategorie_id = team.id, team.kategorien[0].id

    login_as(client, admin_user)
    _ticket_anlegen_mit_datei(
        client, team_id, kategorie_id, "日本語.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20
    )

    with app.app_context():
        anhang = Attachment.query.first()
        assert anhang is not None
        assert anhang.dateiname.endswith(".png")
        assert anhang.mime_type == "image/png"
