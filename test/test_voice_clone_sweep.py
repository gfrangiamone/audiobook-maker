"""Ciclo di vita giornaliero della voce (spec §6.5, §10, §12)."""
import os

import pytest

import community_store
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


def test_sweep_non_si_ferma_su_un_record_rotto(tmp_path, monkeypatch):
    t0 = 1_000_000
    a = voce(tmp_path, "a", "ready", t0)
    b = voce(tmp_path, "b", "ready", t0)
    vc.store().update(a["id"], {"expires_at": "rotto"})
    t1 = t0 + vc.retention_sec() + 1
    out = vc.sweep(now=t1)
    assert out["expired"] == 1 and vc.get(b["id"])["state"] == "expired"


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
