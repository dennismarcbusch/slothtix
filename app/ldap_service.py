"""LDAP-Bind-Authentifizierung gegen einen Univention Corporate Server (UCS).

Der eigentliche Verbindungsaufbau läuft über eine austauschbare
`connection_factory`, damit die Anmeldelogik in Tests ohne echten
LDAP-Server geprüft werden kann.
"""

import logging
import ssl
from dataclasses import dataclass, field

from flask import current_app
from ldap3 import Connection, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPInvalidDnError
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import parse_dn

logger = logging.getLogger(__name__)

_ca_cert_warning_logged = False


@dataclass
class LdapUser:
    anzeigename: str
    email: str
    gruppen: list = field(default_factory=list)


class LdapAuthError(Exception):
    """Anmeldedaten ungültig oder LDAP-Verzeichnis nicht erreichbar."""


def _build_tls(ca_cert_path):
    """Baut die TLS-Konfiguration für den LDAPS-Verbindungsaufbau.

    Ohne konfigurierten CA-Zertifikatspfad validiert ldap3 das
    Server-Zertifikat standardmäßig gar nicht (CERT_NONE) - das
    funktioniert zwar, ist aber anfällig für Man-in-the-Middle. Mit
    LDAP_CA_CERT_PATH wird stattdessen echte Zertifikatsprüfung gegen
    die (meist UCS-eigene) CA erzwungen."""
    global _ca_cert_warning_logged
    if ca_cert_path:
        return Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca_cert_path)

    if not _ca_cert_warning_logged:
        logger.warning(
            "LDAP_CA_CERT_PATH ist nicht gesetzt - die TLS-Zertifikatsprüfung "
            "gegen den LDAP-Server ist deaktiviert (anfällig für "
            "Man-in-the-Middle). Für den produktiven Einsatz sollte die "
            "CA-Zertifikatsdatei der UCS eingebunden werden."
        )
        _ca_cert_warning_logged = True
    return None


def _default_connection_factory(settings):
    tls = _build_tls(current_app.config.get("LDAP_CA_CERT_PATH"))
    # Kein get_info=ALL: wir lesen server.schema nirgendwo, aber ldap3
    # würde mit geladenem Schema unseren Suchfilter strikt dagegen
    # validieren - "sAMAccountName" existiert im (Open)LDAP-Schema von
    # UCS nicht (nur im AD-Schema), was den Bind mit
    # LDAPAttributeError zum Absturz bringen würde.
    server = Server(
        settings.ldap_server,
        port=settings.ldap_port,
        use_ssl=settings.ldap_use_ssl,
        tls=tls,
    )

    def factory(user_dn, password):
        return Connection(server, user=user_dn, password=password, auto_bind=True)

    return factory


def authenticate(settings, bind_password, username, password, connection_factory=None):
    """Prüft Benutzername/Passwort per LDAP-Bind gegen UCS.

    Liefert bei Erfolg ein `LdapUser` (Anzeigename, E-Mail, Gruppen-CNs).
    Wirft `LdapAuthError`, wenn die Zugangsdaten falsch sind, der Nutzer
    unbekannt ist, oder das Verzeichnis nicht erreichbar ist.
    """
    if not settings.ldap_bind_dn or not settings.ldap_base_dn or not settings.ldap_server:
        raise LdapAuthError("LDAP ist nicht konfiguriert.")

    if connection_factory is None:
        connection_factory = _default_connection_factory(settings)

    try:
        search_conn = connection_factory(settings.ldap_bind_dn, bind_password)
    except LDAPException as exc:
        logger.error("LDAP-Service-Bind fehlgeschlagen: %s", exc)
        raise LdapAuthError("LDAP-Verzeichnis nicht erreichbar.") from exc

    try:
        safe_username = escape_filter_chars(username)
        search_filter = f"(|(uid={safe_username})(sAMAccountName={safe_username}))"
        search_conn.search(
            settings.ldap_base_dn,
            search_filter,
            attributes=["cn", "mail", "displayName", "memberOf"],
        )
        if not search_conn.entries:
            raise LdapAuthError("Unbekannter Benutzer.")

        entry = search_conn.entries[0]
        user_dn = entry.entry_dn
        anzeigename = str(entry.displayName) if "displayName" in entry else str(entry.cn)
        email = str(entry.mail) if "mail" in entry else ""
        gruppen = _extract_group_names(entry)
    finally:
        search_conn.unbind()

    try:
        user_conn = connection_factory(user_dn, password)
    except LDAPBindError as exc:
        raise LdapAuthError("Benutzername oder Passwort falsch.") from exc
    except LDAPException as exc:
        logger.error("LDAP-Bind fehlgeschlagen: %s", exc)
        raise LdapAuthError("LDAP-Verzeichnis nicht erreichbar.") from exc
    user_conn.unbind()

    return LdapUser(anzeigename=anzeigename, email=email, gruppen=gruppen)


def _extract_group_names(entry):
    """Extrahiert den CN (bzw. den Wert der ersten RDN-Komponente) aus
    jeder memberOf-DN. Nutzt ldap3s eigenen DN-Parser statt eines naiven
    Komma-Splits, da RDN-Werte escapte Kommas enthalten können (z. B.
    "CN=Doe\\, John,OU=Groups,..."), was ein simples split(",") zerstören
    würde und Gruppenmitgliedschafts-Vergleiche stillschweigend fehlschlagen
    ließe."""
    if "memberOf" not in entry or not entry.memberOf:
        return []
    names = []
    for dn in entry.memberOf:
        try:
            components = parse_dn(str(dn))
        except LDAPInvalidDnError:
            logger.warning("Ungültige DN in memberOf ignoriert: %r", dn)
            continue
        if components:
            names.append(components[0][1])
    return names
