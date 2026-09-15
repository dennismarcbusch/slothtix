"""LDAP-Bind-Authentifizierung gegen einen Univention Corporate Server (UCS).

Der eigentliche Verbindungsaufbau läuft über eine austauschbare
`connection_factory`, damit die Anmeldelogik in Tests ohne echten
LDAP-Server geprüft werden kann.
"""

import logging
import ssl
from dataclasses import dataclass, field

from flask import current_app
from ldap3 import NONE as NO_INFO
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
    # get_info=NONE (explizit!): Server() holt per Default bereits
    # get_info='SCHEMA', auch ohne dass man es angibt. Mit geladenem
    # Schema validiert ldap3 unseren Suchfilter strikt dagegen -
    # "sAMAccountName" existiert im (Open)LDAP-Schema von UCS nicht
    # (nur im AD-Schema), was den Bind mit LDAPAttributeError zum
    # Absturz bringt. Wir lesen server.schema nirgendwo, daher komplett
    # deaktivieren statt nur "nicht explizit anfordern".
    server = Server(
        settings.ldap_server,
        port=settings.ldap_port,
        use_ssl=settings.ldap_use_ssl,
        tls=tls,
        get_info=NO_INFO,
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
        entry = _suche_eintrag(search_conn, settings, username)
        if entry is None:
            raise LdapAuthError("Unbekannter Benutzer.")
        user_dn = entry.entry_dn
        ldap_user = _ldap_user_aus_eintrag(entry, username)
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

    return ldap_user


def lookup_users(settings, bind_password, usernames, connection_factory=None):
    """Schlägt Nutzer nur mit dem Service-Konto nach, ohne deren Passwort.

    Liefert `{username: LdapUser}`; im Verzeichnis nicht gefundene Nutzer
    fehlen im Ergebnis. Jeder Fehler während der Suche bricht komplett mit
    `LdapAuthError` ab: Ein Teilergebnis sähe sonst so aus, als wären die
    restlichen Nutzer aus dem AD verschwunden."""
    if not settings.ldap_bind_dn or not settings.ldap_base_dn or not settings.ldap_server:
        raise LdapAuthError("LDAP ist nicht konfiguriert.")

    if connection_factory is None:
        connection_factory = _default_connection_factory(settings)

    try:
        conn = connection_factory(settings.ldap_bind_dn, bind_password)
    except LDAPException as exc:
        logger.error("LDAP-Service-Bind fehlgeschlagen: %s", exc)
        raise LdapAuthError("LDAP-Verzeichnis nicht erreichbar.") from exc

    gefunden = {}
    try:
        for username in usernames:
            entry = _suche_eintrag(conn, settings, username)
            # ldap3 wirft bei Suchfehlern (z. B. nicht existierende
            # Base-DN) standardmäßig keine Exception, sondern liefert nur
            # keine Einträge - daher den Ergebniscode selbst prüfen.
            if conn.result.get("result") != 0:
                raise LdapAuthError(
                    f"LDAP-Suche fehlgeschlagen: {conn.result.get('description')}"
                )
            if entry is not None:
                gefunden[username] = _ldap_user_aus_eintrag(entry, username)
    except LDAPException as exc:
        logger.error("LDAP-Suche fehlgeschlagen: %s", exc)
        raise LdapAuthError("LDAP-Verzeichnis nicht erreichbar.") from exc
    finally:
        conn.unbind()

    return gefunden


def _suche_eintrag(conn, settings, username):
    safe_username = escape_filter_chars(username)
    conn.search(
        settings.ldap_base_dn,
        f"(|(uid={safe_username})(sAMAccountName={safe_username}))",
        attributes=["cn", "mail", "displayName", "memberOf"],
    )
    return conn.entries[0] if conn.entries else None


def _ldap_user_aus_eintrag(entry, username):
    return LdapUser(
        anzeigename=_attribute_value(entry, "displayName") or _attribute_value(entry, "cn") or username,
        email=_attribute_value(entry, "mail") or "",
        gruppen=_extract_group_names(entry),
    )


def _attribute_value(entry, name):
    """Liefert den Einzelwert eines LDAP-Attributs, oder None, falls es
    fehlt ODER zwar vorhanden, aber leer ist.

    `name in entry` allein reicht nicht: ldap3 liefert dafür auch dann
    True, wenn das Attribut existiert, aber ohne Wert ist - str() auf
    einem solchen leeren Attribut ergibt dann fälschlich den *Text*
    "[]" statt eines Leerstrings (reproduziert und verifiziert gegen
    die echte ldap3-Bibliothek). Das hätte z. B. "[]" als E-Mail-
    Empfänger an smtplib weitergereicht."""
    if name not in entry:
        return None
    value = entry[name].value
    return str(value) if value is not None else None


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
