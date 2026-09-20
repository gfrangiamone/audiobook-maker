# test/test_account_forced_email.py
"""Con sessione attiva ogni job va in modalita' email sull'indirizzo
dell'account e finisce nello storico; i job pagati agganciano lo storico
per email anche senza sessione."""
import json

import pytest

import accounts
import audiobook_app
import db
import email_service

CID = "cid-forced-000001"
HDR = {"X-ABM-Cid": CID}
T0 = 1_800_000_000


class _Info:
    title = "Il Gattopardo"
    author = "Tomasi"
    language = "it"
    chapters = []


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_write_email_pending_marker", lambda p: None)
    monkeypatch.setattr(audiobook_app.pending_jobs, "register", lambda *a, **k: None)
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: env.codes.append((email, kw)) or True)
    audiobook_app._ip_rl_buckets.pop("auth_request", None)
    audiobook_app.app.config["TESTING"] = True
    env.codes = []
    yield env
    for jid in list(audiobook_app.jobs):
        if jid.startswith("jt-"):
            audiobook_app.jobs.pop(jid, None)
    db.close()


def _login(client):
    client.post("/api/auth/request", json={"email": "a@b.it", "lang": "it"}, headers=HDR)
    code = env.codes[-1][1]["code"]
    r = client.post("/api/auth/verify", json={"email": "a@b.it", "code": code}, headers=HDR)
    assert r.status_code == 200
    return accounts.account_for_email("a@b.it")


def _job(jid, **extra):
    job = {"status": "analyzed", "client_id": CID, "info": _Info(), "original_filename": "g.epub",
           "browser_lang": "it"}
    job.update(extra)
    audiobook_app.jobs[jid] = job
    return job


def test_arm_email_delivery_sets_fields_once(env):
    job = _job("jt-1")
    with audiobook_app.app.test_request_context("/", headers=HDR):
        assert audiobook_app._arm_email_delivery(job, "jt-1", "x@y.it", lang="fr",
                                                 output_format="zip_rss", podcast_base_url="https://p") is True
        assert job["notify_email"] == "x@y.it" and job["notify_lang"] == "fr"
        assert job["notify_download_type"] == "podcast" and job["notify_base_url"] == "https://p"
        assert job["email_registered"] is True and job["_auto_batch_notify"] is True
        assert audiobook_app._arm_email_delivery(job, "jt-1", "other@y.it") is False
        assert job["notify_email"] == "x@y.it"


def test_register_paid_job_batch_attaches_history_by_email(env):
    acct = _login(audiobook_app.app.test_client())
    job = _job("jt-2", payment_amount_eur=3.5)
    with audiobook_app.app.test_request_context("/", headers=HDR):
        ok = audiobook_app._register_paid_job_batch("jt-2", job, "tok", engine="Gemini",
                                                    lang="it", email="A@B.it", output_format="m4b")
    assert ok is True
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 1 and rows[0]["job_id"] == "jt-2" and rows[0]["source"] == "payments"
    assert rows[0]["paid_eur"] == pytest.approx(3.5) and rows[0]["book_title"] == "Il Gattopardo"


def test_register_paid_job_batch_unknown_email_no_history(env):
    job = _job("jt-3")
    with audiobook_app.app.test_request_context("/", headers=HDR):
        audiobook_app._register_paid_job_batch("jt-3", job, "tok", email="nobody@b.it")
    assert accounts.account_for_email("nobody@b.it") is None


def test_apply_account_to_job_arms_and_records(env):
    acct = _login(audiobook_app.app.test_client())
    job = _job("jt-4", payment_amount_eur=1.25)
    sess = accounts.open_session(acct["id"])
    with audiobook_app.app.test_request_context("/", headers={**HDR, "Authorization": "Bearer " + sess}):
        out = audiobook_app._apply_account_to_job(job, "jt-4", "generate", output_format="m4b",
                                                  voice="it-IT-IsabellaNeural", lang="it")
    assert out and out["id"] == acct["id"]
    assert job["notify_email"] == "a@b.it" and job["email_registered"] is True
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 1
    r = rows[0]
    assert (r["kind"], r["status"], r["source"]) == ("generate", "running", "forced")
    assert r["output_format"] == "m4b" and r["voice"] == "Isabella"
    assert r["paid_eur"] == pytest.approx(1.25) and r["book_title"] == "Il Gattopardo"


def test_apply_account_to_job_without_session_is_noop(env):
    job = _job("jt-5")
    with audiobook_app.app.test_request_context("/", headers=HDR):
        assert audiobook_app._apply_account_to_job(job, "jt-5", "generate") is None
    assert "notify_email" not in job


def test_apply_account_keeps_existing_manual_email(env):
    acct = _login(audiobook_app.app.test_client())
    job = _job("jt-6", notify_email="manual@x.it", email_registered=True)
    sess = accounts.open_session(acct["id"])
    with audiobook_app.app.test_request_context("/", headers={**HDR, "Authorization": "Bearer " + sess}):
        audiobook_app._apply_account_to_job(job, "jt-6", "optimize")
    assert job["notify_email"] == "manual@x.it"
    assert accounts.list_jobs(acct["id"])[1] == 1


def test_acct_forced_batch(env):
    acct = _login(audiobook_app.app.test_client())
    sess = accounts.open_session(acct["id"])
    with audiobook_app.app.test_request_context("/", headers={"Authorization": "Bearer " + sess}):
        assert audiobook_app._acct_forced_batch(False, "") == (True, "a@b.it")
        assert audiobook_app._acct_forced_batch(True, "x@y.it") == (True, "a@b.it")
    with audiobook_app.app.test_request_context("/"):
        assert audiobook_app._acct_forced_batch(False, "x@y.it") == (False, "x@y.it")


def test_register_email_409_when_logged_in_with_other_email(env):
    c = audiobook_app.app.test_client()
    _login(c)
    _job("jt-7", status="generating")
    r = c.post("/api/register_email", json={"job_id": "jt-7", "email": "other@x.it"}, headers=HDR)
    assert r.status_code == 409
    d = r.get_json()
    assert d["error_code"] == "logged_in_email_forced" and d["email"] == "a@b.it"
    r = c.post("/api/register_email", json={"job_id": "jt-7", "email": "A@B.it"}, headers=HDR)
    assert r.status_code == 200
    assert audiobook_app.jobs["jt-7"]["notify_email"] == "a@b.it"


def test_job_paid_eur_reads_both_pockets():
    f = audiobook_app._job_paid_eur
    assert f({}) == 0.0
    assert f({"payment_amount_eur": "2.5"}) == 2.5
    assert f({"payment": {"total_eur": 4}}) == 4.0
    assert f({"payment_amount_eur": 1, "payment": {"total_eur": 4}}) == 4.0


# -- _voice_public_label ------------------------------------------------
# Etichetta voce presentabile all'utente (mai il nome del provider AI/TTS,
# vedi regola UI): usata dallo storico account, mai dal log (_voice_for_log
# resta l'helper per i log/dossier).

def test_voice_public_label_edge_tts():
    f = audiobook_app._voice_public_label
    assert f("it-IT-IsabellaNeural") == "Isabella"
    assert f("en-US-AndrewMultilingualNeural") == "Andrew"


def test_voice_public_label_gemini(monkeypatch):
    f = audiobook_app._voice_public_label
    assert f("gemini:flash25:Zephyr") == "Zephyr"


def test_voice_public_label_voxcpm():
    f = audiobook_app._voice_public_label
    assert f("voxcpm:v2:it-IT/Stefano") == "Stefano"


def test_voice_public_label_voxcpm_mine_hides_token():
    f = audiobook_app._voice_public_label
    label = f("voxcpm:mine:super-secret-token-123")
    assert label == "your voice"
    assert "super-secret-token-123" not in label


def test_voice_public_label_speechify():
    f = audiobook_app._voice_public_label
    assert f("speechify:simba-3.2:harper_32") == "harper_32"


def test_voice_public_label_empty_and_unknown():
    f = audiobook_app._voice_public_label
    assert f("") == ""
    assert f(None) == ""
    assert f("weird:providerid:foo:bar") == "providerid:foo:bar"
