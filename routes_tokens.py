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
_catalog_book = None
_catalog_langs = ()


def configure(render_install_page, catalog_book=None, catalog_langs=()):
    """`render_install_page(lang, title, body)` -> HTML della pagina install.
    `catalog_book(token)` -> libro del catalogo gratuito per un token `fc-…` o
    None; `catalog_langs` le lingue del catalogo (free_catalog, che questa
    foglia non importa)."""
    global _render_install_page, _catalog_book, _catalog_langs
    _render_install_page = render_install_page
    _catalog_book = catalog_book
    _catalog_langs = tuple(catalog_langs)


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


def render_catalog_landing(book):
    """`/s/fc-…` senza app: invito a installarla per ascoltare quel libro del
    catalogo gratuito (spec catalogo §7.6), nella lingua del visitatore fra le
    6 del catalogo, altrimenti in quella del libro."""
    lang = _i18n.browser_lang(request.headers.get("Accept-Language", ""),
                              supported=_catalog_langs, ranked=True,
                              default=book["book_id"][:2])
    t = _i18n.pick(_i18n.load("free_catalog"), lang)
    body = t["landing_text"].format(title=book["title"], author=book["author"]["name"])
    # pt e nl non sono lingue del sito: la cornice della pagina va in inglese.
    shell = lang if lang in _i18n.LANGS else "en"
    return _render_install_page(shell, _html.escape(t["landing_title"]), _html.escape(body))


@bp.route("/s/<token>")
def share_landing(token):
    # Fallback browser per il deep link /s/<token> quando l'app NON è installata
    # (con app installata + dominio verificato, l'App Link apre l'app prima).
    book = _catalog_book(token) if _catalog_book else None
    page = render_catalog_landing(book) if book else render_transfer_landing(token)
    return (page, 200, {"Content-Type": "text/html; charset=utf-8"})
