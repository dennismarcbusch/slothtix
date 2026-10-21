"""Morgendliche Zusammenfassung der offenen Tickets für Agenten.

Läuft nicht im Web-Prozess, sondern als eigener Dienst (`flask
zusammenfassungen --dauerhaft`, siehe docker-compose.yml): Um 7 Uhr ruft
selten jemand eine Seite auf, an die sich eine Prüfung wie beim
automatischen Schließen hängen könnte.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app, url_for
from sqlalchemy import or_, update
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.mail import send_mails
from app.models import Ticket, TicketPrioritaet, TicketStatus, User, utcnow

OFFENE_STATUS = (TicketStatus.OFFEN, TicketStatus.IN_BEARBEITUNG)

# War der Dienst zur eingestellten Uhrzeit nicht erreichbar (Neustart,
# Update), wird die Zusammenfassung noch so lange nachgeholt - danach
# lohnt sie sich für den Tag nicht mehr.
NACHHOL_FENSTER = timedelta(hours=3)

_PRIO_REIHENFOLGE = {
    TicketPrioritaet.HOCH: 0,
    TicketPrioritaet.MITTEL: 1,
    TicketPrioritaet.NIEDRIG: 2,
}
_STATUS_TEXT = {
    TicketStatus.OFFEN: "offen",
    TicketStatus.IN_BEARBEITUNG: "in Bearbeitung",
}


@contextmanager
def link_kontext(app):
    """Request-Kontext für url_for(..., _external=True) außerhalb eines
    Requests. Der Hostname kommt aus SITE_DOMAIN, wie bei Caddy."""
    domain = app.config.get("SITE_DOMAIN")
    if not domain:
        app.logger.warning(
            "SITE_DOMAIN ist nicht gesetzt - die Links in den Zusammenfassungen "
            "zeigen auf localhost."
        )
        domain = "localhost"
    with app.test_request_context(base_url=f"{app.config['PREFERRED_URL_SCHEME']}://{domain}"):
        yield


def _lokal(jetzt_utc):
    return jetzt_utc.replace(tzinfo=timezone.utc).astimezone(
        ZoneInfo(current_app.config["TIMEZONE"])
    )


def ist_faellig(user, jetzt_lokal):
    if not (user.aktiv and user.zusammenfassung_aktiv and user.ist_agent):
        return False
    if user.zusammenfassung_nur_werktags and jetzt_lokal.weekday() >= 5:
        return False
    heute = jetzt_lokal.date()
    if user.zusammenfassung_gesendet_am is not None and user.zusammenfassung_gesendet_am >= heute:
        return False
    faellig_ab = datetime.combine(heute, user.zusammenfassung_uhrzeit, tzinfo=jetzt_lokal.tzinfo)
    return faellig_ab <= jetzt_lokal < faellig_ab + NACHHOL_FENSTER


def _versand_uebernehmen(user, heute):
    """Bedingtes UPDATE als Sperre: Nur wer das Versanddatum selbst auf
    heute setzt, verschickt - auch wenn der Dienst versehentlich doppelt
    läuft."""
    ergebnis = db.session.execute(
        update(User)
        .where(
            User.id == user.id,
            or_(
                User.zusammenfassung_gesendet_am.is_(None),
                User.zusammenfassung_gesendet_am < heute,
            ),
        )
        .values(zusammenfassung_gesendet_am=heute)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return ergebnis.rowcount == 1


def offene_tickets(user):
    team_ids = [team.id for team in user.teams]
    tickets = (
        Ticket.query.filter(Ticket.team_id.in_(team_ids), Ticket.status.in_(OFFENE_STATUS))
        .options(joinedload(Ticket.team), joinedload(Ticket.zugewiesen_an))
        .all()
    )
    tickets.sort(key=lambda t: (_PRIO_REIHENFOLGE[t.prioritaet], t.erstellt_am))
    return tickets


def _zeile(ticket, jetzt):
    tage = (jetzt - ticket.erstellt_am).days
    alter = "heute erstellt" if tage == 0 else f"seit {tage} Tag{'en' if tage != 1 else ''}"
    details = [ticket.team.name, _STATUS_TEXT[ticket.status], alter]
    return (
        f"#{ticket.id} [{ticket.prioritaet.value}] {ticket.titel}\n"
        f"    {' · '.join(details)}\n"
        f"    {url_for('tickets.detail', ticket_id=ticket.id, _external=True)}"
    )


def baue_zusammenfassung(user, tickets, jetzt):
    """Liefert (Empfänger, Betreff, Text) - oder None, wenn nichts offen
    ist: Eine leere Zusammenfassung wäre nur eine weitere Mail."""
    if not tickets:
        return None

    gruppen = [
        ("Dir zugewiesen", [t for t in tickets if t.zugewiesen_an_id == user.id]),
        ("Noch niemandem zugewiesen", [t for t in tickets if t.zugewiesen_an_id is None]),
    ]
    andere = [t for t in tickets if t.zugewiesen_an_id not in (None, user.id)]
    abschnitte = []
    for titel, gruppe in gruppen:
        if gruppe:
            zeilen = "\n\n".join(_zeile(t, jetzt) for t in gruppe)
            abschnitte.append(f"{titel} ({len(gruppe)}):\n\n{zeilen}")
    if andere:
        zeilen = "\n\n".join(
            f"{_zeile(t, jetzt)}\n    bei {t.zugewiesen_an.anzeigename}" for t in andere
        )
        abschnitte.append(f"Bei Kollegen ({len(andere)}):\n\n{zeilen}")

    anzahl_offen = sum(1 for t in tickets if t.status == TicketStatus.OFFEN)
    anzahl_bearbeitung = len(tickets) - anzahl_offen
    betreff = (
        f"[SlothTix] Zusammenfassung: {anzahl_offen} offen, "
        f"{anzahl_bearbeitung} in Bearbeitung"
    )
    text = (
        f"Guten Morgen {user.anzeigename},\n\n"
        f"in deinen Teams sind {anzahl_offen} Ticket(s) offen und "
        f"{anzahl_bearbeitung} in Bearbeitung.\n\n"
        + "\n\n\n".join(abschnitte)
        + "\n\n--\nDiese Zusammenfassung kannst du unter "
        f"{url_for('benachrichtigungen.einstellungen', _external=True)} anpassen."
    )
    return (user.email, betreff, text)


def sende_faellige_zusammenfassungen(jetzt=None):
    """Verschickt alle jetzt fälligen Zusammenfassungen und liefert die
    Nachrichten zurück. Braucht einen Request-Kontext (link_kontext)."""
    jetzt = jetzt or utcnow()
    jetzt_lokal = _lokal(jetzt)
    nachrichten = []

    kandidaten = User.query.filter_by(aktiv=True, zusammenfassung_aktiv=True).order_by(User.id)
    for user in kandidaten.all():
        if not ist_faellig(user, jetzt_lokal):
            continue
        if not _versand_uebernehmen(user, jetzt_lokal.date()):
            continue
        nachricht = baue_zusammenfassung(user, offene_tickets(user), jetzt)
        if nachricht:
            nachrichten.append(nachricht)

    send_mails(nachrichten)
    return nachrichten
