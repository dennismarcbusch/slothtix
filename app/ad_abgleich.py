"""Abgleich aller bekannten AD-Nutzer mit dem Verzeichnis.

Der Login-Sync (auth.sync_user_from_ldap) aktualisiert einen Nutzer nur,
wenn er sich anmeldet. Wer im AD gelöscht oder aus den Gruppen entfernt
wurde, meldet sich aber nie wieder an und bliebe sonst dauerhaft aktiv und
als Agent seiner Teams sichtbar. Der Abgleich wendet dieselben Regeln auf
alle Nutzer auf einmal an. Neue Nutzer legt er bewusst nicht an - das
bleibt beim ersten Login.
"""

from dataclasses import dataclass, field

from flask import current_app

from app.extensions import db
from app.ldap_service import LdapAuthError, lookup_users
from app.models import Team, Ticket, TicketStatus, User


class AbgleichFehler(Exception):
    """Der Abgleich wurde abgebrochen, es wurde nichts geändert."""


def ermittle_berechtigung(gruppen, settings, aktive_teams):
    """Liefert (ist_user, agent_teams) für die AD-Gruppen eines Nutzers."""
    ist_user = bool(settings.ad_gruppe_user) and settings.ad_gruppe_user in gruppen
    agent_teams = [
        team for team in aktive_teams if team.ad_gruppe_agenten and team.ad_gruppe_agenten in gruppen
    ]
    return ist_user, agent_teams


@dataclass
class NutzerAenderung:
    user: User
    aktiv_neu: bool
    teams_neu: list
    grund: str = None
    anzeigename_neu: str = None
    email_neu: str = None
    teams_entfernt: list = field(default_factory=list)
    teams_hinzu: list = field(default_factory=list)
    # Nicht geschlossene Tickets, die dem Nutzer in einem Team zugewiesen
    # sind, dem er danach nicht mehr angehört. Werden nicht angefasst.
    offene_tickets: list = field(default_factory=list)

    @property
    def deaktiviert(self):
        return self.user.aktiv and not self.aktiv_neu

    def beschreibung(self):
        zeilen = []
        if self.deaktiviert:
            zeilen.append(f"wird deaktiviert ({self.grund})")
        elif self.aktiv_neu and not self.user.aktiv:
            zeilen.append("wird reaktiviert")
        zeilen += [f"verlässt Team {team.name}" for team in self.teams_entfernt]
        zeilen += [f"kommt zu Team {team.name}" for team in self.teams_hinzu]
        if self.anzeigename_neu is not None:
            zeilen.append(f"Anzeigename: {self.user.anzeigename} → {self.anzeigename_neu}")
        if self.email_neu is not None:
            zeilen.append(f"E-Mail: {self.user.email or '(leer)'} → {self.email_neu or '(leer)'}")
        return zeilen


@dataclass
class Abgleich:
    geprueft: int
    aenderungen: list


def plane_abgleich(settings, bind_password):
    """Ermittelt die nötigen Änderungen, ohne etwas zu schreiben.

    Wirft `AbgleichFehler`, wenn das Verzeichnis nicht erreichbar ist oder
    das Ergebnis nach einer Fehlkonfiguration aussieht."""
    nutzer = User.query.filter(User.ad_username.isnot(None)).order_by(User.anzeigename).all()
    if not nutzer:
        return Abgleich(geprueft=0, aenderungen=[])

    try:
        gefunden = lookup_users(settings, bind_password, [u.ad_username for u in nutzer])
    except LdapAuthError as exc:
        raise AbgleichFehler(str(exc)) from exc

    aktive_teams = Team.query.filter_by(aktiv=True).all()
    aenderungen = []
    for user in nutzer:
        aenderung = _plane_nutzer(user, gefunden.get(user.ad_username), settings, aktive_teams)
        if aenderung is not None:
            aenderungen.append(aenderung)

    # Eine falsche Base-DN oder eine umbenannte AD-Gruppe sähe genauso aus
    # wie "alle haben die Schule verlassen". Dann lieber gar nichts tun.
    bisher_aktiv = sum(1 for u in nutzer if u.aktiv)
    deaktiviert = sum(1 for a in aenderungen if a.deaktiviert)
    if bisher_aktiv and deaktiviert == bisher_aktiv:
        raise AbgleichFehler(
            f"Der Abgleich würde alle {bisher_aktiv} aktiven Nutzer deaktivieren. "
            "Das deutet auf eine Fehlkonfiguration hin (Base-DN in den Einstellungen "
            "oder AD-Gruppennamen bei Einstellungen/Teams prüfen)."
        )

    return Abgleich(geprueft=len(nutzer), aenderungen=aenderungen)


def _plane_nutzer(user, ldap_user, settings, aktive_teams):
    grund = None
    if ldap_user is None:
        grund = "nicht mehr im Verzeichnis"
        teams_neu = []
    else:
        ist_user, teams_neu = ermittle_berechtigung(ldap_user.gruppen, settings, aktive_teams)
        if not ist_user and not teams_neu:
            grund = "in keiner berechtigten AD-Gruppe mehr"

    aenderung = NutzerAenderung(user=user, aktiv_neu=grund is None, teams_neu=teams_neu, grund=grund)
    aenderung.teams_entfernt = [t for t in user.teams if t not in teams_neu]
    aenderung.teams_hinzu = [t for t in teams_neu if t not in user.teams]

    if grund is None:
        anzeigename = ldap_user.anzeigename or user.ad_username
        if anzeigename != user.anzeigename:
            aenderung.anzeigename_neu = anzeigename
        if ldap_user.email != user.email:
            aenderung.email_neu = ldap_user.email

    if not (
        aenderung.aktiv_neu != user.aktiv
        or aenderung.teams_entfernt
        or aenderung.teams_hinzu
        or aenderung.anzeigename_neu is not None
        or aenderung.email_neu is not None
    ):
        return None

    team_ids_neu = {t.id for t in teams_neu}
    aenderung.offene_tickets = [
        ticket
        for ticket in Ticket.query.filter(
            Ticket.zugewiesen_an_id == user.id,
            Ticket.status != TicketStatus.GESCHLOSSEN,
        ).order_by(Ticket.id)
        if ticket.team_id not in team_ids_neu
    ]
    return aenderung


def wende_an(abgleich):
    for aenderung in abgleich.aenderungen:
        user = aenderung.user
        current_app.logger.info(
            "AD-Abgleich %s (%s): %s",
            user.anzeigename,
            user.ad_username,
            "; ".join(aenderung.beschreibung()),
        )
        user.aktiv = aenderung.aktiv_neu
        user.teams = aenderung.teams_neu
        if aenderung.anzeigename_neu is not None:
            user.anzeigename = aenderung.anzeigename_neu
        if aenderung.email_neu is not None:
            user.email = aenderung.email_neu
    db.session.commit()
