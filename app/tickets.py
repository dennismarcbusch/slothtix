import json
import os
from datetime import timedelta

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user, login_required

from app.attachments import AttachmentError, save_attachments
from app.extensions import db
from app.forms import CommentForm, TicketForm
from app.models import (
    Attachment,
    Category,
    Comment,
    HistorienAktion,
    Settings,
    Sichtbarkeit,
    Team,
    Ticket,
    TicketHistory,
    TicketPrioritaet,
    TicketStatus,
    User,
    utcnow,
)
from app.notifications import (
    notify_assigned,
    notify_comment_added,
    notify_status_changed,
    notify_ticket_created,
)

tickets_bp = Blueprint("tickets", __name__, url_prefix="/tickets")


def _kann_ticket_sehen(user, ticket):
    return user.ist_admin or user.ist_agent_von(ticket.team_id) or ticket.ersteller_id == user.id


def _kann_ticket_verwalten(user, ticket):
    """Bearbeiten/Zuweisen/Status/Team ändern: Admin oder Agent des
    aktuellen Teams des Tickets."""
    return user.ist_admin or user.ist_agent_von(ticket.team_id)


def _sichtbare_kommentare(user, ticket):
    if user.ist_admin or user.ist_agent_von(ticket.team_id):
        return ticket.kommentare
    return [k for k in ticket.kommentare if k.sichtbarkeit == Sichtbarkeit.OEFFENTLICH]


@tickets_bp.route("/")
@login_required
def list_view():
    query = Ticket.query

    if current_user.ist_admin:
        pass
    elif current_user.ist_agent:
        team_ids = [t.id for t in current_user.teams]
        query = query.filter(
            db.or_(Ticket.team_id.in_(team_ids), Ticket.ersteller_id == current_user.id)
        )
    else:
        query = query.filter(Ticket.ersteller_id == current_user.id)

    show_closed = session.get("show_closed", False)
    if not show_closed:
        query = query.filter(Ticket.status != TicketStatus.GESCHLOSSEN)

    team_filter = request.args.get("team", type=int)
    if team_filter:
        query = query.filter(Ticket.team_id == team_filter)

    status_filter = request.args.get("status")
    if status_filter:
        try:
            query = query.filter(Ticket.status == TicketStatus(status_filter))
        except ValueError:
            pass

    prio_filter = request.args.get("prioritaet")
    if prio_filter:
        try:
            query = query.filter(Ticket.prioritaet == TicketPrioritaet(prio_filter))
        except ValueError:
            pass

    category_filter = request.args.get("kategorie", type=int)
    if category_filter:
        query = query.filter(Ticket.category_id == category_filter)

    suche = request.args.get("q", "").strip()
    if suche:
        like = f"%{suche}%"
        query = query.filter(db.or_(Ticket.titel.ilike(like), Ticket.beschreibung.ilike(like)))

    tickets = query.order_by(Ticket.erstellt_am.desc()).all()

    settings = Settings.get_or_create()
    alt_grenze = utcnow() - timedelta(days=settings.alte_tickets_tage)

    if current_user.ist_admin:
        teams = Team.query.filter_by(aktiv=True).order_by(Team.name).all()
        categories = Category.query.filter_by(aktiv=True).all()
    else:
        teams = current_user.teams
        categories = [c for t in teams for c in t.kategorien if c.aktiv]

    return render_template(
        "tickets/list.html",
        tickets=tickets,
        teams=teams,
        categories=categories,
        show_closed=show_closed,
        alt_grenze=alt_grenze,
        filters=request.args,
        TicketStatus=TicketStatus,
        TicketPrioritaet=TicketPrioritaet,
    )


@tickets_bp.route("/geschlossene-umschalten", methods=["POST"])
@login_required
def toggle_closed():
    session["show_closed"] = not session.get("show_closed", False)
    return redirect(request.referrer or url_for("tickets.list_view"))


@tickets_bp.route("/neu", methods=["GET", "POST"])
@login_required
def new():
    form = TicketForm()
    teams = Team.query.filter_by(aktiv=True).order_by(Team.name).all()
    form.team_id.choices = [(t.id, t.name) for t in teams]
    categories = Category.query.filter_by(aktiv=True).join(Team).order_by(Team.name, Category.name).all()
    form.category_id.choices = [(c.id, f"{c.team.name} – {c.name}") for c in categories]

    categories_by_team = {}
    for c in categories:
        categories_by_team.setdefault(str(c.team_id), []).append({"id": c.id, "name": c.name})
    categories_by_team_json = json.dumps(categories_by_team)

    if form.validate_on_submit():
        team = db.session.get(Team, form.team_id.data)
        category = db.session.get(Category, form.category_id.data)
        if not team or not team.aktiv:
            flash("Ungültiges Team.", "error")
        elif not category or category.team_id != team.id or not category.aktiv:
            flash("Die gewählte Kategorie gehört nicht zu diesem Team.", "error")
        else:
            ticket = Ticket(
                titel=form.titel.data,
                beschreibung=form.beschreibung.data,
                team_id=team.id,
                category_id=category.id,
                ersteller_id=current_user.id,
                prioritaet=TicketPrioritaet(form.prioritaet.data),
            )
            db.session.add(ticket)
            db.session.flush()

            try:
                save_attachments(current_app, form.anhaenge.data, current_user, ticket=ticket)
            except AttachmentError as exc:
                db.session.rollback()
                flash(str(exc), "error")
                return render_template(
                    "tickets/new.html",
                    form=form,
                    categories=categories,
                    categories_by_team_json=categories_by_team_json,
                )

            db.session.commit()
            notify_ticket_created(ticket)
            flash("Ticket wurde erstellt.", "success")
            return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    return render_template(
        "tickets/new.html",
        form=form,
        categories=categories,
        categories_by_team_json=categories_by_team_json,
    )


@tickets_bp.route("/<int:ticket_id>")
@login_required
def detail(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    if not _kann_ticket_sehen(current_user, ticket):
        abort(403)

    kann_verwalten = _kann_ticket_verwalten(current_user, ticket)
    comment_form = CommentForm()
    if not kann_verwalten:
        comment_form.sichtbarkeit.data = Sichtbarkeit.OEFFENTLICH.value

    teams = Team.query.filter_by(aktiv=True).order_by(Team.name).all() if kann_verwalten else []
    kategorien_by_team = {t.id: [c for c in t.kategorien if c.aktiv] for t in teams}
    kategorien_by_team_json = json.dumps(
        {str(tid): [{"id": c.id, "name": c.name} for c in cats] for tid, cats in kategorien_by_team.items()}
    )

    return render_template(
        "tickets/detail.html",
        ticket=ticket,
        kommentare=_sichtbare_kommentare(current_user, ticket),
        comment_form=comment_form,
        kann_verwalten=kann_verwalten,
        teams=teams,
        kategorien_by_team=kategorien_by_team,
        kategorien_by_team_json=kategorien_by_team_json,
        TicketStatus=TicketStatus,
        Sichtbarkeit=Sichtbarkeit,
        HistorienAktion=HistorienAktion,
    )


@tickets_bp.route("/<int:ticket_id>/kommentar", methods=["POST"])
@login_required
def add_comment(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    if not _kann_ticket_sehen(current_user, ticket):
        abort(403)

    form = CommentForm()
    kann_verwalten = _kann_ticket_verwalten(current_user, ticket)

    if form.validate_on_submit():
        sichtbarkeit = (
            Sichtbarkeit(form.sichtbarkeit.data) if kann_verwalten else Sichtbarkeit.OEFFENTLICH
        )
        comment = Comment(
            ticket_id=ticket.id,
            autor_id=current_user.id,
            text=form.text.data,
            sichtbarkeit=sichtbarkeit,
        )
        db.session.add(comment)
        db.session.flush()

        try:
            save_attachments(current_app, form.anhaenge.data, current_user, comment=comment)
        except AttachmentError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("tickets.detail", ticket_id=ticket.id))

        db.session.commit()
        notify_comment_added(comment)
        flash("Kommentar hinzugefügt.", "success")
    else:
        flash("Kommentar konnte nicht gespeichert werden.", "error")

    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/zuweisen", methods=["POST"])
@login_required
def assign(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    if not _kann_ticket_verwalten(current_user, ticket):
        abort(403)

    assignee_id = request.form.get("zugewiesen_an_id", type=int)
    alter_wert = ticket.zugewiesen_an.anzeigename if ticket.zugewiesen_an else "Niemand"

    if assignee_id:
        assignee = db.session.get(User, assignee_id)
        if not assignee or not assignee.ist_agent_von(ticket.team_id):
            flash("Ungültige Zuweisung.", "error")
            return redirect(url_for("tickets.detail", ticket_id=ticket.id))
        ticket.zugewiesen_an_id = assignee.id
        neuer_wert = assignee.anzeigename
    else:
        ticket.zugewiesen_an_id = None
        neuer_wert = "Niemand"

    db.session.add(
        TicketHistory(
            ticket_id=ticket.id,
            aktion=HistorienAktion.ZUGEWIESEN,
            alter_wert=alter_wert,
            neuer_wert=neuer_wert,
            ausgefuehrt_von_id=current_user.id,
        )
    )
    db.session.commit()
    if ticket.zugewiesen_an_id:
        notify_assigned(ticket)
    flash("Zuweisung aktualisiert.", "success")
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/status", methods=["POST"])
@login_required
def change_status(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    if not _kann_ticket_verwalten(current_user, ticket):
        abort(403)

    try:
        neuer_status = TicketStatus(request.form.get("status"))
    except ValueError:
        flash("Ungültiger Status.", "error")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    alter_status = ticket.status
    if neuer_status != alter_status:
        ticket.status = neuer_status
        db.session.add(
            TicketHistory(
                ticket_id=ticket.id,
                aktion=HistorienAktion.STATUS_GEAENDERT,
                alter_wert=alter_status.value,
                neuer_wert=neuer_status.value,
                ausgefuehrt_von_id=current_user.id,
            )
        )
        db.session.commit()
        notify_status_changed(ticket, alter_status.value, neuer_status.value)
        flash("Status aktualisiert.", "success")

    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/<int:ticket_id>/team", methods=["POST"])
@login_required
def change_team(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    if not _kann_ticket_verwalten(current_user, ticket):
        abort(403)

    neues_team = db.session.get(Team, request.form.get("team_id", type=int))
    neue_category = db.session.get(Category, request.form.get("category_id", type=int))

    if not neues_team or not neues_team.aktiv:
        flash("Ungültiges Team.", "error")
    elif not neue_category or neue_category.team_id != neues_team.id:
        flash("Die Kategorie muss zum neuen Team passen.", "error")
    else:
        altes_team_name = ticket.team.name
        ticket.team_id = neues_team.id
        ticket.category_id = neue_category.id
        ticket.zugewiesen_an_id = None
        db.session.add(
            TicketHistory(
                ticket_id=ticket.id,
                aktion=HistorienAktion.TEAM_GEWECHSELT,
                alter_wert=altes_team_name,
                neuer_wert=neues_team.name,
                ausgefuehrt_von_id=current_user.id,
            )
        )
        db.session.commit()
        flash("Team geändert.", "success")

    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets_bp.route("/anhaenge/<int:attachment_id>")
@login_required
def download_attachment(attachment_id):
    attachment = db.get_or_404(Attachment, attachment_id)
    ticket = attachment.ticket or attachment.comment.ticket

    if not _kann_ticket_sehen(current_user, ticket):
        abort(403)
    if (
        attachment.comment is not None
        and attachment.comment.sichtbarkeit != Sichtbarkeit.OEFFENTLICH
        and not _kann_ticket_verwalten(current_user, ticket)
    ):
        abort(403)

    full_path = os.path.join(current_app.instance_path, attachment.pfad)
    return send_from_directory(
        os.path.dirname(full_path),
        os.path.basename(full_path),
        download_name=attachment.dateiname,
    )
