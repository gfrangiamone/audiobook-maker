"""Catalogo audiolibri gratuiti (free_catalog): lettura e validazione del
catalogo pubblico, pagine indice e libro, download contato, import nell'app
con i token di condivisione `fc-<book_id>`."""
import json

import pytest

import audiobook_app
import free_catalog
import seo_ld


def _book(**over):
    b = {"book_id": "it-capinera", "slug": "storia-di-una-capinera",
         "title": "Storia di una capinera",
         "author": {"name": "Giovanni Verga", "born": 1840, "died": 1922},
         "first_published": 1871, "status": "published",
         "description": "Primo paragrafo.\n\nSecondo paragrafo.",
         "voice_label": "Bruno", "voice_id": "voxcpm:v2:it-IT/Bruno",
         "source": {"site": "Wikisource", "url": "https://it.wikisource.org/wiki/X",
                    "license": "pubblico dominio"},
         "published_at": "2026-12-20",
         "file": {"url": "https://files.example/m4b/it/capinera.m4b", "bytes": 120_000_000,
                  "duration_s": 12600,
                  "chapters": [{"title": "I", "start_s": 95}, {"title": "Introduzione", "start_s": 0}]}}
    b.update(over)
    return b


_COMING = {"book_id": "it-coming", "slug": "in-arrivo", "title": "In arrivo",
           "author": {"name": "Matilde Serao", "died": 1927}, "status": "coming"}


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


def test_book_page_has_player_chapters_download_and_app(catalog, client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_qr_data_uri", lambda text: "data:image/png;base64,QR")
    r = client.get("/free-audiobooks/it/storia-di-una-capinera/")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert 'src="https://files.example/m4b/it/capinera.m4b"' in page
    assert 'data-t="95"' in page
    assert 'href="/free-audiobooks/dl/it/storia-di-una-capinera.m4b"' in page
    assert "/s/fc-it-capinera" in page                 # abm:// e QR puntano alla share
    assert 'src="data:image/png;base64,QR"' in page
    assert '"@type": "Audiobook"' in page
    assert "<p>Secondo paragrafo.</p>" in page
    low = page.lower()
    assert "gemini" not in low and "voxcpm" not in low and "runpod" not in low


def test_book_page_without_qr_has_no_broken_image(catalog, client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_qr_data_uri", lambda text: "")
    page = client.get("/free-audiobooks/it/storia-di-una-capinera/").get_data(as_text=True)
    assert 'src=""' not in page


def test_coming_and_unknown_books_are_404(catalog, client):
    assert client.get("/free-audiobooks/it/in-arrivo/").status_code == 404
    assert client.get("/free-audiobooks/it/nessuno/").status_code == 404


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
