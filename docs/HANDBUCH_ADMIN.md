# SlothTix – Handbuch für Admins

Dieses Handbuch richtet sich an die Person, die SlothTix im laufenden
Betrieb verwaltet: Teams und Kategorien pflegen, Einstellungen anpassen und
Nutzer mit dem AD abgleichen. Installation, Server und `.env` beschreibt die
[Setup-Anleitung](SETUP.md). Wie Tickets bearbeitet werden, steht im
[Handbuch für Agenten](HANDBUCH_AGENTEN.md).

## Anmeldung und Passwort

Als Admin meldest du dich **nicht** mit einem Schul-Konto an, sondern mit
dem lokalen Admin-Account, der bei der Einrichtung angelegt wurde
(`ADMIN_USERNAME`/`ADMIN_PASSWORD` aus der `.env`). Es gibt genau diesen
einen Admin; Schul-Konten aus dem AD können keine Admin-Rechte bekommen.

Unter **Passwort** lässt sich das Passwort des Admin-Accounts ändern
(mindestens 12 Zeichen). Danach kann `ADMIN_PASSWORD` aus der `.env`
entfernt werden – es wird nur beim allerersten Start gebraucht.

## Wie Nutzer und Rollen entstehen

In SlothTix gibt es keine manuelle Nutzerverwaltung. Wer was darf, ergibt
sich aus den AD-Gruppen:

- Mitglieder der **AD-Gruppe (User-Zugriff)** aus den Einstellungen dürfen
  Tickets erstellen und ihre eigenen Tickets verfolgen.
- Mitglieder der **AD-Gruppe eines Teams** sind Agenten dieses Teams.
  Wer in mehreren Team-Gruppen ist, ist Agent in mehreren Teams.

Beim Login gleicht SlothTix diese Zugehörigkeiten automatisch ab: Neue
Nutzer werden angelegt, Name, E-Mail und Teams aktualisiert. Wer gar keiner
der Gruppen angehört, kommt nicht hinein.

Wichtig: Dieser Abgleich passiert **nur beim Login**. Wer im AD gelöscht
oder aus einer Gruppe genommen wird, meldet sich nicht mehr an und bliebe
ohne weiteres Zutun in SlothTix sichtbar – z. B. beim Zuweisen von Tickets.
Dafür gibt es den [AD-Abgleich](#ad-abgleich).

## Teams und Kategorien

Unter **Teams** verwaltest du die Teams und ihre Kategorien.

**Team anlegen:** Name und AD-Gruppe eintragen. Bei der AD-Gruppe nur den
Gruppennamen angeben, nicht die volle DN (also `IT-Agenten`, nicht
`cn=IT-Agenten,cn=groups,...`). Die Mitglieder der Gruppe werden beim
nächsten Login bzw. beim nächsten AD-Abgleich zu Agenten des Teams.

**Team umbenennen oder AD-Gruppe ändern:** Direkt im Team-Kasten ändern und
**Speichern**. Eine geänderte AD-Gruppe wirkt ebenfalls erst beim nächsten
Login bzw. AD-Abgleich – vorher den Gruppennamen genau prüfen, sonst
verlieren alle bisherigen Agenten das Team.

**Team deaktivieren:** Das Team steht dann bei neuen Tickets und beim
Team-Wechsel nicht mehr zur Auswahl. Außerdem verlieren seine Agenten die
Mitgliedschaft beim nächsten Login bzw. AD-Abgleich und sehen die Tickets
des Teams danach nicht mehr. Deshalb ein Team erst deaktivieren, wenn seine
offenen Tickets erledigt oder an ein anderes Team übergeben sind. Über
**Aktivieren** lässt es sich jederzeit zurückholen.

**Kategorien:** Unter jedem Team lassen sich Kategorien hinzufügen und
deaktivieren. Deaktivierte Kategorien stehen nicht mehr zur Auswahl.
Bestehende Tickets behalten sie zunächst; wird ein solches Ticket aber
bearbeitet und gespeichert, bekommt es eine der aktiven Kategorien. Ein Team
sollte deshalb immer mindestens eine aktive Kategorie haben. Umbenennen geht
nicht – stattdessen die alte Kategorie deaktivieren und eine neue anlegen.

Teams und Kategorien lassen sich nicht löschen, nur deaktivieren. So bleiben
bestehende Tickets und ihre Historie vollständig.

## Einstellungen

Unter **Einstellungen**:

- **Zugriff** – die AD-Gruppe für den User-Zugriff (siehe oben).
- **LDAP / UCS** – Verbindung zum Verzeichnis. Details und typische
  Stolperfallen (z. B. Port 7636 statt 636) stehen in der
  [Setup-Anleitung, Abschnitt 8](SETUP.md#8-ldap-und-smtp-konfigurieren).
- **E-Mail (SMTP)** – Mailserver für die Benachrichtigungen.
- **Anhang-Größenlimit (MB)** – maximale Größe je Anhang.
- **Frist für „altes" Ticket (Tage)** – ab wie vielen Tagen ein
  unbearbeitet offenes Ticket in der Übersicht farblich hervorgehoben wird
  (Standard 7).

Passwörter (LDAP-Bind, SMTP) stehen bewusst nicht hier, sondern in der
`.env` auf dem Server.

## AD-Abgleich

Der AD-Abgleich prüft **alle** bekannten Nutzer auf einmal gegen das AD,
mit denselben Regeln wie beim Login. Er ist unter **AD-Abgleich** zu finden.

**Wann ausführen?**

- nachdem Personen im AD gelöscht oder aus SlothTix-Gruppen entfernt wurden
  (z. B. zum Schuljahreswechsel),
- nachdem die AD-Gruppe eines Teams geändert oder ein Team deaktiviert
  wurde,
- ansonsten gelegentlich zur Kontrolle – steht dort „Alles aktuell", ist
  nichts zu tun.

**Ablauf:**

1. **AD-Abgleich** öffnen. Die Seite fragt das AD ab und zeigt eine
   **Vorschau** – es wird dabei noch nichts geändert.
2. Die Liste prüfen. Je Nutzer steht dort, was sich ändern würde:
   - *wird deaktiviert (nicht mehr im Verzeichnis)* bzw. *(in keiner
     berechtigten AD-Gruppe mehr)* – der Nutzer kann sich nicht mehr
     anmelden, eine laufende Sitzung endet sofort, und er wird aus allen
     Teams entfernt,
   - *verlässt Team …* / *kommt zu Team …*,
   - *Anzeigename* bzw. *E-Mail* – geänderte Daten aus dem AD,
   - *wird reaktiviert* – ein früher deaktivierter Nutzer ist wieder
     berechtigt.
3. **Änderungen übernehmen** klicken. SlothTix fragt das AD dabei erneut ab
   und übernimmt den aktuellen Stand.

**Noch zugewiesene Tickets:** Unter einem Nutzer erscheinen ggf. Hinweise
wie „Noch zugewiesen: #42 …". Das sind nicht geschlossene Tickets, die ihm
in einem Team zugewiesen sind, dem er danach nicht mehr angehört. Der
Abgleich ändert diese Zuweisungen **nicht** – bitte die verlinkten Tickets
öffnen und neu zuweisen.

**Was nicht passiert:** Es wird nichts gelöscht. Tickets, Kommentare und
Historie deaktivierter Nutzer bleiben erhalten, ihr Name bleibt dort
sichtbar. Neue Nutzer legt der Abgleich nicht an, das passiert weiterhin
beim ersten Login. Taucht ein deaktivierter Nutzer später wieder in einer
Gruppe auf, wird er beim nächsten Login (oder Abgleich) automatisch
reaktiviert.

**Wenn der Abgleich abbricht:** In zwei Fällen ändert der Abgleich nichts
und zeigt stattdessen eine Fehlermeldung:

- Das AD ist nicht erreichbar oder die Suche schlägt fehl – LDAP-Angaben
  unter **Einstellungen** prüfen (insbesondere die Base-DN).
- Der Abgleich würde **alle** aktiven Nutzer deaktivieren. Das passiert
  praktisch nur bei einer Fehlkonfiguration, z. B. einer falschen Base-DN
  oder einer im AD umbenannten Gruppe. Gruppennamen unter
  **Einstellungen** und **Teams** mit dem AD vergleichen.

**Auf der Kommandozeile:** Derselbe Abgleich lässt sich auf dem Server
ausführen, z. B. für eine spätere Automatisierung per Cron (siehe
[Setup-Anleitung, Abschnitt 12](SETUP.md#12-ad-abgleich-ehemalige-mitglieder-entfernen)):

```bash
docker compose exec slothtix flask users-sync        # nur Vorschau
docker compose exec slothtix flask users-sync --ja   # übernehmen
```

## Tickets als Admin

Als Admin siehst du in der Ticket-Übersicht **alle** Tickets aller Teams
und kannst jedes Ticket wie ein Agent bearbeiten (Status, Priorität,
Zuweisung, Team wechseln, interne Kommentare) – siehe
[Handbuch für Agenten](HANDBUCH_AGENTEN.md). Da der Admin-Account keinem
Team angehört, bekommst du keine Benachrichtigungen zu neuen Tickets und
kannst dir selbst keine Tickets zuweisen.

Tickets löschen ist in der Oberfläche nicht möglich. Für das Entfernen von
Testdaten gibt es das Kommando `flask tickets-purge` (siehe
[Setup-Anleitung, Abschnitt 11](SETUP.md#11-testdaten-vor-dem-produktivstart-entfernen)).
