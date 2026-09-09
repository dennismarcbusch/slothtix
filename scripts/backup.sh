#!/bin/sh
# Sichert die SQLite-Datenbank und die Anhänge in ein Zielverzeichnis mit
# Zeitstempel. Für den produktiven Betrieb per Cron einplanen, z.B. täglich:
#   0 3 * * * /app/scripts/backup.sh /app/instance /backups
#
# Optionaler dritter Parameter: Anzahl der Tage, die alte Sicherungen
# aufbewahrt werden (Standard 14). Ältere werden entfernt.
set -eu

INSTANCE_DIR="${1:-instance}"
DEST_DIR="${2:-backups}"
AUFBEWAHRUNG_TAGE="${3:-14}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$DEST_DIR/slothtix-backup-$TIMESTAMP"

mkdir -p "$TARGET"

# Nicht einfach kopieren: Läuft parallel ein Schreibvorgang, entsteht dabei
# eine inkonsistente Datei - und im WAL-Modus fehlt der noch nicht
# eingearbeitete Teil des Write-Ahead-Logs komplett. Die backup-API von
# SQLite erzeugt dagegen einen in sich stimmigen Stand. Über Python, weil
# das schlanke Container-Image kein sqlite3-Kommandozeilenwerkzeug enthält.
python - "$INSTANCE_DIR/slothtix.db" "$TARGET/slothtix.db" <<'PY'
import sqlite3
import sys

quelle, ziel = sys.argv[1], sys.argv[2]
with sqlite3.connect(f"file:{quelle}?mode=ro", uri=True) as src, sqlite3.connect(ziel) as dst:
    src.backup(dst)
PY

if [ -d "$INSTANCE_DIR/uploads" ]; then
    cp -r "$INSTANCE_DIR/uploads" "$TARGET/uploads"
fi

echo "Backup erstellt: $TARGET"

# Alte Sicherungen aufräumen, damit der Cronjob die Platte nicht vollschreibt.
find "$DEST_DIR" -maxdepth 1 -type d -name 'slothtix-backup-*' \
    -mtime "+$AUFBEWAHRUNG_TAGE" -exec rm -rf {} + 2>/dev/null || true
