import os
import uuid

from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Attachment, Settings

# Erlaubte Dateiendungen und der Content-Type, unter dem sie später
# ausgeliefert werden. Bewusst eine feste Zuordnung statt
# mimetypes.guess_type() mit Rückfall auf den Content-Type des Clients:
# Letzterer ist frei wählbar, und guess_type() liefert bei unbekannter
# Endung None - eine Datei "nutzlast.blah" wäre damit allein aufgrund
# eines mitgeschickten "image/png" durch die Prüfung gerutscht.
ERLAUBTE_ENDUNGEN = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}

# Signatur am Dateianfang je Typ. Die Endung sagt nur, was der Uploader
# behauptet - erst der Abgleich mit dem tatsächlichen Inhalt verhindert,
# dass beliebige Daten unter einem harmlosen Namen abgelegt und später
# unter einem Bild-Content-Type ausgeliefert werden.
MAGISCHE_BYTES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "application/pdf": (b"%PDF-",),
}

# Typen, die im Browser gefahrlos direkt angezeigt werden können. Alles
# übrige (aktuell: PDF) wird beim Abruf zum Download gezwungen, statt es
# im Sicherheitskontext der Anwendung zu rendern - siehe
# tickets.download_attachment.
ANZEIGBARE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
}


class AttachmentError(Exception):
    """Datei überschreitet das Größenlimit oder hat einen nicht erlaubten Typ."""


def _sicherer_dateiname(original, endung):
    """Baut den Namen, unter dem die Datei gespeichert und angezeigt wird.

    secure_filename() kann die Endung mit verschlucken - bei einem rein
    nicht-lateinischen Namen bleibt von "<...>.png" nur "png" übrig. Der
    Stamm wird deshalb aus dem bereinigten Namen genommen, die (bereits
    geprüfte) Endung aber wieder fest angehängt, damit gespeicherter Name
    und ausgelieferter Content-Type garantiert zusammenpassen."""
    stamm, bereinigte_endung = os.path.splitext(secure_filename(original))
    if not bereinigte_endung:
        stamm = "datei"
    return f"{stamm}{endung}"


def _uploads_dir(app, ticket_id):
    path = os.path.join(app.instance_path, "uploads", str(ticket_id))
    os.makedirs(path, exist_ok=True)
    return path


def save_attachments(app, files, uploaded_by, ticket=None, comment=None):
    """Speichert hochgeladene Dateien (werkzeug FileStorage-Objekte) als
    Attachment-Zeilen, verknüpft mit genau einem Ticket ODER Kommentar.
    Dateien liegen außerhalb des Web-Roots unter instance/uploads/.
    Wirft AttachmentError, wenn eine Datei zu groß ist, eine unerlaubte
    Endung hat oder ihr Inhalt nicht zur Endung passt. Geprüft wird alles
    vorab: Schlägt eine Datei fehl, wird keine einzige gespeichert -
    weder auf der Platte noch als DB-Zeile."""
    if (ticket is None) == (comment is None):
        raise ValueError("Genau eines von ticket/comment muss gesetzt sein.")

    settings = Settings.get_or_create()
    max_bytes = settings.anhang_max_groesse_mb * 1024 * 1024
    ticket_id = ticket.id if ticket else comment.ticket_id

    to_write = []
    for file in files:
        if not file or not file.filename:
            continue

        # Der vom Client mitgeschickte Content-Type wird bewusst gar
        # nicht mehr betrachtet - er ist frei wählbar und damit wertlos.
        endung = os.path.splitext(file.filename)[1].lower()
        mime_type = ERLAUBTE_ENDUNGEN.get(endung)
        if mime_type is None:
            raise AttachmentError(
                f"Dateityp '{endung or file.filename}' ist nicht erlaubt. "
                f"Erlaubt sind: {', '.join(sorted(ERLAUBTE_ENDUNGEN))}."
            )

        data = file.read()
        if len(data) > max_bytes:
            raise AttachmentError(
                f"Datei '{file.filename}' überschreitet das Limit von "
                f"{settings.anhang_max_groesse_mb} MB."
            )

        if not data.startswith(MAGISCHE_BYTES[mime_type]):
            raise AttachmentError(
                f"Der Inhalt von '{file.filename}' passt nicht zur Dateiendung "
                f"'{endung}'."
            )

        to_write.append((_sicherer_dateiname(file.filename, endung), mime_type, data))

    saved = []
    directory = _uploads_dir(app, ticket_id)
    for filename, mime_type, data in to_write:
        stored_name = f"{uuid.uuid4().hex}_{filename}"
        full_path = os.path.join(directory, stored_name)
        with open(full_path, "wb") as f:
            f.write(data)

        attachment = Attachment(
            ticket_id=ticket.id if ticket else None,
            comment_id=comment.id if comment else None,
            dateiname=filename,
            pfad=os.path.relpath(full_path, app.instance_path),
            groesse_bytes=len(data),
            mime_type=mime_type,
            hochgeladen_von_id=uploaded_by.id,
        )
        db.session.add(attachment)
        saved.append(attachment)

    return saved
