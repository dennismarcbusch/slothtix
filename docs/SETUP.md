# SlothTix – Setup-Anleitung

Diese Anleitung beschreibt die Einrichtung einer neuen SlothTix-Instanz von
Grund auf, per Docker.

## Voraussetzungen

- Ein Linux-Server mit **Docker** und dem **Docker-Compose-Plugin**
  (`docker compose version` sollte funktionieren).
- Ein **DNS-A-Record**, der auf die öffentliche IP des Servers zeigt (nur für
  den Produktivbetrieb mit eigener Domain und HTTPS nötig).
- **Port 80 und 443** von außen auf den Server erreichbar (für Let's
  Encrypt und den eigentlichen Webverkehr).
- Ein **Univention Corporate Server (UCS)** mit einem dedizierten
  Service-Account für den LDAP-Zugriff (siehe unten) und mindestens einer
  AD-Gruppe für den User-Zugriff sowie je einer Gruppe pro Team.

## 1. Repository holen

```bash
git clone git@github.com:dennismarcbusch/slothtix.git
cd slothtix
```

Für den Zugriff über SSH wird ein Deploy-Key benötigt (Repo → Settings →
Deploy keys). Alternativ per HTTPS mit einem Personal Access Token.

## 2. `.env` einrichten

```bash
cp .env.example .env
```

Danach `.env` bearbeiten:

| Variable | Bedeutung |
|---|---|
| `SECRET_KEY` | **Pflichtfeld.** Zufälliger, langer String (z. B. `openssl rand -hex 32`). Ohne gesetzten Wert – oder mit einem Platzhalter wie `change-me` – verweigert die App den Start. |
| `DATABASE_URL` | In der Regel unverändert lassen (`sqlite:///slothtix.db`) |
| `ADMIN_USERNAME` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Zugangsdaten für den initialen, lokalen Admin-Account (nur beim allerersten Start relevant) |
| `LDAP_BIND_PASSWORD` | Passwort des LDAP-Service-Accounts (siehe unten) |
| `SMTP_PASSWORD` | Passwort des SMTP-Versand-Accounts |
| `SMTP_USE_TLS` | `true`, falls der Mailserver STARTTLS auf Port 587 anbietet (Standardfall) |
| `SMTP_CA_CERT_PATH` | Optional: CA-Zertifikat, falls der Mailserver ein Zertifikat der eigenen CA nutzt. Leer = System-CAs |
| `SMTP_TLS_INSECURE` | Notausgang für selbstsignierte Mailserver-Zertifikate – schaltet die Prüfung ab, nur bewusst setzen |
| `LDAP_CA_CERT_PATH` | Pfad zur CA-Zertifikatsdatei für die LDAPS-Prüfung (siehe unten) |
| `FORCE_HTTPS` | `true`, sobald Caddy als Reverse-Proxy davor läuft (siehe Abschnitt 5) – nur lokal ohne Proxy auf `false` setzen |

**Wichtig:** `.env` enthält Geheimnisse und darf nie ins Git-Repository
committet werden (ist bereits über `.gitignore` ausgeschlossen).

## 3. LDAP-Service-Account in UCS anlegen

1. In der Univention Management Console (UMC) unter **Benutzer** einen
   normalen Benutzer-Account anlegen, z. B. `svc.slothtix` (kein
   Join-Account verwenden – die sind für den Domänenbeitritt von Systemen
   gedacht, nicht als allgemeiner Lese-Account).
2. Keine besonderen Gruppenrechte nötig – Standard-Attribute
   (`cn`, `mail`, `displayName`, `memberOf`) sind für jeden authentifizierten
   Bind lesbar.
3. Die volle DN des Accounts notieren, z. B.:
   ```
   uid=svc.slothtix,cn=users,dc=eure-domaene,dc=schule
   ```
   Zu finden per `udm users/user list --filter uid=svc.slothtix` auf dem
   UCS-Server.
4. Die Base-DN der Domäne ermitteln:
   ```bash
   ucr get ldap/base
   ```

## 4. CA-Zertifikat für LDAPS bereitstellen

```bash
mkdir -p certs
curl -k -o certs/ucs-ca.pem https://<euer-ucs-host>/ucs-root-ca.crt
```

Pfad in `.env` unter `LDAP_CA_CERT_PATH=/app/certs/ucs-ca.pem` eintragen.

## 5. HTTPS-Reverse-Proxy (Produktivbetrieb)

Für den Betrieb unter einer eigenen Domain ist `Caddy` als Reverse-Proxy
bereits in `docker-compose.yml` konfiguriert und übernimmt die
Let's-Encrypt-Zertifikatsausstellung automatisch. Domain in der `Caddyfile`
anpassen:

```
eure-domain.schule {
    reverse_proxy slothtix:8000
}
```

Danach `FORCE_HTTPS=true` in `.env` setzen (siehe Schritt 2).

Für einen reinen Test **ohne** eigene Domain/DNS kann `docker-compose.yml`
vorübergehend so angepasst werden, dass `slothtix` direkt Port 8000
veröffentlicht (`ports: ["8000:8000"]`) und der `caddy`-Service entfällt –
dann ist die App nur per HTTP unter `http://<server-ip>:8000` erreichbar.

> **Nur für Tests.** In dieser Variante ist die App direkt erreichbar,
> vertraut aber weiterhin den `X-Forwarded-*`-Headern des (nicht mehr
> vorhandenen) Proxys. Jeder Client kann damit Host und Protokoll
> vortäuschen und so z. B. die Ticket-Links in Benachrichtigungs-E-Mails
> auf eine fremde Domain umlenken. Nicht dauerhaft so betreiben.

## 6. Bauen und starten

```bash
docker compose up -d --build
```

Bei aktivem Caddy-Setup: Zertifikatsstatus prüfen mit
`docker compose logs caddy -f` (Erfolg erkennbar an
„certificate obtained successfully").

## 7. Erste Anmeldung

Unter `https://eure-domain.schule` (bzw. `http://<server-ip>:8000` im
Testbetrieb) mit `ADMIN_USERNAME`/`ADMIN_PASSWORD` aus der `.env` anmelden.

## 8. LDAP und SMTP konfigurieren

Unter **Einstellungen** (als Admin):

- **LDAP-Server**: Hostname des UCS-Servers
- **LDAP-Port**: `636` für Standard-LDAPS. **Achtung bei UCS mit
  Active-Directory-kompatiblem Domänencontroller** (Samba4): dort läuft
  der AD-kompatible LDAPS-Dienst i. d. R. auf **Port 7636**, nicht 636 –
  bei „invalid credentials" trotz korrekter Zugangsdaten zuerst das prüfen.
- **LDAP über SSL/TLS**: aktiviert lassen
- **LDAP Base-DN**: aus Schritt 3
- **LDAP Bind-DN**: volle DN des Service-Accounts aus Schritt 3
- **AD-Gruppe (User-Zugriff)**: Name (nicht die volle DN!) der Gruppe, deren
  Mitglieder Tickets erstellen dürfen
- **SMTP-Server/-Port/-Benutzername/-Absenderadresse**: Zugangsdaten eures
  Mailservers (Port 587 mit STARTTLS wird unterstützt, Port 465 mit
  direktem TLS aktuell nicht). Das Serverzertifikat wird geprüft – bei
  einer eigenen CA `SMTP_CA_CERT_PATH` in der `.env` setzen.

**Anhänge:** Erlaubt sind `.png`, `.jpg`/`.jpeg`, `.gif` und `.pdf`. Geprüft
werden Endung *und* tatsächlicher Dateiinhalt; eine umbenannte Datei wird
abgelehnt.

Zum Testen der LDAP-Zugangsdaten unabhängig von SlothTix eignet sich
`ldapsearch` (siehe Fehlerdiagnose unten).

## 9. Teams und Kategorien anlegen

Unter **Teams**:

1. Für jedes Team (z. B. „IT", „Hausmeister") einen Eintrag mit Name und
   der zugehörigen AD-Gruppe (nur Gruppenname, keine DN) anlegen.
2. Pro Team die gewünschten Kategorien ergänzen (z. B. „Drucker defekt",
   „Passwort-Problem").

Mitglieder dieser AD-Gruppen werden beim nächsten Login automatisch als
Agenten des jeweiligen Teams eingerichtet (Just-in-Time-Synchronisation) –
es ist keine manuelle Nutzerverwaltung in SlothTix nötig.

## 10. Backup einrichten

```bash
crontab -e
```
Ergänzen (täglich um 3 Uhr, Sicherung landet unter `/backups`):
```
0 3 * * * /pfad/zu/slothtix/scripts/backup.sh /pfad/zu/slothtix/instance /backups
```

Das Skript nutzt die Backup-API von SQLite (nicht `cp`), sodass die Sicherung
auch bei laufendem Betrieb in sich stimmig ist. Sicherungen, die älter als 14
Tage sind, werden automatisch entfernt; ein abweichender Wert lässt sich als
dritter Parameter übergeben.

## 11. Testdaten vor dem Produktivstart entfernen

Nach der Testphase lassen sich die angesammelten Test-Tickets entfernen, ohne
Teams, Kategorien, Nutzer oder Einstellungen anzufassen:

```bash
docker compose exec slothtix flask tickets-purge --alle
```

Der Aufruf ist zunächst ein **Probelauf** und zeigt nur an, was gelöscht würde.
Erst mit `--ja` wird tatsächlich gelöscht:

```bash
docker compose exec slothtix flask tickets-purge --alle --ja --verwaiste-dateien
```

- `--vor JJJJ-MM-TT` löscht statt aller Tickets nur die vor diesem Datum (UTC)
  erstellten – nützlich, wenn nur die alte Testphase weg soll.
- `--verwaiste-dateien` entfernt zusätzlich Dateien unter `instance/uploads/`,
  zu denen es keinen Anhang-Datensatz mehr gibt (Reste früherer Resets).

Gelöscht werden mit jedem Ticket auch dessen Kommentare, Historie und Anhänge
inklusive der Dateien auf der Platte. Das ist **nicht rückgängig zu machen** –
vorher einmal `scripts/backup.sh` laufen lassen (siehe Abschnitt 10).

Nebeneffekt, meist erwünscht: Sind alle Tickets gelöscht, beginnt die
Ticket-Nummerierung wieder bei 1.

## Fehlerdiagnose

**Login schlägt mit „Benutzername oder Passwort falsch" fehl, obwohl beides
stimmt:** Die tatsächliche Ursache steht in den Logs
(`docker compose logs -f`), die Meldung im Browser ist bewusst generisch.
Häufige Ursachen: falscher LDAP-Port (siehe Schritt 8), `.env` nach
Änderung nicht neu geladen (`docker compose up -d --force-recreate`
nötig), falsche Bind-DN.

**„Zu viele fehlgeschlagene Anmeldeversuche":** Nach 5 Fehlversuchen je
Benutzername (bzw. 50 je IP-Adresse) wird der Login für 15 Minuten
gesperrt – Schutz gegen das Durchprobieren von Domänen-Passwörtern. Die
Sperre läuft von selbst ab; ein erfolgreicher Login setzt den Zähler des
Benutzernamens sofort zurück. Zum manuellen Aufheben:
```bash
docker compose exec slothtix python -c "from app import create_app; from app.extensions import db; from app.models import LoginAttempt; app=create_app(); ctx=app.app_context(); ctx.push(); LoginAttempt.query.delete(); db.session.commit()"
```

**LDAP-Zugangsdaten isoliert testen:**
```bash
LDAPTLS_REQCERT=never ldapsearch -x -H ldaps://<ucs-host>:<port> \
  -D "<bind-dn>" -w '<passwort>' -b "<base-dn>" "(uid=<testuser>)"
```

**Admin-Passwort ändern:** Als Admin unter **Passwort** in der Navigation.
Danach kann `ADMIN_PASSWORD` aus der `.env` entfernt werden – die Variable
wird nur beim allerersten Start ausgewertet, liegt aber ansonsten dauerhaft
im Klartext in der Container-Umgebung (`docker inspect`).

**Rechte im Volume nach dem Update auf einen unprivilegierten Container:**
Die Anwendung läuft seit dem Umstieg als Nutzer `slothtix` (UID 10001), nicht
mehr als `root`. Ein Volume aus einer älteren Version gehört noch `root`;
falls der Container mit „permission denied" auf `instance/` startet, einmalig:
```bash
docker compose run --rm --user root slothtix chown -R 10001:10001 /app/instance
```

**Container-Update nach Code-Änderungen:**
```bash
git pull
docker compose up -d --build
```

**Daten sichern/wiederherstellen:** Die SQLite-Datenbank und Uploads liegen
in einem benannten Docker-Volume (`slothtix-instance`), das Neustarts und
Image-Updates übersteht. Nur `docker compose down -v` löscht es – niemals
ohne Grund verwenden. Für portable Backups `scripts/backup.sh` nutzen.
