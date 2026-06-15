"""Test API mobile: header cid, device register, my_jobs."""
import time

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


# ---------------------------------------------------------------- Task 1

def test_client_id_from_header():
    with audiobook_app.app.test_request_context(
        headers={"X-ABM-Cid": "mobile-cid-12345"}
    ):
        assert audiobook_app._get_client_id() == "mobile-cid-12345"


def test_client_id_header_wins_over_cookie():
    with audiobook_app.app.test_request_context(
        headers={"X-ABM-Cid": "mobile-cid-12345", "Cookie": "abm_cid=cookiecid"}
    ):
        assert audiobook_app._get_client_id() == "mobile-cid-12345"


def test_client_id_invalid_header_falls_back_to_cookie():
    # spazi e caratteri non ammessi -> ignorato, vince il cookie
    with audiobook_app.app.test_request_context(
        headers={"X-ABM-Cid": "bad cid!!", "Cookie": "abm_cid=cookiecid"}
    ):
        assert audiobook_app._get_client_id() == "cookiecid"


def test_client_id_too_short_header_ignored():
    with audiobook_app.app.test_request_context(headers={"X-ABM-Cid": "abc"}):
        assert audiobook_app._get_client_id() == ""


# ---------------------------------------------------------------- Task 2

def test_completion_token_records_client_id(monkeypatch, tmp_path):
    import email_service
    import generation_engine as ge
    from unittest.mock import patch

    job_id = "mobtok1"
    # Usa i riferimenti iniettati in generation_engine (robusto al reload di
    # audiobook_app da parte di altri test, es. test_cold_*.py).
    ge._jobs[job_id] = {
        "status": "done",
        "client_id": "mobile-cid-12345",
        "notify_email": "u@x.it",
        "email_registered": True,
        "original_filename": "libro.epub",
        "output_format": "m4b",
        "output_m4b": str(tmp_path / "out.m4b"),
        "info": None,
        "last_poll": time.time(),
    }
    (tmp_path / "out.m4b").write_bytes(b"x")
    captured = {}
    try:
        with patch.object(email_service, "_send_email",
                          side_effect=lambda *a, **k: True), \
             patch.object(email_service, "_smtp_available", return_value=True), \
             patch.object(ge, "_save_tokens", side_effect=lambda: None):
            ge._send_completion_email(job_id)
        toks = [t for t, i in ge._download_tokens.items()
                if i.get("job_id") == job_id]
        assert toks, "nessun token creato"
        captured["info"] = ge._download_tokens[toks[0]]
        assert captured["info"].get("client_id") == "mobile-cid-12345"
    finally:
        ge._jobs.pop(job_id, None)
        for t in list(ge._download_tokens):
            if ge._download_tokens[t].get("job_id") == job_id:
                ge._download_tokens.pop(t, None)


# ---------------------------------------------------------------- Task 2 – round-trip persistenza

def test_token_client_id_survives_save_load_roundtrip(monkeypatch, tmp_path):
    import json
    import pathlib

    tokens_file = tmp_path / "_download_tokens.json"
    monkeypatch.setattr(audiobook_app, "_TOKENS_FILE", pathlib.Path(tokens_file))

    token_key = "TOKRT"
    monkeypatch.setattr(audiobook_app, "_download_tokens", {
        token_key: {
            "job_id": "rtjob",
            "client_id": "mobile-cid-12345",
            "created_at": time.time(),
            "book_title": "B",
            "is_gemini": False,
        }
    })

    audiobook_app._save_tokens()

    data = json.loads(tokens_file.read_text(encoding="utf-8"))
    assert token_key in data, "token non salvato"
    assert data[token_key].get("client_id") == "mobile-cid-12345", \
        "client_id non persistito da _save_tokens"


# ---------------------------------------------------------------- Task 3

HDR = {"X-ABM-Cid": "mobile-cid-12345"}


@pytest.fixture
def device_env(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "_DEVICE_TOKENS_FILE",
                        tmp_path / "_device_tokens.json")
    monkeypatch.setattr(audiobook_app, "_device_tokens", {})
    yield


def test_device_register_ok(client, device_env):
    r = client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": "tok-abcdefghij", "platform": "android",
                          "app_version": "1.0.0"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    entries = audiobook_app._device_tokens["mobile-cid-12345"]
    assert entries[0]["fcm_token"] == "tok-abcdefghij"
    assert entries[0]["platform"] == "android"
    assert audiobook_app._DEVICE_TOKENS_FILE.exists()


def test_device_register_requires_cid(client, device_env):
    r = client.post("/api/device/register",
                    json={"fcm_token": "tok-abcdefghij", "platform": "android"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "no_cid"


def test_device_register_invalid_platform(client, device_env):
    r = client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": "tok-abcdefghij", "platform": "windows"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "invalid_platform"


def test_device_register_dedup_and_cap(client, device_env):
    for i in range(7):
        client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": f"tok-device-{i:04d}", "platform": "ios"})
    # ri-registrazione stesso token: niente duplicato
    client.post("/api/device/register", headers=HDR,
                json={"fcm_token": "tok-device-0006", "platform": "ios"})
    entries = audiobook_app._device_tokens["mobile-cid-12345"]
    assert len(entries) == 5  # cap
    assert sum(1 for e in entries if e["fcm_token"] == "tok-device-0006") == 1


def test_device_register_empty_token(client, device_env):
    r = client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": "   ", "platform": "android"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "invalid_token"


def test_device_tokens_save_load_roundtrip(device_env):
    with audiobook_app._device_tokens_lock:
        audiobook_app._device_tokens["mobile-cid-12345"] = [
            {"fcm_token": "tok-rt", "platform": "ios",
             "app_version": "1.0", "registered_at": time.time()}
        ]
        audiobook_app._save_device_tokens()
    audiobook_app._device_tokens.clear()
    audiobook_app._load_device_tokens()
    entries = audiobook_app._device_tokens["mobile-cid-12345"]
    assert entries[0]["fcm_token"] == "tok-rt"


# ---------------------------------------------------------------- Task 4

@pytest.fixture
def my_jobs_env(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_download_tokens", {})
    seeded = []

    def seed_job(jid, **fields):
        with audiobook_app._jobs_lock:
            audiobook_app.jobs[jid] = fields
        seeded.append(jid)

    yield seed_job
    with audiobook_app._jobs_lock:
        for jid in seeded:
            audiobook_app.jobs.pop(jid, None)


def test_my_jobs_requires_cid(client, my_jobs_env):
    r = client.get("/api/my_jobs")
    assert r.status_code == 200
    assert r.get_json()["jobs"] == []


def test_my_jobs_active_job_with_progress(client, my_jobs_env):
    my_jobs_env("mj1", status="generating", client_id="mobile-cid-12345",
                original_filename="libro.epub", output_format="m4b",
                progress_current=3, progress_total=10,
                progress_message="Chapter 3...", start_time=time.time(),
                info=None, last_poll=time.time())
    my_jobs_env("mj2", status="generating", client_id="ALTRO-cid-99999",
                info=None, last_poll=time.time())
    r = client.get("/api/my_jobs", headers=HDR)
    data = r.get_json()["jobs"]
    assert [j["job_id"] for j in data] == ["mj1"]
    assert data[0]["status"] == "generating"
    assert data[0]["progress_current"] == 3
    assert data[0]["progress_total"] == 10


def test_my_jobs_completed_from_token(client, my_jobs_env):
    now = time.time()
    audiobook_app._download_tokens["TOKMJ"] = {
        "job_id": "mjdone",
        "client_id": "mobile-cid-12345",
        "created_at": now - 60,
        "book_title": "Il mio libro",
        "output_format": "m4b",
        "output_m4b": "/x/out.m4b",
        "optimized_abm_path": "",
        "is_gemini": False,
    }
    r = client.get("/api/my_jobs", headers=HDR)
    data = r.get_json()["jobs"]
    assert len(data) == 1
    j = data[0]
    assert j["status"] == "done"
    assert j["download_token"] == "TOKMJ"
    assert j["title"] == "Il mio libro"
    assert j["formats"]["m4b"] is True
    assert j["formats"]["abm"] is False
    assert j["expires_at"] > now


def test_my_jobs_expired_token_hidden(client, my_jobs_env):
    audiobook_app._download_tokens["TOKOLD"] = {
        "job_id": "mjold",
        "client_id": "mobile-cid-12345",
        "created_at": time.time() - 10 * 365 * 86400,
        "is_gemini": False,
    }
    r = client.get("/api/my_jobs", headers=HDR)
    assert r.get_json()["jobs"] == []


def test_my_jobs_token_without_client_id_hidden(client, my_jobs_env):
    audiobook_app._download_tokens["TOKANON"] = {
        "job_id": "mjanon",
        "created_at": time.time() - 60,
        "is_gemini": False,
    }
    r = client.get("/api/my_jobs", headers=HDR)
    assert r.get_json()["jobs"] == []


def test_my_jobs_merges_memory_and_token_for_same_job(client, my_jobs_env):
    now = time.time()
    my_jobs_env("mjboth", status="done", client_id="mobile-cid-12345",
                original_filename="libro.epub", output_format="m4b",
                start_time=now - 120, info=None, last_poll=now)
    audiobook_app._download_tokens["TOKBOTH"] = {
        "job_id": "mjboth",
        "client_id": "mobile-cid-12345",
        "created_at": now - 60,
        "book_title": "Il mio libro",
        "output_format": "m4b",
        "output_m4b": "/x/out.m4b",
        "is_gemini": False,
    }
    r = client.get("/api/my_jobs", headers=HDR)
    data = r.get_json()["jobs"]
    assert len(data) == 1  # merge, niente duplicati
    j = data[0]
    assert j["job_id"] == "mjboth"
    assert j["status"] == "done"
    assert j["download_token"] == "TOKBOTH"
    assert j["formats"]["m4b"] is True
    assert j["created_at"] == pytest.approx(now - 120)  # vince l'in-memory


# ---------------------------------------------------------------- Task 6

def test_push_job_event_sends_to_all_devices_and_purges_dead(monkeypatch):
    import push_service
    calls = []

    def fake_send(tok, title, body, data=None):
        calls.append((tok, data.get("event")))
        return "unregistered" if tok == "dead" else "ok"

    monkeypatch.setattr(push_service, "send_push", fake_send)
    monkeypatch.setattr(push_service, "is_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_device_tokens", {
        "mobile-cid-12345": [
            {"fcm_token": "live", "platform": "android"},
            {"fcm_token": "dead", "platform": "ios"},
        ]
    })
    monkeypatch.setattr(audiobook_app, "_save_device_tokens", lambda: None)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["mjpush"] = {"client_id": "mobile-cid-12345",
                                        "info": None, "last_poll": time.time()}
    try:
        audiobook_app._push_job_event("mjpush", "done", "Il mio libro")
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("mjpush", None)
    assert ("live", "done") in calls
    assert ("dead", "done") in calls
    # il token morto viene rimosso
    toks = [e["fcm_token"]
            for e in audiobook_app._device_tokens["mobile-cid-12345"]]
    assert toks == ["live"]


def test_push_job_event_noop_without_devices(monkeypatch):
    import push_service
    monkeypatch.setattr(push_service, "is_available", lambda: True)
    monkeypatch.setattr(push_service, "send_push",
                        lambda *a, **k: pytest.fail("non deve inviare"))
    monkeypatch.setattr(audiobook_app, "_device_tokens", {})
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["mjnop"] = {"client_id": "sconosciuto-cid",
                                       "info": None, "last_poll": time.time()}
    try:
        audiobook_app._push_job_event("mjnop", "done", "X")  # non deve sollevare
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("mjnop", None)


def test_push_job_event_purge_preserves_device_registered_mid_send(monkeypatch):
    import push_service

    def fake_send(tok, title, body, data=None):
        if tok == "dead":
            # simula una registrazione concorrente durante l'I/O FCM
            audiobook_app._device_tokens["mobile-cid-12345"].append(
                {"fcm_token": "fresh-device-tok", "platform": "android"})
            return "unregistered"
        return "ok"

    monkeypatch.setattr(push_service, "send_push", fake_send)
    monkeypatch.setattr(push_service, "is_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_device_tokens", {
        "mobile-cid-12345": [{"fcm_token": "dead", "platform": "ios"}]
    })
    monkeypatch.setattr(audiobook_app, "_save_device_tokens", lambda: None)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["mjrace"] = {"client_id": "mobile-cid-12345",
                                        "info": None, "last_poll": time.time()}
    try:
        audiobook_app._push_job_event("mjrace", "done", "X")
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("mjrace", None)
    toks = [e["fcm_token"]
            for e in audiobook_app._device_tokens["mobile-cid-12345"]]
    assert toks == ["fresh-device-tok"]  # dead rimosso, fresh sopravvive


# ---------------------------------------------------------------- Task 3b1: batch_mode

def test_generate_batch_mode_sets_email_registered(monkeypatch, tmp_path):
    """batch_mode=true marca il job email_registered (no auto-cancel) senza email."""
    import types
    import audiobook_app
    job_id = "bm-job-1"
    # info stub: chapters vuoti -> selezione 0 char, nessun budget google/gemini.
    info = types.SimpleNamespace(title="", author="", language="it", chapters=[])
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {
            "status": "analyzed",
            "client_id": "mobile-cid-12345",
            "info": info,
            "epub_path": str(tmp_path / "x.epub"),
            "last_poll": time.time(),
        }
    # neutralizza l'avvio reale del thread di generazione
    monkeypatch.setattr(audiobook_app, "run_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    client = audiobook_app.app.test_client()
    try:
        r = client.post("/api/generate",
                        headers={"X-ABM-Cid": "mobile-cid-12345"},
                        json={"job_id": job_id, "voice": "it-IT-IsabellaNeural",
                              "output_format": "m4b", "batch_mode": True})
        assert r.status_code == 200
        assert audiobook_app.jobs[job_id].get("email_registered") is True
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(job_id, None)


def test_create_download_token_without_email(monkeypatch, tmp_path):
    """_create_download_token crea un record token con client_id senza inviare email."""
    import generation_engine as ge
    job_id = "bm-job-2"
    out = tmp_path / "out.m4b"
    out.write_bytes(b"x")
    ge._jobs[job_id] = {
        "status": "done",
        "client_id": "mobile-cid-12345",
        "output_m4b": str(out),
        "output_format": "m4b",
        "info": None,
        "original_filename": "x.epub",
    }
    try:
        token = ge._create_download_token(job_id)
        assert token is not None
        rec = ge._download_tokens[token]
        assert rec["job_id"] == job_id
        assert rec["client_id"] == "mobile-cid-12345"
        assert bool(rec.get("output_m4b"))
    finally:
        ge._jobs.pop(job_id, None)
        for t in list(ge._download_tokens):
            if ge._download_tokens[t].get("job_id") == job_id:
                ge._download_tokens.pop(t, None)


def test_generation_engine_binds_send_push():
    import generation_engine as ge
    # verifica che configure accetti e bindi send_push_fn senza toccare
    # gli altri binding del modulo (riconfigurazione completa = pollution)
    original = ge._send_push
    try:
        pushed = []
        ge._send_push = lambda jid, event, title: pushed.append((jid, event))
        ge._send_push("j1", "done", "T")
        assert pushed == [("j1", "done")]
        import inspect
        assert "send_push_fn" in inspect.signature(ge.configure).parameters
    finally:
        ge._send_push = original
    assert audiobook_app._push_job_event is not None
    assert ge._send_push is audiobook_app._push_job_event


# ---------------------------------------------------------------- Task 7

def test_dl_token_m4b_supports_range(client, tmp_path, monkeypatch):
    m4b = tmp_path / "book.m4b"
    m4b.write_bytes(b"0123456789ABCDEF")
    monkeypatch.setattr(audiobook_app, "_download_tokens", {
        "TOKRANGE": {
            "job_id": "rj1",
            "client_id": "mobile-cid-12345",
            "created_at": time.time(),
            "book_title": "B",
            "output_m4b": str(m4b),
            "output_format": "m4b",
            "is_gemini": False,
        }
    })
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    r = client.get("/dl/TOKRANGE/m4b", headers={"Range": "bytes=4-7"})
    assert r.status_code == 206
    assert r.data == b"4567"
    assert r.headers.get("Content-Range") == "bytes 4-7/16"


def test_send_file_throttled_default_supports_range(client, tmp_path, monkeypatch):
    # Il default del wrapper deve restare conditional=True (Range su tutti
    # gli endpoint file, comportamento storico di Flask >= 2).
    # Verifica tramite un call-site non opt-in (nessun conditional=True esplicito):
    # _try_cold_serve usa bypass_throttle=True senza conditional → deve comunque 206.
    import inspect
    sig = inspect.signature(audiobook_app._send_file_throttled)
    assert sig.parameters["conditional"].default is True, (
        "_send_file_throttled deve avere conditional=True come default"
    )
    # Test comportamentale: senza passare conditional, un Range request restituisce 206.
    f = tmp_path / "x.bin"
    f.write_bytes(b"0123456789")
    with audiobook_app.app.test_request_context(
            "/x.bin", headers={"Range": "bytes=2-5"}):
        r = audiobook_app._send_file_throttled(
            str(f), as_attachment=True, download_name="x.bin",
            bypass_throttle=True)
    assert r.status_code == 206
