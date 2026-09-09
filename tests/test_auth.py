from app.auth import sync_user_from_ldap
from app.extensions import db
from app.ldap_service import LdapAuthError, LdapUser
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


def test_login_via_ldap_creates_agent_and_logs_in(app, client, make_team, monkeypatch):
    with app.app_context():
        make_team(name="IT", ad_gruppe_agenten="grp-it-agenten")
        settings = Settings.get_or_create()
        settings.ad_gruppe_user = "grp-user"
        db.session.commit()

    def fake_authenticate(settings, bind_password, username, password, connection_factory=None):
        return LdapUser(anzeigename="LDAP Agent", email="ldap@example.local", gruppen=["grp-it-agenten"])

    monkeypatch.setattr("app.auth.ldap_authenticate", fake_authenticate)

    response = client.post(
        "/login", data={"username": "ldapuser", "password": "whatever"}, follow_redirects=True
    )

    assert response.status_code == 200
    assert b"Tickets" in response.data

    with app.app_context():
        user = User.query.filter_by(ad_username="ldapuser").first()
        assert user is not None
        assert user.anzeigename == "LDAP Agent"
        assert user.ist_agent


def test_login_via_ldap_denies_access_without_group(app, client, make_team, monkeypatch):
    with app.app_context():
        make_team(name="IT", ad_gruppe_agenten="grp-it-agenten")
        settings = Settings.get_or_create()
        settings.ad_gruppe_user = "grp-user"
        db.session.commit()

    def fake_authenticate(settings, bind_password, username, password, connection_factory=None):
        return LdapUser(anzeigename="Ghost", email="ghost@example.local", gruppen=["andere-gruppe"])

    monkeypatch.setattr("app.auth.ldap_authenticate", fake_authenticate)

    response = client.post(
        "/login", data={"username": "ghost", "password": "whatever"}, follow_redirects=True
    )

    assert b"kein Zugriff auf SlothTix" in response.data
    with app.app_context():
        assert User.query.filter_by(ad_username="ghost").first() is None


def test_login_via_ldap_wrong_credentials_shows_generic_error(app, client, monkeypatch):
    def fake_authenticate(settings, bind_password, username, password, connection_factory=None):
        raise LdapAuthError("Benutzername oder Passwort falsch.")

    monkeypatch.setattr("app.auth.ldap_authenticate", fake_authenticate)

    response = client.post(
        "/login", data={"username": "someone", "password": "wrong"}, follow_redirects=True
    )

    assert b"Benutzername oder Passwort falsch" in response.data


def test_login_ignoriert_externes_next_ziel(client):
    """Open-Redirect-Schutz: ?next= darf nur auf einen internen Pfad zeigen."""
    response = client.post(
        "/login?next=https://evil.example.com/pwned",
        data={"username": "admin", "password": "adminpass"},
    )
    assert response.status_code == 302
    assert "evil.example.com" not in response.headers["Location"]


def test_login_ignoriert_protokollrelatives_next_ziel(client):
    response = client.post(
        "/login?next=//evil.example.com/pwned",
        data={"username": "admin", "password": "adminpass"},
    )
    assert response.status_code == 302
    assert "evil.example.com" not in response.headers["Location"]


def test_login_folgt_internem_next_ziel(client):
    response = client.post(
        "/login?next=/tickets/neu", data={"username": "admin", "password": "adminpass"}
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/tickets/neu")


def test_login_sperrt_nach_zu_vielen_fehlversuchen(client):
    from app.login_throttle import MAX_VERSUCHE_PRO_BENUTZER

    for _ in range(MAX_VERSUCHE_PRO_BENUTZER):
        response = client.post("/login", data={"username": "admin", "password": "falsch"})
        assert b"Benutzername oder Passwort falsch" in response.data

    gesperrt = client.post("/login", data={"username": "admin", "password": "falsch"})
    assert gesperrt.status_code == 429
    assert "Zu viele fehlgeschlagene Anmeldeversuche" in gesperrt.get_data(as_text=True)

    # Auch das richtige Passwort kommt während der Sperre nicht mehr durch.
    trotz_richtigem_passwort = client.post(
        "/login", data={"username": "admin", "password": "adminpass"}
    )
    assert trotz_richtigem_passwort.status_code == 429


def test_login_sperre_ignoriert_gross_kleinschreibung(client):
    from app.login_throttle import MAX_VERSUCHE_PRO_BENUTZER

    for _ in range(MAX_VERSUCHE_PRO_BENUTZER):
        client.post("/login", data={"username": "admin", "password": "falsch"})

    response = client.post("/login", data={"username": "ADMIN", "password": "falsch"})
    assert response.status_code == 429


def test_erfolgreicher_login_setzt_fehlversuchszaehler_zurueck(app, client):
    from app.login_throttle import MAX_VERSUCHE_PRO_BENUTZER
    from app.models import LoginAttempt

    for _ in range(MAX_VERSUCHE_PRO_BENUTZER - 1):
        client.post("/login", data={"username": "admin", "password": "falsch"})

    erfolg = client.post("/login", data={"username": "admin", "password": "adminpass"})
    assert erfolg.status_code == 302

    with app.app_context():
        assert LoginAttempt.query.filter_by(schluessel="user:admin").count() == 0


def test_fehlende_gruppenmitgliedschaft_zaehlt_nicht_als_fehlversuch(
    app, client, make_team, monkeypatch
):
    """Korrekte Zugangsdaten ohne passende AD-Gruppe sind kein Rateversuch -
    sonst sperrte sich ein berechtigter Nutzer durch bloßes Anmelden aus."""
    from app.models import LoginAttempt

    with app.app_context():
        make_team(name="IT", ad_gruppe_agenten="grp-it-agenten")
        settings = Settings.get_or_create()
        settings.ad_gruppe_user = "grp-user"
        db.session.commit()

    def fake_authenticate(settings, bind_password, username, password, connection_factory=None):
        return LdapUser(anzeigename="Ghost", email="ghost@example.local", gruppen=["andere"])

    monkeypatch.setattr("app.auth.ldap_authenticate", fake_authenticate)

    client.post("/login", data={"username": "ghost", "password": "richtig"})

    with app.app_context():
        assert LoginAttempt.query.count() == 0
