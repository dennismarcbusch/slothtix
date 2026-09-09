import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


# Werte, die zwar "gesetzt" sind, aber aus der Beispielkonfiguration bzw.
# einem alten Default stammen und deshalb als öffentlich bekannt gelten
# müssen. Mit einem bekannten SECRET_KEY lässt sich ein Session-Cookie für
# eine beliebige Benutzer-ID (inkl. Admin) selbst signieren - der Login wäre
# damit vollständig umgehbar.
UNSICHERE_SECRET_KEYS = {"dev-secret-key-change-me", "change-me", "changeme"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    # Relative sqlite:/// URIs werden von Flask-SQLAlchemy automatisch
    # relativ zum instance/-Ordner der App aufgelöst.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///slothtix.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Harte Obergrenze für die gesamte Request-Größe (Schutz vor
    # überdimensionierten Uploads). Das admin-konfigurierbare Pro-Datei-
    # Limit in den Settings ist über dieselbe Konstante gedeckelt (siehe
    # forms.SettingsForm) - sonst könnte ein Admin dort einen Wert
    # einstellen, den der Server gar nicht erst entgegennimmt, und Nutzer
    # bekämen statt der freundlichen Meldung ein nacktes 413.
    MAX_UPLOAD_MB = 50
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

    # Geheimnisse für LDAP/SMTP kommen bewusst aus Env-Vars, nicht aus der
    # (admin-editierbaren) Settings-Tabelle - siehe REQUIREMENTS.md Abschnitt 5.
    LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD")
    # Pfad zur CA-Zertifikatsdatei (PEM) für die TLS-Prüfung der
    # LDAPS-Verbindung, z. B. die UCS-eigene Root-CA. Ohne diesen Pfad
    # wird das Server-Zertifikat nicht validiert (siehe ldap_service.py).
    LDAP_CA_CERT_PATH = os.environ.get("LDAP_CA_CERT_PATH")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    # Optionaler Pfad zu einer CA-Zertifikatsdatei (PEM) für die
    # STARTTLS-Prüfung des Mailservers - analog zu LDAP_CA_CERT_PATH, z. B.
    # wenn der Mailserver ein Zertifikat der schuleigenen CA nutzt. Ohne
    # Angabe werden die System-CAs verwendet.
    SMTP_CA_CERT_PATH = os.environ.get("SMTP_CA_CERT_PATH")
    # Notausgang für Mailserver mit selbstsigniertem Zertifikat, das sich
    # nicht über eine CA-Datei einbinden lässt. Schaltet die Prüfung
    # vollständig ab und macht die Verbindung angreifbar - nur bewusst
    # setzen.
    SMTP_TLS_INSECURE = os.environ.get("SMTP_TLS_INSECURE", "false").lower() == "true"

    # Hinter einem TLS-terminierenden Reverse-Proxy (z. B. Caddy) setzen:
    # Session-Cookie wird nur noch über HTTPS übertragen, und url_for(...,
    # _external=True) (z. B. Ticket-Links in Benachrichtigungs-E-Mails)
    # erzeugt https://-URLs statt http://. Lokal beim Entwickeln ohne
    # Proxy/TLS auf false lassen, sonst funktioniert der Login nicht.
    FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "false").lower() == "true"
    SESSION_COOKIE_SECURE = FORCE_HTTPS
    PREFERRED_URL_SCHEME = "https" if FORCE_HTTPS else "http"

    # Das Session-Cookie soll bei Anfragen von fremden Seiten nicht
    # mitgeschickt werden. Die CSRF-Token sind die eigentliche Absicherung,
    # SameSite ist die zweite Ebene darunter.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Absolute Obergrenze für die Lebensdauer einer Anmeldung. Der
    # AD-Abgleich läuft nur beim Login (Just-in-Time, siehe
    # REQUIREMENTS.md 3.2), eine Sitzung überdauert den Entzug einer
    # AD-Gruppe also bis hierher - und nicht länger. Bewusst absolut und
    # nicht als Leerlauf-Zeitfenster: Sonst könnte eine dauerhaft geöffnete
    # Registerkarte die Sitzung unbegrenzt am Leben halten.
    SESSION_MAX_ALTER = timedelta(hours=8)
    PERMANENT_SESSION_LIFETIME = SESSION_MAX_ALTER
