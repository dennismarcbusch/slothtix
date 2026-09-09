from flask import Blueprint, flash, redirect, render_template, url_for

from app.auth import admin_required
from app.extensions import db
from app.forms import CategoryForm, SettingsForm, TeamForm
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
