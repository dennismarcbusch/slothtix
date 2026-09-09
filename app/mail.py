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


def send_mail(to_address, subject, body):
    """Verschickt eine einfache Text-E-Mail. Schlägt der Versand fehl (kein
    SMTP konfiguriert, Server nicht erreichbar, ...), wird das nur geloggt -
    ein Benachrichtigungsfehler darf keine sonstige Aktion (Ticket anlegen,
    kommentieren, ...) verhindern."""
    if not to_address:
        return

    settings = Settings.get_or_create()
    if not settings.smtp_host:
        # WARNING statt INFO: Gunicorn/Produktions-Setups filtern INFO oft
        # weg, wodurch dieser (durchaus relevante) Hinweis sonst spurlos
        # im Log verschwindet.
        current_app.logger.warning(
            "SMTP nicht konfiguriert, E-Mail an %s nicht gesendet: %s",
            to_address,
            subject,
        )
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or "slothtix@localhost"
    msg["To"] = to_address

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port or 25, timeout=10) as server:
            if current_app.config.get("SMTP_USE_TLS"):
                server.starttls(context=_tls_context())
            password = current_app.config.get("SMTP_PASSWORD")
            if settings.smtp_username and password:
                server.login(settings.smtp_username, password)
            server.sendmail(msg["From"], [to_address], msg.as_string())
    except Exception as exc:  # noqa: BLE001 - Versandfehler dürfen nie hochgereicht werden
        current_app.logger.warning("E-Mail-Versand an %s fehlgeschlagen: %s", to_address, exc)
