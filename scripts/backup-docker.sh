#!/bin/sh
# Sichert SlothTix im Docker-Betrieb auf den Host. Für den produktiven
# Betrieb per Cron einplanen, z.B. täglich um 3 Uhr:
#   0 3 * * * /pfad/zu/slothtix/scripts/backup-docker.sh /backups
#
# Die Datenbank liegt im Volume slothtix-instance und ist vom Host aus
# nicht direkt erreichbar. Deshalb läuft scripts/backup.sh im laufenden
# Container, und das Ergebnis wird anschließend herauskopiert.
#
# Optionaler zweiter Parameter: Anzahl der Tage, die alte Sicherungen
# aufbewahrt werden (Standard 14). Ältere werden entfernt.
set -eu

DEST_DIR="${1:-backups}"
AUFBEWAHRUNG_TAGE="${2:-14}"
# Bewusst nicht unter /app/instance: Die Zwischenablage soll nicht im
# Volume landen und dort mitgesichert werden.
ZWISCHENABLAGE=/tmp/slothtix-backup

# Relatives Ziel vor dem Verzeichniswechsel absolut machen.
case "$DEST_DIR" in
    /*) ;;
    *) DEST_DIR="$PWD/$DEST_DIR" ;;
esac

# docker compose braucht das Projektverzeichnis - Cron startet woanders.
cd "$(dirname "$0")/.."

docker compose exec -T slothtix sh -c "rm -rf $ZWISCHENABLAGE"
AUSGABE="$(docker compose exec -T slothtix sh scripts/backup.sh /app/instance "$ZWISCHENABLAGE")"
NAME="$(basename "$(printf '%s\n' "$AUSGABE" | sed -n 's/^Backup erstellt: //p')")"
if [ -z "$NAME" ] || [ "$NAME" = "." ]; then
    echo "Fehler: backup.sh im Container hat kein Backup gemeldet:" >&2
    printf '%s\n' "$AUSGABE" >&2
    exit 1
fi

mkdir -p "$DEST_DIR"
docker compose cp "slothtix:$ZWISCHENABLAGE/$NAME" "$DEST_DIR/$NAME"
docker compose exec -T slothtix sh -c "rm -rf $ZWISCHENABLAGE"

# Ohne diese Prüfung fiele ein Backup ohne Datenbank erst auf, wenn man
# es braucht.
if [ ! -s "$DEST_DIR/$NAME/slothtix.db" ]; then
    echo "Fehler: $DEST_DIR/$NAME/slothtix.db fehlt oder ist leer." >&2
    exit 1
fi

echo "Backup erstellt: $DEST_DIR/$NAME"

# Alte Sicherungen aufräumen, damit der Cronjob die Platte nicht vollschreibt.
find "$DEST_DIR" -maxdepth 1 -type d -name 'slothtix-backup-*' \
    -mtime "+$AUFBEWAHRUNG_TAGE" -exec rm -rf {} + 2>/dev/null || true
