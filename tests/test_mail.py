import ssl

from app.mail import send_mail
from app.models import Settings


def test_send_mail_noop_without_smtp_configured(app):
    with app.app_context():
        # Frische DB ohne konfiguriertes SMTP -> darf nicht crashen.
        send_mail("someone@example.local", "Betreff", "Text")


def test_send_mail_sends_via_smtp_when_configured(app, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            sent["starttls_context"] = context

        def login(self, username, password):
            sent["login"] = (username, password)

        def sendmail(self, from_addr, to_addrs, message):
            sent["from"] = from_addr
            sent["to"] = to_addrs
            sent["message"] = message

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    with app.app_context():
        settings = Settings.get_or_create()
        settings.smtp_host = "mail.example.local"
        settings.smtp_port = 587
        settings.smtp_username = "slothtix"
        settings.smtp_from = "slothtix@example.local"
        from app.extensions import db

        db.session.commit()
        app.config["SMTP_PASSWORD"] = "geheim"

        send_mail("empfaenger@example.local", "Betreff", "Nachrichtentext")

    assert sent["host"] == "mail.example.local"
    assert sent["port"] == 587
    assert sent["login"] == ("slothtix", "geheim")
    # STARTTLS muss mit einem prüfenden Kontext aufgebaut werden.
    assert sent["starttls_context"].verify_mode == ssl.CERT_REQUIRED
    assert sent["starttls_context"].check_hostname is True
    assert sent["to"] == ["empfaenger@example.local"]
    assert "Nachrichtentext" in sent["message"]


def test_send_mail_swallows_smtp_errors(app, monkeypatch):
    def raise_error(*args, **kwargs):
        raise OSError("Verbindung fehlgeschlagen")

    monkeypatch.setattr("smtplib.SMTP", raise_error)

    with app.app_context():
        settings = Settings.get_or_create()
        settings.smtp_host = "mail.example.local"
        from app.extensions import db

        db.session.commit()

        # Darf keine Exception nach außen werfen.
        send_mail("empfaenger@example.local", "Betreff", "Text")


def test_smtp_tls_insecure_schaltet_die_pruefung_ab(app, monkeypatch):
    """Notausgang für selbstsignierte Zertifikate - muss ausdrücklich
    gesetzt werden und darf nicht der Standard sein."""
    erfasst = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            erfasst["context"] = context

        def sendmail(self, *args):
            pass

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    with app.app_context():
        from app.extensions import db

        settings = Settings.get_or_create()
        settings.smtp_host = "mail.example.local"
        db.session.commit()
        app.config["SMTP_TLS_INSECURE"] = True

        send_mail("empfaenger@example.local", "Betreff", "Text")

    assert erfasst["context"].verify_mode == ssl.CERT_NONE
    assert erfasst["context"].check_hostname is False
