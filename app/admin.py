from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from flask_login import current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.ad_abgleich import AbgleichFehler, plane_abgleich, wende_an
from app.auth import admin_required
from app.extensions import db
from app.forms import CategoryForm, PasswortAendernForm, SettingsForm, TeamForm
from app.models import Category, Settings, Team

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/teams")
@admin_required
def teams():
    alle_teams = Team.query.order_by(Team.name).all()
    return render_template(
        "admin/teams.html",
        teams=alle_teams,
        team_form=TeamForm(),
        category_form=CategoryForm(),
    )


@admin_bp.route("/teams/neu", methods=["POST"])
@admin_required
def create_team():
    form = TeamForm()
    if form.validate_on_submit():
        if Team.query.filter_by(name=form.name.data).first():
            flash("Ein Team mit diesem Namen existiert bereits.", "error")
        else:
            team = Team(name=form.name.data, ad_gruppe_agenten=form.ad_gruppe_agenten.data or None)
            db.session.add(team)
            db.session.commit()
            flash(f"Team '{team.name}' wurde angelegt.", "success")
    else:
        flash("Team konnte nicht angelegt werden.", "error")
    return redirect(url_for("admin.teams"))


@admin_bp.route("/teams/<int:team_id>/aktualisieren", methods=["POST"])
@admin_required
def update_team(team_id):
    team = db.get_or_404(Team, team_id)
    form = TeamForm()
    if form.validate_on_submit():
        # Ohne diese Prüfung läuft ein Umbenennen auf einen schon
        # vergebenen Namen in die UNIQUE-Constraint der Datenbank und
        # damit in einen IntegrityError - also HTTP 500 statt einer
        # Meldung. create_team prüft das seit jeher, update_team nicht.
        kollision = Team.query.filter(Team.name == form.name.data, Team.id != team.id).first()
        if kollision is not None:
            flash("Ein Team mit diesem Namen existiert bereits.", "error")
            return redirect(url_for("admin.teams"))

        team.name = form.name.data
        team.ad_gruppe_agenten = form.ad_gruppe_agenten.data or None
        db.session.commit()
        flash(f"Team '{team.name}' wurde aktualisiert.", "success")
    else:
        flash("Team konnte nicht aktualisiert werden.", "error")
    return redirect(url_for("admin.teams"))


@admin_bp.route("/teams/<int:team_id>/umschalten", methods=["POST"])
@admin_required
def toggle_team(team_id):
    team = db.get_or_404(Team, team_id)
    team.aktiv = not team.aktiv
    db.session.commit()
    flash(f"Team '{team.name}' ist jetzt {'aktiv' if team.aktiv else 'inaktiv'}.", "success")
    return redirect(url_for("admin.teams"))


@admin_bp.route("/teams/<int:team_id>/kategorien/neu", methods=["POST"])
@admin_required
def create_category(team_id):
    team = db.get_or_404(Team, team_id)
    form = CategoryForm()
    if form.validate_on_submit():
        if Category.query.filter_by(team_id=team.id, name=form.name.data).first():
            flash("Diese Kategorie existiert für dieses Team bereits.", "error")
        else:
            category = Category(team_id=team.id, name=form.name.data)
            db.session.add(category)
            db.session.commit()
            flash(f"Kategorie '{category.name}' wurde angelegt.", "success")
    else:
        flash("Kategorie konnte nicht angelegt werden.", "error")
    return redirect(url_for("admin.teams"))


@admin_bp.route("/kategorien/<int:category_id>/umschalten", methods=["POST"])
@admin_required
def toggle_category(category_id):
    category = db.get_or_404(Category, category_id)
    category.aktiv = not category.aktiv
    db.session.commit()
    flash(f"Kategorie '{category.name}' ist jetzt {'aktiv' if category.aktiv else 'inaktiv'}.", "success")
    return redirect(url_for("admin.teams"))


@admin_bp.route("/einstellungen", methods=["GET", "POST"])
@admin_required
def settings_view():
    settings = Settings.get_or_create()
    form = SettingsForm(obj=settings)

    if form.validate_on_submit():
        form.populate_obj(settings)
        db.session.commit()
        flash("Einstellungen wurden gespeichert.", "success")
        return redirect(url_for("admin.settings_view"))

    return render_template("admin/settings.html", form=form)


@admin_bp.route("/ad-abgleich")
@admin_required
def ad_abgleich():
    abgleich, fehler = None, None
    try:
        abgleich = plane_abgleich(Settings.get_or_create(), current_app.config.get("LDAP_BIND_PASSWORD"))
    except AbgleichFehler as exc:
        fehler = str(exc)
    return render_template("admin/ad_abgleich.html", abgleich=abgleich, fehler=fehler)


@admin_bp.route("/ad-abgleich", methods=["POST"])
@admin_required
def ad_abgleich_uebernehmen():
    # Neu planen statt die angezeigte Vorschau zu übernehmen: Zwischen
    # Anzeige und Klick kann sich das AD geändert haben.
    try:
        abgleich = plane_abgleich(Settings.get_or_create(), current_app.config.get("LDAP_BIND_PASSWORD"))
    except AbgleichFehler as exc:
        flash(f"{exc} Es wurde nichts geändert.", "error")
        return redirect(url_for("admin.ad_abgleich"))

    wende_an(abgleich)
    flash(f"AD-Abgleich übernommen: {len(abgleich.aenderungen)} Nutzer aktualisiert.", "success")
    return redirect(url_for("admin.ad_abgleich"))


@admin_bp.route("/passwort", methods=["GET", "POST"])
@admin_required
def change_password():
    """Passwortwechsel für den lokalen Admin-Account.

    Betrifft nur diesen einen Account: Alle übrigen Nutzer authentifizieren
    sich per LDAP-Bind, für sie gibt es hier nichts zu ändern. Ohne diese
    Seite ließ sich das Passwort überhaupt nicht wechseln - es stammte
    dauerhaft aus ADMIN_PASSWORD und lag damit im Klartext in der
    Container-Umgebung."""
    if current_user.ad_username is not None:
        flash(
            "Dieser Account meldet sich über das AD an - das Passwort wird "
            "dort verwaltet.",
            "error",
        )
        return redirect(url_for("admin.teams"))

    form = PasswortAendernForm()
    if form.validate_on_submit():
        if not check_password_hash(current_user.passwort_hash or "", form.aktuell.data):
            flash("Das aktuelle Passwort ist falsch.", "error")
        else:
            current_user.passwort_hash = generate_password_hash(form.neu.data)
            db.session.commit()
            flash(
                "Passwort geändert. ADMIN_PASSWORD kann jetzt aus der .env "
                "entfernt werden.",
                "success",
            )
            return redirect(url_for("admin.change_password"))
    elif request.method == "POST":
        flash("Passwort konnte nicht geändert werden.", "error")

    return render_template("admin/passwort.html", form=form)
