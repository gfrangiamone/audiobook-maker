"""Prefill server-side dei testi data-t (templates/seo_i18n.py).

I testi della home arrivano vuoti e li riempie applyI18n(): la pagina cresce
quando arrivano (CLS) e i crawler senza JS non li vedono. Il server li
pre-riempie con lo stesso testo che scriverebbe il client.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


# ── Home con le sole traduzioni della sua lingua (+ inglese) ──

def test_split_copre_tutto_il_file():
    assert seo_i18n._I18N_SPLIT is not None, "i18n_data.js ha un blocco che lo split non riconosce"


def test_split_non_riconosciuto_ricade_sul_file_intero(monkeypatch):
    monkeypatch.setattr(seo_i18n, "_I18N_SPLIT", seo_i18n._split_i18n("const L={it:{a:\"x\"}};\nfoo();\n"))
    assert seo_i18n._I18N_SPLIT is None
    assert seo_i18n.i18n_page_js("it") == seo_i18n._I18N_SRC
    assert seo_i18n.i18n_lang_js("fr") is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_pagina_piu_lingue_caricate_dopo_uguale_al_file_intero(tmp_path):
    """Per ogni lingua della home: L dopo il caricamento delle altre lingue
    (setLang) deve essere identico a quello del file intero."""
    full = tmp_path / "full.js"
    full.write_text(seo_i18n._I18N_SRC + "\nconsole.log(JSON.stringify(L));\n", encoding="utf-8")
    ref = json.loads(subprocess.run(["node", str(full)], capture_output=True, text=True,
                                    encoding="utf-8", check=True).stdout)
    for lang in seo_i18n._LANGS:
        page = seo_i18n.i18n_page_js(lang)
        inline = {"en", lang}
        assert len(page) < len(seo_i18n._I18N_SRC) / 2, lang
        rest = "".join(seo_i18n.i18n_lang_js(o) for o in seo_i18n._LANGS if o not in inline)
        js = tmp_path / f"{lang}.js"
        js.write_text(page + "\nconst first=JSON.stringify(Object.keys(L).sort());\n" + rest
                      + "\nconsole.log(JSON.stringify({first:JSON.parse(first),L}));\n", encoding="utf-8")
        got = json.loads(subprocess.run(["node", str(js)], capture_output=True, text=True,
                                        encoding="utf-8", check=True).stdout)
        assert got["first"] == sorted(inline)
        assert got["L"] == ref, lang


def test_home_inline_solo_la_sua_lingua_e_inglese():
    from templates.index_page import build_html_template
    html = build_html_template("it", {"title": "x"}, "https://audiobook-maker.com", "1.0", "", "")
    assert "const L={};" in html
    assert "L.it={" in html and "L.en={" in html and "L.fr={" not in html
    m = re.search(r"var I18N_SRC=(\{.*?\});", html)
    src = json.loads(m.group(1))
    assert sorted(src) == ["de", "es", "fr", "hi", "zh"]
    assert all(re.fullmatch(r"/i18n/[a-z]{2}\.js\?v=1\.0\.[0-9a-f]{8}", u) for u in src.values())


def test_route_i18n_lingua():
    import routes_pages
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(routes_pages.bp)
    c = app.test_client()
    r = c.get("/i18n/fr.js")
    assert r.status_code == 200 and "javascript" in r.content_type
    assert r.get_data(as_text=True) == seo_i18n.i18n_lang_js("fr")
    assert "immutable" in r.headers["Cache-Control"]
    assert c.get("/i18n/xx.js").status_code == 404


def test_set_lang_carica_la_lingua_mancante():
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    fn = app[app.index("function setLang(l)"):]
    fn = fn[:fn.index("\n}\n")]
    assert "_loadLang(l)" in fn, "setLang deve caricare /i18n/<lang>.js se L[l] manca"


def test_gtag_caricato_dopo_il_load():
    head = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
    assert '<script async src="https://www.googletagmanager.com' not in head
    i = head.index("addEventListener('load'")
    assert "googletagmanager.com/gtag/js?id=G-RBY3J76PDV" in head[i:i + 400]


def test_guida_podcast_senza_immagini_base64():
    pg = (ROOT / "templates/_fragments/podcast_guide_data.js").read_text(encoding="utf-8")
    assert "data:image" not in pg
    for name in re.findall(r"/static/img/([\w.]+)\?v=__APP_VERSION__", pg):
        assert (ROOT / "static/img" / name).stat().st_size > 1000, name


def test_banner_cookie_primo_script_defer_e_fuori_da_app_js():
    """Il testo del banner e' l'LCP per chi arriva la prima volta: non deve
    aspettare il download di app.js."""
    tail = (ROOT / "templates/_fragments/html_tail.html").read_text(encoding="utf-8")
    defers = re.findall(r'<script defer src="/static/js/([\w.]+)\?', tail)
    assert defers[0] == "cookie_banner.js"
    assert "abm_cookie_consent" not in (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "abm_cookie_consent" in (ROOT / "static/js/cookie_banner.js").read_text(encoding="utf-8")
