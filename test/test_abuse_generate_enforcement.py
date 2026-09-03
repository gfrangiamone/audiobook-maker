"""Enforcement anti-abuso: ramo cancel, 403 pre-claim, kill in corsa, progress,
cleanup e ripristino admin."""
import time

import pytest

import abuse_watch as aw
import audiobook_app
import free_tts_quota as ftq
import generation_engine
import payment
from epub_to_tts import BookInfo, Chapter

CID = "cid_abuse_enf_test"
OTHER = "cid_abuse_enf_other"
IP = "7.7.7.7"
VOICE = "en-US-AriaNeural"


class _SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "1000")
    monkeypatch.delenv("ABM_OUTPUT_REUSE", raising=False)
    run_calls, log_calls = [], []

    def _fake_run(job_id, info, voice, rate, single_file, **kw):
        run_calls.append((job_id, voice, kw))

    monkeypatch.setattr(audiobook_app, "run_generation", _fake_run)
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(audiobook_app, "_log_activity",
                         lambda *a, **k: log_calls.append((a, k)))
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    yield {"run": run_calls, "log": log_calls, "dir": tmp_path}
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("abz-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(job_id, n_chars=100, client_id=CID, status="analyzed"):
    ch = Chapter(index=0, title="Cap0", text="A" * n_chars)
    info = BookInfo(title="T", author="A", language="en", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": status, "client_id": client_id,
                                      "client_ip": IP, "original_filename": "book.epub"}
    return audiobook_app.jobs[job_id]


def _ops(env):
    return [a[2] for a, _k in env["log"]]


def _abuse_verdict(cids, scope="cids", confidence=0.95):
    g = aw.group_key(IP, CID)
    for c in cids:
        aw.record_event(g, c, "generate", {"chars": 10})
    aw.set_verdict(g, {"verdict": "abuse", "confidence": confidence, "scope": scope,
                       "cids": cids, "reason": "test"})
    return g


# ---------------------------------------------------------------------------
# Ramo cancel (generation_engine._cancel_cleanup_workdir)
# ---------------------------------------------------------------------------

def _work_dir(tmp_path):
    wd = tmp_path / "job-wd"
    wd.mkdir()
    (wd / "chunk_0001.pcm").write_bytes(b"x" * 10)
    (wd / "prompt_1.txt").write_text("p", encoding="utf-8")
    (wd / "_silence.pcm").write_bytes(b"s")
    return wd


def test_cancel_cleanup_removes_workdir_on_user_cancel(env, tmp_path):
    wd = _work_dir(tmp_path)
    job = {}
    generation_engine._cancel_cleanup_workdir(job, "j1", wd, partial_audio_delivered=False)
    assert not wd.exists() and "abuse_kept_until" not in job


def test_cancel_cleanup_keeps_pcm_only_with_partial_audio(env, tmp_path):
    wd = _work_dir(tmp_path)
    generation_engine._cancel_cleanup_workdir({}, "j1", wd, partial_audio_delivered=True)
    assert wd.exists() and not list(wd.glob("chunk_*.pcm")) and not (wd / "_silence.pcm").exists()


def test_cancel_cleanup_keeps_everything_on_abuse_kill(env, tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_ABUSE_KEEP_HOURS", "2")
    wd = _work_dir(tmp_path)
    job = {"abuse_terminated": True}
    t0 = time.time()
    generation_engine._cancel_cleanup_workdir(job, "j1", wd, partial_audio_delivered=False)
    assert (wd / "chunk_0001.pcm").exists() and (wd / "prompt_1.txt").exists()
    assert 2 * 3600 - 5 <= job["abuse_kept_until"] - t0 <= 2 * 3600 + 5


def test_cancel_cleanup_missing_workdir_sets_no_marker(env, tmp_path):
    job = {"abuse_terminated": True}
    generation_engine._cancel_cleanup_workdir(job, "j1", tmp_path / "nope", partial_audio_delivered=False)
    assert "abuse_kept_until" not in job


def test_analyzed_status_does_not_refund_quota(env):
    """La kill chiude su `analyzed` + cancelled: la quota resta addebitata.
    Solo `error` storna (_set_job_status)."""
    ftq.consume(CID, 400, "abz-q:1")
    job = {"status": "generating", "_free_tts_quota_ref": (CID, "abz-q:1"),
           "cancelled": True, "abuse_terminated": True}
    generation_engine._set_job_status(job, "analyzed")
    assert ftq.month_table().get(CID, {}).get("chars") == 400


# ---------------------------------------------------------------------------
# /api/generate: 403 pre-claim, dossier, marcatori, progress
# ---------------------------------------------------------------------------

def _post(client, job_id, **extra):
    payload = {"job_id": job_id, "voice": VOICE, "rate": "+0%", "single_file": True,
               "output_format": "mp3"}
    payload.update(extra)
    return client.post("/api/generate", json=payload)


def test_403_only_for_cid_in_scope(env, client):
    g = _abuse_verdict([CID])
    job = _mk_job("abz-1")
    r = _post(client, "abz-1")
    assert r.status_code == 403 and r.get_json()["error_code"] == "job_terminated"
    assert "quota" not in r.get_json()["error"].lower()
    assert job["status"] == "analyzed" and env["run"] == []
    assert "QUOTA_ABUSE_BLOCK" in _ops(env)
    assert aw.digest_data()[0]["blocks"] == 1
    # altro cid dello stesso /24, fuori scope: passa
    _mk_job("abz-2", client_id=OTHER)
    client.set_cookie("abm_cid", OTHER)
    r = _post(client, "abz-2")
    assert r.status_code == 200 and [c[0] for c in env["run"]] == ["abz-2"]
    assert audiobook_app.jobs["abz-2"]["abuse_group"] == g


def test_paid_or_premium_job_never_blocked(env, client):
    _abuse_verdict([CID])
    job = _mk_job("abz-3")
    job["payment_amount_eur"] = 1.0
    r = _post(client, "abz-3")
    assert r.status_code == 200 and "QUOTA_ABUSE_BLOCK" not in _ops(env)


def test_kill_disabled_means_no_403(env, client, monkeypatch):
    _abuse_verdict([CID])
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    _mk_job("abz-4")
    assert _post(client, "abz-4").status_code == 200


def test_generate_records_dossier_and_resets_markers(env, client):
    job = _mk_job("abz-5")
    job["abuse_terminated"] = True
    job["abuse_kept_until"] = time.time() + 100
    r = _post(client, "abz-5")
    assert r.status_code == 200
    assert "abuse_terminated" not in job and "abuse_kept_until" not in job
    d = aw.dossier(aw.group_key(IP, CID))
    assert d["cids"][CID]["generate"] == 1 and d["cids"][CID]["chars"] == 100
    assert d["all"]["voices"] == {VOICE: 1} and d["all"]["langs"] == {"en": 1}
    assert len(d["all"]["files"]) == 1


def test_abuse_reset_recovery_markers_clears_stale_flags(env):
    """Il recovery bypassa /api/generate (che resetta questi marker al claim):
    _abuse_reset_recovery_markers deve fare lo stesso lavoro sul job
    ricostruito, cosi' un job rilanciato non eredita marker di un kill
    precedente e resta riconoscibile dal kill loop (abuse_group)."""
    job = {"client_ip": IP, "client_id": CID,
           "abuse_terminated": True, "abuse_kept_until": time.time() + 100}
    out = audiobook_app._abuse_reset_recovery_markers(job)
    assert out is job
    assert "abuse_terminated" not in job and "abuse_kept_until" not in job
    assert job["abuse_group"] == aw.group_key(IP, CID)


def test_quota_block_and_gate_feed_the_dossier(env, client):
    _mk_job("abz-6", n_chars=1500)
    r = _post(client, "abz-6")
    assert r.status_code == 402
    d = aw.dossier(aw.group_key(IP, CID))
    assert d["cids"][CID]["quota_block"] == 1 and aw.signals_for(aw.group_key(IP, CID))["S1"]
    job = audiobook_app.jobs["abz-6"]
    job["notify_email"] = "u@example.com"
    job["email_registered"] = True
    r = _post(client, "abz-6", quota_ack=True)
    assert r.status_code == 200
    d = aw.dossier(aw.group_key(IP, CID))
    assert d["cids"][CID]["quota_gate"] == 1 and d["cids"][CID]["generate"] == 1


def test_register_email_feeds_the_dossier(env, client):
    _mk_job("abz-7")
    r = client.post("/api/register_email", json={"job_id": "abz-7", "email": "Who@Example.com"})
    assert r.status_code == 200
    d = aw.dossier(aw.group_key(IP, CID))
    assert d["cids"][CID]["email"] == 1 and len(d["all"]["emails"]) == 1
    raw = (env["dir"] / "_abuse_dossiers.json").read_text(encoding="utf-8")
    assert "example.com" not in raw.lower()


def test_second_signal_enqueues_judgement(env, client, monkeypatch):
    queued = []
    monkeypatch.setattr(aw, "enqueue", lambda g, c="": queued.append((g, c)) or True)
    g = aw.group_key(IP, CID)
    aw.record_event(g, OTHER, "quota_block", {})           # S1 (+ S2 col cid del test)
    _mk_job("abz-8")
    assert _post(client, "abz-8").status_code == 200
    assert queued == [(g, CID)]


def test_progress_reports_job_terminated(env, client):
    job = _mk_job("abz-9")
    job["cancelled"] = True
    job["abuse_terminated"] = True
    r = client.get("/api/progress/abz-9")
    body = r.get_data(as_text=True)
    assert '"status": "cancelled"' in body and '"error_code": "job_terminated"' in body


# ---------------------------------------------------------------------------
# Kill in corsa (_abuse_apply_verdict)
# ---------------------------------------------------------------------------

def _running(job_id, client_id=CID, group=None):
    job = _mk_job(job_id, client_id=client_id, status="generating")
    job["abuse_group"] = group or aw.group_key(IP, CID)
    job["voice"] = VOICE
    return job


def test_apply_verdict_kills_only_unpaid_in_scope_running(env):
    g = aw.group_key(IP, CID)
    verdict = {"verdict": "abuse", "confidence": 0.95, "scope": "cids", "cids": [CID]}
    victim = _running("abz-k1")
    other_cid = _running("abz-k2", client_id=OTHER)
    paid = _running("abz-k3"); paid["payment_token"] = "tok"
    idle = _mk_job("abz-k4"); idle["abuse_group"] = g
    other_group = _running("abz-k5", group="net:elsewhere")
    assert audiobook_app._abuse_apply_verdict(g, verdict) == 1
    assert victim["abuse_terminated"] is True and victim["cancelled"] is True
    for j in (other_cid, paid, idle, other_group):
        assert not j.get("abuse_terminated") and not j.get("cancelled")
    assert _ops(env).count("QUOTA_ABUSE_KILL") == 1
    assert aw.digest_data()[0]["kills"] == 1
    assert audiobook_app._abuse_apply_verdict(g, verdict) == 0      # idempotente


def test_apply_verdict_respects_confidence_switch_and_kind(env, monkeypatch):
    g = aw.group_key(IP, CID)
    job = _running("abz-k6")
    low = {"verdict": "abuse", "confidence": 0.5, "scope": "group", "cids": [CID]}
    assert audiobook_app._abuse_apply_verdict(g, low) == 0
    clean = {"verdict": "clean", "confidence": 1.0, "scope": "group", "cids": [CID]}
    assert audiobook_app._abuse_apply_verdict(g, clean) == 0
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    high = {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": [CID]}
    assert audiobook_app._abuse_apply_verdict(g, high) == 0
    assert not job.get("cancelled") and "QUOTA_ABUSE_KILL" not in _ops(env)


# ---------------------------------------------------------------------------
# Cleanup della retention e ripristino admin
# ---------------------------------------------------------------------------

def test_abuse_keep_state(env):
    now = time.time()
    assert audiobook_app._abuse_keep_state({}, now) is None
    assert audiobook_app._abuse_keep_state({"abuse_kept_until": "junk"}, now) is None
    assert audiobook_app._abuse_keep_state({"abuse_kept_until": now + 60}, now) == "hold"
    assert audiobook_app._abuse_keep_state({"abuse_kept_until": now - 1}, now) == "expired"


def test_abuse_cleanup_decision_hold_remove_pass(env):
    now = time.time()
    assert audiobook_app._abuse_cleanup_decision({}, now, False) == "pass"           # non ucciso per abuso
    held = {"abuse_kept_until": now + 60}
    assert audiobook_app._abuse_cleanup_decision(held, now, False) == "hold"
    expired_no_token = {"abuse_kept_until": now - 1}
    assert audiobook_app._abuse_cleanup_decision(expired_no_token, now, False) == "remove"
    expired_with_token = {"abuse_kept_until": now - 1}
    assert audiobook_app._abuse_cleanup_decision(expired_with_token, now, True) == "pass"


def test_cleanup_loop_analyzed_branch_uses_abuse_cleanup_decision(env, tmp_path, monkeypatch):
    """Integrazione: il ramo 'analyzed' di _cleanup_loop passa davvero dalla
    decisione pura _abuse_cleanup_decision (issue #10) invece di duplicarne la
    logica inline. Tutto cio' che e' fuori dal ramo abuso e' no-op: il target
    e' l'instradamento, non l'intero giro di cleanup."""
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    for fn in ("_cleanup_expired_shares", "_merge_tokens_from_disk", "_log_memory_stats",
               "_try_send_admin_digest", "_malloc_trim", "_reconcile_cold_offload",
               "_evict_hot_local"):
        monkeypatch.setattr(audiobook_app, fn, lambda *a, **k: None)
    removed = []
    monkeypatch.setattr(audiobook_app, "_cleanup_job",
                        lambda jid, reason="": removed.append((jid, reason)))

    calls = []
    real_decision = audiobook_app._abuse_cleanup_decision

    def _spy(job, now, has_active_token):
        calls.append((job.get("_tag"), has_active_token))
        return real_decision(job, now, has_active_token)

    monkeypatch.setattr(audiobook_app, "_abuse_cleanup_decision", _spy)

    now = time.time()
    held = _mk_job("abz-cl-hold")
    held["abuse_kept_until"] = now + 3600
    held["_tag"] = "held"
    expired = _mk_job("abz-cl-expired")
    expired["abuse_kept_until"] = now - 10
    expired["_tag"] = "expired"

    n_sleeps = [0]

    def _sleep(_sec):
        n_sleeps[0] += 1
        if n_sleeps[0] >= 2:
            raise SystemExit("stop after one _cleanup_loop pass")

    monkeypatch.setattr(audiobook_app.time, "sleep", _sleep)

    with pytest.raises(SystemExit):
        audiobook_app._cleanup_loop()

    assert {t for t, _tok in calls} == {"held", "expired"}     # il ramo e' passato dalla decisione pura
    assert ("expired", False) in calls
    assert "abz-cl-hold" in audiobook_app.jobs                 # hold: mai in to_remove
    assert removed == [("abz-cl-expired", "abuse retention expired")]


def test_admin_clear_endpoint(env, client, monkeypatch):
    g = _abuse_verdict([CID])
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-test")
    r = client.post(f"/admin/api/abuse/clear/{g}")
    assert r.status_code == 403 and aw.verdict_for(g) is not None
    r = client.post(f"/admin/api/abuse/clear/{g}", headers={"X-Admin-Token": "tok-test"})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "group": g, "cleared": True}
    assert aw.verdict_for(g) is None
    r = client.post(f"/admin/api/abuse/clear/{g}", headers={"X-Admin-Token": "tok-test"})
    assert r.get_json()["cleared"] is False
    # dopo il ripristino il cid rigenera normalmente
    _mk_job("abz-c1")
    assert _post(client, "abz-c1").status_code == 200


def test_admin_clear_endpoint_rejects_invalid_group(env, client, monkeypatch):
    """Il path param non validato finiva pari pari in un print(): %0A inietta
    una newline nel log di processo (forgiatura di righe di log). Il ramo
    net: resta solo esadecimale; il ramo cid: accetta l'abm_cid grezzo (con
    trattini) ma non whitespace/caratteri di controllo."""
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-test")
    r = client.post("/admin/api/abuse/clear/net:%0Aforged",
                     headers={"X-Admin-Token": "tok-test"})
    assert r.status_code == 400 and r.get_json() == {"error": "invalid group"}
    r = client.post("/admin/api/abuse/clear/cid:abc%0Adef",
                     headers={"X-Admin-Token": "tok-test"})
    assert r.status_code == 400 and r.get_json() == {"error": "invalid group"}
    r = client.post("/admin/api/abuse/clear/not-a-group",
                     headers={"X-Admin-Token": "tok-test"})
    assert r.status_code == 400 and r.get_json() == {"error": "invalid group"}
    # senza token: 403 prima ancora della validazione del formato
    r = client.post("/admin/api/abuse/clear/net:%0Aforged")
    assert r.status_code == 403


def test_admin_clear_endpoint_accepts_raw_cid_group(env, client, monkeypatch):
    """Il fallback cid: usa l'abm_cid grezzo (uuid4[:12], con trattini), non un
    hash esadecimale: deve superare la validazione e arrivare a
    abuse_watch.clear_verdict (issue #5 follow-up)."""
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-test")
    group = "cid:36e901e8-71d4-4a2b-9c1e-123456789abc"
    r = client.post(f"/admin/api/abuse/clear/{group}",
                     headers={"X-Admin-Token": "tok-test"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["group"] == group and "cleared" in body
