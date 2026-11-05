"""Catalogo audiolibri gratuiti (free_catalog): lettura e validazione del
catalogo pubblico, pagine indice e libro, download contato, import nell'app
con i token di condivisione `fc-<book_id>`."""
import json

import pytest

import audiobook_app
import free_catalog
import routes_pages
import seo_ld


def _book(**over):
    b = {"book_id": "it-capinera", "slug": "storia-di-una-capinera",
         "title": "Storia di una capinera",
         "author": {"name": "Giovanni Verga", "born": 1840, "died": 1922},
         "first_published": 1871, "status": "published",
         "description": "Primo paragrafo.\n\nSecondo paragrafo.",
         "voice_label": "Bruno", "voice_id": "voxcpm:v2:it-IT/Bruno",
         "source": {"site": "Wikisource", "url": "https://it.wikisource.org/wiki/X",
                    "ebook_url": "https://ws-export.example/?format=epub&page=X",
                    "license": "pubblico dominio", "edition": "Treves 1871"},
         "rights": {"eu_pd": True, "us_pd": True},
         "production": {"generated_at": "2026-12-12"},
         "chars": 184219,
         "cover": {"url": "https://files.example/covers/it/capinera.jpg",
                   "thumb": "https://files.example/covers/it/capinera-thumb.jpg"},
         "published_at": "2026-12-20",
         "file": {"url": "https://files.example/m4b/it/capinera.m4b", "bytes": 120_000_000,
                  "duration_s": 12600, "format": "M4B", "codec": "aac", "bitrate_kbps": 64,
                  "sample_rate": 48000, "channels": 1, "sha256": "ab" * 32,
                  "preview_url": "https://files.example/preview/it/capinera.m4a", "preview_s": 300,
                  "chapters": [{"title": "I", "start_s": 95}, {"title": "Introduzione", "start_s": 0}]}}
    b.update(over)
    return b


_COMING = {"book_id": "it-coming", "slug": "in-arrivo", "title": "In arrivo",
           "author": {"name": "Matilde Serao", "died": 1927, "sex": "f"}, "status": "coming",
           "est_duration_s": 19200}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    def write(books, **doc):
        d = {"schema_version": 1, "lang": "it", "books": books}
        d.update(doc)
        (tmp_path / "it.json").write_text(json.dumps(d), encoding="utf-8")
        free_catalog.invalidate_cache()
    monkeypatch.setenv("ABM_FREE_CATALOG_SOURCE", str(tmp_path / "{lang}.json"))
    monkeypatch.setenv("ABM_FREE_CATALOG_TTL_SEC", "0")
    write([_book(), _COMING])
    yield write
    free_catalog.invalidate_cache()


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


# --- validazione --------------------------------------------------------------

def test_validate_rejects_unknown_schema_and_wrong_lang():
    with pytest.raises(ValueError):
        free_catalog.validate({"schema_version": 2, "lang": "it", "books": []}, "it")
    with pytest.raises(ValueError):
        free_catalog.validate({"schema_version": 1, "lang": "de", "books": []}, "it")
    with pytest.raises(ValueError):
        free_catalog.validate([], "it")


def test_validate_drops_malformed_books_and_duplicates():
    books = free_catalog.validate({"schema_version": 1, "lang": "it", "books": [
        _book(),
        _book(book_id="it-dup"),                        # stesso slug: scartato
        _book(slug="Slug Non Valido", book_id="it-x"),  # slug malformato
        _book(slug="senza-file", book_id="it-y", file=None),  # pubblicato senza file
        _book(slug="senza-autore", book_id="it-z", author={}),
        dict(_COMING),
        "non un libro",
    ]}, "it")
    assert [b["slug"] for b in books] == ["storia-di-una-capinera", "in-arrivo"]
    chapters = books[0]["file"]["chapters"]
    assert [c["start_s"] for c in chapters] == [0.0, 95.0]   # ordinati


def test_chapters_outside_the_file_are_dropped():
    f = free_catalog._valid_file({"url": "/x.m4b", "duration_s": 100,
                                  "chapters": [{"title": "a", "start_s": 0},
                                               {"title": "b", "start_s": 150},
                                               {"title": "c", "start_s": -1}]})
    assert [c["title"] for c in f["chapters"]] == ["a"]


def test_catalog_is_off_without_source(monkeypatch, client):
    monkeypatch.delenv("ABM_FREE_CATALOG_SOURCE", raising=False)
    free_catalog.invalidate_cache()
    assert free_catalog.books("it") is None
    assert client.get("/free-audiobooks/it/").status_code == 404


def test_unknown_language_is_404(catalog, client):
    assert free_catalog.books("fr") is None
    assert client.get("/free-audiobooks/fr/").status_code == 404


def test_bad_update_keeps_the_last_valid_copy(catalog, tmp_path):
    assert len(free_catalog.books("it")) == 2
    # Aggiornamento rotto pubblicato senza svuotare la cache: resta l'ultima copia.
    (tmp_path / "it.json").write_text('{"schema_version": 9}', encoding="utf-8")
    assert len(free_catalog.books("it")) == 2
    (tmp_path / "it.json").write_text("non e' JSON", encoding="utf-8")
    assert len(free_catalog.books("it")) == 2


# --- pagine -------------------------------------------------------------------

def test_hub_lists_books_with_status_and_escapes(catalog, client):
    catalog([_book(title='Capinera <script>alert(1)</script>'), _COMING])
    r = client.get("/free-audiobooks/it/")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;" in page
    assert 'href="/free-audiobooks/it/storia-di-una-capinera/"' in page
    assert 'data-status="coming"' in page
    assert 'href="/free-audiobooks/it/in-arrivo/"' not in page   # in arrivo: niente link
    assert "/static/js/free_catalog.js?v=" in page


def test_book_page_has_preview_download_and_app(catalog, client, monkeypatch):
    qr_di = []
    monkeypatch.setattr(audiobook_app, "_qr_data_uri",
                        lambda text: qr_di.append(text) or "data:image/png;base64,QR")
    r = client.get("/free-audiobooks/it/storia-di-una-capinera/")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    # Sul web solo l'anteprima: il file intero non va in un player.
    assert 'src="https://files.example/preview/it/capinera.m4a"' in page
    assert 'src="https://files.example/m4b/it/capinera.m4b"' not in page
    assert "I primi 5 minuti" in page
    # Niente elenco dei capitoli (decisione 05/11/2026): il numero resta fra i chip.
    assert "fc-chapters" not in page and "<time>" not in page and "data-t=" not in page
    assert "2 capitoli" in page
    assert 'href="/free-audiobooks/dl/it/storia-di-una-capinera.m4b"' in page
    assert qr_di and qr_di[0].endswith("/s/fc-it-capinera")   # il QR punta alla share
    assert 'src="data:image/png;base64,QR"' in page
    assert 'class="stores"' in page                    # badge degli store nell'invito
    assert "Apple Books" not in page
    assert '"@type": "Audiobook"' in page
    assert "<p>Secondo paragrafo.</p>" in page
    low = page.lower()
    assert "gemini" not in low and "voxcpm" not in low and "runpod" not in low


def test_book_page_on_a_phone_shows_the_library_button_not_the_qr(catalog):
    page = free_catalog.book_html("it", "storia-di-una-capinera", "https://abm.test",
                                  lambda text: "data:image/png;base64,QR",
                                  app_url=lambda url: url.replace("https://", "abm://"))
    assert 'href="abm://abm.test/s/fc-it-capinera"' in page
    assert "Scarica nella libreria" in page
    assert "data:image/png;base64,QR" not in page          # il QR serve solo dal computer
    assert "Su Android e iOS il file M4B si apre con l&#x27;app Audiobook Maker &amp; Player." in page


def test_book_page_from_a_computer_shows_the_qr(catalog):
    page = free_catalog.book_html("it", "storia-di-una-capinera", "https://abm.test",
                                  lambda text: "data:image/png;base64,QR",
                                  app_url=lambda url: "")
    assert 'src="data:image/png;base64,QR"' in page
    assert "Scarica nella libreria" not in page


@pytest.mark.parametrize("ua, atteso", [
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)",
     'href="abm://localhost:5601/s/fc-it-capinera"'),
    ("Mozilla/5.0 (Linux; Android 15; Pixel 9)",
     'href="intent://localhost:5601/s/fc-it-capinera#Intent;scheme=abm;'
     'package=it.abm.audiobook_maker_mobile;'
     'S.browser_fallback_url=http%3A%2F%2Flocalhost%3A5601%2Fs%2Ffc-it-capinera;end"'),
])
def test_the_route_uses_abm_deep_links_per_platform(catalog, client, monkeypatch, ua, atteso):
    # Gli stessi link della pagina di download: abm:// su iOS, intent:// con la
    # pagina degli store come ripiego su Android.
    monkeypatch.setattr(audiobook_app, "BASE_URL", "http://localhost:5601")
    r = client.get("/free-audiobooks/it/storia-di-una-capinera/", headers={"User-Agent": ua})
    page = r.get_data(as_text=True)
    assert atteso.replace("&", "&amp;") in page or atteso in page
    assert "User-Agent" in r.headers.get("Vary", "")


def test_book_page_without_preview_has_no_audio(catalog, client):
    b = _book()
    b["file"] = {k: v for k, v in b["file"].items() if k not in ("preview_url", "preview_s")}
    catalog([b])
    page = client.get("/free-audiobooks/it/storia-di-una-capinera/").get_data(as_text=True)
    assert "<audio" not in page and 'id="fc-app"' in page


def test_preview_needs_url_and_positive_length():
    f = free_catalog._valid_file({"url": "/x.m4b", "duration_s": 100,
                                  "preview_url": "javascript:alert(1)", "preview_s": 60})
    assert f["preview_url"] == "" and f["preview_s"] == 0
    f = free_catalog._valid_file({"url": "/x.m4b", "duration_s": 100,
                                  "preview_url": "/p.m4a", "preview_s": 0})
    assert f["preview_url"] == ""


def test_book_page_without_qr_has_no_broken_image(catalog, client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_qr_data_uri", lambda text: "")
    page = client.get("/free-audiobooks/it/storia-di-una-capinera/").get_data(as_text=True)
    assert 'src=""' not in page


def test_coming_and_unknown_books_are_404(catalog, client):
    assert client.get("/free-audiobooks/it/in-arrivo/").status_code == 404
    assert client.get("/free-audiobooks/it/nessuno/").status_code == 404


def test_list_shows_covers_and_hm_durations_not_death_dates(catalog, client):
    page = client.get("/free-audiobooks/it/").get_data(as_text=True)
    assert 'src="https://files.example/covers/it/capinera-thumb.jpg"' in page
    assert ">3:30<" in page          # pubblicato: durata reale ore:minuti
    assert ">~5:20<" in page         # in arrivo: stima
    assert "1922" not in page and "1927" not in page and "†" not in page
    assert 'class="fc-shelf"' in page   # scaffale dei disponibili


def test_book_without_cover_falls_back_to_initials(catalog, client):
    catalog([_book(cover=None)])
    page = client.get("/free-audiobooks/it/storia-di-una-capinera/").get_data(as_text=True)
    assert "fc-noimg" in page and "--cover:" not in page


def test_book_page_has_full_details_and_source_ebook(catalog, client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_qr_data_uri", lambda text: "")
    page = client.get("/free-audiobooks/it/storia-di-una-capinera/").get_data(as_text=True)
    assert 'id="fc-scheda"' in page
    for text in ("184.219 caratteri", "64 kbps · 48 kHz · mono", "M4B · AAC", "Treves 1871",
                 "Bruno (voce sintetica)", "12/12/2026", "20/12/2026", "1840–1922",
                 "<code>it-capinera</code>", "abababababababab…"):
        assert text in page, text
    assert 'href="https://ws-export.example/?format=epub&amp;page=X"' in page
    assert 'href="https://it.wikisource.org/wiki/X"' in page
    assert 'src="https://files.example/covers/it/capinera.jpg"' in page
    assert "--cover:url(" in page


def test_unsafe_urls_are_dropped():
    b = free_catalog._valid_book(_book(cover={"url": "javascript:alert(1)",
                                              "thumb": "https://x/a b.jpg"},
                                       source={"site": "S", "url": "https://x/'), url(evil"}))
    assert b["cover"] == {"url": "", "thumb": ""}
    assert b["source"]["url"] == ""


def test_scheda_uses_gendered_death_year_when_birth_is_missing(catalog):
    t = free_catalog._t("it")
    assert free_catalog._life({"died": 1927, "sex": "f"}, t) == "morta nel 1927"
    assert free_catalog._life({"died": 1922}, t) == "morto nel 1922"
    assert free_catalog._years({"died": 1922}) == ""


def test_sitemap_lists_hub_and_published_books_only(catalog):
    entries = free_catalog.sitemap_entries("https://x")
    locs = [e[0] for e in entries]
    assert locs == ["https://x/free-audiobooks/it/",
                    "https://x/free-audiobooks/it/storia-di-una-capinera/"]
    assert entries[1][1] == "2026-12-20"
    monkeypatch_base = routes_pages._cfg["base_url"]
    try:
        routes_pages._cfg["base_url"] = lambda: "https://x"
        xml = routes_pages.sitemap_xml()
    finally:
        routes_pages._cfg["base_url"] = monkeypatch_base
    assert "<loc>https://x/free-audiobooks/it/storia-di-una-capinera/</loc>" in xml
    assert "in-arrivo" not in xml


def test_sitemap_without_catalog_has_no_entries(monkeypatch):
    monkeypatch.delenv("ABM_FREE_CATALOG_SOURCE", raising=False)
    free_catalog.invalidate_cache()
    assert free_catalog.sitemap_entries("https://x") == []


def test_local_files_route_only_in_development(client, tmp_path, monkeypatch):
    (tmp_path / "covers").mkdir()
    (tmp_path / "covers" / "a.jpg").write_bytes(b"JPEGDATA")
    monkeypatch.delenv("ABM_FREE_CATALOG_FILES_DIR", raising=False)
    assert client.get("/free-audiobooks/files/covers/a.jpg").status_code == 404
    monkeypatch.setenv("ABM_FREE_CATALOG_FILES_DIR", str(tmp_path))
    r = client.get("/free-audiobooks/files/covers/a.jpg")
    assert r.status_code == 200 and r.data == b"JPEGDATA"
    assert client.get("/free-audiobooks/files/../secret.txt").status_code == 404


def test_root_redirects_to_italian(client):
    r = client.get("/free-audiobooks/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/free-audiobooks/it/")


# --- download e import nell'app -----------------------------------------------

def test_download_is_counted_and_redirected(catalog, client, monkeypatch):
    seen = []
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: seen.append((a, k)))
    r = client.get("/free-audiobooks/dl/it/storia-di-una-capinera.m4b")
    assert r.status_code == 302
    assert r.headers["Location"] == "https://files.example/m4b/it/capinera.m4b"
    assert seen and seen[0][0][2] == "FREE_CATALOG_DL" and seen[0][0][1] == "it-capinera"
    assert client.get("/free-audiobooks/dl/it/in-arrivo.m4b").status_code == 404


def test_share_claim_resolves_catalog_token(catalog, client):
    r = client.get("/api/share/claim/fc-it-capinera")
    assert r.status_code == 200
    d = r.get_json()
    assert d["download_url"].endswith("/s/fc-it-capinera/dl")
    assert d["filename"] == "Storia_di_una_capinera_-_Giovanni_Verga.m4b"
    assert d["ttl_sec_remaining"] > 0
    assert client.get("/api/share/claim/fc-it-coming").status_code == 404
    assert client.get("/api/share/claim/fc-it-nessuno").status_code == 404


def test_share_download_redirects_catalog_token(catalog, client, monkeypatch):
    seen = []
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: seen.append((a, k)))
    r = client.get("/s/fc-it-capinera/dl")
    assert r.status_code == 302
    assert r.headers["Location"] == "https://files.example/m4b/it/capinera.m4b"
    assert seen[0][0][2] == "FREE_CATALOG_APP"


def test_share_token_helpers(catalog):
    b = free_catalog.book("it", "storia-di-una-capinera")
    assert free_catalog.share_token(b) == "fc-it-capinera"
    assert free_catalog.book_for_share_token("fc-it-capinera")["slug"] == b["slug"]
    assert free_catalog.book_for_share_token("fc-it-coming") is None
    assert free_catalog.book_for_share_token("altro") is None
    assert free_catalog.book_for_share_token(None) is None
    assert free_catalog.file_name(_book(title='A/B: "c"')) == "A_B_c_-_Giovanni_Verga.m4b"


# --- JSON-LD ------------------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [(12600, "PT3H30M"), (30, "PT1M"),
                                              (3600, "PT1H"), (0, "PT1M"), (5430, "PT1H31M")])
def test_iso_duration(seconds, expected):
    assert seo_ld.iso_duration(seconds) == expected


def test_audiobook_ld_is_free_and_has_no_reader():
    ld = seo_ld.audiobook_ld(name="T", author="A", in_lang="it", url="https://x/t/",
                             content_url="https://x/t.m4b", duration_s=600,
                             description="d", date_published="2026-12-20", base="https://x")
    assert ld["@type"] == "Audiobook" and ld["isAccessibleForFree"] is True
    assert ld["offers"]["price"] == "0" and ld["duration"] == "PT10M"
    assert ld["author"] == {"@type": "Person", "name": "A"}
    assert "readBy" not in ld and ld["datePublished"] == "2026-12-20"


def test_la_voce_nella_scheda_porta_il_modello_tts(catalog):
    catalog([_book(voice_label="Sulafat", voice_model="Gemini 3.8")])
    page = free_catalog.book_html("it", "storia-di-una-capinera", "https://abm.test",
                                  lambda text: "data:image/png;base64,QR")
    assert "Sulafat (voce sintetica TTS PREMIUM Gemini 3.8)" in page
    assert "Letto da Sulafat (TTS PREMIUM Gemini 3.8)" in page


def test_senza_modello_la_voce_resta_com_era(catalog):
    page = free_catalog.book_html("it", "storia-di-una-capinera", "https://abm.test",
                                  lambda text: "data:image/png;base64,QR")
    assert "Bruno (voce sintetica)" in page and "TTS PREMIUM" not in page


def test_la_scheda_ha_il_ritorno_al_catalogo_in_testa_e_in_fondo(catalog):
    page = free_catalog.book_html("it", "storia-di-una-capinera", "https://abm.test",
                                  lambda text: "data:image/png;base64,QR")
    link = '<a href="/free-audiobooks/it/">← Torna al catalogo</a>'
    assert page.count(link) == 2
    assert page.index(link) < page.index('class="fc-bhero"')
