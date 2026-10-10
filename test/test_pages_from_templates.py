"""Blocco C1: le pagine HTML/testo di audiobook_app vivono in templates/pages/.

Ogni file e' il contenuto che prima era una stringa Python; i segnaposto
`__Pn__` vengono sostituiti da `_render_page` nell'ordine dato, senza alcuna
interpretazione di graffe o `%`. Il gate di estrazione (2026-10-07) ha
confrontato byte per byte l'HTML servito prima e dopo su 22 pagine.
"""
import re
from pathlib import Path

import pytest

import audiobook_app as app
import routes_dl

PAGES = Path(app.__file__).parent / "templates" / "pages"
EXPECTED = {
    "faq.html", "install.html", "admin_log_activity.html", "admin_gate.html",
    "admin_vouchers.html", "admin_audit_premium.html", "admin_community.html",
    "podcast_index.html", "dl_expired.html", "dl_deleted.html", "dl_cooldown.html",
    "dl_page.html", "llms.txt", "robots.txt", "public_shell.html",
}


def test_every_page_file_exists_and_is_non_trivial():
    present = {p.name for p in PAGES.iterdir()}
    assert EXPECTED <= present, EXPECTED - present
    for name in EXPECTED:
        assert (PAGES / name).stat().st_size > 200, name


def test_render_page_replaces_placeholders_literally(tmp_path, monkeypatch):
    (tmp_path / "x.html").write_text("<p>__P0__ {a} % __P1__ __P10__</p>", encoding="utf-8")
    import page_brand
    monkeypatch.setattr(page_brand, "PAGES_DIR", tmp_path)
    monkeypatch.setattr(page_brand, "_page_cache", {})
    out = app._render_page("x", {"__P0__": "A<b>", "__P1__": 7, "__P10__": "ten"})
    assert out == "<p>A<b> {a} % 7 ten</p>"
    assert app._page_template("x") == "<p>__P0__ {a} % __P1__ __P10__</p>"
    assert app._page_template("x") is app._page_template("x")      # cache


def test_no_placeholder_survives_in_served_pages():
    """Ogni `__Pn__` del file deve avere un valore nel chiamante."""
    for name in ("dl_expired", "dl_deleted"):
        for lang in ("it", "en", "zz"):
            html = routes_dl._render_dl_expired_page(lang, 3) if name == "dl_expired" else routes_dl._render_dl_deleted_page(lang)
            assert not re.search(r"__P\d+__", html), (name, lang)
    html = routes_dl._render_dl_cooldown_page("fr", 10, "http://x/back")
    assert "__P" not in html and "http://x/back" in html
    html = app._render_install_page("it", "T", "<p>b</p>")
    assert "__P" not in html and "<p>b</p>" in html
    assert "__P" not in app._render_admin_gate("G", "/admin/x")


def test_admin_pages_served_from_files(monkeypatch):
    app.app.config["TESTING"] = True
    c = app.app.test_client()
    monkeypatch.setattr(app, "ADMIN_TOKEN", "tok-test")
    for url, marker in (("/admin/vouchers", "<!DOCTYPE html>"),
                        ("/admin/audit-premium", "<!DOCTYPE html>"),
                        ("/admin/community", "<!DOCTYPE html>"),
                        ("/admin/log-activity", "<!DOCTYPE html>")):
        r = c.get(url, headers={"X-Admin-Token": "tok-test"})
        assert r.status_code == 200, url
        body = r.get_data(as_text=True)
        assert marker in body and "__P" not in body, url


def test_robots_and_llms_from_files():
    app.app.config["TESTING"] = True
    c = app.app.test_client()
    r = c.get("/robots.txt")
    assert r.status_code == 200 and "User-agent: *" in r.get_data(as_text=True)
    r = c.get("/llms.txt")
    assert r.status_code == 200 and "Audiobook Maker" in r.get_data(as_text=True)
    assert "__P" not in r.get_data(as_text=True)


def test_no_full_html_document_left_inline():
    src = Path(app.__file__).read_text(encoding="utf-8")
    assert src.count("<!DOCTYPE html") == 0
    # restano solo frammenti brevi (shell _vc_page): nessuna stringa HTML > 40 righe
    for m in re.finditer(r'(?:f|r|rf|fr)?("""|\'\'\')(.*?)\1', src, flags=re.S):
        block = m.group(2)
        if "<html" in block.lower() or "<body" in block.lower():
            assert block.count("\n") < 40, block[:80]


def test_images_served_from_static_files():
    import favicon_data, og_image_data
    img = Path(app.__file__).parent / "static" / "img"
    for name, fn, magic in (("favicon.ico", favicon_data.get_favicon_ico, b"\x00\x00\x01\x00"),
                            ("favicon-192.png", favicon_data.get_favicon_png_192, b"\x89PNG"),
                            ("apple-touch-icon.png", favicon_data.get_apple_touch_icon, b"\x89PNG"),
                            ("favicon.svg", favicon_data.get_favicon_svg, b"<svg"),
                            ("og-image.png", og_image_data.get_og_image, b"\x89PNG")):
        assert (img / name).exists(), name
        data = fn().getvalue()
        assert data == (img / name).read_bytes() and data.startswith(magic), name
