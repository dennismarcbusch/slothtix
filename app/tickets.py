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
from sqlalchemy.orm import joinedload

from app.attachments import ANZEIGBARE_MIME_TYPES, AttachmentError, save_attachments
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


def _category_matches_team(category, team):
    return category is not None and category.aktiv and team is not None and category.team_id == team.id


def _group_categories_by_team(categories):
    grouped = {}
    for c in categories:
        grouped.setdefault(c.team_id, []).append(c)
    return grouped


def _kategorien_fuer_js(categories):
    """Baut die Team->Kategorien-Struktur für das Inline-Skript der
    Formulare (dynamisches Nachladen der Kategorie-Auswahl).

    Bewusst nur einfache Datentypen: Die Struktur wird im Template mit
    dem |tojson-Filter serialisiert, der - anders als json.dumps - auch
    '<', '>' und '&' escaped. Ohne das könnte ein Kategoriename wie
    "</script><img src=x onerror=...>" aus dem <script>-Block ausbrechen
    (gespeichertes XSS)."""
    grouped = _group_categories_by_team(categories)
    return {
        str(team_id): [{"id": c.id, "name": c.name} for c in cats] for team_id, cats in grouped.items()
    }


def _log_history(ticket, aktion, alter_wert, neuer_wert):
    db.session.add(
        TicketHistory(
            ticket_id=ticket.id,
            aktion=aktion,
            alter_wert=alter_wert,
            neuer_wert=neuer_wert,
            ausgefuehrt_von_id=current_user.id,
        )
    )


_PRIORITAET_RANG = {TicketPrioritaet.NIEDRIG: 0, TicketPrioritaet.MITTEL: 1, TicketPrioritaet.HOCH: 2}
_STATUS_RANG = {
    TicketStatus.OFFEN: 0,
    TicketStatus.IN_BEARBEITUNG: 1,
    TicketStatus.GELOEST: 2,
    TicketStatus.GESCHLOSSEN: 3,
}

# Sortierung erfolgt bewusst in Python nach dem Laden statt per DB-Join
# (Team/Kategorie/Ersteller/Zugewiesen sind bereits eager geladen) - bei
# der erwarteten Ticket-Menge (wenige gleichzeitige Nutzer) unproblematisch
# und deutlich einfacher als drei zusätzliche Joins/Aliase für die Sortierung.
# Parameter, die beim Wechsel der Sortierung erhalten bleiben. Die Liste
# ist bewusst eine Allowlist: request.args landete hier früher per ** direkt
# in url_for(), das Schlüssel mit führendem Unterstrich als Steuerparameter
# auswertet (_method, _scheme, _external, _anchor). Ein präpariertes
# "?_method=DELETE" erzeugte damit einen BuildError - also HTTP 500 auf der
# gesamten Ticket-Übersicht, für jeden, der dem Link folgt.
UEBERNOMMENE_FILTER = ("q", "team", "kategorie", "ersteller", "status", "prioritaet")

SORTIER_SPALTEN = {
    "id": lambda t: t.id,
    "titel": lambda t: t.titel.lower(),
    "team": lambda t: t.team.name.lower(),
    "kategorie": lambda t: t.category.name.lower(),
    "prioritaet": lambda t: _PRIORITAET_RANG[t.prioritaet],
    "status": lambda t: _STATUS_RANG[t.status],
    "ersteller": lambda t: t.ersteller.anzeigename.lower(),
    "zugewiesen": lambda t: (t.zugewiesen_an.anzeigename.lower() if t.zugewiesen_an else ""),
    "erstellt": lambda t: t.erstellt_am,
}


def _sichtbare_tickets_basis(user):
    query = Ticket.query
    if user.ist_admin:
        pass
    elif user.ist_agent:
        team_ids = [t.id for t in user.teams]
        query = query.filter(db.or_(Ticket.team_id.in_(team_ids), Ticket.ersteller_id == user.id))
    else:
        query = query.filter(Ticket.ersteller_id == user.id)
    return query


@tickets_bp.route("/")
@login_required
def list_view():
    base_query = _sichtbare_tickets_basis(current_user)

    show_closed = session.get("show_closed", False)
    if not show_closed:
        base_query = base_query.filter(Ticket.status != TicketStatus.GESCHLOSSEN)

    only_mine = current_user.ist_agent and session.get("only_mine_assigned", False)
    if only_mine:
        base_query = base_query.filter(Ticket.zugewiesen_an_id == current_user.id)

    # Erstellbare Filter-Optionen aus dem sichtbaren Scope (vor den
    # eigentlichen Filtern), damit das Dropdown unabhängig von der
    # aktuellen Filterauswahl vollständig bleibt.
    erstellbare_ids = {
        row[0] for row in base_query.with_entities(Ticket.ersteller_id).distinct()
    }
    erstellbare_ersteller = (
        User.query.filter(User.id.in_(erstellbare_ids)).order_by(User.anzeigename).all()
    )

    query = base_query.options(
        joinedload(Ticket.team),
        joinedload(Ticket.category),
        joinedload(Ticket.ersteller),
        joinedload(Ticket.zugewiesen_an),
    )

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

    ersteller_filter = request.args.get("ersteller", type=int)
    if ersteller_filter:
        query = query.filter(Ticket.ersteller_id == ersteller_filter)

    suche = request.args.get("q", "").strip()
    if suche:
        like = f"%{suche}%"
        query = query.filter(db.or_(Ticket.titel.ilike(like), Ticket.beschreibung.ilike(like)))

    sort_spalte = request.args.get("sort", "erstellt")
    if sort_spalte not in SORTIER_SPALTEN:
        sort_spalte = "erstellt"
    sort_richtung = request.args.get("dir")
    if sort_richtung not in ("asc", "desc"):
        sort_richtung = "desc" if sort_spalte == "erstellt" else "asc"

    tickets = query.order_by(Ticket.id).all()
    tickets.sort(key=SORTIER_SPALTEN[sort_spalte], reverse=(sort_richtung == "desc"))

    ansicht = "board" if session.get("board_ansicht", False) else "liste"
    tickets_by_status = {}
    if ansicht == "board":
        for ticket in tickets:
            tickets_by_status.setdefault(ticket.status, []).append(ticket)

    def sort_url(spalte):
        args = {k: request.args[k] for k in UEBERNOMMENE_FILTER if k in request.args}
        args["sort"] = spalte
        if spalte == sort_spalte:
            args["dir"] = "asc" if sort_richtung == "desc" else "desc"
        else:
            args.pop("dir", None)
        return url_for("tickets.list_view", **args)

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
        erstellbare_ersteller=erstellbare_ersteller,
        show_closed=show_closed,
        only_mine=only_mine,
        alt_grenze=alt_grenze,
        filters=request.args,
        sort_url=sort_url,
        sort_spalte=sort_spalte,
        sort_richtung=sort_richtung,
        ansicht=ansicht,
        tickets_by_status=tickets_by_status,
        TicketStatus=TicketStatus,
        TicketPrioritaet=TicketPrioritaet,
    )


@tickets_bp.route("/geschlossene-umschalten", methods=["POST"])
@login_required
def toggle_closed():
    session["show_closed"] = not session.get("show_closed", False)
    return redirect(request.referrer or url_for("tickets.list_view"))


@tickets_bp.route("/ansicht-umschalten", methods=["POST"])
@login_required
def toggle_board_view():
    session["board_ansicht"] = not session.get("board_ansicht", False)
    return redirect(request.referrer or url_for("tickets.list_view"))


@tickets_bp.route("/mir-zugewiesen-umschalten", methods=["POST"])
@login_required
def toggle_only_mine():
    session["only_mine_assigned"] = not session.get("only_mine_assigned", False)
    return redirect(request.referrer or url_for("tickets.list_view"))


@tickets_bp.route("/neu", methods=["GET", "POST"])
@login_required
def new():
    form = TicketForm()
    teams = Team.query.filter_by(aktiv=True).order_by(Team.name).all()
    form.team_id.choices = [("", "Bitte wählen")] + [(t.id, t.name) for t in teams]
    categories = Category.query.filter_by(aktiv=True).join(Team).order_by(Team.name, Category.name).all()
    form.category_id.choices = [("", "Bitte zuerst Team wählen")] + [
        (c.id, f"{c.team.name} – {c.name}") for c in categories
    ]

    kategorien_fuer_js = _kategorien_fuer_js(categories)

    if form.validate_on_submit():
        team = db.session.get(Team, form.team_id.data)
        category = db.session.get(Category, form.category_id.data)
        if not team or not team.aktiv:
            flash("Ungültiges Team.", "error")
        elif not _category_matches_team(category, team):
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
                    kategorien_fuer_js=kategorien_fuer_js,
                )

            db.session.commit()
            notify_ticket_created(ticket)
            flash("Ticket wurde erstellt.", "success")
            return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    elif request.method == "POST":
        flash("Bitte die markierten Pflichtfelder korrekt ausfüllen.", "error")

    return render_template(
        "tickets/new.html",
        form=form,
        categories=categories,
        kategorien_fuer_js=kategorien_fuer_js,
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
    aktive_kategorien = [c for t in teams for c in t.kategorien if c.aktiv]
    kategorien_by_team = _group_categories_by_team(aktive_kategorien)
    kategorien_fuer_js = _kategorien_fuer_js(aktive_kategorien)

    return render_template(
        "tickets/detail.html",
        ticket=ticket,
        kommentare=_sichtbare_kommentare(current_user, ticket),
        comment_form=comment_form,
        kann_verwalten=kann_verwalten,
        teams=teams,
        kategorien_by_team=kategorien_by_team,
        kategorien_fuer_js=kategorien_fuer_js,
        TicketStatus=TicketStatus,
        TicketPrioritaet=TicketPrioritaet,
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


@tickets_bp.route("/<int:ticket_id>/aktualisieren", methods=["POST"])
@login_required
def update_details(ticket_id):
    """Sammel-Endpunkt für Status, Priorität, Zuweisung und Kategorie.

    Bewusst in einem Formular/Endpunkt zusammengefasst, damit Agenten nicht
    für jede der vier Eigenschaften einzeln speichern müssen. Der Team-
    Wechsel bleibt ein eigener Endpunkt (change_team), da er die Kategorie
    auf eine andere Team-Zuordnung umstellt und die Zuweisung zurücksetzt -
    eine deutlich größere Auswirkung als die übrigen Felder."""
    ticket = db.get_or_404(Ticket, ticket_id)
    if not _kann_ticket_verwalten(current_user, ticket):
        abort(403)

    try:
        neuer_status = TicketStatus(request.form.get("status"))
    except ValueError:
        flash("Ungültiger Status.", "error")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    try:
        neue_prioritaet = TicketPrioritaet(request.form.get("prioritaet"))
    except ValueError:
        flash("Ungültige Priorität.", "error")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    neue_category = db.session.get(Category, request.form.get("category_id", type=int))
    if not _category_matches_team(neue_category, ticket.team):
        flash("Ungültige Kategorie.", "error")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    assignee_id = request.form.get("zugewiesen_an_id", type=int)
    neuer_zugewiesener = None
    if assignee_id:
        neuer_zugewiesener = db.session.get(User, assignee_id)
        if not neuer_zugewiesener or not neuer_zugewiesener.ist_agent_von(ticket.team_id):
            flash("Ungültige Zuweisung.", "error")
            return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    status_wurde_geaendert = neuer_status != ticket.status
    prioritaet_wurde_geaendert = neue_prioritaet != ticket.prioritaet
    category_wurde_geaendert = neue_category.id != ticket.category_id
    neue_zuweisung_id = neuer_zugewiesener.id if neuer_zugewiesener else None
    zuweisung_wurde_geaendert = neue_zuweisung_id != ticket.zugewiesen_an_id

    if not (
        status_wurde_geaendert
        or prioritaet_wurde_geaendert
        or category_wurde_geaendert
        or zuweisung_wurde_geaendert
    ):
        flash("Keine Änderungen.", "info")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    alter_status = ticket.status
    if status_wurde_geaendert:
        ticket.status = neuer_status
        _log_history(ticket, HistorienAktion.STATUS_GEAENDERT, alter_status.value, neuer_status.value)

    if prioritaet_wurde_geaendert:
        alte_prioritaet = ticket.prioritaet
        ticket.prioritaet = neue_prioritaet
        _log_history(
            ticket, HistorienAktion.PRIORITAET_GEAENDERT, alte_prioritaet.value, neue_prioritaet.value
        )

    if category_wurde_geaendert:
        alte_category_name = ticket.category.name
        ticket.category_id = neue_category.id
        _log_history(ticket, HistorienAktion.KATEGORIE_GEAENDERT, alte_category_name, neue_category.name)

    if zuweisung_wurde_geaendert:
        alter_wert = ticket.zugewiesen_an.anzeigename if ticket.zugewiesen_an else "Niemand"
        neuer_wert = neuer_zugewiesener.anzeigename if neuer_zugewiesener else "Niemand"
        ticket.zugewiesen_an_id = neue_zuweisung_id
        _log_history(ticket, HistorienAktion.ZUGEWIESEN, alter_wert, neuer_wert)

    db.session.commit()

    if status_wurde_geaendert:
        notify_status_changed(ticket, alter_status.value, neuer_status.value)
    if zuweisung_wurde_geaendert and ticket.zugewiesen_an_id:
        notify_assigned(ticket)

    flash("Ticket aktualisiert.", "success")
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
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))
    if not _category_matches_team(neue_category, neues_team):
        flash("Die Kategorie muss zum neuen Team passen.", "error")
        return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    altes_team_name = ticket.team.name
    ticket.team_id = neues_team.id
    ticket.category_id = neue_category.id
    ticket.zugewiesen_an_id = None
    _log_history(ticket, HistorienAktion.TEAM_GEWECHSELT, altes_team_name, neues_team.name)
    db.session.commit()
    flash("Team geändert.", "success")

    # Nach dem Wechsel zur Übersicht statt zur Detailseite: Ist der
    # ausführende Agent im neuen Team nicht Mitglied (und nicht Ersteller),
    # kann er das Ticket laut _kann_ticket_sehen nicht mehr aufrufen - ein
    # Redirect zur Detailseite würde dann in einem 403 enden.
    return redirect(url_for("tickets.list_view"))


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

    # Der Content-Type kommt aus der beim Upload geprüften Allowlist und
    # wird explizit gesetzt, statt ihn von send_from_directory aus dem
    # Dateinamen raten zu lassen. Zusammen mit dem globalen
    # X-Content-Type-Options: nosniff (siehe app/security.py) steht damit
    # fest, wie der Browser die Datei behandelt.
    #
    # Bilder bleiben bewusst inline abrufbar - Screenshots sind der
    # Hauptanwendungsfall und sollen sich per Klick ansehen lassen. Alles
    # andere wird als Download ausgeliefert, damit es gar nicht erst im
    # Dokumentkontext der Anwendung landet.
    inline_anzeigen = attachment.mime_type in ANZEIGBARE_MIME_TYPES
    return send_from_directory(
        os.path.dirname(full_path),
        os.path.basename(full_path),
        download_name=attachment.dateiname,
        mimetype=attachment.mime_type,
        as_attachment=not inline_anzeigen,
    )
