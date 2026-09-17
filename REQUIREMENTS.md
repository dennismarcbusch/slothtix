# SlothTix – Anforderungen

## 1. Überblick

SlothTix ist ein bewusst schlankes Ticket-System für den Einsatz an einer Schule.
Ziel ist es, die üblichen Schwächen bestehender Lösungen (zu groß, zu kompliziert,
Kernfunktionen fehlerhaft) zu vermeiden. Erste Nutzergruppen sind das IT-Team und
das Hausmeister-Team; weitere Teams (z. B. Verwaltung) sollen später ohne
Code-Änderung ergänzt werden können.

Dieses Dokument beschreibt *was* gebaut wurde und *warum*. Für die praktische
Nutzung/den Betrieb siehe:
- [docs/SETUP.md](docs/SETUP.md) – Installation & Konfiguration
- [docs/HANDBUCH_ADMIN.md](docs/HANDBUCH_ADMIN.md) – Handbuch für Admins (Teams, Einstellungen, AD-Abgleich)
- [docs/HANDBUCH_AGENTEN.md](docs/HANDBUCH_AGENTEN.md) – Handbuch für Team-Mitglieder
- [docs/HANDBUCH_USER.md](docs/HANDBUCH_USER.md) – Handbuch für alle übrigen Nutzer

## 2. Rollen & Begriffe

| Begriff | Bedeutung |
|---|---|
| **Admin** | Verwaltet Teams, AD-Gruppen-Zuordnung, Systemkonfiguration. Zu Beginn genau ein Admin-User (lokal angelegt, nicht über AD). |
| **Agent** | Mitglied eines oder mehrerer Teams. Bearbeitet, kommentiert und weist Tickets seiner Team(s) zu. Kann zusätzlich selbst Tickets erstellen (siehe 3.4). |
| **User** | Kann sich authentifizieren, Tickets für ein bestehendes Team erstellen und den Status seiner eigenen Tickets einsehen. |
| **Team** | Organisationseinheit (z. B. „IT", „Hausmeister"), der Tickets zugeordnet werden und der Agenten angehören. |
| **Ticket** | Anfrage eines Users oder Agenten an ein Team. |

Ein Agent besitzt implizit auch die User-Rolle (kann selbst Tickets anlegen).
Ein Agent kann Mitglied mehrerer Teams sein.

## 3. Funktionale Anforderungen

### 3.1 Authentifizierung
- Anmeldung per **LDAP-Bind** gegen den Univention Corporate Server (UCS): Die
  eingegebenen Zugangsdaten werden direkt gegen das AD geprüft, es werden keine
  Passwörter in SlothTix gespeichert.
- Der initiale **Admin-User** ist eine lokale Ausnahme (kein AD-Konto) und wird
  beim ersten Start über Umgebungsvariablen/Konfiguration angelegt.
- Nutzer ohne Mitgliedschaft in einer der konfigurierten AD-Gruppen (siehe 3.2)
  erhalten keinen Zugriff, auch wenn die AD-Anmeldung selbst erfolgreich wäre.

### 3.2 Benutzer- und Rollensynchronisation mit dem AD
- Synchronisation erfolgt **Just-in-Time beim Login**: Bei jeder Anmeldung wird
  geprüft, in welchen konfigurierten AD-Gruppen der Nutzer aktuell Mitglied ist,
  und die Rollen/Team-Zugehörigkeiten in SlothTix werden entsprechend aktualisiert.
- **AD-Gruppen-Mapping (konfigurierbar durch Admin):**
  - Eine AD-Gruppe legt fest, wer grundsätzlich als **User** zugreifen darf
    (Tickets erstellen, eigene Tickets einsehen).
  - **Pro Team** wird eine eigene AD-Gruppe konfiguriert; Mitgliedschaft in
    dieser Gruppe macht die Person automatisch zum **Agenten dieses Teams**.
    Mitgliedschaft in mehreren Team-Gruppen → Agent in mehreren Teams.
- Verlässt jemand alle konfigurierten Gruppen, verliert er beim nächsten
  Login-Versuch den Zugriff. Ein bereits aktives Login-Token/eine Session wird
  dadurch nicht sofort beendet (Konsequenz von reinem JIT-Sync – siehe Punkt 7).
- Es werden **nur** Mitglieder der konfigurierten Gruppen synchronisiert, nicht
  alle Domänennutzer.
- **AD-Abgleich:** Da sich ehemalige Mitglieder nicht mehr anmelden, gleicht ein
  separater Abgleich (Admin-Seite „AD-Abgleich" bzw. `flask users-sync`) alle
  bekannten Nutzer mit denselben Regeln ab. Wer nicht mehr im AD oder in keiner
  berechtigten Gruppe ist, wird deaktiviert und aus allen Teams entfernt; neue
  Nutzer legt der Abgleich nicht an. Würden alle aktiven Nutzer deaktiviert
  (Verdacht auf Fehlkonfiguration), bricht er ohne Änderungen ab.

### 3.3 Teams
- Admin kann Teams anlegen, umbenennen und deaktivieren.
- Jedem Team ist genau eine AD-Gruppe für die Agenten-Zuordnung zugeordnet
  (konfigurierbar).
- User wählen bei Ticket-Erstellung eines der vorhandenen (aktiven) Teams aus.

### 3.4 Tickets
- **Erstellung:** Authentifizierte User und Agenten können ein Ticket für ein
  bestehendes Team erstellen. Pflichtfelder: Titel, Beschreibung, Team,
  Priorität, Kategorie.
- **Kategorien/Vorlagen:** Bei der Erstellung wählt der Ersteller zusätzlich
  eine Kategorie aus einer pro Team konfigurierbaren Liste (z. B. „Drucker
  defekt", „Passwort-Problem" für IT; „Heizung", „Reinigung" für Hausmeister).
  Kategorien beschleunigen die Eingabe und erleichtern Agenten die
  Ersteinschätzung. Der Admin pflegt die Kategorien je Team.
- **Priorität:** niedrig / mittel / hoch.
- **Status-Workflow:** Offen → In Bearbeitung → Gelöst → Geschlossen.
- **Automatisches Schließen:** Gelöste Tickets werden nach einer
  konfigurierbaren Frist (Standard 14 Tage, 0 = aus) automatisch geschlossen.
  Die Frist beginnt mit dem letzten Wechsel auf „Gelöst"; eine spätere
  öffentliche Antwort des Erstellers startet sie neu. Mangels Scheduler
  prüft die App höchstens einmal pro Stunde bei einem beliebigen
  Seitenaufruf. Der Historieneintrag erscheint als „System", der Ersteller
  wird per E-Mail informiert.
- **Zuweisung:** Agenten eines Teams können Tickets dieses Teams sich selbst
  oder anderen Team-Mitgliedern zuweisen.
- **Team-Wechsel:** Ein Agent kann ein falsch zugeordnetes Ticket nachträglich
  einem anderen Team zuordnen.
- **Einsicht:** User sehen jederzeit den aktuellen Stand (Status, öffentliche
  Kommentare) ihrer eigenen Tickets. Agenten sehen alle Tickets ihrer Team(s).
- **Historie:** Statusänderungen, Zuweisungen und Team-Wechsel werden mit
  Zeitstempel und ausführendem Nutzer protokolliert (Audit-Trail je Ticket).
- **Übersicht – Geschlossene Tickets ein-/ausblenden:** In der Ticket-Übersicht
  gibt es einen einfach erreichbaren Umschalter (z. B. Checkbox/Toggle), um
  geschlossene Tickets ein- oder auszublenden. Standardmäßig sind geschlossene
  Tickets ausgeblendet, um die Übersicht schlank zu halten; die Einstellung
  gilt pro Nutzer für die Dauer der Sitzung.
- **Suche & Filter:** Die Ticket-Übersicht kann nach Status, Priorität, Team,
  Kategorie und Ersteller gefiltert sowie per Volltextsuche (Titel/
  Beschreibung) durchsucht werden. Verhindert Unübersichtlichkeit bei
  wachsender Ticket-Zahl, auch über den Geschlossen-Toggle hinaus.
- **Visuelle Kennzeichnung alter offener Tickets:** Tickets, die seit mehr
  als einer konfigurierbaren Anzahl Tage (Standard: 7 Tage) im Status
  „Offen" oder „In Bearbeitung" verharren, werden in der Übersicht farblich
  hervorgehoben. Dient als einfacher Hinweis gegen Vergessen, ohne eine
  vollständige SLA-Logik einzuführen.
- **Sortierbare Übersicht:** Jede Spalte der Ticket-Übersicht ist per Klick
  auf die Spaltenüberschrift sortierbar (erneuter Klick kehrt die Richtung
  um). Priorität und Status sortieren nach Dringlichkeit/Workflow-Reihenfolge,
  nicht alphabetisch.
- **„Nur mir zugewiesene" Filter:** Agenten können die Übersicht per Toggle
  (analog zum Geschlossen-Toggle) auf ausschließlich ihnen zugewiesene
  Tickets einschränken.
- **Priorität nachträglich änderbar:** Agenten können die bei der
  Ticket-Erstellung gewählte Priorität jederzeit korrigieren (protokolliert
  in der Historie) – Nutzer neigen dazu, ihr eigenes Anliegen als
  dringlicher einzuschätzen als es ist.
- **Pflichtfeld-Validierung:** Team und Kategorie haben bei der
  Ticket-Erstellung bewusst keine Vorauswahl (verhindert versehentliches
  Senden ans falsche Team); fehlende Pflichtfelder werden sowohl durch den
  Browser (native Validierung) als auch serverseitig (Fehlermeldung je
  Feld) zurückgemeldet.

### 3.5 Kommentare
- Kommentare können von Usern (nur öffentlich, nur zu eigenen Tickets) und
  Agenten (öffentlich oder intern) verfasst werden.
- **Öffentliche Kommentare** sind für den Ticket-Ersteller sichtbar.
- **Interne Kommentare** sind ausschließlich für Agenten des zuständigen Teams
  sichtbar (z. B. teaminterne Abstimmung).

### 3.6 Anhänge
- An Tickets und Kommentaren können Dateien angehängt werden (z. B.
  Screenshots, PDFs).
- **Größenlimit:** pro Datei konfigurierbar durch den Admin. Standardwert:
  **5 MB** (deckt übliche Screenshot-Größen ab, auch bei hochauflösenden
  Bildschirmen/Retina-Displays; typische PNG-Screenshots liegen meist deutlich
  darunter).
- **Screenshot-Einfügen per Copy & Paste:** In der Eingabemaske für
  Ticket-Erstellung (und Kommentare) kann ein zuvor mit einem
  Screenshot-Tool aufgenommener Screenshot direkt aus der Zwischenablage
  per Strg+V eingefügt werden – ohne Umweg über Datei speichern und
  hochladen. Das eingefügte Bild wird automatisch als Anhang
  übernommen und vor dem Absenden als Vorschau angezeigt (mit Möglichkeit,
  es wieder zu entfernen).
- Weitere Anforderungen an Umsetzung: Whitelist erlaubter Dateitypen,
  Speicherung außerhalb des Web-Roots.

### 3.7 Benachrichtigungen
- E-Mail-Benachrichtigung bei:
  - neuem öffentlichen Kommentar am eigenen Ticket (an den User),
  - neuem Ticket im eigenen Team bzw. neuem Kommentar/Zuweisung (an betroffene Agenten),
  - Statusänderung, auch durch automatisches Schließen (an den User).
- Interne Kommentare lösen **keine** Benachrichtigung an User aus.
- E-Mail-Adresse stammt aus dem AD-Attribut des Nutzers (Sync bei Login).
- SMTP-Server ist konfigurierbar (Admin-Einstellung).

### 3.8 Admin-Funktionen
- Teams anlegen/bearbeiten/deaktivieren inkl. AD-Gruppen-Zuordnung.
- Konfiguration der User-Zugriffsgruppe.
- Konfiguration von LDAP/UCS-Verbindungsdaten und SMTP.
- Übersicht über alle Teams/Tickets (rollenübergreifend).

## 4. Nicht-funktionale Anforderungen

- **Zielgruppe/Last:** wenige gleichzeitige Nutzer (Schulumfeld), keine
  Hochverfügbarkeitsanforderung.
- **Schlankheit:** minimale Abhängigkeiten, geringer Wartungsaufwand, keine
  separate Datenbank-Serverkomponente.
- **Persistenz:** SQLite-Datei als alleinige Datenhaltung; Sicherung durch
  Kopieren der Datei; optional periodischer Export für Lesbarkeit/Archivierung.
- **Automatisiertes Backup:** Regelmäßige (z. B. tägliche) automatische Sicherung
  der SQLite-Datei sowie des Anhang-Verzeichnisses, da bei Single-File-
  Persistenz ohne separaten DB-Server kein eingebauter Replikations-/
  Backup-Mechanismus existiert. Umsetzung z. B. als Cron-Job/Sidecar im
  Docker-Setup, der Sicherungen an einem konfigurierbaren Ziel ablegt.
- **Deployment:** Docker-Container auf einem selbst verwalteten Server,
  davor ein Caddy-Reverse-Proxy für automatisches HTTPS via Let's Encrypt
  (Zertifikatsausstellung/-erneuerung läuft vollautomatisch, keine
  manuelle Certbot-Pflege nötig). Hostname über `SITE_DOMAIN` konfigurierbar, z. B.
  `https://tickets.example.org`.
- **Responsives Layout:** Die Oberfläche ist für mobile Endgeräte nutzbar
  (Smartphone/Tablet), da insbesondere das Hausmeister-Team häufig unterwegs
  ist und Tickets eher am Handy als am PC bearbeitet.
- **Sprache:** Oberfläche auf Deutsch (Annahme, siehe Abschnitt 7).
- **Branding:** Eigenes Logo/Favicon (Wortmarke auf dem Login-Bildschirm,
  kompaktes Icon in Navbar und Browser-Tab).
- **Datenschutz (DSGVO):** Da personenbezogene Daten von Schulpersonal
  verarbeitet werden, sind Aufbewahrungsfristen/Löschkonzept für geschlossene
  Tickets zu klären (siehe offene Punkte).
- **Übersichtlichkeit:** reduzierte, klare Oberfläche für alle Rollen –
  bewusster Verzicht auf Funktionsvielfalt größerer Ticket-Systeme.

## 5. Datenmodell (grober Entwurf)

- **User**: id, ad_username (falls AD-Nutzer, sonst null für lokalen Admin),
  anzeigename, email, ist_admin, aktiv
- **Team**: id, name, ad_gruppe_agenten, aktiv
- **TeamMitgliedschaft**: user_id, team_id *(ergibt sich aus AD-Sync, N:M)*
- **Kategorie**: id, team_id, name, aktiv
- **Ticket**: id, titel, beschreibung, team_id, kategorie_id, ersteller_id,
  zugewiesen_an_id (nullable), status, priorität, erstellt_am, aktualisiert_am
- **Kommentar**: id, ticket_id, autor_id, text, sichtbarkeit
  (öffentlich/intern), erstellt_am
- **Anhang**: id, ticket_id (oder kommentar_id), dateiname, pfad, größe,
  hochgeladen_von, erstellt_am
- **TicketHistorie**: id, ticket_id, aktion, alter_wert, neuer_wert,
  ausgeführt_von, zeitstempel
- **Zugriffskonfiguration**: ad_gruppe_user (globale User-Zugriffsgruppe),
  LDAP-Verbindungsdaten, SMTP-Einstellungen

## 6. Technische Architektur

- **Backend:** Python, Flask (App-Factory-Pattern in `app/`)
- **Datenhaltung:** SQLite via SQLAlchemy/Flask-Migrate (Alembic)
- **Authentifizierung:** LDAP-Bind gegen UCS via `ldap3`, TLS-Zertifikatsprüfung
  gegen konfigurierbare CA (`LDAP_CA_CERT_PATH`)
- **Deployment:** Dockerfile (gunicorn) + docker-compose; Caddy als
  Reverse-Proxy für TLS-Terminierung und automatisches Let's-Encrypt-Zertifikat
  (`Caddyfile`). Die App ist im Compose-Setup nur noch über Caddy erreichbar,
  nicht mehr direkt vom Host aus. `ProxyFix` (Werkzeug) vertraut den
  Proxy-Headern für korrekte Secure-Cookies und `https://`-Links in
  E-Mails (siehe `FORCE_HTTPS`).
- **Tests:** pytest-Suite (LDAP-Auth inkl. Schema-/Attribut-Sonderfälle,
  Ticket-Workflow/Berechtigungen, Mail-Versand)
- **Versionierung:** Git, Repository unter
  [github.com/dennismarcbusch/slothtix](https://github.com/dennismarcbusch/slothtix.git)

## 7. Offene Punkte / spätere Erweiterungen

Diese Punkte sind für den ersten Wurf nicht blockierend, sollten aber im Blick
behalten werden:

1. **Session-Gültigkeit vs. JIT-Sync:** Da der AD-Abgleich nur beim Login
   erfolgt, bleibt eine bestehende Session aktiv, auch wenn die AD-Gruppe
   zwischenzeitlich entzogen wurde. Eine Sitzung ist inzwischen auf absolut
   8 Stunden begrenzt (`Config.SESSION_MAX_ALTER`), womit der Entzug
   spätestens beim nächsten Login greift. Der AD-Abgleich (siehe 3.2)
   deaktiviert ehemalige Mitglieder, was auch laufende Sitzungen sofort
   beendet – er läuft bisher aber nur manuell; ein automatischer Lauf per
   Cron ist noch nicht eingerichtet.
2. **Aufbewahrung/Löschung** geschlossener Tickets und personenbezogener Daten
   (DSGVO-Löschkonzept) ist noch zu definieren.
3. **Weitere Teams** (Verwaltung etc.) sind strukturell bereits vorgesehen
   und benötigen keine Code-Änderung – einfach über die Admin-Oberfläche
   unter „Teams" anlegen und die passende AD-Gruppe hinterlegen.
4. **Mehrsprachigkeit:** aktuell nur Deutsch vorgesehen; bei Bedarf müsste die
   Oberfläche für Mehrsprachigkeit vorbereitet werden (z. B. via
   Flask-Babel).
5. **Statistiken/Reporting** (z. B. Anzahl offener Tickets pro Team) ist nicht
   Teil des ersten Wurfs, könnte aber als spätere Erweiterung sinnvoll sein.
6. **Tickets löschen** ist in der Oberfläche weiterhin nirgends möglich
   (weder für User, Agenten noch Admin) – einzige Möglichkeit, ein Ticket aus
   der Standardansicht verschwinden zu lassen, ist der Status „Geschlossen".
   Für das Aufräumen der Testdaten vor dem Produktivstart gibt es das
   CLI-Kommando `flask tickets-purge` (siehe
   [docs/SETUP.md](docs/SETUP.md), Abschnitt 11), das Tickets samt
   Kommentaren, Historie und Anhängen entfernt; bewusst nur auf der
   Kommandozeile und nicht als Klick in der Oberfläche. Eine echte
   Löschfunktion für Admins im UI – auch als Grundlage für das
   DSGVO-Löschkonzept aus Punkt 2 – müsste bei Bedarf noch ergänzt werden.

## 8. Zusammenfassung der Kernentscheidungen

| Thema | Entscheidung |
|---|---|
| Datenhaltung | SQLite |
| Authentifizierung | LDAP-Bind gegen UCS |
| AD-Synchronisation | Just-in-Time beim Login + AD-Abgleich (manuell, Admin-Seite/CLI) |
| AD-Gruppen-Mapping | Eine AD-Gruppe pro Team (Agenten) + eine globale Gruppe (User) |
| Deployment | Docker-Container |
| Kommentare | Öffentlich + intern |
| Team-Mitgliedschaft | Mehrere Teams pro Agent möglich |
| Ticket-Status | Offen / In Bearbeitung / Gelöst / Geschlossen |
| Priorität | Niedrig / Mittel / Hoch |
| Anhänge | Ja, nur PNG/JPEG/GIF/PDF (Endung und Dateiinhalt werden geprüft), Größenlimit konfigurierbar (Standard 5 MB, max. 50 MB) |
| Screenshot-Einfügen | Per Copy & Paste (Strg+V) direkt in der Eingabemaske |
| Geschlossene Tickets in Übersicht | Ein-/ausblendbar, standardmäßig ausgeblendet |
| Benachrichtigungen | Per E-Mail |
| Team-Wechsel bei Tickets | Möglich |
| Agenten als Ersteller | Ja, Agenten können auch selbst Tickets erstellen |
| Admin-Setup | Initial per Umgebungsvariable/Config |
| Kategorien/Vorlagen | Ja, pro Team konfigurierbar |
| Suche & Filter | Ja (Status, Priorität, Team, Kategorie, Ersteller, Volltext) |
| Alte offene Tickets | Visuelle Hervorhebung ab konfigurierbarer Frist (Standard 7 Tage) |
| Gelöste Tickets | Automatisch geschlossen nach konfigurierbarer Frist (Standard 14 Tage) |
| Backup | Automatisiert, regelmäßig (z. B. täglich) |
| Responsives Layout | Ja, mobile-tauglich |
| Sortierbare Übersicht | Ja, jede Spalte klickbar (Priorität/Status nach Dringlichkeit, nicht alphabetisch) |
| „Nur mir zugewiesene"-Filter | Ja, Toggle für Agenten |
| Priorität nachträglich ändern | Ja, durch Agenten, mit Historie |
| HTTPS/Zertifikat | Caddy-Reverse-Proxy, automatisches Let's-Encrypt-Zertifikat |
| Branding | Eigenes Logo/Favicon |
