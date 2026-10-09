"""routes_tokens — pagine di atterraggio dei deep link /t/<token> e /s/<token>
(E3, primo seam, 2026-10-09).

Primo Blueprint estratto da `audiobook_app`, per collaudare il metodo:
`bp = Blueprint(...)`, `configure(...)` che riceve dalla app le funzioni di
cui le route hanno bisogno, registrazione del blueprint dopo `configure`.
Le route sono spostate pari pari: nel browser senza app installata mostrano
la pagina di installazione (bottoni store); con l'app e il dominio
verificato l'App Link apre l'app prima di arrivare qui.
"""
import html as _html

from flask import Blueprint, request

import i18n as _i18n

bp = Blueprint("tokens", __name__)

_render_install_page = None


def configure(render_install_page):
    """`render_install_page(lang, title, body)` -> HTML della pagina install."""
    global _render_install_page
    _render_install_page = render_install_page


def render_transfer_landing(token):
    # Fallback per il deep link /t/<token>: mostrato nel browser quando l'app NON
    # è installata. Riusa la pagina install (bottoni store).
    _html.escape(str(token or ""), quote=True)  # token non riflesso, ma validato
    try:
        al = (request.headers.get("Accept-Language") or "").strip().lower()
        lang = "it" if al.startswith("it") else "en"
    except Exception:
        lang = "en"
    T = {
        "it": ("Apri in Audiobook Maker &amp; Player",
               "Se hai l'app installata, questo link la apre per importare il processo. Altrimenti scaricala:"),
        "en": ("Open in Audiobook Maker &amp; Player",
               "If you have the app installed, this link opens it to import the job. Otherwise get the app:"),
    }
    title, body = _i18n.pick(T, lang, merge=False)
    return _render_install_page(lang, title, body)


@bp.route("/t/<token>")
def transfer_landing(token):
    return (render_transfer_landing(token), 200,
            {"Content-Type": "text/html; charset=utf-8"})


@bp.route("/s/<token>")
def share_landing(token):
    # Fallback browser per il deep link /s/<token> quando l'app NON è installata
    # (con app installata + dominio verificato, l'App Link apre l'app prima).
    return (render_transfer_landing(token), 200,
            {"Content-Type": "text/html; charset=utf-8"})
