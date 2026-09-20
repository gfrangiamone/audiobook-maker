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


def test_apply_account_overrides_payment_armed_email(env):
    """L'account ha sempre precedenza sull'email del pagamento (design doc:
    "Pagamento PayPal con email del pagatore diversa da quella dell'account:
    la notifica resta forzata all'email dell'account"): force=True sovrascrive
    un notify_email gia' armato da un pagamento su un indirizzo diverso, e il
    job resta batch/armato con una sola riga di storico (niente duplicati)."""
    acct = _login(audiobook_app.app.test_client())
    job = _job("jt-6", payment_amount_eur=2.0)
    sess = accounts.open_session(acct["id"])
    with audiobook_app.app.test_request_context("/", headers={**HDR, "Authorization": "Bearer " + sess}):
        # Arming gia' avvenuto per pagamento (PayPal/voucher), su un'email
        # diversa da quella dell'account.
        audiobook_app._arm_email_delivery(job, "jt-6", "payer@paypal.it", lang="en")
        assert job["notify_email"] == "payer@paypal.it"
        audiobook_app._apply_account_to_job(job, "jt-6", "optimize")
    assert job["notify_email"] == "a@b.it" and job["email_registered"] is True
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 1 and rows[0]["job_id"] == "jt-6"


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
    # Provider ignoto a 3+ segmenti: ultimo segmento soltanto, mai un nome di
    # modello/provider davanti all'utente.
    assert f("weird:providerid:foo:bar") == "bar"


# -- storico account scritto da /api/register_email (residuo 6) ---------
# La riga di storico la scrive la partenza (_apply_account_to_job). Un job
# avviato da sloggato e poi "adottato" registrando l'email da loggato non
# comparirebbe mai in /account: /api/register_email deve scriverla.

def test_register_email_logged_in_records_history_row(env):
    c = audiobook_app.app.test_client()
    acct = _login(c)
    _job("jt-h1", status="generating", output_format="m4b",
         voice="it-IT-IsabellaNeural", payment_amount_eur=2.0)

    r = c.post("/api/register_email", json={"job_id": "jt-h1", "email": "a@b.it"}, headers=HDR)
    assert r.status_code == 200, r.get_data(as_text=True)

    rows, total = accounts.list_jobs(acct["id"])
    assert total == 1
    row = rows[0]
    assert row["job_id"] == "jt-h1"
    assert (row["kind"], row["status"], row["source"]) == ("generate", "running", "forced")
    assert row["book_title"] == "Il Gattopardo" and row["output_format"] == "m4b"
    # Etichetta presentabile, mai l'id grezzo del provider.
    assert row["voice"] == "Isabella"
    assert row["paid_eur"] == pytest.approx(2.0)

    # Idempotente: una seconda registrazione non duplica la riga.
    r2 = c.post("/api/register_email", json={"job_id": "jt-h1", "email": "a@b.it"}, headers=HDR)
    assert r2.status_code == 200
    _rows, total2 = accounts.list_jobs(acct["id"])
    assert total2 == 1


def test_register_email_kind_follows_phase(env):
    c = audiobook_app.app.test_client()
    acct = _login(c)
    _job("jt-h2", status="optimizing")
    _job("jt-h3", status="translating")
    assert c.post("/api/register_email", json={"job_id": "jt-h2", "email": "a@b.it"},
                  headers=HDR).status_code == 200
    assert c.post("/api/register_email", json={"job_id": "jt-h3", "email": "a@b.it",
                                               "download_type": "translated"},
                  headers=HDR).status_code == 200
    rows, _t = accounts.list_jobs(acct["id"])
    kinds = {r["job_id"]: r["kind"] for r in rows}
    assert kinds == {"jt-h2": "optimize", "jt-h3": "translate"}


def test_register_email_never_steals_another_accounts_row(env):
    """record_job e' un upsert su job_id che riassegna account_id: senza la
    guardia job_owner, un secondo account che registra l'email sullo stesso
    job si porterebbe via lo storico del primo."""
    c = audiobook_app.app.test_client()
    acct = _login(c)
    _tok, _code = accounts.request_code("other@b.it")
    _st, other = accounts.verify(token=_tok)
    assert _st == "ok"
    accounts.record_job(other["id"], "jt-h4", kind="generate", book_title="Suo")
    _job("jt-h4", status="generating")

    r = c.post("/api/register_email", json={"job_id": "jt-h4", "email": "a@b.it"}, headers=HDR)
    assert r.status_code == 200
    assert accounts.list_jobs(acct["id"])[1] == 0
    rows, total = accounts.list_jobs(other["id"])
    assert total == 1 and rows[0]["book_title"] == "Suo"


def test_register_email_job_never_started_writes_no_row(env):
    """Job in 'analyzed': lo snapshot di adesso puo' non avverarsi mai; la riga
    la scrive la partenza, con i parametri reali."""
    c = audiobook_app.app.test_client()
    acct = _login(c)
    _job("jt-h5")  # status 'analyzed'
    assert c.post("/api/register_email", json={"job_id": "jt-h5", "email": "a@b.it"},
                  headers=HDR).status_code == 200
    assert accounts.list_jobs(acct["id"])[1] == 0


def test_register_email_history_failure_does_not_break_registration(env, monkeypatch):
    c = audiobook_app.app.test_client()
    _login(c)
    _job("jt-h6", status="generating")

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(accounts, "record_job", _boom)
    r = c.post("/api/register_email", json={"job_id": "jt-h6", "email": "a@b.it"}, headers=HDR)
    assert r.status_code == 200
    assert audiobook_app.jobs["jt-h6"]["notify_email"] == "a@b.it"


# -- end-to-end: /api/generate con sessione attiva (M10) ----------------
# I test sopra chiamano gli helper direttamente; questo attraversa la rotta
# vera, l'unica che dimostra che l'aggancio all'account avviene davvero nel
# flusso di generazione (e non solo in un helper che nessuno chiama).

class _SyncThread:
    """threading.Thread sincrono: run_generation e' intercettato, ma senza
    questo il target girerebbe in un thread reale in race con le asserzioni."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


def test_generate_with_session_forces_email_and_records_history(env, monkeypatch):
    from epub_to_tts import BookInfo, Chapter

    run_calls = []
    monkeypatch.setattr(audiobook_app, "run_generation",
                        lambda job_id, info, voice, rate, single_file, **kw:
                        run_calls.append((job_id, voice)))
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)

    c = audiobook_app.app.test_client()
    acct = _login(c)

    ch = Chapter(index=0, title="Cap0", text="A" * 500)
    info = BookInfo(title="Il Gattopardo", author="Tomasi", language="it", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    _job("jt-e2e", info=info)

    r = c.post("/api/generate", json={"job_id": "jt-e2e", "voice": "it-IT-IsabellaNeural",
                                      "rate": "+0%", "output_format": "mp3", "lang": "it"},
               headers=HDR)
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["status"] == "started"
    assert run_calls == [("jt-e2e", "it-IT-IsabellaNeural")]

    # Consegna forzata sull'email dell'account: la rotta la restituisce
    # mascherata (nessun indirizzo in chiaro fuori dal server).
    assert body["auto_batch_email"] == audiobook_app._mask_email(acct["email"])
    assert audiobook_app.jobs["jt-e2e"]["notify_email"] == "a@b.it"
    assert audiobook_app.jobs["jt-e2e"]["email_registered"] is True

    # ...e riga di storico per quel job.
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 1
    assert rows[0]["job_id"] == "jt-e2e"
    assert (rows[0]["kind"], rows[0]["status"], rows[0]["source"]) == ("generate", "running", "forced")
    assert rows[0]["output_format"] == "mp3" and rows[0]["voice"] == "Isabella"
