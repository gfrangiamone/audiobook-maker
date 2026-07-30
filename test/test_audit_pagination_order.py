"""Audit TTS/traduzione/ottimizzazione: la paginazione non deve tagliare i job recenti.

I JSONL di audit sono append-only in ordine cronologico crescente. Gli endpoint
paginavano `live + persisted` senza riordinare, quindi con piu' di `limit` (200)
record la pagina conteneva i piu' VECCHI e i job del giorno corrente non
comparivano nella tabella admin (segnalato 2026-07-30).

Copre i tre endpoint: ordinamento desc per `ts`, live sempre in testa,
`count` = totale non paginato, e la nota di troncamento nella UI.
"""
from pathlib import Path
import json

import pytest

import audiobook_app as app_mod


ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(app_mod, "ADMIN_TOKEN", ADMIN_TOKEN)
    app_mod.app.config["TESTING"] = True
    with app_mod.app.test_client() as c:
        yield c


def _write_audit(tmp_path, module, prefix, n, day="2026-07"):
    """Scrive n record cronologici crescenti; l'ultimo e' il piu' recente."""
    fp = tmp_path / f"{prefix}_2026-07.jsonl"
    with open(fp, "w", encoding="utf-8") as f:
        for i in range(n):
            # i=0 -> 2026-07-01, i cresce -> data piu' recente
            ts = f"{day}-{(i % 30) + 1:02d}T{(i % 24):02d}:00:00"
            f.write(json.dumps({
                "ts": ts, "job_id": f"job-{i:04d}", "outcome": "completed",
                "model_key": "m", "language": "en",
                "source_lang": "en", "target_lang": "it",
                "user_price_eur_charged": 1.0, "google_cost_eur_actual": 0.5,
                "_seq": i,
            }) + "\n")
    module._DATA_DIR = tmp_path
    return fp


def _no_live(monkeypatch):
    monkeypatch.setattr(app_mod, "_synth_running_gemini_audit_records", lambda: [])
    monkeypatch.setattr(app_mod, "_synth_running_translation_audit_records", lambda: [])
    monkeypatch.setattr(app_mod, "_synth_running_optimization_audit_records", lambda: [])


CASES = [
    ("gemini_cost_audit", "gemini_cost_audit", "/admin/api/gemini_cost_audit"),
    ("translation_cost_audit", "translation_cost_audit", "/admin/api/translation_cost_audit"),
    ("optimization_cost_audit", "optimization_cost_audit", "/admin/api/optimization_cost_audit"),
]


@pytest.mark.parametrize("mod_name,prefix,url", CASES)
def test_page_contains_most_recent_records(client, monkeypatch, tmp_path,
                                           mod_name, prefix, url):
    import importlib
    module = importlib.import_module(mod_name)
    _write_audit(tmp_path, module, prefix, 250)
    _no_live(monkeypatch)

    r = client.get(f"{url}?limit=200", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert r.status_code == 200
    d = r.get_json()
    recs = d["records"]

    assert len(recs) == 200
    assert d["count"] == 250, "count deve essere il totale non paginato"
    # Vengono scartati i record piu' vecchi, non i piu' recenti
    seqs = [r_["_seq"] for r_ in recs]
    assert max(seqs) == 249, "il record piu' recente deve essere in pagina"
    ts_list = [r_["ts"] for r_ in recs]
    assert ts_list == sorted(ts_list, reverse=True), "ordine cronologico decrescente"


@pytest.mark.parametrize("mod_name,prefix,url", CASES)
def test_live_records_stay_on_top(client, monkeypatch, tmp_path,
                                  mod_name, prefix, url):
    import importlib
    module = importlib.import_module(mod_name)
    _write_audit(tmp_path, module, prefix, 30)
    live = [{"ts": "2026-01-01T00:00:00", "job_id": "live-1", "outcome": "running",
             "model_key": "m", "language": "en", "source_lang": "en",
             "target_lang": "it", "_live": True}]
    _no_live(monkeypatch)
    for name in ("_synth_running_gemini_audit_records",
                 "_synth_running_translation_audit_records",
                 "_synth_running_optimization_audit_records"):
        monkeypatch.setattr(app_mod, name, lambda _l=live: list(_l))

    r = client.get(f"{url}?limit=200", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert r.status_code == 200
    recs = r.get_json()["records"]
    # Il live ha ts vecchissimo ma deve restare in testa (job in corso)
    assert recs[0]["job_id"] == "live-1"
    persisted_ts = [x["ts"] for x in recs[1:]]
    assert persisted_ts == sorted(persisted_ts, reverse=True)


def test_admin_page_reports_truncation():
    src = Path("audiobook_app.py").read_text(encoding="utf-8")
    assert "function auditTruncNote(" in src
    # tutte e tre le tabelle devono usarla (colspan 12/13/11)
    assert "auditTruncNote(recs.length, total, 12)" in src
    assert "auditTruncNote(recs.length, total, 13)" in src
    assert "auditTruncNote(recs.length, total, 11)" in src
