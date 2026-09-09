import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    # Relative sqlite:/// URIs werden von Flask-SQLAlchemy automatisch
    # relativ zum instance/-Ordner der App aufgelöst.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///slothtix.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Harte Obergrenze für die gesamte Request-Größe (Schutz vor
    # überdimensionierten Uploads, unabhängig vom admin-konfigurierbaren
    # Pro-Datei-Limit in den Settings).
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

    # Geheimnisse für LDAP/SMTP kommen bewusst aus Env-Vars, nicht aus der
    # (admin-editierbaren) Settings-Tabelle - siehe REQUIREMENTS.md Abschnitt 5.
    LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
