import smtplib
from email.mime.text import MIMEText

from flask import current_app

from app.models import Settings


def send_mail(to_address, subject, body):
    """Verschickt eine einfache Text-E-Mail. Schlägt der Versand fehl (kein
    SMTP konfiguriert, Server nicht erreichbar, ...), wird das nur geloggt -
    ein Benachrichtigungsfehler darf keine sonstige Aktion (Ticket anlegen,
    kommentieren, ...) verhindern."""
    if not to_address:
        return

    settings = Settings.get_or_create()
    if not settings.smtp_host:
        current_app.logger.info(
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
                server.starttls()
            password = current_app.config.get("SMTP_PASSWORD")
            if settings.smtp_username and password:
                server.login(settings.smtp_username, password)
            server.sendmail(msg["From"], [to_address], msg.as_string())
    except Exception as exc:  # noqa: BLE001 - Versandfehler dürfen nie hochgereicht werden
        current_app.logger.warning("E-Mail-Versand an %s fehlgeschlagen: %s", to_address, exc)
