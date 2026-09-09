#!/bin/sh
# Sichert die SQLite-Datenbank und die Anhänge in ein Zielverzeichnis mit
# Zeitstempel. Für den produktiven Betrieb per Cron einplanen, z.B. täglich:
#   0 3 * * * /app/scripts/backup.sh /app/instance /backups
set -eu

INSTANCE_DIR="${1:-instance}"
DEST_DIR="${2:-backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$DEST_DIR/slothtix-backup-$TIMESTAMP"

mkdir -p "$TARGET"
cp "$INSTANCE_DIR/slothtix.db" "$TARGET/slothtix.db"
if [ -d "$INSTANCE_DIR/uploads" ]; then
    cp -r "$INSTANCE_DIR/uploads" "$TARGET/uploads"
fi

echo "Backup erstellt: $TARGET"
