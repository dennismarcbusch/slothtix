from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, MultipleFileField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models import Sichtbarkeit, TicketPrioritaet


class TicketForm(FlaskForm):
    titel = StringField("Titel", validators=[DataRequired(), Length(max=255)])
    beschreibung = TextAreaField("Beschreibung", validators=[DataRequired()])
    team_id = SelectField("Team", coerce=int, validators=[DataRequired()])
    category_id = SelectField("Kategorie", coerce=int, validators=[DataRequired()])
    prioritaet = SelectField(
        "Priorität",
        choices=[(p.value, p.value.capitalize()) for p in TicketPrioritaet],
        validators=[DataRequired()],
    )
    anhaenge = MultipleFileField("Anhänge")


class CommentForm(FlaskForm):
    text = TextAreaField("Kommentar", validators=[DataRequired()])
    sichtbarkeit = SelectField(
        "Sichtbarkeit",
        choices=[(s.value, s.value) for s in Sichtbarkeit],
        default=Sichtbarkeit.OEFFENTLICH.value,
    )
    anhaenge = MultipleFileField("Anhänge")


class TeamForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    ad_gruppe_agenten = StringField("AD-Gruppe (Agenten)", validators=[Optional(), Length(max=255)])


class CategoryForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])


class SettingsForm(FlaskForm):
    ad_gruppe_user = StringField("AD-Gruppe (User-Zugriff)", validators=[Optional(), Length(max=255)])
    ldap_server = StringField("LDAP-Server", validators=[Optional(), Length(max=255)])
    ldap_port = IntegerField("LDAP-Port", validators=[Optional(), NumberRange(min=1, max=65535)])
    ldap_use_ssl = BooleanField("LDAP über SSL/TLS")
    ldap_base_dn = StringField("LDAP Base-DN", validators=[Optional(), Length(max=255)])
    ldap_bind_dn = StringField("LDAP Bind-DN (Service-Account)", validators=[Optional(), Length(max=255)])
    smtp_host = StringField("SMTP-Server", validators=[Optional(), Length(max=255)])
    smtp_port = IntegerField("SMTP-Port", validators=[Optional(), NumberRange(min=1, max=65535)])
    smtp_username = StringField("SMTP-Benutzername", validators=[Optional(), Length(max=255)])
    smtp_from = StringField("SMTP Absenderadresse", validators=[Optional(), Length(max=255)])
    anhang_max_groesse_mb = IntegerField(
        "Anhang-Größenlimit (MB)", validators=[DataRequired(), NumberRange(min=1, max=1000)]
    )
    alte_tickets_tage = IntegerField(
        "Frist für 'altes' Ticket (Tage)", validators=[DataRequired(), NumberRange(min=1, max=365)]
    )
