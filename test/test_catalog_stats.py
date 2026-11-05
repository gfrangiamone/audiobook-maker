"""Statistiche del catalogo gratuito per /admin/audit-catalog (spec §10.1)."""
from datetime import datetime

import pytest

import activity_log
import catalog_stats
import free_catalog


def _row(ts, book_id, op, ip="h1", platform=""):
    return activity_log.Row("", ts, book_id, op, "", ip, "", book_id[:2], platform)


@pytest.fixture
def dati(monkeypatch):
    libri = [("it", {"book_id": "it-capinera", "title": "Storia di una capinera",
                     "author": {"name": "Giovanni Verga"}, "voice_model": "VoxCPM2",
                     "published_at": "2026-12-20", "status": "published"}),
             ("it", {"book_id": "it-ventre", "title": "Il ventre di Napoli",
                     "author": {"name": "Matilde Serao"}, "voice_model": "Gemini 3.8",
                     "published_at": "2026-12-21", "status": "published"}),
             ("en", {"book_id": "en-moby", "title": "Moby Dick",
                     "author": {"name": "Herman Melville"}, "voice_model": "Gemini 3.8",
                     "published_at": "", "status": "coming"})]
    righe = [_row("2026-12-22 10:00:00", "it-capinera", "FREE_CATALOG_DL"),
             _row("2026-12-22 11:00:00", "it-capinera", "FREE_CATALOG_APP", "h2", "android"),
             _row("2026-12-23 09:00:00", "it-capinera", "FREE_CATALOG_APP", "h2", "ios"),
             _row("2026-12-23 09:30:00", "it-capinera", "FREE_CATALOG_APP", "h3", "app"),
             _row("2026-12-23 12:00:00", "it-vecchio", "FREE_CATALOG_DL", "h1")]
    visti = {}

    def iter_rows(since, until=None, ops=None):
        visti["periodo"] = (since, until, ops)
        return iter(righe)
    monkeypatch.setattr(free_catalog, "all_books", lambda: libri)
    monkeypatch.setattr(activity_log, "iter_rows", iter_rows)
    monkeypatch.setattr(catalog_stats.metrics_store, "read_range",
                        lambda days: {"web_visit_from_catalog": {"unknown": 7}})
    monkeypatch.setattr(catalog_stats.gemini_cost_audit, "iter_records", lambda **k: iter([
        {"acquisition_source": "catalog", "user_price_eur_charged": 4.5},
        {"acquisition_source": "app", "user_price_eur_charged": 9.0}]))
    monkeypatch.setattr(catalog_stats.optimization_cost_audit, "iter_records", lambda **k: iter([]))
    return visti


def test_totali_per_libro_e_piattaforma(dati):
    s = catalog_stats.stats("2026-12-20", "2026-12-23")
    assert dati["periodo"][0] == datetime(2026, 12, 20) and dati["periodo"][1] == datetime(2026, 12, 24)
    assert s["totals"] == {"download": 2, "android": 1, "ios": 1, "app_other": 1, "total": 5,
                           "visitors": 3, "books_with_events": 2}
    capinera = next(r for r in s["books"] if r["book_id"] == "it-capinera")
    assert (capinera["download"], capinera["android"], capinera["ios"], capinera["total"]) == (1, 1, 1, 4)
    assert [r["book_id"] for r in s["books"]][-1] == "it-ventre"       # senza eventi in fondo
    assert all(r["book_id"] != "en-moby" for r in s["books"])          # in arrivo, nessun evento
    assert any(r["book_id"] == "it-vecchio" for r in s["books"])       # ritirato: resta contato
    assert [d["day"] for d in s["days"]] == ["2026-12-20", "2026-12-21", "2026-12-22", "2026-12-23"]
    assert s["return"] == {"visits": 7, "payments": 1, "payments_eur": 4.5}


def test_filtri_per_lingua_e_modello(dati):
    assert catalog_stats.stats("2026-12-20", "2026-12-23", lang="en")["totals"]["total"] == 0
    s = catalog_stats.stats("2026-12-20", "2026-12-23", model="Gemini 3.8")
    assert [r["book_id"] for r in s["books"]] == ["it-ventre"]


def test_periodo_di_default_e_tetto():
    oggi = datetime(2026, 12, 31, 15, 0)
    start, end = catalog_stats.period(today=oggi)
    assert (end - start).days == catalog_stats.DEFAULT_DAYS and end == datetime(2027, 1, 1)
    start, end = catalog_stats.period("2020-01-01", "2026-12-31", today=oggi)
    assert (end - start).days == catalog_stats.MAX_DAYS


def test_api_admin(dati, monkeypatch):
    import audiobook_app
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "segreto")
    c = audiobook_app.app.test_client()
    assert c.get("/admin/api/catalog_stats").status_code == 401
    r = c.get("/admin/api/catalog_stats?from=2026-12-20&to=2026-12-23",
              headers={"X-Admin-Token": "segreto"})
    assert r.status_code == 200 and r.get_json()["totals"]["total"] == 5
    page = c.get("/admin/audit-catalog", headers={"X-Admin-Token": "segreto"}).get_data(as_text=True)
    assert "Audit catalogo audiolibri gratuiti" in page
