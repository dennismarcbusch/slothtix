"""Fakes für LDAP-Tests ohne echten UCS-Server."""

from ldap3.core.exceptions import LDAPBindError


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
        return bool(self._data.get(key))

    def __getattr__(self, key):
        return self._data.get(key)


class FakeSearchConnection:
    def __init__(self, users):
        self.users = users
        self.entries = []

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
