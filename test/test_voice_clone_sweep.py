"""Ciclo di vita giornaliero della voce (spec §6.5, §10, §12)."""
import os
import time

import pytest

import community_store
import payment
import storage_backend
import voice_clone as vc
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT = "Ogni mattina apro la finestra prima di fare il caffe."
D = 86400


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    ev, rel, ref = [], [], []
    vc.set_hooks(notify=lambda e, rec, **x: ev.append((e, rec["id"], x)),
                 relaunch=rel.append, refund=lambda cid, reason: ref.append((cid, reason)))
    yield {"ev": ev, "rel": rel, "ref": ref}
    vc.set_hooks()
    voxcpm_catalog.invalidate_cache()


@pytest.fixture(autouse=True)
def pagamenti(tmp_path, monkeypatch):
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_pending_orders", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    yield


def _file(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"x")
    return str(p)


def voce(tmp_path, cid, state, now, email=None):
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="f", prompt_text=PROMPT,
                          sample_wav=_file(tmp_path, cid + "s.wav"),
                          original_path=_file(tmp_path, cid + "o.webm"), original_ext="webm",
                          metrics={}, ui_lang="it", now=now)
    if state == "sample_ok":
        return rec
    rec, _ = vc.commit(rec["id"], cid, email=email or cid + "@x.it", extra_id="m",
                       extra_text="e", common_text="c", payment_token="", price_eur=0.0, now=now)
    # "demo_failed" si raggiunge solo da "demos_generating" (TRANSITIONS):
    # fermarsi li' invece di proseguire fino a "ready".
    reach = "demos_generating" if state == "demo_failed" else state
    for s in ("demos_generating", "demos_ready", "ready"):
        if rec["state"] == reach:
            break
        rec = vc.transition(rec["id"], s, now=now)
    if state == "demo_failed":
        rec = vc.transition(rec["id"], "demo_failed",
                            {"demo": dict(rec["demo"], failed_at=now, first_failed_at=now, fail_count=1)},
                            now=now)
    return rec


def test_avviso_di_scadenza_una_volta_e_azzerato_dall_uso(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "ready", t0)
    vc.store().update(rec["id"], {"expires_at": t0 + 29 * D})
    out = vc.sweep(now=t0)
    assert out["warned"] == 1 and ambiente["ev"][-1][0] == "expiring"
    assert ambiente["ev"][-1][2]["days"] == 29
    assert vc.sweep(now=t0 + 60)["warned"] == 0
    vc.touch_used(rec["id"], now=t0 + 100)
    assert vc.get(rec["id"])["expiry_warned_at"] is None


def test_scadenza_rimuove_i_file_e_il_record_dopo_90_giorni(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "ready", t0)
    d = vc.voice_dir(rec["token"])
    t1 = t0 + vc.retention_sec() + 1
    out = vc.sweep(now=t1)
    assert out["expired"] == 1 and not os.path.isdir(d)
    assert vc.get(rec["id"])["state"] == "expired" and ambiente["ev"][-1][0] == "expired"
    assert vc.sweep(now=t1 + 89 * D)["purged"] == 0
    assert vc.sweep(now=t1 + 91 * D)["purged"] == 1 and vc.get(rec["id"]) is None


def test_bozze_stantie_purgate_dal_sweep(tmp_path):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "sample_ok", t0)
    assert vc.sweep(now=t0 + vc.sample_ttl_sec() + 1)["drafts_purged"] == 1
    assert vc.get(rec["id"]) is None


def test_demo_failed_rilancia_ogni_6h_e_rimborsa_a_7_giorni(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "demo_failed", t0)
    assert vc.sweep(now=t0 + 3600)["relaunched"] == 0
    assert vc.sweep(now=t0 + 6 * 3600 + 1)["relaunched"] == 1 and ambiente["rel"] == [rec["id"]]
    # il rilancio (finto) non ha cambiato stato: dopo altre 6 h rilancia di nuovo
    vc.store().update(rec["id"], {"demo": dict(vc.get(rec["id"])["demo"], failed_at=t0 + 6 * 3600 + 1)})
    assert vc.sweep(now=t0 + 12 * 3600 + 5)["relaunched"] == 1
    out = vc.sweep(now=t0 + 7 * D + 1)
    assert out["refunded"] == 1 and ambiente["ref"] == [(rec["id"], "demo_failed_timeout")]


def test_promemoria_di_approvazione_e_rimborso_a_30_giorni(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "demos_ready", t0)
    assert vc.sweep(now=t0 + 3600)["reminded"] == 0
    assert vc.sweep(now=t0 + D + 1)["reminded"] == 1
    assert ambiente["ev"][-1] == ("approval_reminder", rec["id"], {"stage": 1})
    assert vc.sweep(now=t0 + 2 * D)["reminded"] == 0
    assert vc.sweep(now=t0 + 7 * D + 1)["reminded"] == 1
    assert ambiente["ev"][-1][2]["stage"] == 2
    assert vc.get(rec["id"])["demo"]["reminders"] == [1, 2]
    assert vc.sweep(now=t0 + 30 * D + 1)["refunded"] == 1
    assert ambiente["ref"] == [(rec["id"], "no_approval")]


def test_paid_fermo_oltre_un_ora_rilancia(tmp_path, ambiente):
    """I1: un record fermo in `paid`/`demos_generating` senza cambio di stato
    oltre STALE_INFLIGHT_SEC e' quasi sempre un thread morto (crash/riavvio):
    va rilanciato come per demo_failed."""
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "paid", t0)
    assert vc.sweep(now=t0 + 1800)["relaunched"] == 0
    out = vc.sweep(now=t0 + vc.STALE_INFLIGHT_SEC + 1)
    assert out["relaunched"] == 1 and ambiente["rel"] == [rec["id"]]


def test_demos_generating_fermo_oltre_un_ora_rilancia(tmp_path, ambiente):
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "paid", t0)
    rec = vc.transition(rec["id"], "demos_generating", now=t0 + 5)
    out = vc.sweep(now=t0 + 5 + vc.STALE_INFLIGHT_SEC + 1)
    assert out["relaunched"] == 1 and ambiente["rel"] == [rec["id"]]


def test_hook_fallito_non_logga_il_messaggio_dell_eccezione(tmp_path, capsys):
    """m3: un hook (qui notify) puo' incapsulare un errore SMTP col testo
    dell'email del destinatario: nel log deve comparire solo il tipo
    dell'eccezione, mai str(e)."""
    def notify_fallace(ev, rec, **x):
        raise RuntimeError("SMTP error sending to owner@example.com")
    vc.set_hooks(notify=notify_fallace)
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "ready", t0)
    vc.store().update(rec["id"], {"expires_at": t0 + 29 * D})
    vc.sweep(now=t0)
    out = capsys.readouterr().out
    assert "owner@example.com" not in out
    assert "RuntimeError" in out


def test_sweep_non_si_ferma_su_un_record_rotto(tmp_path, monkeypatch):
    t0 = 1_000_000
    a = voce(tmp_path, "a", "ready", t0)
    b = voce(tmp_path, "b", "ready", t0)
    vc.store().update(a["id"], {"expires_at": "rotto"})
    t1 = t0 + vc.retention_sec() + 1
    out = vc.sweep(now=t1)
    assert out["expired"] == 1 and vc.get(b["id"])["state"] == "expired"


def _capture(order_id, job_id, captured_at, amount=5.0, email="p@x.it", used=False):
    payment._payments[order_id] = {"order_id": order_id, "amount_eur": amount, "email": email,
                                   "captured_at": captured_at, "used": used, "job_id": job_id}


def test_bozza_rimpiazzata_rimborsa_il_capture_del_draft_precedente(tmp_path):
    """C1 item 2 (create_draft): la bozza rimpiazzata puo' avere un capture
    gia' incassato (creato prima di commit()) che non verra' mai consumato."""
    t0 = 1_000_000
    prima = voce(tmp_path, "a", "sample_ok", t0)
    _capture("ORDD1", "vc:" + prima["id"], t0)
    seconda = voce(tmp_path, "a", "sample_ok", t0 + 10)
    assert vc.get(prima["id"]) is None and vc.get(seconda["id"]) is not None
    assert payment._payments["ORDD1"]["used"] is True


def test_bozza_scaduta_purgata_rimborsa_il_capture(tmp_path):
    """C1 item 2 (purge_stale_drafts)."""
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "sample_ok", t0)
    _capture("ORDD2", "vc:" + rec["id"], t0)
    assert vc.sweep(now=t0 + vc.sample_ttl_sec() + 1)["drafts_purged"] == 1
    assert payment._payments["ORDD2"]["used"] is True


def test_transizione_terminale_rimborsa_il_capture(tmp_path, ambiente):
    """C1 item 3: ogni transizione verso uno stato terminale rimborsa i
    capture non consumati di quella voce (qui: scadenza -> expired)."""
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "ready", t0)
    _capture("ORDD3", "vc:" + rec["id"], t0)
    t1 = t0 + vc.retention_sec() + 1
    out = vc.sweep(now=t1)
    assert out["expired"] == 1
    assert payment._payments["ORDD3"]["used"] is True


def test_sweep_rimborsa_capture_vc_orfano_su_voce_sparita(tmp_path):
    """C1 item 4 (safety net): un capture `vc:` la cui voce non esiste piu'
    viene rimborsato dal giro di riconciliazione a fine sweep."""
    t0 = 1_000_000
    _capture("ORDD4", "vc:non_esiste", t0)
    vc.sweep(now=t0 + vc.sample_ttl_sec() + 1)
    assert payment._payments["ORDD4"]["used"] is True


def test_sweep_non_rimborsa_capture_su_voce_viva_solo_logga(tmp_path, capsys):
    """C1 item 4: un capture non consumato su una voce ANCORA VIVA (paid/demos_*
    /ready) e' impossibile per costruzione (commit consuma prima di scrivere):
    se accade comunque, va solo loggato (id pubblico, mai token/email), MAI
    rimborsato d'ufficio."""
    t0 = 1_000_000
    rec = voce(tmp_path, "a", "demos_ready", t0)
    _capture("ORDD5", "vc:" + rec["id"], t0)
    vc.sweep(now=t0 + vc.sample_ttl_sec() + 1)
    assert payment._payments["ORDD5"]["used"] is False
    out = capsys.readouterr().out
    assert "ORPHAN capture" in out and rec["id"] in out and "p@x.it" not in out


def test_digest_data_conta_nella_finestra(tmp_path):
    t0 = 1_000_000
    voce(tmp_path, "a", "ready", t0)
    voce(tmp_path, "b", "demo_failed", t0)
    c = voce(tmp_path, "c", "demos_ready", t0)
    vc.transition(c["id"], "refunded", {"refund": {"reason": "user_rejected"}}, now=t0)
    d = vc.digest_data(window_hours=24, now=t0 + 3600)
    labels = {r["label"]: r["count"] for r in d["rows"]}
    assert labels["paid"] == 3 and labels["ready"] == 1 and labels["demo_failed"] == 1
    assert labels["refunded:user_rejected"] == 1 and d["active_ready"] == 1
    assert vc.digest_data(window_hours=24, now=t0 + 3 * D)["rows"] == [
        {"label": "demo_failed", "count": 1}]
