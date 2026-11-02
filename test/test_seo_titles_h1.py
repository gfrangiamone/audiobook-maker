"""SEO (2026-11-02, Bing Webmaster): title <= 60 caratteri su guide e
/content/, un solo <h1> su /content/<lang>/."""
import re

import pytest

import audiobook_app
import i18n
from content_store import content_json

MAX_TITLE = 60


def _guide_metas():
    meta = content_json("guides", "meta.json")
    meta["voice-cloning-audiobook"] = content_json("guides", "voice-cloning-audiobook", "meta.json")
    for gid, langs in meta.items():
        for lang, m in langs.items():
            if isinstance(m, dict) and "title" in m:
                yield gid, lang, m


def test_guide_titles_fit_serp():
    long = [(g, l, len(m["title"])) for g, l, m in _guide_metas() if len(m["title"]) > MAX_TITLE]
    assert not long


def test_content_titles_fit_serp():
    c = content_json("seo", "content.json")
    for lang in i18n.LANGS:
        assert c[lang]["title"], lang
        assert len(c[lang]["title"]) <= MAX_TITLE, (lang, c[lang]["title"])


@pytest.mark.parametrize("lang", i18n.LANGS)
def test_content_page_has_one_h1_and_short_title(lang):
    audiobook_app.app.config["TESTING"] = True
    html = audiobook_app.app.test_client().get(f"/content/{lang}/").get_data(as_text=True)
    assert len(re.findall(r"<h1[\s>]", html)) == 1
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    assert content_json("seo", "content.json")[lang]["title"].replace("&", "&amp;") == title
