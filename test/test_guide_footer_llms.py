"""Pie' di pagina delle guide nella lingua della pagina, recensioni di
/llms.txt senza Markdown, guida PDF inglese allineata all'italiana."""
import re
from pathlib import Path

import pytest

import guide_content
import i18n
import seo_reviews
from content_store import content_json


@pytest.mark.parametrize("lang", i18n.LANGS)
def test_pie_di_pagina_delle_guide_nella_lingua_della_pagina(lang):
    ui = content_json("guides", "ui.json")
    assert set(ui[lang]) == {"footer_tagline", "footer_cta"}
    page = guide_content.build_guide_html("m4b-format", lang, "https://audiobook-maker.com")
    assert ui[lang]["footer_tagline"] in page and f'>{ui[lang]["footer_cta"]}</a>' in page
    if lang != "en":
        assert "Start converting" not in page and ui[lang] != ui["en"]


def test_recensioni_di_llms_senza_markdown(monkeypatch):
    class _Store:
        def all(self, include_archived=False):
            return [{"created_at": 1795000000, "rating": 5,
                     "comment": "## ⭐⭐⭐⭐⭐ An **Outstanding** Tool\n\n> really `good`"}]
    monkeypatch.setattr(seo_reviews.community_store, "feedback", lambda: _Store())
    block = seo_reviews.llms_txt_block()
    assert '"⭐⭐⭐⭐⭐ An Outstanding Tool really good"' in block
    assert not re.search(r"[#*`>]", block.split("\n", 1)[1])


def test_guida_pdf_en_ha_le_sezioni_dell_italiana():
    conta = lambda l: len(re.findall(r"<h2", Path(f"content/guides/pdf-to-audiobook/{l}.html").read_text(encoding="utf-8")))
    assert conta("en") == conta("it") == 11
    en = Path("content/guides/pdf-to-audiobook/en.html").read_text(encoding="utf-8")
    assert "PDF to audio converter" in en and "2 minutes of listening per page" in en
