# SlothTix – Handbuch für Agenten

Dieses Handbuch richtet sich an Mitglieder eines Teams (z. B. IT,
Hausmeister), die Tickets bearbeiten. Für die Grundfunktionen aus
Nutzer-Sicht (Ticket erstellen, eigenen Status verfolgen) siehe zusätzlich
das [Handbuch für User](HANDBUCH_USER.md) – als Agent kannst du alles davon
ebenfalls nutzen.

## Anmeldung

Ruf die SlothTix-Adresse eurer Schule auf und melde dich mit deinem
gewohnten Schul-Zugangsdaten (Benutzername + Passwort) an. Ein eigenes
SlothTix-Passwort gibt es nicht – die Anmeldung läuft über euer normales
Schul-Konto.

## Die Ticket-Übersicht

Nach der Anmeldung siehst du alle Tickets deines Teams (bzw. aller Teams,
falls du in mehreren bist) sowie Tickets, die du selbst erstellt hast.

**Spalten sortieren:** Auf eine Spaltenüberschrift klicken sortiert danach;
nochmal klicken kehrt die Richtung um. Bei „Priorität" und „Status" wird
sinnvoll nach Dringlichkeit bzw. Bearbeitungsstand sortiert (nicht
alphabetisch).

**Filtern:** Über die Dropdown-Felder oben lässt sich nach Team, Kategorie,
Ersteller, Status und Priorität filtern, zusätzlich per Volltextsuche nach
Titel/Beschreibung.

**Geschlossene Tickets ein-/ausblenden:** Über den entsprechenden Button –
standardmäßig sind geschlossene Tickets ausgeblendet, um die Übersicht
übersichtlich zu halten.

**„Nur mir zugewiesene anzeigen":** Blendet die Übersicht auf Tickets ein,
die dir persönlich zugewiesen sind. Praktisch, um schnell die eigene
Arbeitsliste zu sehen.

**„Board-Ansicht":** Zeigt die (gefilterten) Tickets statt als Tabelle als
Spalten nach Status (Offen, In Bearbeitung, Gelöst, Geschlossen) an - für
einen schnellen Überblick über den Bearbeitungsstand. Ein Klick auf eine
Karte öffnet wie gewohnt die Detailansicht; Verschieben per Drag & Drop
gibt es (noch) nicht. Über „Listenansicht" geht es zurück zur Tabelle.

Tickets, die seit mehreren Tagen unbearbeitet offen sind, werden farblich
hervorgehoben (Frist ist vom Admin konfigurierbar, Standard 7 Tage).

## Ein Ticket bearbeiten

Auf ein Ticket in der Übersicht klicken öffnet die Detailansicht. Dort
stehen dir folgende Aktionen zur Verfügung:

Status, Priorität, Kategorie und Zuweisung lassen sich gemeinsam in einem
Formular mit einem Klick auf **Speichern** übernehmen - du musst also nicht
mehr für jede Eigenschaft einzeln speichern:

- **Status**: Offen → In Bearbeitung → Gelöst → Geschlossen. Der Ersteller
  wird per E-Mail über die Änderung informiert.
- **Priorität**: Falls die ursprüngliche Einschätzung nicht passt, kannst
  du sie jederzeit korrigieren.
- **Kategorie**: Auswahl aus den Kategorien des aktuellen Teams.
- **Zuweisen**: An dich selbst oder ein anderes Mitglied deines Teams. Die
  zugewiesene Person bekommt eine Benachrichtigung.

**Team wechseln** bleibt ein eigener Button, da die Auswirkung deutlich
größer ist: Falls ein Ticket beim falschen Team gelandet ist, kannst du es
an ein anderes Team weiterleiten (dabei wird auch die Kategorie neu
gewählt, da Kategorien team-spezifisch sind). Eine bestehende Zuweisung
wird dabei zurückgesetzt, da sie sich auf das alte Team bezog. Da Nutzer
ohne Mitgliedschaft im neuen Team danach eventuell keinen Zugriff mehr auf
das Ticket haben, erscheint vor dem Wechsel ein Bestätigungshinweis.

Alle diese Änderungen werden mit Zeitstempel und deinem Namen in der
**Historie** am Ende der Ticket-Seite protokolliert.

## Kommentieren

Unter „Kommentar hinzufügen" kannst du zwischen zwei Sichtbarkeiten wählen:

- **Öffentlich**: sichtbar für den Ersteller des Tickets.
- **Intern**: nur für Agenten des zuständigen Teams sichtbar – praktisch
  für teaminterne Abstimmung, ohne den User zu verwirren oder zu
  benachrichtigen.

Der Ersteller selbst kann nur öffentlich kommentieren.

## Anhänge / Screenshots

Sowohl beim Ticket selbst als auch bei jedem Kommentar können Dateien
angehängt werden (Bilder, PDFs). Am schnellsten geht das per
**Copy & Paste**: Screenshot mit dem Windows-Snipping-Tool (oder ähnlichem)
aufnehmen, in das gestrichelte Feld „Anhänge" klicken und **Strg+V**
drücken – das Bild erscheint direkt als Vorschau und wird beim Absenden
mitgeschickt.

## Selbst Tickets erstellen

Als Agent kannst du – genau wie ein User – über „Neues Ticket" auch für ein
**anderes** Team ein Ticket erstellen, z. B. wenn dir als IT-Mitarbeiter ein
kaputter Stuhl auffällt, den das Hausmeister-Team reparieren soll.

## Benachrichtigungen

Du bekommst eine E-Mail, wenn:
- ein neues Ticket in deinem Team erstellt wird,
- dir ein Ticket zugewiesen wird,
- der Ersteller eines Tickets in deinem Team öffentlich antwortet.

Interne Kommentare lösen keine Benachrichtigung an den User aus.
