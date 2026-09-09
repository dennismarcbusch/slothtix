"""HTTP-Sicherheitsheader für alle Antworten.

Die Anwendung liefert unter /tickets/anhaenge/<id> von Nutzern
hochgeladene Dateien aus - und zwar von derselben Origin wie die
Anwendung selbst. Alles, was ein Browser dort doch als aktiven Inhalt
interpretiert, liefe damit im Sicherheitskontext der angemeldeten
Sitzung. Die Header hier schließen diese Lücke von zwei Seiten:
`nosniff` verbietet dem Browser, den deklarierten Content-Type zu
übergehen, und die CSP verhindert die Ausführung von Skripten, die nicht
aus der Anwendung selbst stammen.
"""

import secrets

from flask import g

# 'nonce-...' statt 'unsafe-inline': Die beiden Inline-Skripte der
# Formulare (dynamische Kategorie-Auswahl) tragen ein pro Request neu
# gewürfeltes Nonce-Attribut. Eingeschleuster Markup-Code kennt dieses
# Nonce nicht und wird deshalb auch dann nicht ausgeführt, wenn er es
# doch einmal in den HTML-Quelltext schaffen sollte.
#
# img-src erlaubt zusätzlich blob:, weil paste-upload.js die Vorschau
# eingefügter Screenshots über URL.createObjectURL() erzeugt.
def _csp(nonce):
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}'",
            "style-src 'self'",
            "img-src 'self' blob:",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        )
    )


def csp_nonce():
    """Nonce des aktuellen Requests (bei Bedarf erzeugt). Wird sowohl vom
    Template als auch vom Header-Hook benutzt, damit beide denselben Wert
    sehen."""
    if "csp_nonce" not in g:
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce


def registriere_security_header(app):
    @app.context_processor
    def _nonce_im_template():
        return {"csp_nonce": csp_nonce}

    @app.after_request
    def _security_header(response):
        # setdefault statt Zuweisung: Einzelne Endpunkte (z. B. die
        # Anhang-Auslieferung) dürfen eine strengere eigene Regel setzen.
        response.headers.setdefault("Content-Security-Policy", _csp(csp_nonce()))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
