"""Demo, approvazione, rigenerazione, rifiuto (spec §3.5, §5.5, §7.4, §10)."""
import os
import shutil

import pytest

import community_store
import payment
import storage_backend
import voice_clone as vc
import voice_clone_demo as vcd
import voxcpm_catalog
import voxcpm_tts

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
    # niente ffmpeg nei test: il "wav" e' il pcm rinominato
    monkeypatch.setattr(vcd, "pcm_to_wav48", lambda p, w: shutil.move(p, w))
    eventi = []
    vcd.configure(notifier=lambda ev, rec, **extra: eventi.append((ev, rec["id"], extra)))
    yield eventi
    vcd.configure(notifier=None)
    voxcpm_catalog.invalidate_cache()


def _file(tmp_path, name, content=b"RIFF-finto"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def voce_pagata(tmp_path, cid="cid-uno", price=0.0, token="", email="u@example.com"):
    rec = vc.create_draft(cid, lang="it", locale="it-IT", gender="f", prompt_text=PROMPT,
                          sample_wav=_file(tmp_path, f"{cid}-s.wav"),
                          original_path=_file(tmp_path, f"{cid}-o.webm", b"webm"),
                          original_ext="webm", metrics={"duration": 16.4}, ui_lang="it")
    out, _ = vc.commit(rec["id"], cid, email=email, extra_id="memory", extra_text="Frase extra.",
                       common_text="Frase comune.", payment_token=token, price_eur=price)
    return out


class WorkerFinto:
    """Doppio di voxcpm_tts.synthesize_chapter: un copione di esiti per chiamata."""

    def __init__(self, *esiti):
        self.esiti = list(esiti)
        self.chiamate = []

    def __call__(self, chunks, voice_id, dest_path, **kw):
        self.chiamate.append((list(chunks), voice_id, kw.get("key", "")))
        e = self.esiti.pop(0) if self.esiti else "ok"
        if isinstance(e, Exception):
            raise e
        with open(dest_path, "wb") as f:
            f.write(b"\x01\x02" * 100)
        return {"bytes": 200}


def test_generate_demos_produce_i_due_file_con_due_job_da_un_chunk(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    w = WorkerFinto()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", w)
    esito, _ = vcd.generate_demos(rec["id"], sleep=lambda s: None)
    assert esito == "ok"
    d = vc.voice_dir(rec["token"])
    assert sorted(f for f in os.listdir(d) if f.startswith("demo")) == ["demo_common.wav", "demo_extra.wav"]
    assert [c[0] for c in w.chiamate] == [["Frase comune."], ["Frase extra."]]
    assert all(c[1] == vc.voice_id_of(rec) and c[2] == "" for c in w.chiamate)
    assert vc.get(rec["id"])["demo"]["runpod_job_id"] is None


def test_generate_demos_salta_le_demo_gia_presenti(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    open(os.path.join(vc.voice_dir(rec["token"]), "demo_common.wav"), "wb").write(b"x")
    w = WorkerFinto()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", w)
    assert vcd.generate_demos(rec["id"], sleep=lambda s: None)[0] == "ok"
    assert [c[0] for c in w.chiamate] == [["Frase extra."]]


def test_generate_demos_ritenta_e_poi_fallisce(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_DEMO_RETRIES", "2")
    rec = voce_pagata(tmp_path)
    w = WorkerFinto(voxcpm_tts.VoxcpmJobError("boom 1"), voxcpm_tts.VoxcpmJobError("boom 2"))
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", w)
    pause = []
    esito, dettaglio = vcd.generate_demos(rec["id"], sleep=pause.append)
    assert esito == "failed" and "boom 2" in dettaglio
    assert len(w.chiamate) == 2 and pause == [1]


def test_generate_demos_riconosce_il_campione_inutilizzabile(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    w = WorkerFinto(voxcpm_tts.VoxcpmJobError("prompt audio rejected by worker"))
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", w)
    assert vcd.generate_demos(rec["id"], sleep=lambda s: None)[0] == "unusable"
    assert len(w.chiamate) == 1


def test_start_demos_inline_porta_a_demos_ready_e_notifica(tmp_path, monkeypatch, ambiente):
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    out = vcd.start_demos(rec["id"], background=False)
    assert out["state"] == "demos_ready" and out.get("demos_ready_at")
    assert ambiente[-1][0] == "demos_ready"


def test_start_demos_fallito_va_in_demo_failed(tmp_path, monkeypatch, ambiente):
    monkeypatch.setenv("ABM_VOICE_CLONE_DEMO_RETRIES", "1")
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto(voxcpm_tts.VoxcpmJobError("giu")))
    out = vcd.start_demos(rec["id"], background=False)
    assert out["state"] == "demo_failed"
    assert out["demo"]["fail_count"] == 1 and out["demo"]["failed_at"]
    assert "giu" in out["demo"]["last_error"]
    assert ambiente[-1][0] == "demo_failed"
    # retry: torna a generare, senza consumare rigenerazioni
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    out = vcd.retry(rec["id"], "cid-uno", background=False)
    assert out["state"] == "demos_ready" and out["demo"]["regen_used"] == 0


def test_campione_inutilizzabile_rimborsa_subito_con_bonus(tmp_path, monkeypatch, ambiente):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    rec = voce_pagata(tmp_path, price=5.0, token=code)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter",
                        WorkerFinto(voxcpm_tts.VoxcpmJobError("campione non utilizzabile")))
    out = vcd.start_demos(rec["id"], background=False)
    assert out["state"] == "refunded" and out["refund"]["reason"] == "sample_unusable"
    assert payment._voucher_remaining(payment._vouchers[code]) == pytest.approx(5.5, abs=0.01)
    assert ambiente[-1][0] == "refunded" and ambiente[-1][2]["reason"] == "sample_unusable"
    assert not os.path.isdir(vc.voice_dir(rec["token"]))


def test_approve_carica_su_r2_e_pulisce_i_tentativi(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    vcd.start_demos(rec["id"], background=False)
    d = vc.voice_dir(rec["token"])
    open(os.path.join(d, "demo_try_0_common.wav"), "wb").write(b"x")
    caricati = []
    monkeypatch.setattr(vc, "upload_to_r2", lambda r, name: caricati.append(name) or True)
    with pytest.raises(PermissionError):
        vcd.approve(rec["id"], "cid-estraneo")
    out = vcd.approve(rec["id"], "cid-uno", now=5_000_000)
    assert out["state"] == "ready" and out["ready_at"] == 5_000_000
    assert out["expires_at"] == 5_000_000 + vc.retention_sec()
    assert out["last_used_at"] == 5_000_000
    assert sorted(caricati) == ["demo_common.wav", "demo_extra.wav", "original.webm", "sample.wav"]
    assert not [f for f in os.listdir(d) if f.startswith("demo_try_")]
    with pytest.raises(vc.BadTransition):
        vcd.approve(rec["id"], "cid-uno")


def test_regenerate_rispetta_il_massimo_e_archivia_i_tentativi(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_REGEN_MAX", "1")
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    vcd.start_demos(rec["id"], background=False)
    out = vcd.regenerate(rec["id"], "cid-uno", extra_id="quote", extra_text="Altra frase.",
                         background=False)
    assert out["state"] == "demos_ready"
    assert out["demo"]["regen_used"] == 1 and out["demo"]["extra_id"] == "quote"
    d = vc.voice_dir(rec["token"])
    assert os.path.exists(os.path.join(d, "demo_try_0_common.wav"))
    assert os.path.exists(os.path.join(d, "demo_try_0_extra.wav"))
    assert os.path.exists(os.path.join(d, "demo_extra.wav"))
    with pytest.raises(vcd.RegenExhausted):
        vcd.regenerate(rec["id"], "cid-uno", extra_id="q", extra_text="x", background=False)


def test_reject_paypal_emette_voucher_senza_bonus_e_notifica(tmp_path, monkeypatch, ambiente):
    import time
    payment._payments["VCORD9"] = {"order_id": "VCORD9", "amount_eur": 5.0, "email": "u@example.com",
                                  "captured_at": time.time(), "used": False}
    try:
        rec = voce_pagata(tmp_path, price=5.0, token="VCORD9")
        monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
        vcd.start_demos(rec["id"], background=False)
        out = vcd.reject(rec["id"], "cid-uno")
        assert out["state"] == "refunded" and out["refund"]["reason"] == "user_rejected"
        ev, _, extra = ambiente[-1]
        assert ev == "refunded" and extra["method"] == "paypal"
        assert extra["voucher_code"] in payment._vouchers
        assert payment._vouchers[extra["voucher_code"]]["amount_eur"] == pytest.approx(5.0)
        assert payment.has_refund_for_job("vc:" + rec["id"])
        # idempotente
        again = vcd.refund(rec["id"], "user_rejected")
        assert again["state"] == "refunded"
        assert sum(1 for v in payment._vouchers.values() if v.get("origin_job_id") == "vc:" + rec["id"]) == 1
    finally:
        payment._payments.pop("VCORD9", None)


def test_reject_solo_da_demos_ready_o_demo_failed(tmp_path):
    rec = voce_pagata(tmp_path)
    with pytest.raises(vc.BadTransition):
        vcd.reject(rec["id"], "cid-uno")


def test_recover_rilancia_le_generazioni_interrotte(tmp_path, monkeypatch):
    rec = voce_pagata(tmp_path)
    vc.transition(rec["id"], "demos_generating")
    altro = voce_pagata(tmp_path, cid="cid-due", email="b@example.com")   # resta `paid`
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    lanciati = []
    monkeypatch.setattr(vcd, "start_demos", lambda cid, **kw: lanciati.append(cid))
    assert vcd.recover() == 2
    assert sorted(lanciati) == sorted([rec["id"], altro["id"]])


def test_run_eccezione_dopo_generate_demos_porta_a_demo_failed(tmp_path, monkeypatch, ambiente):
    """I1: un'eccezione nel blocco dopo generate_demos (scrittura record,
    notify, ecc.) non deve lasciare il record bloccato in demos_generating:
    il fallback lo porta a demo_failed."""
    rec = voce_pagata(tmp_path)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", WorkerFinto())
    orig_transition = vc.transition

    def transition_fallace(clone_id, new_state, *a, **kw):
        if new_state == "demos_ready":
            raise RuntimeError("scrittura record fallita")
        return orig_transition(clone_id, new_state, *a, **kw)

    monkeypatch.setattr(vc, "transition", transition_fallace)
    out = vcd.start_demos(rec["id"], background=False)
    assert out["state"] == "demo_failed"
    assert out["demo"]["fail_count"] == 1 and out["demo"]["failed_at"]
    assert out["demo"]["last_error"] == "RuntimeError"
    assert ambiente[-1][0] == "demo_failed"


def test_run_pulisce_i_file_se_la_voce_diventa_terminale_durante_la_generazione(
        tmp_path, monkeypatch, ambiente):
    """I2: se, mentre il thread di demo genera, un altro attore porta la voce
    a uno stato terminale (rimborso/cancellazione concorrente), i file
    scritti dopo quel momento non devono restare orfani su disco."""
    rec = voce_pagata(tmp_path)
    vc.transition(rec["id"], "demos_generating")
    d = vc.voice_dir(rec["token"])

    def generate_finto(clone_id, sleep=None):
        # simula un refund concorrente mentre il thread genera
        vc.transition(clone_id, "refunded",
                      {"refund": {"reason": "concurrent", "method": "free",
                                  "amount_eur": 0, "at": 0}})
        # file scritto DOPO la pulizia del refund concorrente: orfano se
        # nessuno lo ripulisce
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "demo_common.wav"), "wb").write(b"tardivo")
        return "ok", ""

    monkeypatch.setattr(vcd, "generate_demos", generate_finto)
    vcd._run(rec["id"])
    assert not os.path.isdir(d) or not os.listdir(d)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg assente")
def test_pcm_to_wav48_reale(tmp_path, monkeypatch):
    monkeypatch.undo()
    import importlib
    importlib.reload(vcd)
    pcm = tmp_path / "a.pcm"
    pcm.write_bytes(b"\x00\x00" * 48000)
    wav = tmp_path / "a.wav"
    vcd.pcm_to_wav48(str(pcm), str(wav))
    assert wav.exists() and wav.read_bytes()[:4] == b"RIFF" and not pcm.exists()
