from app.auth import sync_user_from_ldap
from app.extensions import db
from app.ldap_service import LdapUser
from app.models import Settings, User


def test_local_admin_can_log_in(client):
    response = client.post(
        "/login", data={"username": "admin", "password": "adminpass"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Tickets" in response.data


def test_local_admin_wrong_password_rejected(client):
    response = client.post(
        "/login", data={"username": "admin", "password": "falsch"}, follow_redirects=True
    )
    assert b"Benutzername oder Passwort falsch" in response.data


def test_login_required_redirects_to_login(client):
    response = client.get("/tickets/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_sync_user_from_ldap_denies_without_matching_group(app, make_team):
    with app.app_context():
        make_team(name="IT", ad_gruppe_agenten="grp-it-agenten")
        settings = Settings.get_or_create()
        settings.ad_gruppe_user = "grp-user"
        db.session.commit()

        ldap_user = LdapUser(anzeigename="Ghost", email="ghost@example.local", gruppen=["andere-gruppe"])
        result = sync_user_from_ldap("ghost", ldap_user, settings)

        assert result is None
        assert User.query.filter_by(ad_username="ghost").first() is None


def test_sync_user_from_ldap_creates_agent_for_team_group(app, make_team):
    with app.app_context():
        team = make_team(name="IT", ad_gruppe_agenten="grp-it-agenten")
        settings = Settings.get_or_create()
        settings.ad_gruppe_user = "grp-user"
        db.session.commit()

        ldap_user = LdapUser(
            anzeigename="Jane Agent", email="jane@example.local", gruppen=["grp-it-agenten"]
        )
        result = sync_user_from_ldap("jagent", ldap_user, settings)

        assert result is not None
        assert result.ist_agent_von(team.id)
        assert result.anzeigename == "Jane Agent"


def test_sync_user_from_ldap_updates_existing_user_on_repeat_login(app, make_team):
    with app.app_context():
        make_team(name="IT", ad_gruppe_agenten="grp-it-agenten")
        settings = Settings.get_or_create()
        settings.ad_gruppe_user = "grp-user"
        db.session.commit()

        ldap_user_v1 = LdapUser(anzeigename="Jane", email="jane@old.local", gruppen=["grp-user"])
        first = sync_user_from_ldap("jane", ldap_user_v1, settings)
        first_id = first.id

        ldap_user_v2 = LdapUser(anzeigename="Jane Doe", email="jane@new.local", gruppen=["grp-user"])
        second = sync_user_from_ldap("jane", ldap_user_v2, settings)

        assert second.id == first_id
        assert second.email == "jane@new.local"
        assert User.query.filter_by(ad_username="jane").count() == 1
