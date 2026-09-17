"""Benachrichtigungs-Trigger für Ticket-Ereignisse (REQUIREMENTS.md 3.7).

Interne Kommentare lösen bewusst keine Benachrichtigung an den User aus.
"""

from flask import url_for

from app.mail import send_mail, send_mails
from app.models import Sichtbarkeit


def _ticket_url(ticket):
    return url_for("tickets.detail", ticket_id=ticket.id, _external=True)


def notify_ticket_created(ticket):
    betreff = f"[SlothTix] Neues Ticket in {ticket.team.name}: {ticket.titel}"
    text = (
        f"Ein neues Ticket wurde erstellt von {ticket.ersteller.anzeigename}:\n\n"
        f"{ticket.titel}\n\n{ticket_summary(ticket)}"
    )
    send_mails([(agent.email, betreff, text) for agent in ticket.team.mitglieder])


def notify_comment_added(comment):
    ticket = comment.ticket
    if comment.sichtbarkeit != Sichtbarkeit.OEFFENTLICH:
        return

    if comment.autor_id == ticket.ersteller_id:
        # Der Ersteller hat selbst geantwortet -> Team-Agenten informieren.
        betreff = f"[SlothTix] Neue Antwort zu Ticket #{ticket.id}: {ticket.titel}"
        text = (
            f"{comment.autor.anzeigename} hat geantwortet:\n\n{comment.text}\n\n"
            f"{_ticket_url(ticket)}"
        )
        send_mails(
            [
                (agent.email, betreff, text)
                for agent in ticket.team.mitglieder
                if agent.id != comment.autor_id
            ]
        )
    else:
        send_mail(
            ticket.ersteller.email,
            f"[SlothTix] Neuer Kommentar zu deinem Ticket #{ticket.id}: {ticket.titel}",
            f"{comment.autor.anzeigename} hat kommentiert:\n\n{comment.text}\n\n"
            f"{_ticket_url(ticket)}",
        )


def notify_status_changed(ticket, alter_status, neuer_status):
    send_mail(
        ticket.ersteller.email,
        f"[SlothTix] Statusänderung bei Ticket #{ticket.id}: {ticket.titel}",
        f"Der Status deines Tickets hat sich geändert: {alter_status} -> {neuer_status}\n\n"
        f"{_ticket_url(ticket)}",
    )


def benachrichtigung_auto_geschlossen(ticket, tage):
    """Liefert (Empfänger, Betreff, Text) statt direkt zu senden: Der
    Versand passiert erst nach der Antwort, der Ticket-Link braucht aber
    noch den Request-Kontext."""
    return (
        ticket.ersteller.email,
        f"[SlothTix] Ticket #{ticket.id} automatisch geschlossen: {ticket.titel}",
        f"Dein Ticket war seit {tage} Tagen als gelöst markiert und wurde deshalb "
        f"automatisch geschlossen.\n\n"
        f"Falls das Problem weiterhin besteht, erstelle bitte ein neues Ticket.\n\n"
        f"{_ticket_url(ticket)}",
    )


def notify_assigned(ticket):
    if ticket.zugewiesen_an is None:
        return
    send_mail(
        ticket.zugewiesen_an.email,
        f"[SlothTix] Ticket #{ticket.id} wurde dir zugewiesen: {ticket.titel}",
        f"Dir wurde folgendes Ticket zugewiesen:\n\n{ticket_summary(ticket)}\n\n"
        f"{_ticket_url(ticket)}",
    )


def ticket_summary(ticket):
    return (
        f"Team: {ticket.team.name}\n"
        f"Kategorie: {ticket.category.name}\n"
        f"Priorität: {ticket.prioritaet.value}\n\n"
        f"{ticket.beschreibung}"
    )
