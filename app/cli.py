import os
from datetime import datetime

import click
from sqlalchemy import func, or_
from sqlalchemy.exc import OperationalError
from werkzeug.security import generate_password_hash

from app.ad_abgleich import AbgleichFehler, plane_abgleich, wende_an
from app.extensions import db
from app.models import Attachment, Comment, Settings, Ticket, TicketHistory, User


def bootstrap_admin(app):
    """Legt den initialen Admin-User aus den ADMIN_*-Env-Vars an,
    falls noch kein Admin existiert. Wird auch beim App-Start ausgeführt,
    daher robust gegen eine noch nicht migrierte Datenbank (z. B. während
    `flask db init`/`migrate`, bevor die User-Tabelle existiert)."""
    with app.app_context():
        try:
            admin_exists = User.query.filter_by(ist_admin=True).first() is not None
        except OperationalError:
            return
        if admin_exists:
            return

        username = app.config.get("ADMIN_USERNAME")
        email = app.config.get("ADMIN_EMAIL")
        password = app.config.get("ADMIN_PASSWORD")
        if not (username and email and password):
            return

        admin = User(
            anzeigename=username,
            email=email,
            ist_admin=True,
            aktiv=True,
            passwort_hash=generate_password_hash(password),
        )
        db.session.add(admin)
        db.session.commit()
        app.logger.info("Admin-User %r wurde angelegt.", username)


def _menschliche_groesse(bytes_):
    """Byte-Zahl als kurze, lesbare Größe - reine Ausgabehilfe."""
    einheiten = ("B", "KB", "MB", "GB")
    wert = float(bytes_)
    for einheit in einheiten:
        if wert < 1024 or einheit == einheiten[-1]:
            return f"{wert:.1f} {einheit}" if einheit != "B" else f"{int(wert)} B"
        wert /= 1024


def _tickets_query(grenze):
    query = Ticket.query
    if grenze is not None:
        query = query.filter(Ticket.erstellt_am < grenze)
    return query


def _anhang_filter(ticket_ids, kommentar_ids):
    """Anhänge hängen entweder am Ticket oder an einem seiner Kommentare
    (siehe CheckConstraint in models.Attachment) - beide Wege müssen
    berücksichtigt werden."""
    return or_(
        Attachment.ticket_id.in_(ticket_ids),
        Attachment.comment_id.in_(kommentar_ids),
    )


def _zaehle_betroffenes(grenze):
    """Zählt, was an einem Purge hängt, ohne die Objekte zu laden."""
    ticket_ids = _tickets_query(grenze).with_entities(Ticket.id).scalar_subquery()
    kommentar_ids = (
        Comment.query.filter(Comment.ticket_id.in_(ticket_ids))
        .with_entities(Comment.id)
        .scalar_subquery()
    )
    anhang_filter = _anhang_filter(ticket_ids, kommentar_ids)
    anhang_bytes = db.session.query(
        func.coalesce(func.sum(Attachment.groesse_bytes), 0)
    ).filter(anhang_filter).scalar()

    return {
        "tickets": _tickets_query(grenze).count(),
        "kommentare": Comment.query.filter(Comment.ticket_id.in_(ticket_ids)).count(),
        "historie": TicketHistory.query.filter(
            TicketHistory.ticket_id.in_(ticket_ids)
        ).count(),
        "anhaenge": Attachment.query.filter(anhang_filter).count(),
        "anhang_bytes": anhang_bytes,
    }


def _finde_verwaiste_dateien(app):
    """Dateien unter instance/uploads/, zu denen es keine Attachment-Zeile
    (mehr) gibt - etwa Reste aus früheren Datenbank-Resets, die kein
    Cascade je erwischt hat."""
    uploads = os.path.join(app.instance_path, "uploads")
    if not os.path.isdir(uploads):
        return []

    def _schluessel(pfad):
        # normcase, weil die Pfade unter Windows case-insensitiv sind und
        # sonst je nach Schreibweise fälschlich als verwaist gelten.
        return os.path.normcase(os.path.normpath(pfad))

    bekannt = {
        _schluessel(os.path.join(app.instance_path, pfad))
        for (pfad,) in Attachment.query.with_entities(Attachment.pfad)
    }

    verwaist = []
    for verzeichnis, _, dateien in os.walk(uploads):
        for datei in dateien:
            voll = os.path.join(verzeichnis, datei)
            if _schluessel(voll) not in bekannt:
                verwaist.append(voll)
    return verwaist


def _entferne_leere_upload_ordner(app):
    """Nach dem Löschen bleiben die (jetzt leeren) uploads/<ticket_id>-
    Ordner stehen. Nur leere Ordner werden entfernt, das Wurzelverzeichnis
    bleibt bestehen."""
    uploads = os.path.join(app.instance_path, "uploads")
    if not os.path.isdir(uploads):
        return 0

    entfernt = 0
    for verzeichnis, unterordner, dateien in os.walk(uploads, topdown=False):
        if verzeichnis == uploads or unterordner or dateien:
            continue
        try:
            os.rmdir(verzeichnis)
            entfernt += 1
        except OSError:
            pass
    return entfernt


def register_cli(app):
    @app.cli.command("create-admin")
    def create_admin_command():
        """Legt den initialen Admin-User aus den ADMIN_*-Env-Vars an."""
        if User.query.filter_by(ist_admin=True).first() is not None:
            click.echo("Es existiert bereits ein Admin-User.")
            return

        username = app.config.get("ADMIN_USERNAME")
        email = app.config.get("ADMIN_EMAIL")
        password = app.config.get("ADMIN_PASSWORD")
        if not (username and email and password):
            click.echo(
                "ADMIN_USERNAME, ADMIN_EMAIL und ADMIN_PASSWORD müssen "
                "gesetzt sein."
            )
            return

        admin = User(
            anzeigename=username,
            email=email,
            ist_admin=True,
            aktiv=True,
            passwort_hash=generate_password_hash(password),
        )
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Admin-User {username!r} wurde angelegt.")

    @app.cli.command("tickets-purge")
    @click.option("--alle", is_flag=True, help="Alle Tickets löschen.")
    @click.option(
        "--vor",
        metavar="JJJJ-MM-TT",
        help="Nur Tickets löschen, die vor diesem Datum (UTC) erstellt wurden.",
    )
    @click.option(
        "--verwaiste-dateien",
        "verwaiste_dateien",
        is_flag=True,
        help=(
            "Zusätzlich Dateien unter instance/uploads/ entfernen, zu denen es "
            "keinen Anhang-Datensatz mehr gibt (Reste früherer Resets)."
        ),
    )
    @click.option(
        "--ja",
        is_flag=True,
        help="Tatsächlich löschen. Ohne diese Option läuft nur ein Probelauf.",
    )
    def tickets_purge_command(alle, vor, verwaiste_dateien, ja):
        """Löscht Tickets samt Kommentaren, Historie und Anhängen.

        Gedacht zum Aufräumen der Testdaten vor dem Produktivstart: Teams,
        Kategorien, Nutzer und Einstellungen bleiben unangetastet.

        Gelöscht wird bewusst über das ORM statt per DELETE-Statement. Nur
        so greifen die Cascades (Kommentare/Historie/Anhänge) und der
        after_commit-Hook aus app/attachments.py, der die zugehörigen
        Dateien unter instance/uploads/ von der Platte räumt.
        """
        if alle and vor:
            raise click.UsageError("--alle und --vor schließen sich gegenseitig aus.")
        if not (alle or vor or verwaiste_dateien):
            raise click.UsageError(
                "Bitte --alle oder --vor JJJJ-MM-TT angeben "
                "(oder --verwaiste-dateien zum reinen Aufräumen)."
            )

        grenze = None
        if vor:
            try:
                grenze = datetime.strptime(vor, "%Y-%m-%d")
            except ValueError:
                raise click.UsageError(
                    f"{vor!r} ist kein Datum im Format JJJJ-MM-TT."
                )

        loescht_tickets = alle or grenze is not None
        zahlen = _zaehle_betroffenes(grenze) if loescht_tickets else None
        verwaist = _finde_verwaiste_dateien(app) if verwaiste_dateien else []
        verwaist_bytes = sum(
            os.path.getsize(pfad) for pfad in verwaist if os.path.exists(pfad)
        )

        if loescht_tickets:
            umfang = "alle Tickets" if alle else f"Tickets erstellt vor {vor} (UTC)"
            click.echo(f"Umfang: {umfang}")
            click.echo(f"  Tickets:     {zahlen['tickets']}")
            click.echo(f"  Kommentare:  {zahlen['kommentare']}")
            click.echo(f"  Historie:    {zahlen['historie']}")
            click.echo(
                f"  Anhänge:     {zahlen['anhaenge']} "
                f"({_menschliche_groesse(zahlen['anhang_bytes'])})"
            )
        if verwaiste_dateien:
            click.echo(
                f"  Verwaiste Dateien: {len(verwaist)} "
                f"({_menschliche_groesse(verwaist_bytes)})"
            )

        if not ja:
            click.echo("")
            click.echo("Probelauf - es wurde nichts gelöscht.")
            click.echo("Vorher sichern: scripts/backup.sh")
            click.echo("Zum tatsächlichen Löschen dieselbe Zeile mit --ja wiederholen.")
            return

        if loescht_tickets:
            # Objektweise löschen, damit SQLAlchemy die Cascades ausführt
            # und der Datei-Hook je Anhang greift. Für die Größenordnung
            # eines Schul-Ticketsystems ist das unkritisch.
            for ticket in _tickets_query(grenze).all():
                db.session.delete(ticket)
            db.session.commit()
            click.echo(f"{zahlen['tickets']} Ticket(s) gelöscht.")

        if verwaiste_dateien:
            entfernt = 0
            for pfad in verwaist:
                try:
                    os.remove(pfad)
                    entfernt += 1
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    click.echo(f"  {pfad} konnte nicht gelöscht werden: {exc}", err=True)
            click.echo(f"{entfernt} verwaiste Datei(en) entfernt.")

        ordner = _entferne_leere_upload_ordner(app)
        if ordner:
            click.echo(f"{ordner} leere Upload-Ordner entfernt.")

    @app.cli.command("users-sync")
    @click.option(
        "--ja",
        is_flag=True,
        help="Änderungen übernehmen. Ohne diese Option läuft nur ein Probelauf.",
    )
    def users_sync_command(ja):
        """Gleicht alle bekannten AD-Nutzer und ihre Teams mit dem AD ab.

        Wer nicht mehr im Verzeichnis oder in keiner berechtigten Gruppe ist,
        wird deaktiviert und aus allen Teams entfernt. Bei einem LDAP-Fehler
        endet das Kommando mit Exit-Code 1, ohne etwas zu ändern.
        """
        try:
            abgleich = plane_abgleich(
                Settings.get_or_create(), app.config.get("LDAP_BIND_PASSWORD")
            )
        except AbgleichFehler as exc:
            raise click.ClickException(f"{exc} Es wurde nichts geändert.")

        click.echo(f"Geprüfte Nutzer: {abgleich.geprueft}")
        if not abgleich.aenderungen:
            click.echo("Keine Änderungen nötig.")
            return

        for aenderung in abgleich.aenderungen:
            click.echo(f"{aenderung.user.anzeigename} ({aenderung.user.ad_username})")
            for zeile in aenderung.beschreibung():
                click.echo(f"  - {zeile}")
            for ticket in aenderung.offene_tickets:
                click.echo(
                    f"  ! noch zugewiesen: #{ticket.id} {ticket.titel} (Team {ticket.team.name})"
                )

        if not ja:
            click.echo("")
            click.echo("Probelauf - es wurde nichts geändert.")
            click.echo("Zum Übernehmen dieselbe Zeile mit --ja wiederholen.")
            return

        wende_an(abgleich)
        click.echo(f"{len(abgleich.aenderungen)} Nutzer aktualisiert.")
