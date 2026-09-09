"""Sperre gegen Passwort-Raten am Login (Brute Force / Password Spraying).

Jeder Anmeldeversuch führt zu einem echten LDAP-Bind gegen den UCS. Ohne
Begrenzung wäre SlothTix damit zweierlei: ein bequemer Automat zum
Durchprobieren von Domänen-Passwörtern und - bei aktiver
Lockout-Richtlinie im AD - ein Werkzeug, um fremde Konten gezielt sperren
zu lassen.

Gezählt wird in zwei getrennten Töpfen, weil beide Fälle unterschiedlich
gelagert sind:

* **je Benutzername** eng (fünf Versuche): Das ist der Topf, der gezieltes
  Raten eines einzelnen Kontos stoppt.
* **je IP** bewusst großzügig (fünfzig Versuche): In einer Schule sitzen
  alle Nutzer hinter derselben NAT-Adresse. Eine enge IP-Grenze würde
  regelmäßig das ganze Kollegium aussperren, sobald sich ein paar Leute
  vertippen. Der Topf greift daher erst bei Volumen, wie es beim
  Durchprobieren vieler verschiedener Benutzernamen entsteht.
"""

from datetime import timedelta

from sqlalchemy import func

from app.extensions import db
from app.models import LoginAttempt, utcnow

MAX_VERSUCHE_PRO_BENUTZER = 5
MAX_VERSUCHE_PRO_IP = 50
ZEITFENSTER = timedelta(minutes=15)


def _benutzer_schluessel(username):
    # casefold(), damit "Admin" und "admin" denselben Topf teilen - sonst
    # ließe sich die Sperre durch bloßes Ändern der Groß-/Kleinschreibung
    # umgehen.
    return f"user:{username.casefold()}"


def _ip_schluessel(ip):
    return f"ip:{ip}"


def _anzahl_seit(schluessel, seit):
    return (
        db.session.query(func.count(LoginAttempt.id))
        .filter(LoginAttempt.schluessel == schluessel, LoginAttempt.zeitstempel >= seit)
        .scalar()
    )


def ist_gesperrt(username, ip):
    """True, wenn für diesen Benutzernamen oder diese IP im aktuellen
    Zeitfenster bereits zu viele Fehlversuche gezählt wurden."""
    seit = utcnow() - ZEITFENSTER
    if _anzahl_seit(_benutzer_schluessel(username), seit) >= MAX_VERSUCHE_PRO_BENUTZER:
        return True
    return bool(ip) and _anzahl_seit(_ip_schluessel(ip), seit) >= MAX_VERSUCHE_PRO_IP


def merke_fehlversuch(username, ip):
    """Zählt einen Fehlversuch in beiden Töpfen und räumt dabei abgelaufene
    Einträge ab (kein separater Cron-Job nötig)."""
    db.session.add(LoginAttempt(schluessel=_benutzer_schluessel(username)))
    if ip:
        db.session.add(LoginAttempt(schluessel=_ip_schluessel(ip)))
    LoginAttempt.query.filter(LoginAttempt.zeitstempel < utcnow() - ZEITFENSTER).delete()
    db.session.commit()


def loesche_fehlversuche(username):
    """Nach erfolgreicher Anmeldung: Zähler dieses Benutzernamens leeren,
    damit ein paar Tippfehler nicht bis zum Ende des Zeitfensters
    nachwirken.

    Der IP-Topf bleibt bewusst stehen: Sonst könnte sich jemand, der ein
    einziges gültiges Konto besitzt, die IP-Grenze jederzeit selbst
    zurücksetzen und darunter beliebig weiter raten."""
    LoginAttempt.query.filter_by(schluessel=_benutzer_schluessel(username)).delete()
    db.session.commit()
