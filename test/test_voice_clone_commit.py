"""commit della voce: pagamento, email unica, idempotenza (spec §3.4, §7.2, §10)."""
import os
import threading

import pytest

import community_store
import payment
import storage_backend
import voice_clone as vc
import voxcpm_catalog

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
PROMPT = "Ogni mattina apro la finestra prima di fare il caffe."


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "VOUCHER_BONUS_PERCENT", 10)
    yield
    voxcpm_catalog.invalidate_cache()


def _file(tmp_path, name, content=b"RIFF-finto"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def bozza(tmp_path, cid="cid-uno", **kw):
    args = dict(lang="it", locale="it-IT", gender="f", prompt_text=PROMPT,
                sample_wav=_file(tmp_path, f"{cid}-s.wav"),
                original_path=_file(tmp_path, f"{cid}-o.webm", b"webm"),
                original_ext="webm", metrics={"duration": 16.4, "snr_db": 31.2},
                ui_lang="it")
    args.update(kw)
    return vc.create_draft(cid, **args)


def _commit(rec, cid="cid-uno", **kw):
    args = dict(email="Utente@Example.com", extra_id="memory", extra_text="Frase extra.",
                common_text="Frase comune.", payment_token="", price_eur=0.0)
    args.update(kw)
    return vc.commit(rec["id"], cid, **args)


def test_env_helpers(monkeypatch):
    monkeypatch.delenv("ABM_VOICE_CLONE_ENABLED", raising=False)
    assert vc.enabled() is True
    monkeypatch.setenv("ABM_VOICE_CLONE_ENABLED", "0")
    assert vc.enabled() is False
    monkeypatch.setenv("ABM_VOICE_CLONE_ENABLED", "false")
    assert vc.enabled() is False
    for nome in ("ABM_VOICE_CLONE_REGEN_MAX", "ABM_VOICE_CLONE_DEMO_RETRIES", "ABM_VOICE_CLONE_MAX_UPLOAD_MB"):
        monkeypatch.delenv(nome, raising=False)
    assert vc.regen_max() == 3 and vc.demo_retries() == 3 and vc.max_upload_mb() == 20
    monkeypatch.setenv("ABM_VOICE_CLONE_REGEN_MAX", "1")
    assert vc.regen_max() == 1
    assert vc.DEMO_NAMES == ("demo_common.wav", "demo_extra.wav")


def test_commit_gratis_crea_la_voce_paid(tmp_path):
    rec = bozza(tmp_path)
    out, created = _commit(rec, now=1_000_000)
    assert created is True and out["state"] == "paid"
    assert out["owner_email"] == "utente@example.com"
    assert out["owner_email_hash"] == vc.email_hash("utente@example.com")
    assert out["payment"] == {"type": "free", "token": "", "amount_eur": 0.0, "paid_at": 1_000_000}
    assert out["demo"] == {"common_text": "Frase comune.", "extra_id": "memory",
                           "extra_text": "Frase extra.", "regen_used": 0,
                           "regen_max": 3, "runpod_job_id": None}
    assert out["paid_at"] == 1_000_000
    assert out["resume_token"]["expires_at"] == 1_000_000 + vc.RESUME_TOKEN_DAYS * 86400
    assert out["resume_token"]["value"] == rec["resume_token"]["value"]


def test_commit_consuma_il_voucher_e_scrive_il_pagamento(tmp_path):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    rec = bozza(tmp_path)
    out, created = _commit(rec, payment_token=code, price_eur=5.0)
    assert created and out["payment"]["type"] == "voucher"
    assert out["payment"]["token"] == code and out["payment"]["amount_eur"] == 5.0
    assert payment._voucher_remaining(payment._vouchers[code]) == pytest.approx(0.5, abs=0.01)
    assert payment._is_paid_job_done("vc:" + rec["id"])


def test_commit_pagamento_invalido_lascia_la_bozza(tmp_path):
    """m4: consume_payment_token che fallisce solleva vc.PaymentInvalid, non
    un ValueError generico, cosi' il chiamante puo' distinguerlo da
    EmailHasVoice/BadTransition/VoiceGone (anch'essi ValueError)."""
    rec = bozza(tmp_path)
    with pytest.raises(vc.PaymentInvalid):
        _commit(rec, payment_token="NOPE", price_eur=5.0)
    assert vc.get(rec["id"])["state"] == "sample_ok"


def test_commit_rilascia_il_pagamento_se_la_scrittura_fallisce(tmp_path, monkeypatch):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    rec = bozza(tmp_path)

    def esplode(*a, **k):
        raise OSError("disco pieno")
    monkeypatch.setattr(vc, "transition", esplode)
    with pytest.raises(OSError):
        _commit(rec, payment_token=code, price_eur=5.0)
    assert payment._voucher_remaining(payment._vouchers[code]) == pytest.approx(5.5, abs=0.01)


def test_commit_doppio_click_ritorna_la_stessa_voce(tmp_path):
    rec = bozza(tmp_path)
    a, c1 = _commit(rec)
    b, c2 = _commit(rec)
    assert c1 is True and c2 is False and a["id"] == b["id"] and b["state"] == "paid"


def test_commit_rifiuta_cid_estraneo(tmp_path):
    rec = bozza(tmp_path)
    with pytest.raises(PermissionError):
        _commit(rec, cid="altro")


def test_email_unica_fra_voci_vive(tmp_path):
    r1 = bozza(tmp_path, cid="cid-uno")
    _commit(r1)
    r2 = bozza(tmp_path, cid="cid-due")
    with pytest.raises(vc.EmailHasVoice):
        _commit(r2, cid="cid-due", email="utente@example.com")
    assert vc.get(r2["id"])["state"] == "sample_ok"
    assert vc.email_has_active_voice("UTENTE@example.com") is True
    assert vc.email_has_active_voice("utente@example.com", exclude_id=r1["id"]) is False
    # una voce rimborsata libera l'email
    vc.transition(r1["id"], "refunded")
    out, created = _commit(r2, cid="cid-due", email="utente@example.com")
    assert created and out["state"] == "paid"


def test_email_unica_sotto_concorrenza(tmp_path):
    recs = [bozza(tmp_path, cid=f"cid-{i}") for i in range(6)]
    esiti = []

    def prova(i):
        try:
            vc.commit(recs[i]["id"], f"cid-{i}", email="same@example.com", extra_id="m",
                      extra_text="x", common_text="c", payment_token="", price_eur=0.0)
            esiti.append("ok")
        except vc.EmailHasVoice:
            esiti.append("dup")
    th = [threading.Thread(target=prova, args=(i,)) for i in range(6)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    assert esiti.count("ok") == 1 and esiti.count("dup") == 5


def test_mine_espone_demo_urls_e_codice_solo_al_proprietario(tmp_path):
    rec = bozza(tmp_path)
    _commit(rec)
    for s in ("demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    mio = vc.mine("cid-uno")[0]
    assert mio["demo_urls"] == {"common": f"/api/voice_clone/{rec['id']}/demo/common",
                                "extra": f"/api/voice_clone/{rec['id']}/demo/extra"}
    assert mio["voice_code"] == rec["voice_code"] and mio["owner"] is True
    vc.store().update(rec["id"], {"devices": rec["devices"] + [{"cid": "cid-due", "added_at": 1, "via": "code"}]})
    altro = vc.mine("cid-due")[0]
    assert altro["owner"] is False and "voice_code" not in altro
    assert "owner_email" not in altro and "token" not in altro
