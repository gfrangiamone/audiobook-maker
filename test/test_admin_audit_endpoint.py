"""Test /admin/api/gemini_cost_audit endpoint."""
import os
import json
import pytest
import routes_admin_audit
import gemini_cost_audit


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Set admin token directly on the loaded module (avoid reload, which
    # would mutate global state shared with other test modules).
    import audiobook_app
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


@pytest.fixture
def admin_headers():
    return {"X-Admin-Token": "test-admin-token"}


def test_admin_audit_endpoint_returns_records(client, admin_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    for i in range(3):
        gemini_cost_audit.append_record({
            "job_id": f"j{i}", "model_key": "flash31",
            "language": "it", "outcome": "completed",
            "user_price_eur_charged": 1.0,
            "google_cost_eur_actual": 0.5,
            "delta_pct": 2.0,
        })
    r = client.get("/admin/api/gemini_cost_audit?model=flash31&limit=10",
                   headers=admin_headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["count"] == 3
    assert d["aggregates"]["count"] == 3
    assert len(d["records"]) == 3


def test_admin_audit_requires_auth(client):
    r = client.get("/admin/api/gemini_cost_audit")
    # No token -> 401 (or 404 if admin disabled)
    assert r.status_code in (401, 403, 404)


def test_admin_audit_filter_by_outcome(client, admin_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    gemini_cost_audit.append_record({"job_id": "g1", "model_key": "flash31",
                                      "outcome": "completed", "language": "it"})
    gemini_cost_audit.append_record({"job_id": "g2", "model_key": "flash31",
                                      "outcome": "failed_refunded", "language": "it"})
    r = client.get("/admin/api/gemini_cost_audit?outcome=completed",
                   headers=admin_headers)
    d = r.get_json()
    assert d["count"] == 1
    assert d["records"][0]["job_id"] == "g1"


def test_admin_audit_pagination(client, admin_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    for i in range(5):
        gemini_cost_audit.append_record({"job_id": f"p{i}", "model_key": "flash31",
                                          "outcome": "completed", "language": "it"})
    r = client.get("/admin/api/gemini_cost_audit?limit=2&offset=1",
                   headers=admin_headers)
    d = r.get_json()
    assert d["count"] == 5  # total
    assert len(d["records"]) == 2  # page size


def test_admin_audit_live_rerun_row_visible(client, admin_headers, monkeypatch, tmp_path):
    """B2 (incidente jgIehwtzU2D6jog1S8f5vw, 2026-06): un job ri-lanciato dal
    recovery dopo un esito terminale persistito deve comparire come riga live
    `running` marcata `_rerun`, NON essere soppresso dalla dedup per job_id."""
    import audiobook_app
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    gemini_cost_audit.append_record({
        "job_id": "rr1", "model_key": "flash31",
        "outcome": "failed_quality_refunded", "language": "it",
        "user_price_eur_charged": 2.0, "google_cost_eur_actual": 0.4,
    })
    audiobook_app.jobs["rr1"] = {
        "status": "generating",
        "voice": "gemini:flash31:Puck",
        "rate": "+0%",
        "gemini_actual": {"chars": 100, "google_cost_eur": 0.01,
                          "audio_seconds": 5.0},
        "payment": {"total_eur": 2.0},
    }
    try:
        r = client.get("/admin/api/gemini_cost_audit", headers=admin_headers)
        assert r.status_code == 200
        d = r.get_json()
        by_outcome = {(rec["job_id"], rec["outcome"]) for rec in d["records"]}
        # Il record storico resta visibile...
        assert ("rr1", "failed_quality_refunded") in by_outcome
        # ...e la riga live del re-run e' presente e marcata
        live = [rec for rec in d["records"]
                if rec["job_id"] == "rr1" and rec["outcome"] == "running"]
        assert len(live) == 1
        assert live[0].get("_rerun") is True
        assert live[0].get("_live") is True
    finally:
        audiobook_app.jobs.pop("rr1", None)


def test_admin_audit_live_row_paypal_fee(client, admin_headers, monkeypatch, tmp_path):
    """La riga live porta il metodo di pagamento: un job PayPal in corso sconta
    la fee nel margine netto come il record persistito (prima restava 0 e il
    margine netto era uguale al margine), un job a voucher no."""
    import audiobook_app
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app.gemini_tts, "PAYPAL_PERCENT_FEE", 3.4)
    monkeypatch.setattr(audiobook_app.gemini_tts, "PAYPAL_FIXED_FEE_EUR", 0.35)
    base = {"status": "generating", "voice": "gemini:flash31:Puck", "rate": "+0%",
            "gemini_actual": {"chars": 100, "google_cost_eur": 0.19,
                              "audio_seconds": 5.0}}
    audiobook_app.jobs["Jlivepp"] = dict(base, payment={
        "total_eur": 6.54, "method": "paypal", "token": "ORDER1234567890"})
    audiobook_app.jobs["Jlivevc"] = dict(base, payment={
        "total_eur": 6.54, "method": "voucher", "token": "ABCD-EFGH-IJKL"})
    try:
        r = client.get("/admin/api/gemini_cost_audit", headers=admin_headers)
        assert r.status_code == 200
        live = {rec["job_id"]: rec for rec in r.get_json()["records"]
                if rec.get("_live")}
        pp, vc = live["Jlivepp"], live["Jlivevc"]
        assert pp["payment_method"] == "paypal"
        assert pp["_paypal_fee_eur"] == round(6.54 * 3.4 / 100 + 0.35, 4)
        assert pp["_net_margin_eur"] == round(6.54 - 0.19 - pp["_paypal_fee_eur"], 4)
        assert vc["payment_method"] == "voucher"
        assert vc["_paypal_fee_eur"] == 0
        assert vc["_net_margin_eur"] == round(6.54 - 0.19, 4)
    finally:
        audiobook_app.jobs.pop("Jlivepp", None)
        audiobook_app.jobs.pop("Jlivevc", None)


def test_running_gemini_row_uses_real_audio_seconds_not_cost_for_drift(monkeypatch):
    """Mirror di test_write_gemini_audit_drift_uses_real_audio_seconds_not_cost
    (generation_engine.py) per la riga LIVE del pannello: il listino dovuto
    si calcola sull'audio prodotto finora, mai sul costo del backend."""
    import audiobook_app
    captured = []

    def _fake_price(audio_seconds, model_key):
        captured.append(audio_seconds)
        return {"user_price_eur": round(audio_seconds / 3600 * 2.22, 2)}

    monkeypatch.setattr(audiobook_app.gemini_tts, "compute_user_price_eur", _fake_price)
    audiobook_app.jobs["Jliveposit"] = {
        "status": "generating",
        "voice": "gemini:flash31:Puck",
        "rate": "+0%",
        "gemini_actual": {"chars": 100, "google_cost_eur": 0.30,
                          "audio_seconds": 7200.0, "model_key": "flash31"},
        "payment": {"total_eur": 3.0},
    }
    try:
        recs = routes_admin_audit._synth_running_gemini_audit_records()
        rec = next(r for r in recs if r["job_id"] == "Jliveposit")
        assert captured == [7200.0]
        assert rec["google_cost_eur_actual"] == 0.30
        assert "pricing_cost_eur_actual" not in rec
        assert rec["margin_eur_actual"] == round(3.0 - 0.30, 4)
        assert rec["user_price_eur_should_have_been"] == 4.44
        assert rec["delta_eur"] == round(4.44 - 3.0, 4)
    finally:
        audiobook_app.jobs.pop("Jliveposit", None)


def test_running_gemini_row_language_is_tts_language_not_book_metadata(monkeypatch):
    """La riga LIVE deve riportare la lingua della GENERAZIONE TTS (voce scelta
    in UI, `gen_lang`/`opt_lang`), non `info.language` dei metadata del libro:
    altrimenti un libro con dc:language sporco ("c") o una voce in lingua
    diversa dal testo mostravano una lingua che cambiava a job concluso, quando
    subentra il record persistito scritto da `_audit_language`."""
    import audiobook_app

    class _Info:
        language = "c"

    audiobook_app.jobs["Jlivelang"] = {
        "status": "generating",
        "voice": "gemini:flash31:Puck",
        "rate": "+0%",
        "gen_lang": "de",
        "info": _Info(),
        "gemini_actual": {"chars": 10, "google_cost_eur": 0.1,
                          "audio_seconds": 1.0, "model_key": "flash31"},
    }
    try:
        recs = routes_admin_audit._synth_running_gemini_audit_records()
        rec = next(r for r in recs if r["job_id"] == "Jlivelang")
        assert rec["language"] == "de"
    finally:
        audiobook_app.jobs.pop("Jlivelang", None)


def test_admin_audit_aggregate_delta_pct_uses_listino_not_real_cost(
        client, admin_headers, monkeypatch, tmp_path):
    """L'endpoint /admin/api/gemini_cost_audit divide delta_pct_avg per il
    listino dovuto a consuntivo, non per il costo del backend (Cloudflare
    molto piu' economico del listino): altrimenti la cifra letta in un
    incidente vero sarebbe gonfiata."""
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    # Se il denominatore fosse il costo reale (0.20 totali) invece del
    # listino (3.20 totali), delta_pct_avg risulterebbe 100.0 invece di 6.25.
    gemini_cost_audit.append_record({
        "job_id": "cf1", "model_key": "flash31", "language": "it",
        "outcome": "completed", "user_price_eur_charged": 1.0,
        "user_price_eur_should_have_been": 1.10,
        "google_cost_eur_actual": 0.10, "delta_eur": 0.10,
    })
    gemini_cost_audit.append_record({
        "job_id": "cf2", "model_key": "flash31", "language": "it",
        "outcome": "completed", "user_price_eur_charged": 2.0,
        "user_price_eur_should_have_been": 2.10,
        "google_cost_eur_actual": 0.10, "delta_eur": 0.10,
    })
    r = client.get("/admin/api/gemini_cost_audit?model=flash31", headers=admin_headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    agg = r.get_json()["aggregates"]
    assert agg["count"] == 2
    assert agg["delta_pct_avg"] == pytest.approx(6.25, abs=0.01)
    # google_cost_eur (reale) resta usato per margin_eur/net_margin_eur.
    assert agg["google_cost_eur"] == pytest.approx(0.20, abs=0.001)
