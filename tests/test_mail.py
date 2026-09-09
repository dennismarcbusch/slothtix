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

        def starttls(self):
            sent["starttls"] = True

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
