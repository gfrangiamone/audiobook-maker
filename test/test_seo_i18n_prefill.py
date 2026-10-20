"""Prefill server-side dei testi data-t (templates/seo_i18n.py).

I testi della home arrivano vuoti e li riempie applyI18n(): la pagina cresce
quando arrivano (CLS) e i crawler senza JS non li vedono. Il server li
pre-riempie con lo stesso testo che scriverebbe il client.
"""
import re
from pathlib import Path

from templates import seo_i18n
from templates.seo_i18n import SEO_TEXT, _parse_i18n, prefill_seo_text

ROOT = Path(__file__).resolve().parent.parent


def test_parser_legge_oggetto_principale_e_object_assign(tmp_path):
    js = tmp_path / "i18n.js"
    js.write_text(
        'const L={\nit:{a:"uno",langs:{en:"Inglese",it:"Italiano"},b:"l\\\'altro \\"x\\" \\u00e8"},\n'
        'en:{a:"one",b:"other"}\n};\n'
        'Object.assign(L.it,{a:"uno bis",c:"tre"});\n', encoding="utf-8")
    got = _parse_i18n(js)
    assert got["it"] == {"a": "uno bis", "b": "l'altro \"x\" è", "c": "tre"}
    assert got["en"] == {"a": "one", "b": "other"}


def test_parser_copre_tutte_le_lingue_reali():
    for lang in seo_i18n._LANGS:
        assert len(SEO_TEXT[lang]) > 600, lang
    # chiavi aggiunte dai blocchi Object.assign in coda al file
    assert SEO_TEXT["it"]["faq_q1"]
    assert SEO_TEXT["it"]["s1_title"]


def test_prefill_riempie_ogni_elemento_vuoto():
    html = ('<h2 id="x" data-t="s1_title"></h2><button class="b" data-t="s1_title" disabled></button>'
            '<span data-t-html="app_dl_title"></span>')
    out = prefill_seo_text(html, "it")
    assert f'<h2 id="x" data-t="s1_title">{SEO_TEXT["it"]["s1_title"]}</h2>' in out
    assert f'disabled>{SEO_TEXT["it"]["s1_title"]}</button>' in out
    # data-t-html: markup del progetto, scritto come HTML come fa il client
    assert "<strong>" in out


def test_prefill_non_tocca_contenuti_attributi_e_script():
    html = ('<span data-t="s1_title">gia\' scritto</span>'
            '<a data-t-title="s1_title"></a><input data-t-ph="s1_title">'
            '<span data-t="chiave_inesistente"></span>'
            '<script>var s=\'<span data-t="s1_title"></span>\';</script>')
    assert prefill_seo_text(html, "it") == html


def test_prefill_escape_e_fallback_inglese(monkeypatch):
    monkeypatch.setitem(SEO_TEXT, "it", {"k": "a <b> & c"})
    monkeypatch.setitem(SEO_TEXT, "en", {"k": "x", "solo_en": "english"})
    out = prefill_seo_text('<p data-t="k"></p><p data-t="solo_en"></p>', "it")
    assert out == '<p data-t="k">a &lt;b&gt; &amp; c</p><p data-t="solo_en">english</p>'


def test_home_renderizzata_senza_data_t_vuoti():
    from templates.index_page import build_html_template
    html = build_html_template("it", None, "https://audiobook-maker.com", "x",
                               "https://audiobook-maker.com/it/", "")
    body = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
    vuoti = re.findall(r'<([a-z][a-z0-9]*)\s[^<>]*\sdata-t(?:-html)?="([^"]+)"[^<>]*></\1>', body)
    assert vuoti == []


def test_canonical_della_radice_resta_radice():
    """applySEO non deve riscrivere il canonical di / in /{lang}/."""
    js = (ROOT / "templates/_fragments/seo_data.js").read_text(encoding="utf-8")
    assert 'location.pathname==="/"?baseUrl+"/"' in js
    assert 'can.href=pageUrl' in js and 'og_url.content=pageUrl' in js
    assert 'baseUrl + "/" + lang + "/"' not in js
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    fn = app[app.index("function setLang(l)"):]
    assert fn.index("history.replaceState") < fn.index("applySEO(l)"), \
        "il pathname va aggiornato prima di calcolare il canonical"
