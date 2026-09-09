"""SQLite-spezifische Verbindungseinstellungen.

Beides gilt pro Verbindung und muss deshalb bei jedem Verbindungsaufbau
neu gesetzt werden - ein einmaliges Statement beim Start genügt nicht.
"""

import sqlite3

from sqlalchemy import event
from sqlalchemy.engine import Engine


def registriere_sqlite_pragmas(app):
    @event.listens_for(Engine, "connect")
    def _setze_pragmas(dbapi_connection, connection_record):
        # Nur für SQLite - bei einem anderen Backend (DATABASE_URL zeigt
        # z. B. auf PostgreSQL) sind diese PRAGMAs unbekannt.
        if not isinstance(dbapi_connection, sqlite3.Connection):
            return

        cursor = dbapi_connection.cursor()
        try:
            # SQLite prüft Fremdschlüssel per Default NICHT - die
            # ForeignKey-Constraints im Schema wären ohne das hier reine
            # Dokumentation, und ein Ticket könnte auf ein gelöschtes Team
            # zeigen.
            cursor.execute("PRAGMA foreign_keys=ON")

            # WAL erlaubt Lesern und einem Schreiber gleichzeitig zu
            # arbeiten. Ohne das sperrt jeder Schreibvorgang die gesamte
            # Datei, was bei vier Gunicorn-Workern auf einer Datei zu
            # sporadischen "database is locked"-Fehlern führt.
            cursor.execute("PRAGMA journal_mode=WAL")

            # Trifft ein Worker doch auf eine gesperrte Datenbank, wartet
            # er bis zu 15 Sekunden, statt sofort abzubrechen.
            cursor.execute("PRAGMA busy_timeout=15000")
        finally:
            cursor.close()
