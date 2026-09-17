"""Guida «Audiolibri con la tua voce»: contenuti, JSON-LD, route e link in home."""
import json
import re

import guide_content
import guide_voice_clone as gvc

GID = "voice-cloning-audiobook"
LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _html(lang):
    return guide_content.build_guide_html(GID, lang, base_url="https://x.test")


def test_guide_id_registered():
    import audiobook_app
    assert GID in audiobook_app._VALID_GUIDES
    assert guide_content._GUIDE_PUBLISHED.get(GID) == "2026-09-17"


def test_tutte_le_lingue_hanno_corpo_e_meta_propri():
    corpi = set()
    for lang in LANGS:
        assert set(gvc.META[lang]) == {"title", "h1", "kw", "desc"}
        h = _html(lang)
        assert "Guide content not available" not in h
        for anchor in ("what-you-need", "steps", "tips", "other-devices", "privacy", "faq"):
            assert f'id="{anchor}"' in h, (lang, anchor)
        assert h.count('<li id="step-') == 8
        assert f"<title>{gvc.META[lang]['title']}</title>" in h
        corpi.add(gvc.body(lang))
    # Nessuna lingua (hi compresa) ricade sul testo inglese.
    assert len(corpi) == len(LANGS)


def test_json_ld_howto_e_faq_validi():
    for lang in LANGS:
        tipi = {}
        for raw in _LD_RE.findall(_html(lang)):
            d = json.loads(raw)
            tipi[d["@type"]] = d
        assert {"Article", "BreadcrumbList", "HowTo", "FAQPage"} <= set(tipi), lang
        steps = tipi["HowTo"]["step"]
        assert len(steps) == 8 and steps[0]["url"].endswith("#step-1")
        assert all("<" not in s["text"] for s in steps)
        assert len(tipi["FAQPage"]["mainEntity"]) == 6


def test_etichette_ui_citate_esistono_in_i18n():
    """Le etichette fra «» nella guida devono essere quelle vere della UI."""
    from pathlib import Path
    import unicodedata
    # NFC: l'hindi ha la stessa lettera sia precomposta sia scomposta.
    i18n = unicodedata.normalize("NFC", Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8"))
    for lang in LANGS:
        body = unicodedata.normalize("NFC", gvc.body(lang))
        for label in re.findall(r"«([^»]+)»", body):
            assert f':"{label}"' in i18n or f':"★ {label}"' in i18n, (lang, label)


def test_nessun_provider_nominato():
    testo = json.dumps([gvc.META, gvc._T], ensure_ascii=False).lower()
    for nome in ("voxcpm", "runpod", "gemini", "openai", "elevenlabs", "deepseek", "google"):
        assert nome not in testo, nome


def test_cta_localizzata():
    assert "Prova Audiobook Maker gratis" in _html("it")
    assert "Try Audiobook Maker Free" in _html("en")


def test_link_in_home_i18n_seo_e_llms():
    from pathlib import Path
    head = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
    assert f"/guide/{GID}/__GUIDE_SUFFIX__" in head
    assert 'data-t="guide_voice_clone"' in head
    i18n = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    for lang in LANGS:
        assert f"Object.assign(L.{lang},{{guide_voice_clone:" in i18n
    seo = Path("seo_content.py").read_text(encoding="utf-8")
    assert f'href="/guide/{GID}/"' in seo
    for lang in ["it", "fr", "es", "de", "zh", "hi"]:
        assert f'href="/guide/{GID}/{lang}/"' in seo


def test_route_sitemap_e_llms_txt():
    import audiobook_app
    client = audiobook_app.app.test_client()
    assert client.get(f"/guide/{GID}/").status_code == 200
    for lang in ["it", "fr", "es", "de", "zh", "hi"]:
        r = client.get(f"/guide/{GID}/{lang}/")
        assert r.status_code == 200, (lang, r.status_code)
        assert gvc.META[lang]["h1"] in r.get_data(as_text=True)
    assert client.get(f"/guide/{GID}/en/").status_code == 301
    r_it = client.get(f"/guide/{GID}/?lang=it")
    assert r_it.status_code == 301 and r_it.headers["Location"].endswith(f"/guide/{GID}/it/")
    assert client.get(f"/guide/{GID}/xx/").status_code == 404
    sm = client.get("/sitemap.xml").data
    assert f"/guide/{GID}/it/".encode() in sm
    assert f"/guide/{GID}/".encode() in client.get("/llms.txt").data
