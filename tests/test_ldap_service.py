import pytest

from app.ldap_service import LdapAuthError, authenticate
from tests.fakes import FakeEntry, FakeSettings, make_connection_factory


def test_authenticate_success_returns_display_name_email_and_groups():
    entry = FakeEntry(
        "uid=jdoe,dc=example,dc=local",
        displayName="Jane Doe",
        mail="jane@example.local",
        memberOf=["cn=IT-Agenten,dc=example,dc=local", "cn=SlothTix-User,dc=example,dc=local"],
    )
    settings = FakeSettings()
    users = {"jdoe": {"dn": "uid=jdoe,dc=example,dc=local", "password": "secret", "entry": entry}}
    factory = make_connection_factory(settings.ldap_bind_dn, "servicepw", users)

    result = authenticate(settings, "servicepw", "jdoe", "secret", connection_factory=factory)

    assert result.anzeigename == "Jane Doe"
    assert result.email == "jane@example.local"
    assert set(result.gruppen) == {"IT-Agenten", "SlothTix-User"}


def test_authenticate_falls_back_to_cn_without_display_name():
    entry = FakeEntry("uid=jdoe,dc=example,dc=local", cn="jdoe")
    settings = FakeSettings()
    users = {"jdoe": {"dn": "uid=jdoe,dc=example,dc=local", "password": "secret", "entry": entry}}
    factory = make_connection_factory(settings.ldap_bind_dn, "servicepw", users)

    result = authenticate(settings, "servicepw", "jdoe", "secret", connection_factory=factory)

    assert result.anzeigename == "jdoe"


def test_authenticate_wrong_password_raises():
    entry = FakeEntry("uid=jdoe,dc=example,dc=local", displayName="Jane Doe")
    settings = FakeSettings()
    users = {"jdoe": {"dn": "uid=jdoe,dc=example,dc=local", "password": "secret", "entry": entry}}
    factory = make_connection_factory(settings.ldap_bind_dn, "servicepw", users)

    with pytest.raises(LdapAuthError):
        authenticate(settings, "servicepw", "jdoe", "wrong", connection_factory=factory)


def test_authenticate_unknown_user_raises():
    settings = FakeSettings()
    factory = make_connection_factory(settings.ldap_bind_dn, "servicepw", {})

    with pytest.raises(LdapAuthError):
        authenticate(settings, "servicepw", "ghost", "whatever", connection_factory=factory)


def test_authenticate_service_bind_failure_raises():
    settings = FakeSettings()
    factory = make_connection_factory(settings.ldap_bind_dn, "servicepw", {})

    with pytest.raises(LdapAuthError):
        authenticate(settings, "wrong-service-pw", "jdoe", "secret", connection_factory=factory)


def test_authenticate_requires_configured_settings():
    settings = FakeSettings(ldap_server=None, ldap_bind_dn=None, ldap_base_dn=None)

    with pytest.raises(LdapAuthError):
        authenticate(settings, "servicepw", "jdoe", "secret", connection_factory=lambda u, p: None)
