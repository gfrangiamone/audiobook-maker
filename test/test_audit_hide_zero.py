"""Filtro «Nascondi transazioni a importo zero» di /admin/audit-premium.

Le tabelle audit mescolano transazioni vere e usi gratuiti (voce standard,
ottimizzazione sotto la soglia free, voce campionata omaggio). Con
`hide_zero=1` le righe senza addebito spariscono da TUTTE e quattro le tab,
aggregati compresi: i totali devono sempre descrivere la tabella mostrata.

Criterio: l'ADDEBITO all'utente, non il ricavo effettivo. Un job rimborsato
resta una transazione (addebito > 0, ricavo 0) e deve restare visibile.
"""
import json

import pytest

import audiobook_app as app_mod
import voice_clone_audit as vca


ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_mod, "ADMIN_TOKEN", ADMIN_TOKEN)
    app_mod.app.config["TESTING"] = True
    with app_mod.app.test_client() as c:
        yield c


def _no_live(monkeypatch):
    monkeypatch.setattr(app_mod, "_synth_running_gemini_audit_records", lambda: [])
    monkeypatch.setattr(app_mod, "_synth_running_translation_audit_records", lambda: [])
    monkeypatch.setattr(app_mod, "_synth_running_optimization_audit_records", lambda: [])


def _write_audit(tmp_path, module, prefix, records):
    fp = tmp_path / f"{prefix}_2026-07.jsonl"
    with open(fp, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    module._DATA_DIR = tmp_path
    return fp


def _rec(job_id, charged, *, outcome="completed", ts="2026-07-10T10:00:00"):
    return {
        "ts": ts, "job_id": job_id, "outcome": outcome,
        "model_key": "m", "language": "en",
        "source_lang": "en", "target_lang": "it",
        "user_price_eur_charged": charged, "google_cost_eur_actual": 0.20,
    }


CASES = [
    ("gemini_cost_audit", "gemini_cost_audit", "/admin/api/gemini_cost_audit"),
    ("translation_cost_audit", "translation_cost_audit", "/admin/api/translation_cost_audit"),
    ("optimization_cost_audit", "optimization_cost_audit", "/admin/api/optimization_cost_audit"),
]


@pytest.mark.parametrize("mod_name,prefix,url", CASES)
def test_hide_zero_toglie_le_righe_senza_addebito(client, monkeypatch, tmp_path,
                                                  mod_name, prefix, url):
    import importlib
    module = importlib.import_module(mod_name)
    _write_audit(tmp_path, module, prefix, [
        _rec("pagato", 1.00),
        _rec("gratis", 0.0),
    ])
    _no_live(monkeypatch)
    h = {"X-Admin-Token": ADMIN_TOKEN}

    tutti = client.get(url, headers=h).get_json()
    assert {r["job_id"] for r in tutti["records"]} == {"pagato", "gratis"}
    assert tutti["count"] == 2

    solo_pagati = client.get(f"{url}?hide_zero=1", headers=h).get_json()
    assert [r["job_id"] for r in solo_pagati["records"]] == ["pagato"]
    assert solo_pagati["count"] == 1
    # Gli aggregati seguono il filtro: un solo job e un solo costo provider.
    agg = solo_pagati["aggregates"]
    assert agg["count"] == 1
    assert agg["revenue_eur"] == pytest.approx(1.00)
    assert round(agg["margin_eur"], 4) == pytest.approx(0.80)


@pytest.mark.parametrize("mod_name,prefix,url", CASES)
def test_hide_zero_tiene_i_rimborsati(client, monkeypatch, tmp_path,
                                      mod_name, prefix, url):
    """Rimborso = ricavo zero ma addebito avvenuto: resta una transazione."""
    import importlib
    module = importlib.import_module(mod_name)
    _write_audit(tmp_path, module, prefix, [
        _rec("rimborsato", 2.00, outcome="failed_refunded"),
        _rec("gratis", 0.0),
    ])
    _no_live(monkeypatch)

    d = client.get(f"{url}?hide_zero=1",
                   headers={"X-Admin-Token": ADMIN_TOKEN}).get_json()
    assert [r["job_id"] for r in d["records"]] == ["rimborsato"]
    assert d["records"][0]["_eff_revenue_eur"] == 0.0


def test_hide_zero_voci_campionate():
    """Tab «Voci campionate»: criterio sull'importo addebitato, non sul ricavo."""
    T = 1_786_000_000.0
    base = {"state": "ready", "lang": "it", "created_at": T - 600,
            "demo_cost": {"usd": 0.1, "gpu_seconds": 40.0, "jobs": 2}}
    recs = [
        dict(base, id="vc_pagata",
             payment={"type": "paypal", "amount_eur": 5.0, "paid_at": T}),
        dict(base, id="vc_omaggio",
             payment={"type": "free", "amount_eur": 0.0, "paid_at": T}),
        dict(base, id="vc_rimborsata", state="refunded",
             payment={"type": "paypal", "amount_eur": 5.0, "paid_at": T},
             refund={"amount_eur": 5.0, "reason": "test"}),
    ]

    tutte = vca.report(recs, state="paid")
    assert {r["id"] for r in tutte["records"]} == {"vc_pagata", "vc_omaggio", "vc_rimborsata"}

    solo_pagate = vca.report(recs, state="paid", hide_zero=True)
    ids = {r["id"] for r in solo_pagate["records"]}
    assert ids == {"vc_pagata", "vc_rimborsata"}, "la rimborsata resta: l'addebito c'e' stato"
    assert solo_pagate["count"] == 2
    assert solo_pagate["aggregates"]["count"] == 2
    assert solo_pagate["aggregates"]["charged_eur"] == pytest.approx(10.0)


def test_pagina_espone_il_filtro(client, monkeypatch):
    monkeypatch.setattr(app_mod, "_admin_auth_ok", lambda tok: tok == ADMIN_TOKEN)
    body = client.get("/admin/audit-premium",
                      headers={"X-Admin-Token": ADMIN_TOKEN}).get_data(as_text=True)
    assert 'id="hideZeroAmount"' in body
    # Il filtro viaggia al server su tutte e quattro le tab.
    assert body.count("applyHideZero(") >= 5
    assert 'hide_zero' in body
