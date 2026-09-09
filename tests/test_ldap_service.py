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


def test_authenticate_handles_group_dn_with_escaped_comma():
    entry = FakeEntry(
        "uid=jdoe,dc=example,dc=local",
        displayName="Jane Doe",
        mail="jane@example.local",
        memberOf=[r"cn=Doe\, John,ou=Groups,dc=example,dc=local", "cn=IT-Agenten,dc=example,dc=local"],
    )
    settings = FakeSettings()
    users = {"jdoe": {"dn": "uid=jdoe,dc=example,dc=local", "password": "secret", "entry": entry}}
    factory = make_connection_factory(settings.ldap_bind_dn, "servicepw", users)

    result = authenticate(settings, "servicepw", "jdoe", "secret", connection_factory=factory)

    assert "IT-Agenten" in result.gruppen
    assert not any("Groups" in g for g in result.gruppen)


def test_build_tls_without_ca_path_returns_none():
    from app.ldap_service import _build_tls

    assert _build_tls(None) is None


def test_build_tls_with_ca_path_requires_verification(tmp_path):
    import ssl

    from app.ldap_service import _build_tls

    fake_cert = tmp_path / "ca.pem"
    fake_cert.write_text("not a real cert, just for path testing")

    tls = _build_tls(str(fake_cert))

    assert tls is not None
    assert tls.validate == ssl.CERT_REQUIRED
    assert tls.ca_certs_file == str(fake_cert)
