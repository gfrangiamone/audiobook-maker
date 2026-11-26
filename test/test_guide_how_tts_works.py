"""Guida «Come funziona il text to speech» (/guide/how-text-to-speech-works/):
impaginata a slide (static/js/guide_slides.js), con campioni audio serviti da
static/guide-audio/ e grafiche SVG nel corpo."""
import re
from pathlib import Path

import content_store as cs
import guide_content

GID = "how-text-to-speech-works"
ROOT = Path(guide_content.__file__).resolve().parent
# Nessun fornitore nei testi per l'utente (CLAUDE.md, regola 4).
PROVIDERS = re.compile(r"gemini|google|voxcpm|pocket|edge|microsoft|speechify|deepseek|openrouter|runpod", re.I)


def _langs():
    return [p.stem for p in (ROOT / "content" / "guides" / GID).glob("*.html")]


def _text(html):
    html = re.sub(r"<(script|style|svg)[\s\S]*?</\1>", " ", html)
    return re.sub(r"<[^>]+>", " ", html)


def test_meta_nelle_misure_della_serp():
    meta = cs.content_json("guides", "meta.json")[GID]
    for lang in _langs():
        assert len(meta[lang]["title"]) <= 60, lang
        assert len(meta[lang]["desc"]) <= 160, lang


def test_pagina_a_slide_con_asset_versionati():
    for lang in _langs():
        page = guide_content.build_guide_html(GID, lang, "https://audiobook-maker.com")
        assert re.search(r'/static/css/guide_slides\.css\?v=[0-9a-f]{8}"', page), lang
        assert re.search(r'/static/js/guide_slides\.js\?v=[0-9a-f]{8}" defer', page), lang
        assert 'class="guide-deck"' in page and "data-next=" in page
        assert "__APP_VERSION__" not in page and "<!--SPECTRO" not in page and "<!--SRWAVES" not in page
        srcs = re.findall(r'<audio[^>]+src="(/static/[^"?]+)\?v=([0-9a-f]{8})"', page)
        assert srcs, lang
        for path, _v in srcs:
            assert (ROOT / path.lstrip("/")).is_file(), path


def test_le_altre_guide_restano_senza_slide():
    page = guide_content.build_guide_html("pdf-to-audiobook", "it", "https://audiobook-maker.com")
    assert "guide_slides" not in page


def test_nessun_fornitore_nel_testo():
    for lang in _langs():
        body = cs.content_text("guides", GID, f"{lang}.html")
        assert not PROVIDERS.search(_text(body)), lang
        meta = cs.content_json("guides", "meta.json")[GID][lang]
        assert not PROVIDERS.search(" ".join(meta.values())), lang


def test_link_da_home_llms_e_guida_tts():
    head = (ROOT / "templates" / "_fragments" / "html_head.html").read_text(encoding="utf-8")
    assert f"/guide/{GID}/__GUIDE_SUFFIX__" in head and 'data-t="guide_how_tts"' in head
    i18n = (ROOT / "templates" / "_fragments" / "i18n_data.js").read_text(encoding="utf-8")
    assert i18n.count("guide_how_tts:") == 7
    assert f"/guide/{GID}/" in (ROOT / "templates" / "pages" / "llms.txt").read_text(encoding="utf-8")
    for lang in ("en", "it", "fr", "es", "de", "zh"):
        assert f"/guide/{GID}/" in cs.content_text("guides", "text-to-speech-audiobook", f"{lang}.html"), lang


def test_la_route_risponde():
    import audiobook_app
    r = audiobook_app.app.test_client().get(f"/guide/{GID}/it/")
    assert r.status_code == 200
    assert "Come funziona la sintesi vocale" in r.get_data(as_text=True)
