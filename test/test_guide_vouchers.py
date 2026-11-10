"""Guida «Buoni e coupon» (/guide/vouchers/): registrazione, corpi in 7 lingue
allineati alle regole dei voucher in payment, link da home, donazioni e email."""
from pathlib import Path

import content_store
import guide_content
import payment
import routes_pages

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
GID = "vouchers"


def test_registered_with_meta_in_serp_limits():
    assert GID in routes_pages._VALID_GUIDES
    assert guide_content._GUIDE_PUBLISHED[GID] == "2026-11-10"
    meta = content_store.content_json("guides", "meta.json")[GID]
    assert set(meta) == set(LANGS)
    for lang, m in meta.items():
        assert len(m["title"]) <= 60, lang
        assert len(m["desc"]) <= 155, lang
        assert m["h1"] and m["kw"], lang


def test_bodies_same_structure_in_every_language():
    for lang in LANGS:
        body = content_store.content_text("guides", GID, f"{lang}.html")
        assert body.count("<h2>") == 8, lang
        assert body.count("<details>") == 5, lang
        assert body.count("<tr>") == 5, lang
        assert "Audiobook Maker (VoxCPM2)" in body, lang
        for prefix in ("PROMO-", "GIFT-", "SUB-"):
            assert prefix in body, (lang, prefix)
        assert "180" in body and "30" in body, lang
        assert f'href="/{lang}/"' in body if lang != "en" else 'href="/"' in body
        suffix = "" if lang == "en" else f"{lang}/"
        assert f'href="/guide/voice-cloning-audiobook/{suffix}"' in body, lang


def test_body_numbers_follow_payment_rules():
    # Le cifre scritte nella guida restano quelle del codice.
    assert payment.VOUCHER_EXPIRY_DAYS == 180
    assert payment.VOUCHER_DEFAULT_SERVICES == ("llm", "translate", "voxcpm", "voice_clone")
    codes = "".join(payment._generate_voucher_code() for _ in range(50))
    assert not set("OI01") & set(codes)
    assert "180 days" in content_store.content_text("guides", GID, "en.html")
    # La maggiorazione dei buoni di rimborso non si annuncia nella guida.
    for lang in LANGS:
        body = content_store.content_text("guides", GID, f"{lang}.html")
        assert "10%" not in body and "10 %" not in body, lang


def test_no_excluded_model_named():
    # I limiti dei buoni si dicono in positivo: nessun modello escluso nominato.
    for lang in LANGS:
        body = content_store.content_text("guides", GID, f"{lang}.html")
        for name in ("Gemini", "Simba", "Speechify", "DeepSeek"):
            assert name not in body, (lang, name)


def test_pages_render_in_all_languages():
    import audiobook_app
    client = audiobook_app.app.test_client()
    assert client.get(f"/guide/{GID}/").status_code == 200
    for lang in LANGS:
        if lang == "en":
            continue
        assert client.get(f"/guide/{GID}/{lang}/").status_code == 200, lang
    for lang in LANGS:
        html = guide_content.build_guide_html(GID, lang, base_url="https://x.test")
        assert "Guide content not available" not in html
        assert "<h1>" in html and '"articleSection": "Help"' in html, lang
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    assert f"/guide/{GID}/" in sitemap and f"/guide/{GID}/de/" in sitemap


def test_links_from_home_donations_and_llms():
    head = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
    assert head.count(f"/guide/{GID}/__GUIDE_SUFFIX__") == 2
    assert 'data-t="guide_vouchers"' in head and 'data-t="donate_voucher_link"' in head
    i18n = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    assert i18n.count("guide_vouchers:") == 7
    assert i18n.count("donate_voucher_link:") == 7
    llms = Path("templates/pages/llms.txt").read_text(encoding="utf-8")
    assert f"__P0__/guide/{GID}/" in llms
