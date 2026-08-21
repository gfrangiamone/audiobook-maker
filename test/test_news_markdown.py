"""Formattazione Markdown-lite nelle news pubblicate sul sito.

Le news sono scritte dall'admin in Markdown ridotto (**grassetto**, *corsivo*,
[testo](url), elenchi `- `, paragrafi) e rese in HTML dal client. Il body resta
Markdown grezzo nello store e nell'API: la conversione avviene solo a video,
cosi' le traduzioni LLM continuano a lavorare sul testo sorgente.

Il rendering e' l'unico punto in cui testo redazionale diventa HTML: i test di
sicurezza qui sotto sono la difesa contro l'XSS (tag iniettati, URL
`javascript:`, rottura dell'attributo href con virgolette).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MD_JS = Path("static/js/news_md.js")
APP_JS = Path("static/js/app.js")
CSS = Path("static/css/style.css")
HEAD = Path("templates/_fragments/html_head.html")
TAIL = Path("templates/_fragments/html_tail.html")


# ─────────────────────────── rendering (node) ───────────────────────────

def _render(*sources):
    """Esegue ABMNewsMd.toHtml() con node su piu' sorgenti, ritorna la lista."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node non disponibile")
    script = (
        MD_JS.read_text(encoding="utf-8")
        + "\nconst __in=" + json.dumps(list(sources)) + ";\n"
        + "console.log(JSON.stringify(__in.map(s=>ABMNewsMd.toHtml(s))));\n"
    )
    res = subprocess.run([node, "-e", script], capture_output=True, text=True,
                         encoding="utf-8")
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_bold_and_italic():
    out, = _render("Voci **PREMIUM** ora in *hindi*.")
    assert "<strong>PREMIUM</strong>" in out
    assert "<em>hindi</em>" in out


def test_external_link_has_label_href_and_rel():
    out, = _render("Vedi la [guida](https://audiobook-maker.com/guide).")
    assert 'href="https://audiobook-maker.com/guide"' in out
    assert ">guida</a>" in out
    assert 'target="_blank"' in out
    assert "noopener" in out


def test_internal_link_stays_in_page():
    out, = _render("Apri la [guida](/guide/gemini).")
    assert 'href="/guide/gemini"' in out
    assert "target=" not in out


def test_mailto_link_allowed():
    out, = _render("Scrivi a [noi](mailto:info@audiobook-maker.com).")
    assert 'href="mailto:info@audiobook-maker.com"' in out


def test_bullet_list():
    out, = _render("Novita':\n- qualita' audio\n- 50+ lingue")
    assert out.count("<li>") == 2
    assert "<ul>" in out and "</ul>" in out
    assert "qualita' audio" in out


def test_blank_line_makes_paragraph_single_newline_makes_br():
    out, = _render("Prima riga\nseconda riga\n\nNuovo paragrafo")
    assert out.count("<p>") == 2
    assert "<br>" in out


def test_plain_text_unchanged_semantics():
    """Una news senza marker (tutte quelle gia' pubblicate) resta identica."""
    out, = _render("Da oggi supportiamo l'hindi.")
    assert out == "<p>Da oggi supportiamo l'hindi.</p>"


def test_empty_input():
    out, = _render("")
    assert out == ""


# ─────────────────────────────── sicurezza ──────────────────────────────

def test_script_tag_is_escaped_not_executed():
    out, = _render("<script>alert(1)</script> e <img src=x onerror=alert(1)>")
    assert "<script" not in out.lower()
    assert "<img" not in out.lower()
    assert "onerror" not in out.lower() or "&lt;img" in out
    assert "&lt;script&gt;" in out


def test_javascript_url_is_dropped_keeping_label():
    out, = _render("[clicca](javascript:alert(1))")
    assert "javascript:" not in out.lower()
    assert "<a" not in out
    assert "clicca" in out


def test_javascript_url_mixed_case_is_dropped():
    out, = _render("[x](JaVaScRiPt:alert(1))")
    assert "<a" not in out
    assert "javascript" not in out.lower()


def test_data_url_is_dropped():
    out, = _render("[x](data:text/html;base64,PHNjcmlwdD4=)")
    assert "<a" not in out
    assert "data:" not in out


def test_quote_in_url_cannot_break_out_of_attribute():
    out, = _render('[x](https://evil.test/" onmouseover="alert(1))')
    assert 'onmouseover="alert' not in out
    assert '"' not in out.replace('href="', "").replace('" ', "").replace('">', "") \
        or "&quot;" in out


def test_html_in_link_label_is_escaped():
    out, = _render("[<b>x</b>](https://audiobook-maker.com)")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_protocol_relative_url_is_dropped():
    """//evil.test eredita lo schema della pagina: non e' un path interno."""
    out, = _render("[x](//evil.test/p)")
    assert "<a" not in out


# ───────────────────────── sanitize lato server ─────────────────────────

def test_sanitize_text_preserves_newlines_when_requested():
    import audiobook_app as app
    src = "riga uno\n\n- punto\n- altro punto"
    out = app._sanitize_text(src, 2000, keep_newlines=True)
    assert out == src


def test_sanitize_text_still_strips_html_tags():
    import audiobook_app as app
    out = app._sanitize_text("a <script>bad()</script> b", 2000,
                             keep_newlines=True)
    assert "<script>" not in out
    assert "bad()" in out


def test_sanitize_text_collapses_excess_blank_lines():
    import audiobook_app as app
    out = app._sanitize_text("a\n\n\n\n\nb", 2000, keep_newlines=True)
    assert out == "a\n\nb"


def test_sanitize_text_default_still_single_line():
    """Il titolo (e ogni altro uso) non deve cambiare comportamento."""
    import audiobook_app as app
    assert app._sanitize_text("a\n\nb", 200) == "a b"


def test_sanitize_text_truncates():
    import audiobook_app as app
    assert len(app._sanitize_text("x" * 5000, 2000, keep_newlines=True)) == 2000


def test_news_create_keeps_markdown_body():
    """L'endpoint admin deve salvare il Markdown, non appiattirlo."""
    src = Path("audiobook_app.py").read_text(encoding="utf-8")
    i = src.index("def admin_api_news_create")
    body = src[i:i + 2000]
    assert "keep_newlines=True" in body


# ─────────────────── traduzione: il markup deve sopravvivere ────────────

def test_translator_prompt_protects_markdown_and_urls():
    src = Path("community_translator.py").read_text(encoding="utf-8")
    i = src.index("_TRANSLATE_SYSTEM_PROMPT")
    prompt = src[i:src.index('"""', src.index('"""', i) + 3)]
    low = prompt.lower()
    assert "markdown" in low
    assert "url" in low


# ───────────────────────────── wiring frontend ──────────────────────────

def test_news_md_included_before_app_js():
    tail = TAIL.read_text(encoding="utf-8")
    assert "/static/js/news_md.js" in tail
    assert tail.index("news_md.js") < tail.index("app.js")


def test_app_js_renders_news_through_md():
    app = APP_JS.read_text(encoding="utf-8")
    assert "ABMNewsMd" in app
    # nessuno dei tre punti di rendering deve piu' usare textContent sul body
    i = app.index("function buildItem")
    block = app[i:i + 2000]
    assert "bodyEl.textContent" not in block


def test_news_body_is_div_not_paragraph():
    """Un <ul> dentro un <p> e' HTML invalido: il body deve essere un <div>."""
    app = APP_JS.read_text(encoding="utf-8")
    i = app.index("function buildItem")
    block = app[i:i + 2000]
    assert '<div class="news-item-body"></div>' in block
    head = HEAD.read_text(encoding="utf-8")
    assert 'id="newsModalBody" class="news-modal-body"' in head
    assert '<p id="newsModalBody"' not in head


def test_css_styles_news_body_markup():
    css = CSS.read_text(encoding="utf-8")
    assert ".news-item-body a" in css
    assert ".news-item-body ul" in css


def test_admin_page_has_markdown_help_and_preview():
    src = Path("audiobook_app.py").read_text(encoding="utf-8")
    i = src.index("Nuova news")
    block = src[i:i + 4000]
    assert "news_md.js" in src[i - 4000:i + 4000]
    assert "nPreview" in block
