import smtplib
import ssl
from email.mime.text import MIMEText

from flask import current_app

from app.models import Settings

_tls_warnung_geloggt = False


def _tls_context():
    """TLS-Kontext für STARTTLS.

    smtplib baut ohne übergebenen Kontext einen mit
    ssl._create_stdlib_context() - der prüft weder Zertifikat noch
    Hostname. Die Verbindung wäre damit zwar verschlüsselt, aber nicht
    authentifiziert: Wer sich dazwischenhängt, liest SMTP-Benutzername
    und -Passwort im Klartext mit. Deshalb hier explizit ein
    prüfender Kontext."""
    global _tls_warnung_geloggt

    if current_app.config.get("SMTP_TLS_INSECURE"):
        if not _tls_warnung_geloggt:
            current_app.logger.warning(
                "SMTP_TLS_INSECURE ist gesetzt - das Zertifikat des "
                "Mailservers wird nicht geprüft (anfällig für "
                "Man-in-the-Middle). Besser das CA-Zertifikat über "
                "SMTP_CA_CERT_PATH einbinden."
            )
            _tls_warnung_geloggt = True
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    return ssl.create_default_context(cafile=current_app.config.get("SMTP_CA_CERT_PATH"))


def _kopfzeilentauglich(text):
    """Entfernt Zeilenumbrüche aus einem Header-Wert.

    Der Betreff enthält den Ticket-Titel, also freien Nutzertext. Steckt
    darin ein Zeilenumbruch, wirft msg.as_string() einen HeaderParseError -
    der wandert unten in das pauschale except und die Benachrichtigung
    verschwindet lautlos. (Ein Header-Injection-Risiko besteht dank dieser
    Prüfung in Python nicht; hier geht es darum, dass die Mail überhaupt
    ankommt.)"""
    return " ".join(text.split())


def send_mail(to_address, subject, body):
    """Verschickt eine einzelne Text-E-Mail."""
    send_mails([(to_address, subject, body)])


def send_mails(nachrichten):
    """Verschickt mehrere E-Mails über *eine* SMTP-Verbindung.

    Zuvor baute jede einzelne Benachrichtigung ihre eigene Verbindung auf
    (mit je 10 s Timeout) und lud die Settings neu. Bei einem Team mit
    fünfzehn Agenten hing das Anlegen eines Tickets damit im
    schlimmsten Fall minutenlang, bevor der Nutzer seine Weiterleitung sah.

    Schlägt der Versand fehl (kein SMTP konfiguriert, Server nicht
    erreichbar, ...), wird das nur geloggt - ein Benachrichtigungsfehler
    darf keine sonstige Aktion (Ticket anlegen, kommentieren, ...)
    verhindern.
    """
    nachrichten = [(to, betreff, text) for to, betreff, text in nachrichten if to]
    if not nachrichten:
        return

    settings = Settings.get_or_create()
    if not settings.smtp_host:
        # WARNING statt INFO: Gunicorn/Produktions-Setups filtern INFO oft
        # weg, wodurch dieser (durchaus relevante) Hinweis sonst spurlos
        # im Log verschwindet.
        current_app.logger.warning(
            "SMTP nicht konfiguriert, %d E-Mail(s) nicht gesendet: %s",
            len(nachrichten),
            ", ".join(betreff for _, betreff, _ in nachrichten),
        )
        return

    absender = settings.smtp_from or "slothtix@localhost"

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port or 25, timeout=10) as server:
            if current_app.config.get("SMTP_USE_TLS"):
                server.starttls(context=_tls_context())
            password = current_app.config.get("SMTP_PASSWORD")
            if settings.smtp_username and password:
                server.login(settings.smtp_username, password)

            for to_address, subject, body in nachrichten:
                msg = MIMEText(body)
                msg["Subject"] = _kopfzeilentauglich(subject)
                msg["From"] = absender
                msg["To"] = to_address
                try:
                    server.sendmail(absender, [to_address], msg.as_string())
                except Exception as exc:  # noqa: BLE001
                    # Einzelne kaputte Empfängeradresse darf die übrigen
                    # Empfänger derselben Benachrichtigung nicht mitreißen.
                    current_app.logger.warning(
                        "E-Mail-Versand an %s fehlgeschlagen: %s", to_address, exc
                    )
    except Exception as exc:  # noqa: BLE001 - Versandfehler dürfen nie hochgereicht werden
        current_app.logger.warning("E-Mail-Versand fehlgeschlagen: %s", exc)
