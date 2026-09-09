import mimetypes
import os
import uuid

from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Attachment, Settings

ERLAUBTE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "application/pdf",
}


class AttachmentError(Exception):
    """Datei überschreitet das Größenlimit oder hat einen nicht erlaubten Typ."""


def _uploads_dir(app, ticket_id):
    path = os.path.join(app.instance_path, "uploads", str(ticket_id))
    os.makedirs(path, exist_ok=True)
    return path


def save_attachments(app, files, uploaded_by, ticket=None, comment=None):
    """Speichert hochgeladene Dateien (werkzeug FileStorage-Objekte) als
    Attachment-Zeilen, verknüpft mit genau einem Ticket ODER Kommentar.
    Dateien liegen außerhalb des Web-Roots unter instance/uploads/.
    Wirft AttachmentError bei Größen-/Typverstoß (nichts wird gespeichert,
    weder Datei noch DB-Zeile)."""
    if (ticket is None) == (comment is None):
        raise ValueError("Genau eines von ticket/comment muss gesetzt sein.")

    settings = Settings.get_or_create()
    max_bytes = settings.anhang_max_groesse_mb * 1024 * 1024
    ticket_id = ticket.id if ticket else comment.ticket_id

    to_write = []
    for file in files:
        if not file or not file.filename:
            continue

        # Dateiendung hat Vorrang vor dem client-gelieferten Content-Type:
        # Letzterer wird vom Client selbst gesetzt und ist daher trivial
        # fälschbar (z. B. ein Skript mit vorgetäuschtem "image/png").
        mime_type = (
            mimetypes.guess_type(file.filename)[0]
            or file.mimetype
            or "application/octet-stream"
        )
        if mime_type not in ERLAUBTE_MIME_TYPES:
            raise AttachmentError(f"Dateityp '{mime_type}' ist nicht erlaubt.")

        data = file.read()
        if len(data) > max_bytes:
            raise AttachmentError(
                f"Datei '{file.filename}' überschreitet das Limit von "
                f"{settings.anhang_max_groesse_mb} MB."
            )

        filename = secure_filename(file.filename) or "datei"
        to_write.append((filename, mime_type, data))

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
