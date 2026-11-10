"""Guida M4B: meta per l'intento «cos'e' / come aprirlo / convertirlo» e data
di aggiornamento unica fra pagina e sitemap (guide_lastmod)."""
import json
import os
from datetime import datetime, timezone

import content_store
import guide_content

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
BODY_LANGS = ["it", "en", "fr", "es", "de", "zh"]
GID = "m4b-format"


def test_meta_fits_serp_limits():
    meta = content_store.content_json("guides", "meta.json")[GID]
    assert set(meta) == set(LANGS)
    for lang, m in meta.items():
        assert len(m["title"]) <= 60, lang
        assert len(m["desc"]) <= 155, lang
        assert "m4a vs m4b" in m["kw"] or "m4a与m4b" in m["kw"] or "m4a बनाम m4b" in m["kw"], lang


def test_bodies_cover_open_and_convert():
    for lang in BODY_LANGS:
        body = content_store.content_text("guides", GID, f"{lang}.html")
        assert body.count("<h2>") == 6, lang
        assert body.count("<details>") == 6, lang
        assert "libmp3lame" in body and "m4b-tool merge" in body, lang
        assert "Audiobookshelf" in body and "VLC" in body, lang
        # il link all'app punta alla home della lingua (EN alla radice)
        assert f'href="/{lang}/"' in body if lang != "en" else 'href="/"' in body


def test_page_dates_match_sitemap_lastmod():
    for lang in LANGS:
        html = guide_content.build_guide_html(GID, lang, base_url="https://x.test")
        lastmod = guide_content.guide_lastmod(GID, lang)
        assert "Guide content not available" not in html
        assert f'"dateModified": "{lastmod}"' in html, lang
        assert f'<time datetime="{lastmod}">' in html, lang


def test_guide_lastmod_follows_content_files():
    body = content_store.content_path("guides", GID, "en.html")
    expected = datetime.fromtimestamp(os.path.getmtime(body), timezone.utc).strftime("%Y-%m-%d")
    assert guide_content.guide_lastmod(GID, "en") >= expected


def test_file_lastmod_takes_newest_and_skips_missing(tmp_path):
    old, new = tmp_path / "old.txt", tmp_path / "new.txt"
    old.write_text("a")
    new.write_text("b")
    os.utime(old, (1_700_000_000, 1_700_000_000))   # 2023-11-14
    os.utime(new, (1_760_000_000, 1_760_000_000))   # 2025-10-09
    assert content_store.file_lastmod(old, new, tmp_path / "missing") == "2025-10-09"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert content_store.file_lastmod(tmp_path / "missing") == today


def test_article_ld_is_valid_json():
    html = guide_content.build_guide_html(GID, "en", base_url="https://x.test")
    start = html.index('"@type": "Article"')
    block = html[html.rindex("<script", 0, start):]
    block = block[block.index(">") + 1:block.index("</script>")]
    assert json.loads(block)["headline"].startswith("What Is an M4B File?")
