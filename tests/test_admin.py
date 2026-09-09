from app.extensions import db
from app.models import Category, Team

from tests.conftest import login_as


def test_admin_routes_reject_non_admin(app, client, make_team, make_user):
    with app.app_context():
        make_team()
        user = make_user()
        login_as(client, user)

    response = client.get("/admin/teams")
    assert response.status_code == 403

    response = client.get("/admin/einstellungen")
    assert response.status_code == 403


def test_admin_routes_reject_agent_who_is_not_admin(app, client, make_team, make_user):
    with app.app_context():
        team = make_team()
        agent = make_user(teams=[team])
        login_as(client, agent)

    response = client.post(
        "/admin/teams/neu", data={"name": "Neues Team", "ad_gruppe_agenten": ""}
    )
    assert response.status_code == 403


def test_admin_can_create_and_toggle_team(app, client, admin_user):
    login_as(client, admin_user)

    response = client.post(
        "/admin/teams/neu",
        data={"name": "Hausmeister", "ad_gruppe_agenten": "grp-hm"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        team = Team.query.filter_by(name="Hausmeister").first()
        assert team is not None
        assert team.aktiv is True
        team_id = team.id

    client.post(f"/admin/teams/{team_id}/umschalten", follow_redirects=True)

    with app.app_context():
        assert db.session.get(Team, team_id).aktiv is False


def test_admin_can_create_category_for_team(app, client, admin_user, make_team):
    with app.app_context():
        team = make_team(kategorien=())
        team_id = team.id

    login_as(client, admin_user)
    response = client.post(
        f"/admin/teams/{team_id}/kategorien/neu",
        data={"name": "Netzwerk"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        category = Category.query.filter_by(team_id=team_id, name="Netzwerk").first()
        assert category is not None
        assert category.aktiv is True


def test_settings_roundtrip(app, client, admin_user):
    login_as(client, admin_user)

    response = client.post(
        "/admin/einstellungen",
        data={
            "ad_gruppe_user": "SlothTix-User",
            "ldap_server": "ucs.example.local",
            "ldap_port": "636",
            "ldap_use_ssl": "y",
            "ldap_base_dn": "dc=example,dc=local",
            "ldap_bind_dn": "cn=service,dc=example,dc=local",
            "smtp_host": "mail.example.local",
            "smtp_port": "587",
            "smtp_username": "slothtix",
            "smtp_from": "slothtix@example.local",
            "anhang_max_groesse_mb": "10",
            "alte_tickets_tage": "14",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        from app.models import Settings

        settings = Settings.get_or_create()
        assert settings.ad_gruppe_user == "SlothTix-User"
        assert settings.ldap_port == 636
        assert settings.anhang_max_groesse_mb == 10
        assert settings.alte_tickets_tage == 14
