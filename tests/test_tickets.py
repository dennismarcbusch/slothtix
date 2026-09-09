import io

from app.extensions import db
from app.models import Comment, Settings, Sichtbarkeit, Team, Ticket, TicketPrioritaet, TicketStatus

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
            f"/tickets/{ticket.id}/status", data={"status": "geschlossen"}
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
            f"/tickets/{ticket.id}/status", data={"status": "in_bearbeitung"}, follow_redirects=True
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
            f"/tickets/{ticket.id}/zuweisen",
            data={"zugewiesen_an_id": str(outsider.id)},
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
        from app.models import Attachment

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
        response = client.post(f"/tickets/{ticket.id}/prioritaet", data={"prioritaet": "hoch"})

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
            f"/tickets/{ticket.id}/prioritaet", data={"prioritaet": "niedrig"}, follow_redirects=True
        )

        assert response.status_code == 200
        updated = db.session.get(Ticket, ticket.id)
        assert updated.prioritaet == TicketPrioritaet.NIEDRIG
        assert len(updated.historie) == 1
        assert updated.historie[0].alter_wert == "mittel"
        assert updated.historie[0].neuer_wert == "niedrig"


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
