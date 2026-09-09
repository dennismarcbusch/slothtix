import enum
from datetime import datetime, timezone

from flask_login import UserMixin

from app.extensions import db


def utcnow():
    """Naive UTC-Zeitstempel. SQLite verliert Zeitzoneninfo beim
    Round-Trip ohnehin, daher wird konsequent naiv (aber UTC) gearbeitet,
    um Vergleiche zwischen frisch erzeugten und aus der DB geladenen
    Zeitstempeln zu vermeiden (naive vs. aware TypeError)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TicketStatus(enum.Enum):
    OFFEN = "offen"
    IN_BEARBEITUNG = "in_bearbeitung"
    GELOEST = "geloest"
    GESCHLOSSEN = "geschlossen"


class TicketPrioritaet(enum.Enum):
    NIEDRIG = "niedrig"
    MITTEL = "mittel"
    HOCH = "hoch"


class Sichtbarkeit(enum.Enum):
    OEFFENTLICH = "oeffentlich"
    INTERN = "intern"


class HistorienAktion(enum.Enum):
    STATUS_GEAENDERT = "status_geaendert"
    ZUGEWIESEN = "zugewiesen"
    TEAM_GEWECHSELT = "team_gewechselt"


team_memberships = db.Table(
    "team_memberships",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("team_id", db.Integer, db.ForeignKey("team.id"), primary_key=True),
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad_username = db.Column(db.String(255), unique=True, nullable=True)
    anzeigename = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    ist_admin = db.Column(db.Boolean, nullable=False, default=False)
    aktiv = db.Column(db.Boolean, nullable=False, default=True)
    # Nur für den lokalen Admin-Account gesetzt - reguläre Nutzer
    # authentifizieren ausschließlich per LDAP-Bind, ohne lokal
    # gespeichertes Passwort.
    passwort_hash = db.Column(db.String(255), nullable=True)
    erstellt_am = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    letzter_login_am = db.Column(db.DateTime(timezone=True), nullable=True)

    teams = db.relationship(
        "Team", secondary=team_memberships, back_populates="mitglieder"
    )

    @property
    def is_active(self):
        return self.aktiv

    @property
    def ist_agent(self):
        return len(self.teams) > 0

    def ist_agent_von(self, team_id):
        return any(t.id == team_id for t in self.teams)

    def __repr__(self):
        return f"<User {self.anzeigename!r}>"


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    ad_gruppe_agenten = db.Column(db.String(255), nullable=True)
    aktiv = db.Column(db.Boolean, nullable=False, default=True)

    mitglieder = db.relationship(
        "User", secondary=team_memberships, back_populates="teams"
    )
    kategorien = db.relationship(
        "Category", back_populates="team", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Team {self.name!r}>"


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    aktiv = db.Column(db.Boolean, nullable=False, default=True)

    team = db.relationship("Team", back_populates="kategorien")

    __table_args__ = (
        db.UniqueConstraint("team_id", "name", name="uq_category_team_name"),
    )

    def __repr__(self):
        return f"<Category {self.name!r}>"


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titel = db.Column(db.String(255), nullable=False)
    beschreibung = db.Column(db.Text, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    ersteller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    zugewiesen_an_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    status = db.Column(
        db.Enum(TicketStatus), nullable=False, default=TicketStatus.OFFEN
    )
    prioritaet = db.Column(db.Enum(TicketPrioritaet), nullable=False)
    erstellt_am = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    aktualisiert_am = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    team = db.relationship("Team")
    category = db.relationship("Category")
    ersteller = db.relationship("User", foreign_keys=[ersteller_id])
    zugewiesen_an = db.relationship("User", foreign_keys=[zugewiesen_an_id])
    kommentare = db.relationship(
        "Comment", back_populates="ticket", cascade="all, delete-orphan"
    )
    anhaenge = db.relationship(
        "Attachment", back_populates="ticket", cascade="all, delete-orphan"
    )
    historie = db.relationship(
        "TicketHistory", back_populates="ticket", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Ticket {self.id} {self.titel!r}>"


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("ticket.id"), nullable=False)
    autor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    sichtbarkeit = db.Column(db.Enum(Sichtbarkeit), nullable=False)
    erstellt_am = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    ticket = db.relationship("Ticket", back_populates="kommentare")
    autor = db.relationship("User")
    anhaenge = db.relationship(
        "Attachment", back_populates="comment", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Comment {self.id} auf Ticket {self.ticket_id}>"


class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("ticket.id"), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comment.id"), nullable=True)
    dateiname = db.Column(db.String(255), nullable=False)
    pfad = db.Column(db.String(1024), nullable=False)
    groesse_bytes = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(255), nullable=False)
    hochgeladen_von_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    erstellt_am = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    ticket = db.relationship("Ticket", back_populates="anhaenge")
    comment = db.relationship("Comment", back_populates="anhaenge")
    hochgeladen_von = db.relationship("User")

    __table_args__ = (
        db.CheckConstraint(
            "(ticket_id IS NOT NULL AND comment_id IS NULL) OR "
            "(ticket_id IS NULL AND comment_id IS NOT NULL)",
            name="ck_attachment_exactly_one_parent",
        ),
    )

    def __repr__(self):
        return f"<Attachment {self.dateiname!r}>"


class TicketHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("ticket.id"), nullable=False)
    aktion = db.Column(db.Enum(HistorienAktion), nullable=False)
    alter_wert = db.Column(db.String(255), nullable=True)
    neuer_wert = db.Column(db.String(255), nullable=True)
    ausgefuehrt_von_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    zeitstempel = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    ticket = db.relationship("Ticket", back_populates="historie")
    ausgefuehrt_von = db.relationship("User")

    def __repr__(self):
        return f"<TicketHistory {self.aktion.value} auf Ticket {self.ticket_id}>"


class Settings(db.Model):
    """Singleton-Zeile (id=1) für admin-konfigurierbare, nicht-geheime
    Einstellungen. Geheimnisse (LDAP-Bind-Passwort, SMTP-Passwort) werden
    bewusst nicht hier, sondern über Env-Vars verwaltet."""

    id = db.Column(db.Integer, primary_key=True)
    ad_gruppe_user = db.Column(db.String(255), nullable=True)
    ldap_server = db.Column(db.String(255), nullable=True)
    ldap_port = db.Column(db.Integer, nullable=True)
    ldap_use_ssl = db.Column(db.Boolean, nullable=False, default=True)
    ldap_base_dn = db.Column(db.String(255), nullable=True)
    ldap_bind_dn = db.Column(db.String(255), nullable=True)
    smtp_host = db.Column(db.String(255), nullable=True)
    smtp_port = db.Column(db.Integer, nullable=True)
    smtp_username = db.Column(db.String(255), nullable=True)
    smtp_from = db.Column(db.String(255), nullable=True)
    anhang_max_groesse_mb = db.Column(db.Integer, nullable=False, default=5)
    alte_tickets_tage = db.Column(db.Integer, nullable=False, default=7)

    @classmethod
    def get_or_create(cls):
        settings = db.session.get(cls, 1)
        if settings is None:
            settings = cls(id=1)
            db.session.add(settings)
            # flush() statt commit(): darf keine fremde, noch offene
            # Transaktion des Aufrufers committen (z. B. ein bereits
            # geflushtes, aber noch nicht bestätigtes Ticket).
            db.session.flush()
        return settings

    def __repr__(self):
        return "<Settings>"
