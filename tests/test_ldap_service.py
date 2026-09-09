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


def test_default_connection_factory_disables_schema_fetch(app, monkeypatch):
    """Regression: ldap3.Server() defaults to get_info='SCHEMA' even when
    the parameter is omitted entirely - merely not passing get_info=ALL
    (an earlier, incomplete fix) still left schema fetching on via that
    default. With a schema loaded, ldap3 validates our search filter's
    attribute names against it, and sAMAccountName (valid in AD's schema,
    not in plain OpenLDAP's) crashed every login with
    LDAPAttributeError('invalid attribute sAMAccountName') on a real UCS
    server. Asserts the effective value, not just "was it passed", since
    that distinction is exactly what let the incomplete fix through."""
    from ldap3 import NONE as NO_INFO

    from app import ldap_service
    from app.models import Settings

    captured = {}

    class FakeServer:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(ldap_service, "Server", FakeServer)

    with app.app_context():
        settings = Settings.get_or_create()
        settings.ldap_server = "ucs.example.local"
        settings.ldap_port = 636
        settings.ldap_use_ssl = True
        ldap_service._default_connection_factory(settings)

    assert captured.get("get_info") == NO_INFO


def test_attribute_value_handles_present_but_empty_attribute():
    """Regression: ldap3's `name in entry` is True even when the
    attribute exists with zero values (e.g. a UCS user whose 'mail'
    field was left blank). str() on such an attribute returns the
    literal text "[]", not an empty string - which was silently passed
    to smtplib as the recipient address ("Recipient address rejected:
    need fully-qualified address"). Uses a real ldap3 MOCK_SYNC entry
    (not our own FakeEntry) since this is exactly the ldap3-internal
    behavior under test."""
    from ldap3 import Connection, MOCK_SYNC, Server

    from app.ldap_service import _attribute_value

    server = Server("mock")
    conn = Connection(server, client_strategy=MOCK_SYNC)
    conn.strategy.add_entry(
        "uid=test,dc=example,dc=local",
        {"objectClass": "inetOrgPerson", "cn": "Test User", "mail": [], "displayName": []},
    )
    conn.bind()
    conn.search("dc=example,dc=local", "(uid=test)", attributes=["cn", "mail", "displayName"])
    entry = conn.entries[0]

    assert _attribute_value(entry, "mail") is None
    assert _attribute_value(entry, "displayName") is None
    assert _attribute_value(entry, "cn") == "Test User"
    assert _attribute_value(entry, "doesNotExist") is None
