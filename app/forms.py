from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    IntegerField,
    MultipleFileField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, EqualTo, Length, NumberRange, Optional

from app.config import Config
from app.models import Sichtbarkeit, TicketPrioritaet


def _coerce_int_or_none(value):
    """coerce für SelectFields mit Leer-Option: eine leere Auswahl ('')
    wird zu None statt einen ValueError beim int()-Cast auszulösen, damit
    DataRequired() sie sauber als "nicht ausgefüllt" ablehnen kann."""
    if value in (None, "", "None"):
        return None
    return int(value)


class TicketForm(FlaskForm):
    titel = StringField("Titel", validators=[DataRequired(), Length(max=255)])
    beschreibung = TextAreaField("Beschreibung", validators=[DataRequired()])
    team_id = SelectField(
        "Team", coerce=_coerce_int_or_none, validators=[DataRequired(message="Bitte ein Team auswählen.")]
    )
    category_id = SelectField(
        "Kategorie",
        coerce=_coerce_int_or_none,
        validators=[DataRequired(message="Bitte eine Kategorie auswählen.")],
    )
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
        "Anhang-Größenlimit (MB)",
        validators=[DataRequired(), NumberRange(min=1, max=Config.MAX_UPLOAD_MB)],
    )
    alte_tickets_tage = IntegerField(
        "Frist für 'altes' Ticket (Tage)", validators=[DataRequired(), NumberRange(min=1, max=365)]
    )


class PasswortAendernForm(FlaskForm):
    aktuell = PasswordField("Aktuelles Passwort", validators=[DataRequired()])
    neu = PasswordField(
        "Neues Passwort",
        validators=[
            DataRequired(),
            # Zwölf Zeichen, weil dieser Account als einziger ohne AD und
            # damit ohne dessen Passwortrichtlinie auskommt.
            Length(min=12, message="Das neue Passwort muss mindestens 12 Zeichen lang sein."),
        ],
    )
    wiederholung = PasswordField(
        "Neues Passwort wiederholen",
        validators=[DataRequired(), EqualTo("neu", message="Die Passwörter stimmen nicht überein.")],
    )
