"""Gelöste Tickets nach einer einstellbaren Frist automatisch schließen.

SlothTix hat keinen Scheduler. Die Prüfung hängt sich deshalb an normale
Seitenaufrufe und läuft höchstens einmal pro Stunde - bei einer Frist von
Tagen spielt es keine Rolle, ob ein Ticket ein paar Stunden später zugeht.
"""

import time
from datetime import timedelta

from flask import after_this_request, current_app, request
from sqlalchemy import or_, update
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.mail import send_mails
from app.models import (
    HistorienAktion,
    Settings,
    Sichtbarkeit,
    Ticket,
    TicketHistory,
    TicketStatus,
    utcnow,
)
from app.notifications import benachrichtigung_auto_geschlossen

PRUEF_INTERVALL = timedelta(hours=1)


def frist_beginn(ticket):
    """Letzter Wechsel auf "Gelöst" - oder, falls später, die letzte
    öffentliche Antwort des Erstellers: Wer nach der Lösung noch schreibt,
    dem soll das Ticket nicht unter den Füßen zugehen."""
    geloest_am = [
        eintrag.zeitstempel
        for eintrag in ticket.historie
        if eintrag.aktion == HistorienAktion.STATUS_GEAENDERT
        and eintrag.neuer_wert == TicketStatus.GELOEST.value
    ]
    antworten = [
        kommentar.erstellt_am
        for kommentar in ticket.kommentare
        if kommentar.autor_id == ticket.ersteller_id
        and kommentar.sichtbarkeit == Sichtbarkeit.OEFFENTLICH
    ]
    return max((geloest_am or [ticket.aktualisiert_am]) + antworten)


def schliesse_faellige_tickets(tage, jetzt=None):
    """Schließt alle gelösten Tickets, deren Frist abgelaufen ist, und
    liefert sie zurück."""
    jetzt = jetzt or utcnow()
    grenze = jetzt - timedelta(days=tage)
    geschlossen = []

    for ticket in Ticket.query.filter_by(status=TicketStatus.GELOEST).order_by(Ticket.id).all():
        if frist_beginn(ticket) > grenze:
            continue
        # Bedingtes UPDATE: Hat jemand das Ticket seit dem Laden wieder
        # geöffnet, bleibt es offen.
        ergebnis = db.session.execute(
            update(Ticket)
            .where(Ticket.id == ticket.id, Ticket.status == TicketStatus.GELOEST)
            .values(status=TicketStatus.GESCHLOSSEN, aktualisiert_am=jetzt)
            .execution_options(synchronize_session=False)
        )
        if ergebnis.rowcount != 1:
            continue
        db.session.add(
            TicketHistory(
                ticket_id=ticket.id,
                aktion=HistorienAktion.STATUS_GEAENDERT,
                alter_wert=TicketStatus.GELOEST.value,
                neuer_wert=TicketStatus.GESCHLOSSEN.value,
                ausgefuehrt_von_id=None,
                zeitstempel=jetzt,
            )
        )
        geschlossen.append(ticket)

    db.session.commit()
    return geschlossen


def _pruefung_uebernehmen(jetzt):
    """Sperre über alle Gunicorn-Worker hinweg: Prüfen darf nur, wer den
    Zeitstempel in der Datenbank selbst weiterschiebt."""
    ergebnis = db.session.execute(
        update(Settings)
        .where(
            Settings.id == 1,
            or_(
                Settings.auto_schliessen_geprueft_am.is_(None),
                Settings.auto_schliessen_geprueft_am <= jetzt - PRUEF_INTERVALL,
            ),
        )
        .values(auto_schliessen_geprueft_am=jetzt)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return ergebnis.rowcount == 1


def registriere_auto_schliessen(app):
    # Pro Worker zusätzlich lokal drosseln, damit nicht jeder Seitenaufruf
    # die Datenbank nach dem Prüfzeitpunkt fragt.
    naechste_lokale_pruefung = [0.0]

    @app.before_request
    def geloeste_tickets_automatisch_schliessen():
        if request.endpoint == "static" or time.monotonic() < naechste_lokale_pruefung[0]:
            return
        naechste_lokale_pruefung[0] = time.monotonic() + PRUEF_INTERVALL.total_seconds()

        try:
            tage = Settings.get_or_create().auto_schliessen_tage
            if not tage or not _pruefung_uebernehmen(utcnow()):
                return
            geschlossen = schliesse_faellige_tickets(tage)
        except SQLAlchemyError as exc:
            # Darf den eigentlichen Seitenaufruf nie scheitern lassen; der
            # nächste Lauf holt das nach.
            db.session.rollback()
            current_app.logger.warning("Automatisches Schließen gelöster Tickets fehlgeschlagen: %s", exc)
            return

        if not geschlossen:
            return

        current_app.logger.info(
            "Gelöste Tickets automatisch geschlossen: %s",
            ", ".join(f"#{ticket.id}" for ticket in geschlossen),
        )
        # Die Mails samt Ticket-Links hier im Request bauen, aber erst nach
        # der Antwort verschicken - sonst wartet der Nutzer, der zufällig
        # die Prüfung ausgelöst hat, auf den Mailserver.
        nachrichten = [benachrichtigung_auto_geschlossen(ticket, tage) for ticket in geschlossen]

        @after_this_request
        def mails_nach_der_antwort(response):
            def senden():
                with app.app_context():
                    send_mails(nachrichten)

            response.call_on_close(senden)
            return response
