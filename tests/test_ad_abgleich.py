"""Tests für den AD-Abgleich (app/ad_abgleich.py), das CLI-Kommando
`flask users-sync` und die Admin-Seite /admin/ad-abgleich."""

import pytest

from app.ad_abgleich import AbgleichFehler, plane_abgleich, wende_an
from app.extensions import db
from app.ldap_service import LdapAuthError, LdapUser
from app.models import Settings, Team, Ticket, TicketPrioritaet, TicketStatus, User

from tests.conftest import login_as


@pytest.fixture
def ad(monkeypatch):
    """Simuliertes Verzeichnis: {ad_username: LdapUser}."""
    verzeichnis = {}

    def fake_lookup(settings, bind_password, usernames, connection_factory=None):
        return {u: verzeichnis[u] for u in usernames if u in verzeichnis}

    monkeypatch.setattr("app.ad_abgleich.lookup_users", fake_lookup)
    return verzeichnis


@pytest.fixture
def settings(app):
    with app.app_context():
        s = Settings.get_or_create()
        s.ad_gruppe_user = "grp-user"
        db.session.commit()


def _ticket(team, ersteller, zugewiesen_an, status=TicketStatus.OFFEN):
    ticket = Ticket(
        titel="Drucker",
        beschreibung="geht nicht",
        team_id=team.id,
        category_id=team.kategorien[0].id,
        ersteller_id=ersteller.id,
        zugewiesen_an_id=zugewiesen_an.id,
        prioritaet=TicketPrioritaet.MITTEL,
        status=status,
    )
    db.session.add(ticket)
    db.session.commit()
    return ticket


def _plane():
    return plane_abgleich(Settings.get_or_create(), "servicepw")


def test_aus_dem_ad_geloeschter_agent_wird_deaktiviert_und_verlaesst_team(
    app, ad, settings, make_team, make_user
):
    with app.app_context():
        it = make_team(name="IT", ad_gruppe_agenten="grp-it")
        bleibt = make_user(anzeigename="Bleibt", email="b@x", ad_username="bleibt", teams=[it])
        weg = make_user(anzeigename="Weg", email="w@x", ad_username="weg", teams=[it])
        ad["bleibt"] = LdapUser(anzeigename="Bleibt", email="b@x", gruppen=["grp-it"])
        offen = _ticket(it, bleibt, weg)
        _ticket(it, bleibt, weg, status=TicketStatus.GESCHLOSSEN)

        abgleich = _plane()

        assert abgleich.geprueft == 2
        [aenderung] = abgleich.aenderungen
        assert aenderung.user.ad_username == "weg"
        assert aenderung.beschreibung() == [
            "wird deaktiviert (nicht mehr im Verzeichnis)",
            "verlässt Team IT",
        ]
        assert aenderung.offene_tickets == [offen]

        wende_an(abgleich)

        assert User.query.filter_by(ad_username="weg").one().aktiv is False
        assert [u.ad_username for u in db.session.get(Team, it.id).mitglieder] == ["bleibt"]
        # Zuweisung bleibt bewusst unangetastet.
        assert db.session.get(Ticket, offen.id).zugewiesen_an_id is not None


def test_entzogene_team_gruppe_entfernt_nur_das_team(app, ad, settings, make_team, make_user):
    with app.app_context():
        it = make_team(name="IT", ad_gruppe_agenten="grp-it")
        hm = make_team(name="Hausmeister", ad_gruppe_agenten="grp-hm", kategorien=("Heizung",))
        user = make_user(anzeigename="Jo", email="jo@x", ad_username="jo", teams=[it, hm])
        _ticket(it, user, user)
        ticket_hm = _ticket(hm, user, user)
        ad["jo"] = LdapUser(anzeigename="Jo", email="jo@x", gruppen=["grp-user", "grp-it"])

        [aenderung] = _plane().aenderungen

        assert aenderung.beschreibung() == ["verlässt Team Hausmeister"]
        assert aenderung.offene_tickets == [ticket_hm]


def test_ohne_berechtigte_gruppe_wird_deaktiviert(app, ad, settings, make_team, make_user):
    with app.app_context():
        make_user(anzeigename="Andere", email="a@x", ad_username="andere")
        make_user(anzeigename="Ex", email="ex@x", ad_username="ex")
        ad["andere"] = LdapUser(anzeigename="Andere", email="a@x", gruppen=["grp-user"])
        ad["ex"] = LdapUser(anzeigename="Ex", email="ex@x", gruppen=["sonstwas"])

        [aenderung] = _plane().aenderungen

        assert aenderung.beschreibung() == ["wird deaktiviert (in keiner berechtigten AD-Gruppe mehr)"]


def test_uebernimmt_name_mail_und_neue_teams_und_reaktiviert(app, ad, settings, make_team, make_user):
    with app.app_context():
        it = make_team(name="IT", ad_gruppe_agenten="grp-it")
        user = make_user(anzeigename="Alt", email="alt@x", ad_username="jo")
        user.aktiv = False
        make_user(anzeigename="Aktiv", email="ak@x", ad_username="aktiv")
        db.session.commit()
        ad["jo"] = LdapUser(anzeigename="Neu", email="neu@x", gruppen=["grp-it"])
        ad["aktiv"] = LdapUser(anzeigename="Aktiv", email="ak@x", gruppen=["grp-user"])

        abgleich = _plane()
        [aenderung] = abgleich.aenderungen
        assert aenderung.beschreibung() == [
            "wird reaktiviert",
            "kommt zu Team IT",
            "Anzeigename: Alt → Neu",
            "E-Mail: alt@x → neu@x",
        ]

        wende_an(abgleich)

        jo = User.query.filter_by(ad_username="jo").one()
        assert (jo.aktiv, jo.anzeigename, jo.email) == (True, "Neu", "neu@x")
        assert jo.ist_agent_von(it.id)


def test_keine_aenderungen_und_lokaler_admin_bleibt_aussen_vor(app, ad, settings, make_user):
    with app.app_context():
        make_user(anzeigename="Jo", email="jo@x", ad_username="jo")
        ad["jo"] = LdapUser(anzeigename="Jo", email="jo@x", gruppen=["grp-user"])

        abgleich = _plane()

        assert abgleich.geprueft == 1
        assert abgleich.aenderungen == []


def test_bricht_ab_wenn_alle_aktiven_nutzer_deaktiviert_wuerden(app, ad, settings, make_user):
    """Schutz vor Fehlkonfiguration, z. B. falscher Base-DN."""
    with app.app_context():
        make_user(anzeigename="A", email="a@x", ad_username="a")
        make_user(anzeigename="B", email="b@x", ad_username="b")

        with pytest.raises(AbgleichFehler, match="alle 2 aktiven Nutzer"):
            _plane()


def test_ldap_fehler_wird_zu_abgleichfehler(app, settings, make_user, monkeypatch):
    def kaputt(*args, **kwargs):
        raise LdapAuthError("LDAP-Verzeichnis nicht erreichbar.")

    monkeypatch.setattr("app.ad_abgleich.lookup_users", kaputt)
    with app.app_context():
        make_user()
        with pytest.raises(AbgleichFehler, match="nicht erreichbar"):
            _plane()


def test_deaktivierter_nutzer_verliert_laufende_sitzung(app, client, make_user):
    with app.app_context():
        user_id = make_user().id
    login_as(client, user_id)
    assert client.get("/tickets/").status_code == 200

    with app.app_context():
        db.session.get(User, user_id).aktiv = False
        db.session.commit()

    response = client.get("/tickets/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def _zwei_nutzer_einer_weg(make_team, make_user, ad):
    it = make_team(name="IT", ad_gruppe_agenten="grp-it")
    make_user(anzeigename="Bleibt", email="b@x", ad_username="bleibt", teams=[it])
    make_user(anzeigename="Weg", email="w@x", ad_username="weg", teams=[it])
    ad["bleibt"] = LdapUser(anzeigename="Bleibt", email="b@x", gruppen=["grp-it"])


def test_cli_probelauf_aendert_nichts(app, ad, settings, make_team, make_user):
    with app.app_context():
        _zwei_nutzer_einer_weg(make_team, make_user, ad)

    ergebnis = app.test_cli_runner().invoke(args=["users-sync"])

    assert ergebnis.exit_code == 0, ergebnis.output
    assert "wird deaktiviert (nicht mehr im Verzeichnis)" in ergebnis.output
    assert "Probelauf" in ergebnis.output
    with app.app_context():
        assert User.query.filter_by(ad_username="weg").one().aktiv is True


def test_cli_mit_ja_uebernimmt(app, ad, settings, make_team, make_user):
    with app.app_context():
        _zwei_nutzer_einer_weg(make_team, make_user, ad)

    ergebnis = app.test_cli_runner().invoke(args=["users-sync", "--ja"])

    assert ergebnis.exit_code == 0, ergebnis.output
    assert "1 Nutzer aktualisiert" in ergebnis.output
    with app.app_context():
        weg = User.query.filter_by(ad_username="weg").one()
        assert weg.aktiv is False
        assert weg.teams == []


def test_cli_fehler_liefert_exit_code(app, settings, make_user, monkeypatch):
    def kaputt(*args, **kwargs):
        raise LdapAuthError("LDAP-Verzeichnis nicht erreichbar.")

    monkeypatch.setattr("app.ad_abgleich.lookup_users", kaputt)
    with app.app_context():
        make_user()

    ergebnis = app.test_cli_runner().invoke(args=["users-sync", "--ja"])

    assert ergebnis.exit_code == 1
    assert "nichts geändert" in ergebnis.output


def test_admin_seite_zeigt_vorschau_und_uebernimmt(
    app, client, admin_user, ad, settings, make_team, make_user
):
    with app.app_context():
        _zwei_nutzer_einer_weg(make_team, make_user, ad)
    login_as(client, admin_user)

    vorschau = client.get("/admin/ad-abgleich")
    assert vorschau.status_code == 200
    text = vorschau.get_data(as_text=True)
    assert "wird deaktiviert (nicht mehr im Verzeichnis)" in text
    with app.app_context():
        assert User.query.filter_by(ad_username="weg").one().aktiv is True

    antwort = client.post("/admin/ad-abgleich", follow_redirects=True)
    assert "1 Nutzer aktualisiert" in antwort.get_data(as_text=True)
    with app.app_context():
        assert User.query.filter_by(ad_username="weg").one().aktiv is False


def test_admin_seite_zeigt_fehler_ohne_zu_aendern(app, client, admin_user, ad, settings, make_user):
    with app.app_context():
        make_user(anzeigename="A", email="a@x", ad_username="a")
    login_as(client, admin_user)

    assert "alle 1 aktiven Nutzer" in client.get("/admin/ad-abgleich").get_data(as_text=True)

    antwort = client.post("/admin/ad-abgleich", follow_redirects=True)
    assert "Es wurde nichts geändert" in antwort.get_data(as_text=True)
    with app.app_context():
        assert User.query.filter_by(ad_username="a").one().aktiv is True


def test_admin_seite_nur_fuer_admins(app, client, make_user):
    with app.app_context():
        user = make_user()
        login_as(client, user)

    assert client.get("/admin/ad-abgleich").status_code == 403
    assert client.post("/admin/ad-abgleich").status_code == 403
