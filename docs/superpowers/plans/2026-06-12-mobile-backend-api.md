# Backend Mobile API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preparare il backend Flask per l'app mobile Flutter: identificazione client via header, registrazione device FCM, elenco job per client robusto ai riavvii, notifiche push al COMPLETE/ERROR, download con resume (Range).

**Architecture:** Interventi additivi su `audiobook_app.py` (2 endpoint nuovi + header cid + Range), nuovo modulo `push_service.py` (pattern `email_service.py`: config da env, mai import dell'entry-point), hook push in `generation_engine.py` via callback iniettata con `configure()`. Persistenza `_device_tokens.json` con lo stesso pattern atomico tmp+fsync+replace dei file JSON esistenti.

**Tech Stack:** Flask, google-auth (FCM HTTP v1), requests, pytest.

**Branch:** `abm_mobile`. ⚠️ La working copy principale è condivisa con sessioni parallele: eseguire questo piano in un **worktree dedicato** (`git worktree add "$env:TEMP\abm-mobile-exec" abm_mobile`) e committare solo lì. I riferimenti `file:riga` sono ancore indicative (rilevate il 2026-06-12 su `main`): verificarle con grep prima di ogni modifica.

**Spec di riferimento:** `docs/superpowers/specs/2026-06-11-mobile-app-design.md`

**Convenzioni test:** import diretto di `audiobook_app` (MAI `importlib.reload`, MAI from-import di `jobs`/`app` — vedi commento in `test/test_paypal_create_gemini.py:8-12`), fixture `client` locale al file, seed di `jobs` con cleanup in fixture, `monkeypatch` per funzioni/file JSON. Comandi PowerShell, niente `&&`.

---

### Task 1: Header `X-ABM-Cid` in `_get_client_id()`

L'app mobile non gestisce cookie: manda il proprio cid in un header. Il fallback cookie resta identico per il browser.

**Files:**
- Modify: `audiobook_app.py` (funzione `_get_client_id`, ~riga 563; grep `def _get_client_id`)
- Test: `test/test_mobile_api.py` (nuovo)

- [ ] **Step 1: Scrivere i test che falliscono**

Creare `test/test_mobile_api.py`:

```python
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
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `pytest test/test_mobile_api.py -v --tb=short`
Expected: 3 FAIL (`test_client_id_from_header`, `test_client_id_header_wins_over_cookie`, `test_client_id_too_short_header_ignored` — l'header oggi è ignorato), 1 PASS (`test_client_id_invalid_header_falls_back_to_cookie` passa già per coincidenza: ok).

- [ ] **Step 3: Implementare**

In `audiobook_app.py`, sostituire `_get_client_id` (vicino a `_CLIENT_COOKIE_NAME`, ~riga 563):

```python
_CLIENT_COOKIE_NAME = "abm_cid"
_CLIENT_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year
_MOBILE_CID_HEADER = "X-ABM-Cid"
_MOBILE_CID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _get_client_id():
    """Return the client_id from mobile header or cookie, or empty string."""
    hdr = (request.headers.get(_MOBILE_CID_HEADER) or "").strip()
    if hdr and _MOBILE_CID_RE.match(hdr):
        return hdr
    return request.cookies.get(_CLIENT_COOKIE_NAME, "")
```

`re` è già importato in testa al file (verificare con grep `^import re`).

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest test/test_mobile_api.py -v --tb=short`
Expected: 4 PASS

- [ ] **Step 5: Verifica sintassi + regressioni ownership**

Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_cancel_endpoint_lock.py test/test_combined_payment_enforcement.py -v --tb=short`
Expected: PASS (l'ownership check usa `_get_client_id`, comportamento cookie invariato)

- [ ] **Step 6: Commit**

```powershell
git add test/test_mobile_api.py audiobook_app.py
git commit -m "feat(mobile): client id via header X-ABM-Cid accanto al cookie"
```

---

### Task 2: `client_id` nei record di `_download_tokens`

Oggi il token non registra il proprietario (verificato: `generation_engine.py:1357-1386`), quindi dopo un riavvio del server non è possibile ricostruire "i job completati di questo client". Campo additivo: i token vecchi senza `client_id` semplicemente non compaiono in `my_jobs`.

**Files:**
- Modify: `generation_engine.py` (creazione token in `_send_completion_email`, ~riga 1357; grep `_download_tokens\[token\] = {` su TUTTO il repo per trovare eventuali altri siti di creazione, es. flusso traduzione — aggiungere il campo in OGNUNO)
- Test: `test/test_mobile_api.py`

- [ ] **Step 1: Trovare tutti i siti di creazione token**

Run: `grep -n "_download_tokens\[token\] = {" *.py` (PowerShell: `Select-String -Path *.py -Pattern "_download_tokens\[token\] = \{"`)
Annotare ogni file:riga trovato — i passi seguenti si applicano a ciascuno.

- [ ] **Step 2: Scrivere il test che fallisce**

Aggiungere a `test/test_mobile_api.py`:

```python
# ---------------------------------------------------------------- Task 2

def test_completion_token_records_client_id(monkeypatch, tmp_path):
    import email_service
    import generation_engine as ge
    from unittest.mock import patch

    job_id = "mobtok1"
    audiobook_app.jobs[job_id] = {
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
             patch.object(email_service, "_smtp_available", return_value=True):
            ge._send_completion_email(job_id)
        toks = [t for t, i in audiobook_app._download_tokens.items()
                if i.get("job_id") == job_id]
        assert toks, "nessun token creato"
        captured["info"] = audiobook_app._download_tokens[toks[0]]
        assert captured["info"].get("client_id") == "mobile-cid-12345"
    finally:
        audiobook_app.jobs.pop(job_id, None)
        for t in list(audiobook_app._download_tokens):
            if audiobook_app._download_tokens[t].get("job_id") == job_id:
                audiobook_app._download_tokens.pop(t, None)
```

Nota esecutore: se `_send_completion_email` richiede altri campi job per non uscire prima della creazione token (leggere il corpo reale, ~`generation_engine.py:1316-1399`), aggiungere al seed i campi minimi necessari — il criterio del test resta "il record token contiene client_id".

- [ ] **Step 3: Eseguire il test e verificarne il fallimento**

Run: `pytest test/test_mobile_api.py::test_completion_token_records_client_id -v --tb=short`
Expected: FAIL su `assert ... client_id`

- [ ] **Step 4: Implementare**

In ogni sito di creazione trovato allo Step 1, aggiungere al dict del token:

```python
        "client_id": job.get("client_id", ""),
```

(dove `job` è il dict del job disponibile nel contesto; nel sito principale di `_send_completion_email` esiste già).

- [ ] **Step 5: Eseguire test e verifica sintassi**

Run: `pytest test/test_mobile_api.py -v --tb=short`
Expected: PASS
Run: `python -m py_compile generation_engine.py`

- [ ] **Step 6: Commit**

```powershell
git add generation_engine.py test/test_mobile_api.py
git commit -m "feat(mobile): client_id nei record dei download token"
```

---

### Task 3: Persistenza device token + `POST /api/device/register`

**Files:**
- Modify: `audiobook_app.py` (nuova sezione vicino a `_TOKENS_FILE`/`_load_tokens`, ~riga 1274; endpoint vicino alle altre route `/api/*`)
- Test: `test/test_mobile_api.py`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere a `test/test_mobile_api.py`:

```python
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
                    json={"fcm_token": "tok-abc", "platform": "android",
                          "app_version": "1.0.0"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    entries = audiobook_app._device_tokens["mobile-cid-12345"]
    assert entries[0]["fcm_token"] == "tok-abc"
    assert entries[0]["platform"] == "android"
    assert audiobook_app._DEVICE_TOKENS_FILE.exists()


def test_device_register_requires_cid(client, device_env):
    r = client.post("/api/device/register",
                    json={"fcm_token": "tok-abc", "platform": "android"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "no_cid"


def test_device_register_invalid_platform(client, device_env):
    r = client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": "tok-abc", "platform": "windows"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "invalid_platform"


def test_device_register_dedup_and_cap(client, device_env):
    for i in range(7):
        client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": f"tok-{i}", "platform": "ios"})
    # ri-registrazione stesso token: niente duplicato
    client.post("/api/device/register", headers=HDR,
                json={"fcm_token": "tok-6", "platform": "ios"})
    entries = audiobook_app._device_tokens["mobile-cid-12345"]
    assert len(entries) == 5  # cap
    assert sum(1 for e in entries if e["fcm_token"] == "tok-6") == 1
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `pytest test/test_mobile_api.py -k device -v --tb=short`
Expected: ERROR/FAIL (`_DEVICE_TOKENS_FILE` non esiste come attributo)

- [ ] **Step 3: Implementare persistenza**

In `audiobook_app.py`, dopo il blocco `_load_tokens`/`_save_tokens` (~riga 1363), aggiungere:

```python
# ---------------------------------------------------------------------------
# Device tokens (app mobile): cid -> lista device FCM. Persistenza atomica.
_DEVICE_TOKENS_FILE = DATA_DIR / "_device_tokens.json"
_MAX_DEVICES_PER_CLIENT = 5
_device_tokens = {}
_device_tokens_lock = threading.Lock()


def _load_device_tokens():
    global _device_tokens
    try:
        if _DEVICE_TOKENS_FILE.exists():
            with open(_DEVICE_TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _device_tokens = data
                print(f"[device] Loaded FCM tokens for {len(_device_tokens)} clients")
    except Exception as e:
        print(f"[device] Failed to load device tokens: {e}")


def _save_device_tokens():
    """Caller MUST hold _device_tokens_lock."""
    try:
        _tmp = _DEVICE_TOKENS_FILE.with_suffix(_DEVICE_TOKENS_FILE.suffix + ".tmp")
        with open(_tmp, "w", encoding="utf-8") as f:
            json.dump(_device_tokens, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(str(_tmp), str(_DEVICE_TOKENS_FILE))
    except Exception as e:
        print(f"[device] Failed to save device tokens: {e}")
```

Nota: verificare il nome reale della costante della data dir (grep `_TOKENS_FILE =` — usa lo stesso parent, es. `DATA_DIR` o `_DATA_DIR`) e usare quello. Chiamare `_load_device_tokens()` allo startup accanto a `_load_tokens()` (grep `_load_tokens()` per il punto esatto).

- [ ] **Step 4: Implementare endpoint**

Vicino alle altre route `/api/*` JSON:

```python
@app.route("/api/device/register", methods=["POST"])
def api_device_register():
    """Registra/aggiorna il device FCM del client mobile per le notifiche push."""
    data = request.json or {}
    cid = _get_client_id()
    if not cid:
        return jsonify({"error": "Missing client id", "error_code": "no_cid"}), 400
    fcm_token = (data.get("fcm_token") or "").strip()
    platform_name = (data.get("platform") or "").strip().lower()
    app_version = (data.get("app_version") or "").strip()[:32]
    if not fcm_token or len(fcm_token) > 4096:
        return jsonify({"error": "Invalid fcm_token", "error_code": "invalid_token"}), 400
    if platform_name not in ("android", "ios"):
        return jsonify({"error": "Invalid platform", "error_code": "invalid_platform"}), 400
    with _device_tokens_lock:
        entries = [e for e in _device_tokens.get(cid, [])
                   if e.get("fcm_token") != fcm_token]
        entries.append({
            "fcm_token": fcm_token,
            "platform": platform_name,
            "app_version": app_version,
            "registered_at": time.time(),
        })
        _device_tokens[cid] = entries[-_MAX_DEVICES_PER_CLIENT:]
        _save_device_tokens()
    return jsonify({"ok": True})
```

- [ ] **Step 5: Eseguire i test e verificare che passino**

Run: `pytest test/test_mobile_api.py -v --tb=short`
Expected: tutti PASS
Run: `python -m py_compile audiobook_app.py`

- [ ] **Step 6: Commit**

```powershell
git add audiobook_app.py test/test_mobile_api.py
git commit -m "feat(mobile): POST /api/device/register con persistenza _device_tokens.json"
```

---

### Task 4: `GET /api/my_jobs`

Combina `jobs` in-memory (attivi e appena finiti) + `_download_tokens` (completati entro retention, sopravvivono al riavvio). Nessun dato di altri client.

**Files:**
- Modify: `audiobook_app.py` (endpoint nuovo; riusa `_effective_retention_for_token_info`, ~riga 494)
- Test: `test/test_mobile_api.py`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere a `test/test_mobile_api.py`:

```python
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
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `pytest test/test_mobile_api.py -k my_jobs -v --tb=short`
Expected: FAIL con 404 (route inesistente)

- [ ] **Step 3: Implementare**

In `audiobook_app.py`, vicino alle altre route `/api/*`:

```python
_MY_JOBS_LIVE_STATUSES = (
    "analyzed", "optimizing", "optimized", "translating", "generating",
    "done", "error", "cancelled",
)


@app.route("/api/my_jobs")
def api_my_jobs():
    """Job del client chiamante: attivi (in-memory) + completati (token su disco).

    Usato dall'app mobile per ricostruire la tab Attivita' a ogni avvio.
    """
    cid = _get_client_id()
    if not cid:
        return jsonify({"jobs": []})
    now = time.time()
    out = {}

    with _jobs_lock:
        snapshot = list(jobs.items())
    for jid, job in snapshot:
        if job.get("client_id") != cid:
            continue
        status = job.get("status", "")
        if status not in _MY_JOBS_LIVE_STATUSES:
            continue
        info = job.get("info")
        entry = {
            "job_id": jid,
            "status": status,
            "title": (getattr(info, "title", "") or
                      job.get("original_filename", "")),
            "output_format": job.get("output_format", ""),
            "created_at": job.get("start_time") or job.get("last_poll") or 0,
        }
        if status == "generating":
            entry.update({
                "progress_current": job.get("progress_current", 0),
                "progress_total": job.get("progress_total", 0),
                "progress_message": job.get("progress_message", ""),
            })
        elif status == "optimizing":
            entry.update({
                "opt_processed_chars": job.get("opt_processed_chars", 0),
                "opt_total_chars": job.get("opt_total_chars", 0),
            })
        elif status == "translating":
            entry.update({
                "tr_progress_current": job.get("tr_progress_current", 0),
                "tr_progress_total": job.get("tr_progress_total", 0),
            })
        out[jid] = entry

    for token, tinfo in list(_download_tokens.items()):
        if not isinstance(tinfo, dict) or tinfo.get("client_id") != cid:
            continue
        created = tinfo.get("created_at", 0)
        retention = _effective_retention_for_token_info(tinfo)
        if (now - created) > retention:
            continue
        jid = tinfo.get("job_id", "")
        entry = out.setdefault(jid, {"job_id": jid, "created_at": created})
        entry.update({
            "status": "done",
            "title": tinfo.get("book_title") or entry.get("title", ""),
            "output_format": tinfo.get("output_format",
                                       entry.get("output_format", "")),
            "download_token": token,
            "expires_at": created + retention,
            "downloaded_at": tinfo.get("downloaded_at") or None,
            "formats": {
                "m4b": bool(tinfo.get("output_m4b")),
                "zip": bool(tinfo.get("output_zip")),
                "mp3": bool(tinfo.get("output_file")),
                "abm": bool(tinfo.get("optimized_abm_path")),
            },
        })

    ordered = sorted(out.values(),
                     key=lambda e: -(e.get("created_at") or 0))
    return jsonify({"jobs": ordered})
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest test/test_mobile_api.py -v --tb=short`
Expected: tutti PASS
Run: `python -m py_compile audiobook_app.py`

- [ ] **Step 5: Commit**

```powershell
git add audiobook_app.py test/test_mobile_api.py
git commit -m "feat(mobile): GET /api/my_jobs (in-memory jobs + download token entro retention)"
```

---

### Task 5: Modulo `push_service.py` (FCM HTTP v1)

Pattern `email_service.py`: configurazione da env (`ABM_FCM_CREDENTIALS_FILE`), nessun import di `audiobook_app`, fallimenti mai bloccanti. Project id letto dal service-account JSON.

**Files:**
- Create: `push_service.py`
- Modify: `requirements.txt` (aggiungere `google-auth`)
- Test: `test/test_push_service.py` (nuovo)

- [ ] **Step 1: Scrivere i test che falliscono**

Creare `test/test_push_service.py`:

```python
"""Test push_service (FCM HTTP v1) con HTTP e credenziali mockati."""
import json
from unittest.mock import MagicMock, patch

import pytest

import push_service


@pytest.fixture
def fcm_env(monkeypatch, tmp_path):
    sa = tmp_path / "sa.json"
    sa.write_text(json.dumps({"project_id": "test-proj",
                              "type": "service_account"}), encoding="utf-8")
    monkeypatch.setattr(push_service, "_FCM_CREDENTIALS_FILE", str(sa))
    monkeypatch.setattr(push_service, "_creds", None)
    monkeypatch.setattr(push_service, "_project_id", "")
    yield


def test_not_available_without_credentials(monkeypatch):
    monkeypatch.setattr(push_service, "_FCM_CREDENTIALS_FILE", "")
    assert push_service.is_available() is False


def test_available_with_credentials(fcm_env):
    assert push_service.is_available() is True


def _mock_creds():
    creds = MagicMock()
    creds.token = "fake-bearer"
    creds.expired = False
    creds.valid = True
    return creds


def test_send_push_ok(fcm_env):
    resp = MagicMock(status_code=200)
    with patch.object(push_service, "_get_credentials",
                      return_value=_mock_creds()), \
         patch.object(push_service.requests, "post",
                      return_value=resp) as mock_post:
        result = push_service.send_push("device-tok", "Titolo", "Corpo",
                                        data={"job_id": "j1", "event": "done"})
    assert result == "ok"
    url = mock_post.call_args[0][0]
    assert url == "https://fcm.googleapis.com/v1/projects/test-proj/messages:send"
    payload = mock_post.call_args[1]["json"]
    assert payload["message"]["token"] == "device-tok"
    assert payload["message"]["notification"]["title"] == "Titolo"
    assert payload["message"]["data"]["job_id"] == "j1"


def test_send_push_unregistered(fcm_env):
    resp = MagicMock(status_code=404,
                     text='{"error":{"status":"NOT_FOUND"}}')
    with patch.object(push_service, "_get_credentials",
                      return_value=_mock_creds()), \
         patch.object(push_service.requests, "post", return_value=resp):
        result = push_service.send_push("dead-tok", "T", "B")
    assert result == "unregistered"


def test_send_push_retries_then_error(fcm_env, monkeypatch):
    monkeypatch.setattr(push_service.time, "sleep", lambda s: None)
    resp = MagicMock(status_code=500, text="boom")
    with patch.object(push_service, "_get_credentials",
                      return_value=_mock_creds()), \
         patch.object(push_service.requests, "post",
                      return_value=resp) as mock_post:
        result = push_service.send_push("tok", "T", "B")
    assert result == "error"
    assert mock_post.call_count == 3


def test_send_push_never_raises(fcm_env):
    with patch.object(push_service, "_get_credentials",
                      side_effect=RuntimeError("auth down")):
        assert push_service.send_push("tok", "T", "B") == "error"
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `pytest test/test_push_service.py -v --tb=short`
Expected: ERROR all'import (`push_service` non esiste)

- [ ] **Step 3: Implementare `push_service.py`**

```python
"""push_service.py — Notifiche push FCM (HTTP v1) per l'app mobile.

Pattern email_service: configurazione da env, nessun import di audiobook_app.
Disabilitato se ABM_FCM_CREDENTIALS_FILE non e' impostata. I fallimenti non
sono mai bloccanti: send_push ritorna 'ok' | 'unregistered' | 'error'.
"""
import json
import os
import threading
import time

import requests

_FCM_CREDENTIALS_FILE = os.environ.get("ABM_FCM_CREDENTIALS_FILE", "")
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_SEND_RETRIES = 3

_creds = None
_project_id = ""
_creds_lock = threading.Lock()


def is_available():
    """True se le credenziali FCM sono configurate e il file esiste."""
    return bool(_FCM_CREDENTIALS_FILE) and os.path.isfile(_FCM_CREDENTIALS_FILE)


def _load_project_id():
    global _project_id
    if not _project_id:
        with open(_FCM_CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            _project_id = json.load(f).get("project_id", "")
    return _project_id


def _get_credentials():
    """Credenziali google-auth con cache e refresh. Caller gestisce le eccezioni."""
    global _creds
    from google.auth.transport.requests import Request as _GAuthRequest
    from google.oauth2 import service_account
    with _creds_lock:
        if _creds is None:
            _creds = service_account.Credentials.from_service_account_file(
                _FCM_CREDENTIALS_FILE, scopes=[_FCM_SCOPE])
        if not _creds.valid or _creds.expired:
            _creds.refresh(_GAuthRequest())
        return _creds


def send_push(fcm_token, title, body, data=None):
    """Invia una notifica a un singolo device. Mai eccezioni verso il caller.

    Ritorna: 'ok' | 'unregistered' (token da rimuovere) | 'error'.
    """
    if not is_available():
        return "error"
    try:
        creds = _get_credentials()
        project_id = _load_project_id()
    except Exception as e:
        print(f"[push] FCM auth failed: {e}")
        return "error"
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    payload = {
        "message": {
            "token": fcm_token,
            "notification": {"title": title, "body": body},
            "data": {str(k): str(v) for k, v in (data or {}).items()},
        }
    }
    headers = {"Authorization": f"Bearer {creds.token}"}
    for attempt in range(_SEND_RETRIES):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
        except Exception as e:
            print(f"[push] FCM request failed (attempt {attempt + 1}): {e}")
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 200:
            return "ok"
        if resp.status_code in (400, 404):
            # Token invalido/non registrato: inutile ritentare.
            print(f"[push] FCM token unregistered ({resp.status_code})")
            return "unregistered"
        print(f"[push] FCM error {resp.status_code} (attempt {attempt + 1}): "
              f"{resp.text[:200]}")
        time.sleep(2 ** attempt)
    return "error"
```

Aggiungere a `requirements.txt` la riga:

```
google-auth>=2.23          # FCM HTTP v1 push notifications (app mobile)
```

(`requests` è già dipendenza dell'app — verificare con grep in requirements; se assente aggiungere anche `requests`.)

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest test/test_push_service.py -v --tb=short`
Expected: 6 PASS
Run: `python -m py_compile push_service.py`

- [ ] **Step 5: Commit**

```powershell
git add push_service.py test/test_push_service.py requirements.txt
git commit -m "feat(mobile): push_service FCM HTTP v1 (retry, unregistered, mai bloccante)"
```

---

### Task 6: Push al COMPLETE e all'ERROR

`audiobook_app.py` possiede device token e job → espone `_push_job_event(job_id, event, title)`; `generation_engine` la riceve via `configure()` (nuovo parametro `send_push_fn`) e la chiama nel post-COMPLETE e nel path di errore. Fallimenti push solo loggati.

**Files:**
- Modify: `audiobook_app.py` (helper + parametro in `generation_engine.configure(...)`, ~riga 11645)
- Modify: `generation_engine.py` (firma `configure`, ~riga 169; post-COMPLETE ~riga 4349 grep `post-COMPLETE: triggering email`; path errore: grep `_notify_user_gemini_job_failed(` definizione)
- Test: `test/test_mobile_api.py`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere a `test/test_mobile_api.py`:

```python
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
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `pytest test/test_mobile_api.py -k push_job_event -v --tb=short`
Expected: FAIL (`_push_job_event` non esiste)

- [ ] **Step 3: Implementare l'helper in `audiobook_app.py`**

Dopo il blocco device tokens del Task 3:

```python
def _push_job_event(job_id, event, title=""):
    """Invia push FCM a tutti i device del client proprietario del job.

    event: 'done' | 'error'. Mai bloccante: ogni errore e' solo loggato.
    """
    try:
        import push_service
        if not push_service.is_available():
            return
        with _jobs_lock:
            job = jobs.get(job_id) or {}
            cid = job.get("client_id", "")
        if not cid:
            return
        with _device_tokens_lock:
            devices = list(_device_tokens.get(cid, []))
        if not devices:
            return
        if event == "done":
            subject = title or "Audiolibro pronto"
            body = "La generazione è completata: scarica il file nella libreria."
        else:
            subject = title or "Generazione non riuscita"
            body = "Il lavoro si è interrotto: apri l'app per i dettagli."
        dead = []
        for dev in devices:
            outcome = push_service.send_push(
                dev.get("fcm_token", ""), subject, body,
                data={"job_id": job_id, "event": event})
            if outcome == "unregistered":
                dead.append(dev.get("fcm_token"))
        if dead:
            with _device_tokens_lock:
                _device_tokens[cid] = [
                    e for e in _device_tokens.get(cid, [])
                    if e.get("fcm_token") not in dead]
                _save_device_tokens()
    except Exception as e:
        print(f"[push] _push_job_event failed (non-fatal): {e}")
```

- [ ] **Step 4: Iniettare in `generation_engine` e agganciare COMPLETE/ERROR**

1. In `generation_engine.py`, firma `configure` (~riga 169): aggiungere parametro keyword `send_push_fn=None`; nel corpo, `global _send_push; _send_push = send_push_fn` (dichiarare `_send_push = None` a livello modulo accanto agli altri global).
2. In `audiobook_app.py`, chiamata `generation_engine.configure(...)` (~riga 11645): aggiungere `send_push_fn=_push_job_event`.
3. In `generation_engine.py`, nel post-COMPLETE di `run_generation` (grep `post-COMPLETE: triggering email`, ~riga 4349), PRIMA del blocco `if notify_email:` aggiungere:

```python
    if _send_push:
        try:
            _book_title = ""
            try:
                _info = job.get("info")
                _book_title = getattr(_info, "title", "") or ""
            except Exception:
                pass
            _send_push(job_id, "done", _book_title)
        except Exception as _push_err:
            print(f"[{job_id}] push notify failed (non-fatal): {_push_err}")
```

4. Path di errore: dentro `_notify_user_gemini_job_failed` (grep `def _notify_user_gemini_job_failed`), all'inizio del corpo aggiungere lo stesso blocco con evento `"error"`:

```python
    if _send_push:
        try:
            _send_push(job_id, "error", "")
        except Exception as _push_err:
            print(f"[{job_id}] push notify failed (non-fatal): {_push_err}")
```

Nota esecutore: se esistono altri punti in cui `job["status"]` passa a `"error"` senza passare da `_notify_user_gemini_job_failed` (grep `_set_job_status(job, "error")`), NON coprirli tutti in questo task: il path Gemini è quello con refund/notifica utente; estensioni ulteriori sono YAGNI per l'MVP.

- [ ] **Step 5: Test mirato dell'aggancio post-COMPLETE**

Aggiungere a `test/test_mobile_api.py`:

```python
def test_generation_engine_calls_send_push_on_complete(monkeypatch):
    import generation_engine as ge
    pushed = []
    monkeypatch.setattr(ge, "_send_push",
                        lambda jid, event, title: pushed.append((jid, event)))
    # Il blocco push nel post-COMPLETE deve essere isolabile: lo testiamo
    # indirettamente verificando che configure() accetti e bindi il parametro.
    ge.configure(
        jobs={}, upload_dir=None, download_tokens={},
        save_tokens_fn=lambda: None, log_activity_fn=lambda *a, **k: None,
        send_push_fn=lambda jid, event, title: pushed.append((jid, event)),
    )
    assert ge._send_push is not None
    ge._send_push("j1", "done", "T")
    assert pushed[-1] == ("j1", "done")
```

Nota esecutore: dopo questo test, ri-eseguire `generation_engine.configure` non è necessario per gli altri test (il modulo viene riconfigurato dai test che lo usano); se la suite completa mostra pollution da questa configure minimale, spostare il test in fondo al file o ripristinare i binding originali nel teardown con i valori letti prima della chiamata.

- [ ] **Step 6: Eseguire i test e verifica sintassi**

Run: `pytest test/test_mobile_api.py test/test_push_service.py -v --tb=short`
Expected: tutti PASS
Run: `python -m py_compile audiobook_app.py generation_engine.py`

- [ ] **Step 7: Commit**

```powershell
git add audiobook_app.py generation_engine.py test/test_mobile_api.py
git commit -m "feat(mobile): push FCM al COMPLETE/ERROR via send_push_fn iniettata"
```

---

### Task 7: Download con Range/resume (`conditional=True`)

Flask gestisce `Range`/`206` da solo se `send_file(..., conditional=True)`. Si abilita nel wrapper `_send_file_throttled` con un parametro opt-in, attivato sugli endpoint file usati dall'app (m4b/mp3/zip/abm).

**Files:**
- Modify: `audiobook_app.py` — `_send_file_throttled` (~riga 1073) e le chiamate in `/api/download/<job_id>` (~righe 10561-10726), `/dl/<token>/m4b` (~9469-9524), `/dl/<token>/abm` (~9390-9428), `/dl/<token>/download` (~9603)
- Test: `test/test_mobile_api.py`

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere a `test/test_mobile_api.py`:

```python
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
```

Nota esecutore: leggere il corpo reale di `/dl/<token>/m4b` (~riga 9469) prima di eseguire: se la route richiede altri campi token o passaggi (cold storage check, marker `downloaded_at`), adeguare il seed del token mantenendo l'assert su 206 + Content-Range.

- [ ] **Step 2: Eseguire il test e verificarne il fallimento**

Run: `pytest test/test_mobile_api.py::test_dl_token_m4b_supports_range -v --tb=short`
Expected: FAIL — status 200 con file intero (Range ignorato)

- [ ] **Step 3: Implementare**

1. `_send_file_throttled` (~riga 1073): aggiungere parametro `conditional=False` alla firma e propagarlo:

```python
def _send_file_throttled(file_path, as_attachment=True, download_name=None,
                         mimetype=None, no_cache=False, bypass_throttle=False,
                         conditional=False, **kwargs):
    ...
    response = send_file(file_path, as_attachment=as_attachment,
                         download_name=download_name, mimetype=mimetype,
                         conditional=conditional, **kwargs)
```

2. Aggiungere `conditional=True` alle chiamate `_send_file_throttled` dei file binari scaricati dall'app: in `/api/download/<job_id>` (m4b, kit zip, mp3, zip, abm) e in `/dl/<token>/m4b`, `/dl/<token>/abm`, `/dl/<token>/download`. NON toccare le risposte non-file (preview, json).

Attenzione: con `conditional=True` Flask può rispondere `304` o `206`; verificare che la logica di `downloaded_at`/`_log_activity` su `/dl/<token>/m4b` già esclude le richieste `Range` dal logging (verificato: `if request.method != "HEAD" and not request.headers.get("Range")`, ~riga 9520) — comportamento corretto, nessuna modifica.

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest test/test_mobile_api.py -v --tb=short`
Expected: tutti PASS
Run: `python -m py_compile audiobook_app.py`

- [ ] **Step 5: Regressioni sui download esistenti**

Run: `pytest test/test_cold_redirect.py test/test_hot_eviction.py -v --tb=short`
Expected: PASS (o stessi fallimenti pre-esistenti su main, da annotare)

- [ ] **Step 6: Commit**

```powershell
git add audiobook_app.py test/test_mobile_api.py
git commit -m "feat(mobile): download con Range/resume (conditional=True) su m4b/mp3/zip/abm"
```

---

### Task 8: Documentazione parametri + suite completa

**Files:**
- Modify: `PARAMETRI_CONFIGURAZIONE.md` (sezione nuova "Push FCM (app mobile)")

- [ ] **Step 1: Aggiornare `PARAMETRI_CONFIGURAZIONE.md`**

Aggiungere (nella sezione delle variabili d'ambiente, stile delle voci esistenti):

```markdown
### Push FCM (app mobile)

| Variabile | Descrizione | Default | Sorgente |
|-----------|-------------|---------|----------|
| `ABM_FCM_CREDENTIALS_FILE` | Path del service-account JSON Firebase per le notifiche push FCM HTTP v1 (push disabilitate se vuota) | *(empty)* | `push_service.py` |

Costanti interne: `_SEND_RETRIES = 3` (tentativi invio push con backoff 1s/2s/4s, `push_service.py`); `_MAX_DEVICES_PER_CLIENT = 5` (device FCM per client, `audiobook_app.py`); file di persistenza `_device_tokens.json` in `ABM_DATA_DIR`.
```

Adeguare formato/posizione allo stile reale del file (leggerne la struttura prima di inserire).

- [ ] **Step 2: Suite completa**

Run: `pytest test/ -v --tb=short`
Expected: nessun nuovo fallimento rispetto a `abm_mobile` pre-piano (noti: i 4 `test_paypal_create_gemini` possono fallire per pollution da reload nella suite completa — pre-esistente, verificare che fallissero anche prima).

- [ ] **Step 3: Commit finale**

```powershell
git add PARAMETRI_CONFIGURAZIONE.md
git commit -m "docs(config): variabili push FCM app mobile"
```

NON fare push: richiede sempre conferma esplicita dell'utente.

---

## Note per l'esecutore

- **Ancore di riga**: rilevate su `main` il 2026-06-12; su `abm_mobile` possono differire di poco. Usare sempre grep sul simbolo indicato, mai la riga cieca.
- **Mai `importlib.reload(audiobook_app)`** nei test nuovi: causa pollution della suite (lezione di `test_paypal_create_gemini.py`).
- **Mai import di `audiobook_app` da `push_service` o `generation_engine`**: il re-import dell'entry-point ri-esegue l'app (incidente documentato). La direzione è sempre audiobook_app → configure() → sub-modulo.
- I nomi esatti di costanti/funzioni citati (es. `DATA_DIR`, `_effective_retention_for_token_info`) vanno verificati con grep al primo uso: se il nome reale differisce, usare quello reale e segnalarlo nel commit.
