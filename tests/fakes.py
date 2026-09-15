"""Fakes für LDAP-Tests ohne echten UCS-Server."""

from ldap3.core.exceptions import LDAPBindError


class FakeAttribute:
    """Mimics ldap3's real Attribute duck type just enough for our code:
    `.value`, truthiness/iteration over the raw value, and str() that
    reproduces ldap3's real (surprising) behavior of rendering an empty
    attribute as the literal text "[]" rather than an empty string -
    the exact behavior that caused a real production bug. Keeping this
    faithful is the point: a fake that's *too* simple is what let that
    bug slip through the test suite in the first place."""

    def __init__(self, value):
        self._value = value

    @property
    def value(self):
        return self._value

    def __bool__(self):
        return bool(self._value)

    def __iter__(self):
        return iter(self._value or [])

    def __str__(self):
        return str(self._value) if self._value else "[]"


class FakeEntry:
    def __init__(self, dn, cn=None, mail=None, displayName=None, memberOf=None):
        self.entry_dn = dn
        self._data = {
            "cn": cn,
            "mail": mail,
            "displayName": displayName,
            "memberOf": memberOf or [],
        }

    def __contains__(self, key):
        # Wie ldap3: True, sobald das Attribut bekannt ist - auch wenn
        # es (noch) keinen Wert hat.
        return key in self._data

    def __getitem__(self, key):
        return FakeAttribute(self._data.get(key))

    def __getattr__(self, key):
        return FakeAttribute(self._data.get(key))


class FakeSearchConnection:
    def __init__(self, users):
        self.users = users
        self.entries = []
        self.result = {"result": 0, "description": "success"}

    def search(self, base_dn, search_filter, attributes):
        for username, info in self.users.items():
            if f"uid={username}" in search_filter or f"sAMAccountName={username}" in search_filter:
                self.entries = [info["entry"]]
                return
        self.entries = []

    def unbind(self):
        pass


class FakeUserConnection:
    def unbind(self):
        pass


def make_connection_factory(service_dn, service_password, users):
    """users: {username: {"dn": ..., "password": ..., "entry": FakeEntry}}"""

    def factory(user, password):
        if user == service_dn:
            if password != service_password:
                raise LDAPBindError("Service-Bind fehlgeschlagen")
            return FakeSearchConnection(users)

        for info in users.values():
            if info["dn"] == user:
                if info["password"] != password:
                    raise LDAPBindError("Benutzer-Bind fehlgeschlagen")
                return FakeUserConnection()

        raise LDAPBindError("Unbekannter DN")

    return factory


class FakeSettings:
    def __init__(
        self,
        ldap_server="fake-server",
        ldap_bind_dn="cn=service,dc=example,dc=local",
        ldap_base_dn="dc=example,dc=local",
        ad_gruppe_user="SlothTix-User",
    ):
        self.ldap_server = ldap_server
        self.ldap_bind_dn = ldap_bind_dn
        self.ldap_base_dn = ldap_base_dn
        self.ad_gruppe_user = ad_gruppe_user
