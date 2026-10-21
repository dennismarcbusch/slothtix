"""Seite, auf der Agenten ihre E-Mail-Benachrichtigungen einstellen.

Nur für Agenten: Die Mails an Ersteller (Kommentar, Statusänderung) bleiben
bewusst immer an - sonst erfährt ein User nicht, dass sein Ticket erledigt
ist.
"""

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import BenachrichtigungenForm

benachrichtigungen_bp = Blueprint("benachrichtigungen", __name__)


@benachrichtigungen_bp.route("/benachrichtigungen", methods=["GET", "POST"])
@login_required
def einstellungen():
    if not current_user.ist_agent:
        abort(403)

    form = BenachrichtigungenForm(obj=current_user)
    if form.validate_on_submit():
        form.populate_obj(current_user)
        db.session.commit()
        flash("Benachrichtigungen wurden gespeichert.", "success")
        return redirect(url_for("benachrichtigungen.einstellungen"))

    return render_template("benachrichtigungen.html", form=form)
