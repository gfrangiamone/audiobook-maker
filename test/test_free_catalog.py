"""Catalogo audiolibri gratuiti (free_catalog): lettura e validazione del
catalogo pubblico, pagine indice e libro, download contato, import nell'app
con i token di condivisione `fc-<book_id>`."""
import json
import re
from pathlib import Path

import pytest

import audiobook_app
import free_catalog
import routes_pages
import seo_ld
import storage_backend


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


def test_contract_sample_is_accepted_whole():
    # Contratto col repo abm-free-catalog (spec §6.3): stessa fixture e stesso
    # schema nei due repo; catalog_cli scrive cio' che lo schema descrive e qui
    # nessun campo dello schema va perso nella normalizzazione.
    fx = Path(__file__).parent / "fixtures" / "free_catalog"
    doc = json.loads((fx / "sample_it.json").read_text(encoding="utf-8"))
    schema = json.loads((fx / "catalog.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == free_catalog.SCHEMA_VERSION
    assert schema["properties"]["lang"]["enum"] == list(free_catalog.LANGS)
    books = free_catalog.validate(doc, "it")
    assert [b["book_id"] for b in books] == [b["book_id"] for b in doc["books"]]
    pub, raw = books[0], doc["books"][0]
    for key in ("voice_model", "voice_id", "voice_label", "description", "published_at"):
        assert pub[key] == raw[key], key
    assert pub["file"]["sha256"] == raw["file"]["sha256"]
    assert pub["file"]["preview_url"] == raw["file"]["preview_url"]
    assert [c["title"] for c in pub["file"]["chapters"]] == [c["title"] for c in raw["file"]["chapters"]]
    assert pub["source"]["ebook_url"] == raw["source"]["ebook_url"]
    assert books[1]["status"] == "coming" and books[1]["est_duration_s"] == doc["books"][1]["est_duration_s"]
    book_props = set(schema["$defs"]["book"]["properties"])
    assert book_props <= set(pub) | {"rights"}, book_props - set(pub)


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
    # Il motore compare solo nell'id voce dell'invito (?voice=); nel testo
    # della pagina resta il modello dichiarato (voice_model), mai il fornitore.
    low = page.lower().replace("voice=voxcpm%3a", "voice=")
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
    assert 'class="fc-shelf"' not in page   # pubblicato il 20/12: non e' fra i nuovi


def test_scaffale_dei_nuovi_solo_per_i_libri_degli_ultimi_tre_giorni(catalog, client):
    from datetime import date, datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    catalog([_book(published_at=today.isoformat()),
             _book(book_id="it-vecchio", slug="vecchio", title="Vecchio",
                   published_at=(today - timedelta(days=10)).isoformat()), dict(_COMING)])
    page = client.get("/free-audiobooks/it/").get_data(as_text=True)
    start = page.index('class="fc-shelf"')
    shelf = page[start:page.index("</section>", start)]
    assert "Nuovi audiolibri aggiunti al catalogo!" in page and "Disponibili ora" not in page
    assert "storia-di-una-capinera" in shelf and "/vecchio/" not in shelf
    items = [("it", {"status": "published", "published_at": d}) for d in
             ("2026-11-05", "2026-11-02", "2026-11-01", "2026-11-09", "", "x")]
    got = free_catalog.new_books(items, today=date(2026, 11, 5))
    assert [b["published_at"] for _, b in got] == ["2026-11-05", "2026-11-02"]


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
    assert locs == ["https://x/free-audiobooks/",
                    "https://x/free-audiobooks/it/",
                    "https://x/free-audiobooks/it/storia-di-una-capinera/"]
    assert entries[2][1] == "2026-12-20"
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


def _secondo_catalogo(tmp_path, lang, books):
    (tmp_path / f"{lang}.json").write_text(json.dumps(
        {"schema_version": 1, "lang": lang, "books": books}), encoding="utf-8")
    free_catalog.invalidate_cache()


def _libro_en(**over):
    return _book(book_id="en-moby", slug="moby-dick", title="Moby Dick",
                 author={"name": "Herman Melville", "died": 1891}, **over)


def test_l_indice_e_unico_con_tutte_le_lingue(catalog, client, tmp_path):
    _secondo_catalogo(tmp_path, "en", [_libro_en()])
    r = client.get("/free-audiobooks/", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert r.status_code == 200 and "Accept-Language" in r.headers.get("Vary", "")
    page = r.get_data(as_text=True)
    assert 'data-lang="it"' in page and 'data-lang="en"' in page
    assert 'href="/free-audiobooks/en/moby-dick/"' in page
    assert '<option value="en" selected>English</option>' in page   # lingua dell'utente
    assert '<link rel="canonical" href="' in page and '/free-audiobooks/"' in page


def test_filtro_su_tutte_se_la_lingua_dell_utente_non_ha_libri(catalog, client):
    page = client.get("/free-audiobooks/", headers={"Accept-Language": "fr-FR"}).get_data(as_text=True)
    assert '<option value="" selected>' in page
    page = client.get("/free-audiobooks/?lang=it").get_data(as_text=True)
    assert '<option value="it" selected>Italiano</option>' in page


def test_lingua_preimpostata_solo_con_libri_pubblicati(catalog, tmp_path):
    _secondo_catalogo(tmp_path, "en", [_libro_en(status="coming")])
    assert free_catalog.preset_lang(["en", "it"]) == "it"
    assert free_catalog.preset_lang(["pt-BR"]) == ""


def test_la_pagina_per_lingua_resta_per_la_seo(catalog, client, tmp_path):
    _secondo_catalogo(tmp_path, "en", [_libro_en()])
    page = client.get("/free-audiobooks/en/").get_data(as_text=True)
    assert '<option value="en" selected>English</option>' in page
    assert 'data-lang="it"' in page                         # stesso catalogo unico
    assert '/free-audiobooks/en/"' in page                  # canonical della lingua
    assert client.get("/free-audiobooks/xx/").status_code == 404


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


def test_l_invito_apre_abm_con_la_voce_del_libro(catalog):
    page = free_catalog.book_html("it", "storia-di-una-capinera", "https://abm.test",
                                  lambda text: "data:image/png;base64,QR")
    assert ('href="/?voice=voxcpm%3Av2%3Ait-IT%2FBruno&amp;utm_source=catalog'
            '&amp;utm_campaign=it-storia-di-una-capinera"') in page


def test_voce_malformata_l_invito_resta_senza_voce(catalog):
    catalog([_book(voice_id="javascript:alert(1)")])
    page = free_catalog.book_html("it", "storia-di-una-capinera", "https://abm.test",
                                  lambda text: "data:image/png;base64,QR")
    assert "voice=" not in page and "utm_source=catalog" in page


def test_il_link_del_libro_senza_app_invita_a_installarla(catalog, client):
    r = client.get("/s/fc-it-capinera", headers={"Accept-Language": "de-DE,de;q=0.9"})
    page = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Dieses Hörbuch in der App hören" in page
    assert "Storia di una capinera" in page and "Giovanni Verga" in page
    page = client.get("/s/fc-it-capinera", headers={"Accept-Language": "fr-FR"}).get_data(as_text=True)
    assert "Ascolta questo audiolibro nell&#x27;app" in page          # lingua del libro


def test_libro_ritirato_resta_la_pagina_generica(catalog, client):
    page = client.get("/s/fc-it-ritirato", headers={"Accept-Language": "it"}).get_data(as_text=True)
    assert "importare il processo" in page


def test_le_pagine_per_lingua_si_dichiarano_alternative(catalog, client, tmp_path):
    _secondo_catalogo(tmp_path, "en", [_libro_en()])
    page = client.get("/free-audiobooks/it/").get_data(as_text=True)
    assert '<link rel="alternate" hreflang="it" href="' in page and '/free-audiobooks/it/">' in page
    assert '<link rel="alternate" hreflang="en" href="' in page
    assert 'hreflang="x-default"' in page and 'hreflang="de"' not in page   # de senza catalogo


# --- bucket privato (decisione utente 05/11/2026) ------------------------------

_FILES = "/free-audiobooks/files"


@pytest.fixture
def bucket_catalog(monkeypatch):
    """Catalogo sul bucket privato: R2 finto e file con URL relativi."""
    b = _book(cover={"url": f"{_FILES}/covers/it/storia-di-una-capinera.jpg",
                     "thumb": f"{_FILES}/covers/it/storia-di-una-capinera-thumb.jpg"})
    b["file"] = dict(b["file"], url=f"{_FILES}/m4b/it/storia-di-una-capinera.m4b",
                     preview_url=f"{_FILES}/preview/it/storia-di-una-capinera.m4a")
    doc = {"schema_version": 1, "lang": "it", "books": [b]}
    signed, read = [], []

    def get_bytes(key, bucket=None):
        read.append((bucket, key))
        return json.dumps(doc).encode("utf-8") if key == "catalog/it.json" else None

    def presign(key, download_name=None, ttl=None, bucket=None):
        signed.append((bucket, key, download_name))
        return f"https://r2.example/{bucket}/{key}?sig=1"
    for name in ("ABM_FREE_CATALOG_SOURCE", "ABM_FREE_CATALOG_FILES_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ABM_FREE_CATALOG_BUCKET", "catalogo-abm")
    monkeypatch.setenv("ABM_FREE_CATALOG_TTL_SEC", "0")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "get_bytes", get_bytes)
    monkeypatch.setattr(storage_backend, "presigned_get_url", presign)
    free_catalog.invalidate_cache()
    yield signed, read
    free_catalog.invalidate_cache()


def test_catalogo_dal_bucket_e_file_con_url_firmati(bucket_catalog, client, monkeypatch):
    signed, read = bucket_catalog
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    assert [b["slug"] for b in free_catalog.books("it")] == ["storia-di-una-capinera"]
    assert ("catalogo-abm", "catalog/it.json") in read

    r = client.get(f"{_FILES}/covers/it/storia-di-una-capinera.jpg")
    assert r.status_code == 302
    assert r.headers["Location"] == "https://r2.example/catalogo-abm/covers/it/storia-di-una-capinera.jpg?sig=1"
    assert f"max-age={free_catalog.FILE_REDIRECT_MAX_AGE}" in r.headers["Cache-Control"]
    # Si firmano solo i file che scrive catalog_cli, non il resto del bucket.
    assert client.get(f"{_FILES}/catalog/it.json").status_code == 404
    assert client.get(f"{_FILES}/m4b/it/x.mp3").status_code == 404

    book = free_catalog.book("it", "storia-di-una-capinera")
    for url in ("/free-audiobooks/dl/it/storia-di-una-capinera.m4b", "/s/fc-it-capinera/dl"):
        r = client.get(url)
        assert r.status_code == 302, url
        assert r.headers["Location"].startswith("https://r2.example/catalogo-abm/m4b/it/"), url
        assert signed[-1][2] == free_catalog.file_name(book)        # "<Titolo> - <Autore>.m4b"

    page = client.get("/free-audiobooks/it/storia-di-una-capinera/").get_data(as_text=True)
    og = re.search(r"<meta[^>]+og:image[^>]*>", page).group(0)
    assert 'content="http' in og and "/covers/it/storia-di-una-capinera.jpg" in og


def test_senza_r2_il_bucket_non_accende_il_catalogo(monkeypatch):
    for name in ("ABM_FREE_CATALOG_SOURCE", "ABM_FREE_CATALOG_FILES_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ABM_FREE_CATALOG_BUCKET", "catalogo-abm")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    free_catalog.invalidate_cache()
    assert free_catalog.files_bucket() == ""
    assert free_catalog.bucket_file_url("covers/it/x.jpg") is None


def test_home_ha_la_faq_del_catalogo_con_il_link(client):
    # FAQ della home (i18n_data.js, pre-riempita lato server), la prima della
    # card, e pagina /faq/ con il link cliccabile.
    for lang in ("it", "en", "fr", "es", "de", "zh", "hi"):
        page = client.get(f"/{lang}/", follow_redirects=True).get_data(as_text=True)
        m = re.search(r'data-t="faq_catalog_a">(.*?)</div>', page, flags=re.S)
        assert m and "href='/free-audiobooks/'" in m.group(1), lang
        card = page[page.index('class="resources-card faq-card"'):]
        assert re.search(r'<summary data-t="(\w+)"', card).group(1) == "faq_catalog_q", lang
        faq = client.get(f"/faq/{lang}/").get_data(as_text=True)
        assert '<a href="https://audiobook-maker.com/free-audiobooks/">' in faq, lang
        assert '<a href="https://play.google.com/store/apps/details?id=it.abm.audiobook_maker_mobile"' \
               ' target="_blank" rel="noopener">' in faq, lang


def test_linkify_lascia_fuori_la_punteggiatura():
    import page_brand
    out = page_brand.linkify("vedi (https://alternativeto.net/software/x/about/). Fine")
    assert out == ('vedi (<a href="https://alternativeto.net/software/x/about/" target="_blank" '
                   'rel="noopener">https://alternativeto.net/software/x/about/</a>). Fine')
    assert page_brand.linkify("nessun link &amp; basta") == "nessun link &amp; basta"


def test_csp_ammette_lo_storage_per_copertine_e_anteprime(client, monkeypatch):
    # Dopo il 302 di /free-audiobooks/files/ l'immagine e l'audio arrivano dallo
    # storage R2: senza la sua origine nella CSP il browser li blocca (05/11/2026).
    monkeypatch.setenv("ABM_S3_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    csp = client.get("/it/").headers["Content-Security-Policy"]
    img = next(d for d in csp.split(";") if d.strip().startswith("img-src"))
    media = next(d for d in csp.split(";") if d.strip().startswith("media-src"))
    assert "https://acct.r2.cloudflarestorage.com" in img and "https://acct.r2.cloudflarestorage.com" in media
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    assert "cloudflarestorage" not in client.get("/it/").headers["Content-Security-Policy"]
