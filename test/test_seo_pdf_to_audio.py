"""Ricerche «pdf to audio» / «pdf to audio converter» (Search Console 26/11/2026:
impressioni x5 in 28 giorni, ma la home EN e' in posizione 9 con CTR 1,4% e la
guida PDF in posizione 61): la home inglese lo dice nella description e il
link alla guida PDF usa quelle parole; la guida le ha nel title."""
import re

import guide_content


def _client():
    import audiobook_app
    return audiobook_app.app.test_client()


def test_description_della_home_inglese():
    for url in ("/", "/en/"):
        r = _client().get(url)
        if r.status_code in (301, 302, 308):
            r = _client().get(r.headers["Location"])
        page = r.get_data(as_text=True)
        desc = re.search(r'<meta name="description"[^>]*content="([^"]*)"', page).group(1)
        assert "PDF to audio converter" in desc, url
        assert len(desc) <= 160, len(desc)


def test_link_della_home_alla_guida_pdf():
    page = _client().get("/").get_data(as_text=True)
    m = re.search(r'href="/guide/pdf-to-audiobook/"[^>]*>.*?<span data-t="guide_pdf">([^<]*)</span>',
                  page, flags=re.S)
    assert m and m.group(1) == "PDF to audio converter"


def test_title_della_guida_pdf_inglese():
    page = guide_content.build_guide_html("pdf-to-audiobook", "en", "https://audiobook-maker.com")
    title = re.search(r"<title>([^<]*)</title>", page).group(1)
    assert "PDF to Audio Converter" in title and len(title) <= 60
