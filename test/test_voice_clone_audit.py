"""Tab admin «Voci campionate» di /admin/audit-premium: righe, filtri,
aggregati, tracciamento del costo delle demo e dei libri generati."""
import json
import os
import shutil

import pytest

import audiobook_app
import community_store
import gemini_cost_audit
import generation_engine
import payment
import storage_backend
import voice_clone as vc
import voice_clone_audit as vca
import voice_clone_demo as vcd
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
GIORNO = 86400
T_AGO = 1_786_000_000.0      # 2026-08-06 UTC circa


def _rec(**kw):
    base = {
        "id": "vc_uno", "state": "ready", "name": "Anna", "lang": "it", "locale": "it-IT",
        "gender": "f", "owner_email": "anna@example.com", "created_at": T_AGO - 600,
        "payment": {"type": "paypal", "token": "segreto-pagamento", "amount_eur": 5.0,
                    "paid_at": T_AGO},
        "demo": {"extra_id": "memory", "fail_count": 1},
        "demo_cost": {"usd": 0.1, "gpu_seconds": 40.0, "jobs": 2},
        "devices": [{"cid": "c1", "name": "Telefono"}, {"cid": "c2", "name": "PC"}],
        "books": ["j1", "j2", "j3"],
        "ready_at": T_AGO + 300, "expires_at": T_AGO + 180 * GIORNO,
        "token": "f" * 32,
    }
    base.update(kw)
    return base


def _fee(rev, method):
    return 0.5 if method == "paypal" else 0.0


# ------------------------------------------------------------- funzioni pure
def test_riga_con_incasso_costo_e_margini():
    r = vca.row(_rec(), usd_eur=0.9, fee_fn=_fee)
    assert r["revenue_eur"] == 5.0 and r["gpu_cost_eur"] == 0.09
    assert r["margin_eur"] == 4.91 and r["paypal_fee_eur"] == 0.5 and r["net_margin_eur"] == 4.41
    assert r["devices"] == 2 and r["device_names"] == ["Telefono", "PC"] and r["books"] == 3
    assert r["ready_at"] == T_AGO + 300 and r["expires_at"] == T_AGO + 180 * GIORNO
    # niente segreti nella riga
    testo = json.dumps(r)
    assert "f" * 32 not in testo and "segreto-pagamento" not in testo


def test_voce_rimborsata_non_ha_ricavo_ma_tiene_il_costo():
    r = vca.row(_rec(state="refunded", refund={"reason": "user_rejected", "amount_eur": 5.0}),
                usd_eur=1.0, fee_fn=_fee)
    assert r["revenue_eur"] == 0 and r["refund_eur"] == 5.0 and r["paypal_fee_eur"] == 0
    assert r["net_margin_eur"] == -0.1 and r["charged_eur"] == 5.0


def test_filtri_di_stato_bozze_escluse_di_default():
    bozza = _rec(id="vc_bozza", state="sample_ok", payment=None, created_at=T_AGO)
    pagata = _rec()
    scaduta = _rec(id="vc_scad", state="expired")
    demo = _rec(id="vc_demo", state="demos_ready")
    tutte = [bozza, pagata, scaduta, demo]
    ids = lambda st: {r["id"] for r in vca.select(tutte, state=st)}
    assert ids(None) == {"vc_uno", "vc_scad", "vc_demo"}
    assert ids("drafts") == {"vc_bozza"}
    assert ids("all") == {"vc_bozza", "vc_uno", "vc_scad", "vc_demo"}
    assert ids("ready") == {"vc_uno"} and ids("demos") == {"vc_demo"}
    assert ids("expired") == {"vc_scad"}
    # una bozza scartata finisce `deleted` ma resta una bozza
    scartata = _rec(id="vc_scart", state="deleted", payment=None)
    assert {r["id"] for r in vca.select([scartata], state="deleted")} == set()


def test_periodo_sulla_data_di_pagamento_e_creazione_per_le_bozze():
    giorno = vca._day(T_AGO)
    vecchia = _rec(id="vc_old", created_at=T_AGO - 40 * GIORNO,
                   payment={"type": "free", "amount_eur": 0, "paid_at": T_AGO - 30 * GIORNO})
    creata_prima = _rec(id="vc_prima", created_at=T_AGO - 40 * GIORNO)
    bozza = _rec(id="vc_bozza", state="sample_ok", payment=None, created_at=T_AGO)
    sel = vca.select([vecchia, creata_prima, bozza], state="all", date_from=giorno, date_to=giorno)
    assert {r["id"] for r in sel} == {"vc_bozza", "vc_prima"}


def test_report_aggrega_e_pagina():
    recs = [_rec(id=f"vc_{i}", payment={"type": "voucher", "amount_eur": 5.0,
                                        "paid_at": T_AGO + i}) for i in range(3)]
    out = vca.report(recs, usd_eur=1.0, fee_fn=_fee, limit=2)
    a = out["aggregates"]
    assert out["count"] == 3 and len(out["records"]) == 2
    assert out["records"][0]["id"] == "vc_2"
    assert a["revenue_eur"] == 15.0 and a["gpu_cost_eur"] == 0.3 and a["paypal_fees_eur"] == 0
    assert a["net_margin_eur"] == 14.7 and a["books"] == 9 and a["devices"] == 6
    assert out["languages"] == ["it"]


# ------------------------------------------------- tracciamento sulla voce
@pytest.fixture
def negozio(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(vcd, "pcm_to_wav48", lambda p, w: shutil.move(p, w))
    yield tmp_path
    voxcpm_catalog.invalidate_cache()


def _voce(tmp_path, cid="cid-uno", email="u@example.com"):
    s = tmp_path / f"{cid}-s.wav"
    s.write_bytes(b"RIFF")
    o = tmp_path / f"{cid}-o.webm"
    o.write_bytes(b"webm")
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="f",
                          prompt_text="Ogni mattina apro la finestra.",
                          sample_wav=str(s), original_path=str(o), original_ext="webm",
                          metrics={"duration": 16.0}, ui_lang="it")
    out, _ = vc.commit(rec["id"], cid, email=email, extra_id="memory",
                       extra_text="Frase extra.", common_text="Frase comune.",
                       payment_token="", price_eur=0.0)
    return out


def test_costo_demo_e_libri_si_accumulano_e_restano_privati(negozio):
    rec = _voce(negozio)
    vc.add_demo_cost(rec["id"], 0.01, 5.0, 1)
    vc.add_demo_cost(rec["id"], 0.02, 7.5, 2)
    vc.add_demo_cost(rec["id"], 0, 0, 0)
    vc.note_book(rec["id"], "job-a")
    vc.note_book(rec["id"], "job-a")
    vc.note_book(rec["id"], "job-b")
    cur = vc.get(rec["id"])
    assert cur["demo_cost"] == {"usd": 0.03, "gpu_seconds": 12.5, "jobs": 3}
    assert cur["books"] == ["job-a", "job-b"]
    pub = vc.public_view(cur)
    assert "demo_cost" not in pub and "books" not in pub
    assert vc.clone_id_of(vc.voice_id_of(cur)) == rec["id"]
    assert vc.clone_id_of("voxcpm:mine:" + "0" * 32) is None


def test_generate_demos_registra_il_costo_gpu(negozio, monkeypatch):
    rec = _voce(negozio)

    def worker(chunks, voice_id, dest_path, **kw):
        with open(dest_path, "wb") as f:
            f.write(b"\x01\x02" * 50)
        return {"runpod": [{"exec_s": 10.0, "queue_s": 1.0, "worker": "w", "gpu": "x"}]}

    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", worker)
    monkeypatch.setattr(voxcpm_tts, "gpu_cost_usd",
                        lambda rows: {"cost_usd": 0.004 * len(rows), "gpu_seconds": 10.0 * len(rows),
                                      "jobs": len(rows)})
    assert vcd.generate_demos(rec["id"], sleep=lambda s: None)[0] == "ok"
    assert vc.get(rec["id"])["demo_cost"] == {"usd": 0.008, "gpu_seconds": 20.0, "jobs": 2}


def test_audit_voxcpm_con_voce_campionata_scrive_l_id_e_conta_il_libro(negozio, monkeypatch):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", negozio)
    monkeypatch.setenv("ABM_DATA_DIR", str(negozio))
    rec = _voce(negozio)
    voice_id = vc.voice_id_of(rec)
    job = {"voxcpm_actual": {"chars": 1000, "audio_seconds": 60.0, "tts_seconds": 5.0},
           "payment": {"total_eur": 1.0, "method": "voucher", "token": "t"}, "rate": "+0%"}
    generation_engine._write_voxcpm_audit("job-x", job, voice_id, "it", "completed")
    generation_engine._write_voxcpm_audit("job-x", job, voice_id, "it", "completed")
    generation_engine._write_voxcpm_audit("job-y", job, voice_id, "it", "failed_refunded")
    righe = []
    for fp in sorted(negozio.glob("gemini_cost_audit_*.jsonl")):
        righe.extend(json.loads(r) for r in open(fp, encoding="utf-8") if r.strip())
    assert righe and all(r["voice_clone_id"] == rec["id"] for r in righe)
    assert all(rec["token"] not in json.dumps(r) for r in righe)
    assert vc.get(rec["id"])["books"] == ["job-x"]


# ------------------------------------------------------------ endpoint/pagina
@pytest.fixture
def admin(negozio, monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "segreto-admin")
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


def test_endpoint_richiede_admin(admin):
    assert admin.get("/admin/api/voice_clone_audit").status_code == 401


def test_endpoint_restituisce_le_voci(admin, negozio, monkeypatch):
    rec = _voce(negozio)
    vc.add_demo_cost(rec["id"], 0.05, 20.0, 2)
    vc.note_book(rec["id"], "job-1")
    _voce(negozio, cid="cid-due", email="due@example.com")   # pagata anche lei
    s = negozio / "bozza.wav"
    s.write_bytes(b"RIFF")
    o = negozio / "bozza.webm"
    o.write_bytes(b"webm")
    vc.create_draft("cid-tre", lang="it", locale="it-IT", gender="m", prompt_text="x",
                    sample_wav=str(s), original_path=str(o), original_ext="webm",
                    metrics={"duration": 16.0}, ui_lang="it")
    monkeypatch.setattr(audiobook_app.speechify_tts, "usd_eur_rate", lambda: 1.0)
    h = {"X-Admin-Token": "segreto-admin"}
    d = admin.get("/admin/api/voice_clone_audit", headers=h).get_json()
    assert d["count"] == 2
    riga = next(r for r in d["records"] if r["id"] == rec["id"])
    assert riga["gpu_cost_eur"] == 0.05 and riga["books"] == 1 and riga["devices"] == 1
    assert d["aggregates"]["net_margin_eur"] == -0.05
    assert rec["token"] not in json.dumps(d)
    assert admin.get("/admin/api/voice_clone_audit?state=drafts", headers=h).get_json()["count"] == 1
    assert admin.get("/admin/api/voice_clone_audit?state=all", headers=h).get_json()["count"] == 3
    assert admin.get("/admin/api/voice_clone_audit?date_from=2000-01-01&date_to=2000-01-02",
                     headers=h).get_json()["count"] == 0


def test_pagina_ha_la_tab_e_alimenta_il_margine_totale(admin):
    body = admin.get("/admin/audit-premium",
                     headers={"X-Admin-Token": "segreto-admin"}).get_data(as_text=True)
    assert 'data-tab="voices"' in body and 'id="tab_voices"' in body
    assert "voices: null" in body and "netMarginByService.voices]" in body
    assert "netMarginByService.voices = Number(a.net_margin_eur)" in body
    assert '"optDateFrom","vcaDateFrom"' in body and '"optDateTo","vcaDateTo"' in body
    assert '_h === "#tab-voices"' in body and "window._vcaLoaded = true;\n  vcaFetch();" in body
    assert 'value="drafts"' in body and body.index('value="paid"') < body.index('value="drafts"')
