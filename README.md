# SlothTix

Ein bewusst schlankes Ticket-System für den Einsatz an einer Schule – als
Alternative zu bestehenden Lösungen, die oft zu groß, zu kompliziert sind
oder deren Kernfunktionen fehlerhaft sind.

Erste Nutzergruppen sind das IT-Team und das Hausmeister-Team; weitere Teams
(z. B. Verwaltung) lassen sich später ohne Code-Änderung ergänzen.

## Funktionen

- **Tickets**: Titel, Beschreibung, Team, Priorität, Kategorie, Anhänge
- **Status-Workflow**: Offen → In Bearbeitung → Gelöst → Geschlossen, inkl.
  vollständiger Historie zu Status-, Zuweisungs- und Team-Änderungen
- **Teams**: frei konfigurierbar, mit je eigenen Kategorien
- **Rollen**: Admin (Teams & Konfiguration), Agent (bearbeitet Tickets seiner
  Teams), User (erstellt Tickets, sieht deren Status)
- **Authentifizierung per LDAP-Bind** gegen einen Univention Corporate Server
  (UCS) – es werden keine Passwörter lokal gespeichert; Rollen/Teams werden
  beim Login anhand der AD-Gruppenmitgliedschaft synchronisiert
- **E-Mail-Benachrichtigungen** per SMTP bei relevanten Ticket-Ereignissen

## Tech-Stack

Flask · SQLAlchemy · Flask-Migrate (Alembic) · Flask-Login · Flask-WTF ·
ldap3 · SQLite · Gunicorn (Produktion) · Caddy (Reverse Proxy/TLS)

## Installation

Primärer Betrieb ist per Docker Compose (siehe [docs/SETUP.md](docs/SETUP.md)
für die ausführliche Anleitung):

```bash
cp .env.example .env
# .env ausfüllen (siehe unten), dann:
docker compose up -d --build
```

`docker-compose.yml` startet zwei Dienste:
- `slothtix` – die Anwendung (Gunicorn, führt beim Start automatisch
  `flask db upgrade` aus)
- `caddy` – Reverse Proxy mit TLS auf Port 80/443

### Lokale Entwicklung ohne Docker

```bash
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # SECRET_KEY setzen, FORCE_HTTPS=false für lokal
flask --app wsgi:app db upgrade
flask --app wsgi:app run
```

## Konfiguration (`.env`)

| Variable | Bedeutung |
|---|---|
| `SECRET_KEY` | Pflicht – zufälliger, langer Wert (z. B. `openssl rand -hex 32`); die App startet ohne gültigen Wert nicht |
| `DATABASE_URL` | Datenbank-URL, standardmäßig SQLite |
| `ADMIN_USERNAME` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Initialer lokaler Admin-Bootstrap (nur beim allerersten Start relevant) |
| `LDAP_BIND_PASSWORD` | Bind-Passwort für die LDAP-Anbindung |
| `LDAP_CA_CERT_PATH` | Pfad zum CA-Zertifikat für LDAPS (Datei unter `./certs/` ablegen) |
| `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_CA_CERT_PATH`, `SMTP_TLS_INSECURE` | SMTP-Zugangsdaten und TLS-Prüfung für den Mailversand |
| `FORCE_HTTPS` | `true` (Standard); nur für lokale Entwicklung ohne Reverse Proxy auf `false` setzen |

Server-/Verbindungsdetails für LDAP und SMTP (Host, Base-DN, AD-Gruppen, …)
werden nicht über `.env`, sondern später über die Admin-Oberfläche unter
`/admin/einstellungen` konfiguriert.

## CLI-Befehle

- `flask create-admin` – legt den initialen Admin aus den `ADMIN_*`-Variablen an (läuft beim App-Start ohnehin automatisch)
- `flask tickets-purge [--alle | --vor JJJJ-MM-TT] [--verwaiste-dateien] [--ja]` – entfernt Test-Tickets vor dem Go-Live (Dry-Run ohne `--ja`)

## Tests

```bash
pytest
```

## Dokumentation

- [REQUIREMENTS.md](REQUIREMENTS.md) – was gebaut wurde und warum
- [docs/SETUP.md](docs/SETUP.md) – Installation & Konfiguration im Detail
- [docs/HANDBUCH_AGENTEN.md](docs/HANDBUCH_AGENTEN.md) – Handbuch für Team-Mitglieder
- [docs/HANDBUCH_USER.md](docs/HANDBUCH_USER.md) – Handbuch für alle übrigen Nutzer

## Lizenz

[CC BY-NC-SA 4.0](LICENSE) – Namensnennung erforderlich, keine kommerzielle
Nutzung ohne Erlaubnis, Weitergabe unter derselben Lizenz.
