"""Donazione PayPal in finestra popup con overlay modale (static/js/donate_popup.js).

PayPal non si lascia incorniciare, quindi i link al bottone di donazione
aprono una finestra dimensionata e la pagina mostra #ppDonateOverlay con
"Riapri" e "Chiudi". Qui si controlla il cablaggio: link marcati, overlay e
script presenti in SPA e pagina /dl, testi in tutte le lingue, cache-busting
dello script anche sulla pagina servita da templates/pages.
"""
import re
from pathlib import Path

import audiobook_app  # noqa: F401  (configura routes_dl)
import page_brand
import routes_dl
from i18n import LANGS

ROOT = Path(__file__).resolve().parent.parent
HEAD = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
TAIL = (ROOT / "templates/_fragments/html_tail.html").read_text(encoding="utf-8")
I18N = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
DL = (ROOT / "templates/pages/dl_page.html").read_text(encoding="utf-8")

DONATE_URL = "https://www.paypal.com/donate/?hosted_button_id=QY5ZEBUULE4PQ"


def _paypal_links(html):
    return re.findall(r'<a [^>]*href="https://www\.paypal\.com/[^"]*"[^>]*>', html)


def test_paypal_links_point_to_donate_button_and_open_in_popup():
    for html in (HEAD, DL):
        links = _paypal_links(html)
        assert links
        for a in links:
            assert f'href="{DONATE_URL}"' in a
            assert "data-donate-popup" in a
        assert "paypalme" not in html


def test_overlay_markup_in_spa_and_dl_page():
    for html in (HEAD, DL):
        assert 'id="ppDonateOverlay"' in html
        assert "data-pp-reopen" in html
        assert html.count("data-pp-close") >= 2   # X e "Chiudi"


def test_spa_loads_donate_popup_script():
    assert 'src="/static/js/donate_popup.js?v=__APP_VERSION__"' in TAIL


def test_dl_page_loads_donate_popup_with_fingerprint():
    html = routes_dl._render_dl_page("TOK", "Libro", "1h", "m4b", lang="it")
    fp = page_brand.static_fingerprint("/static/js/donate_popup.js")
    assert re.fullmatch(r"[0-9a-f]{8}", fp)
    assert f'src="/static/js/donate_popup.js?v={fp}"' in html
    assert "__APP_VERSION__" not in html


def test_bust_static_refs_prefix_and_missing_file():
    html = '<script src="/static/js/donate_popup.js?v=__APP_VERSION__"></script>' \
           '<script src="/static/js/nope.js?v=__APP_VERSION__"></script>'
    out = page_brand.bust_static_refs(html, "9.9.")
    fp = page_brand.static_fingerprint("/static/js/donate_popup.js")
    assert f'/static/js/donate_popup.js?v=9.9.{fp}"' in out
    assert '/static/js/nope.js?v=9.9.0"' in out


def _lang_blocks(js):
    starts = [(m.start(), m.group(1)) for m in re.finditer(r"^([a-z]{2}):\{", js, re.M)]
    return {lang: js[pos:(starts[i + 1][0] if i + 1 < len(starts) else len(js))]
            for i, (pos, lang) in enumerate(starts)}


def test_spa_overlay_texts_in_all_languages():
    blocks = _lang_blocks(I18N)
    for lang in LANGS:
        for key in ("donate_pp_body", "donate_pp_reopen", "donate_pp_close"):
            assert re.search(rf'{key}:"[^"]+"', blocks[lang]), (lang, key)


def test_dl_page_overlay_texts_in_all_languages():
    for lang in LANGS:
        m = re.search(rf"^    {lang}:\{{.*\}}", DL, re.M)
        assert m, lang
        for key in ("ppBody", "ppReopen", "ppClose"):
            assert re.search(rf"{key}:'[^']+'", m.group(0)), (lang, key)
