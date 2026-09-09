"""Fehlerseiten im Layout der Anwendung.

Ohne diese Handler liefert Werkzeug seine nackten Standardseiten aus - die
sehen nicht nur fremd aus, sie sind auch englisch und erklären dem Nutzer
nicht, was er tun soll. Besonders 413 trat bisher ohne jede Erklärung auf.
"""

from flask import render_template

from app.config import Config

MELDUNGEN = {
    403: "Für diesen Bereich fehlen dir die Rechte.",
    404: "Diese Seite gibt es nicht (mehr).",
    413: (
        f"Der Upload ist zu groß. Pro Anfrage sind höchstens "
        f"{Config.MAX_UPLOAD_MB} MB möglich - bei mehreren Anhängen zählt "
        f"die Summe."
    ),
    500: "Da ist etwas schiefgelaufen. Der Fehler wurde protokolliert.",
}


def registriere_fehlerseiten(app):
    def _seite(code):
        def handler(error):
            return render_template("fehler.html", code=code, meldung=MELDUNGEN[code]), code

        return handler

    for code in MELDUNGEN:
        app.register_error_handler(code, _seite(code))
