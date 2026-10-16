# test/test_user_archive.py
"""Archivio dell'app: libri archiviati dallo smartphone su R2 entro la quota
dell'abbonamento, collegamento ai job gia' archiviati, grazia dopo la revoca."""
import hashlib

import pytest

import accounts
import db
import storage_backend
import user_archive


T0 = 1_800_000_000
GIB = accounts.GIB
FP = "a" * 64


class FakeR2:
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.fail_delete = False

    def install(self, monkeypatch):
        monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
        monkeypatch.setattr(storage_backend, "presigned_put_url", lambda k, ttl=None: f"https://r2/put/{k}")
        monkeypatch.setattr(storage_backend, "presigned_get_url",
                            lambda k, download_name=None, ttl=None: f"https://r2/get/{k}")
        monkeypatch.setattr(storage_backend, "object_size",
                            lambda k: len(self.objects[k]) if k in self.objects else None)
        monkeypatch.setattr(storage_backend, "get_range",
                            lambda k, s, e: self.objects.get(k, b"")[s:e + 1])
        monkeypatch.setattr(storage_backend, "delete_object", self.delete)
        monkeypatch.setattr(storage_backend, "object_exists", lambda k: k in self.objects)

    def delete(self, k):
        if self.fail_delete:
            raise RuntimeError("r2 down")
        self.deleted.append(k)
        self.objects.pop(k, None)


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(accounts, "_voice_ids_for_email", None)
    monkeypatch.setattr(accounts, "_unlink_voice", None)
    accounts._archive_cache_clear()
    user_archive._sweep_state["at"] = 0.0
    r2 = FakeR2()
    r2.install(monkeypatch)
    yield r2
    accounts._archive_cache_clear()
    db.close()


def _login(email="a@b.it", plan="archive_10"):
    token, code = accounts.request_code(email, "login", "it", now=T0)
    status, acct = accounts.verify(token=token, code=code, purpose="login", now=T0)
    assert status == "ok"
    if plan:
        accounts.set_plan(acct["id"], plan, now=T0)
    return accounts.get(acct["id"])


def _create(acct, fp=FP, size=100, **kw):
    return user_archive.create(acct, fingerprint=fp, size=size, filename="Libro.m4b",
                               title="Titolo", author="Autore", duration_ms=1234, now=T0, **kw)


# ------------------------------------------------------------ fingerprint

def _dart_fp(data):
    """Riferimento: shareFingerprint dell'app (lib/core/api/share_fingerprint.dart)."""
    n = len(data)
    body = data if n <= 128 * 1024 else data[:65536] + data[-65536:]
    return hashlib.sha256(f"{n}:".encode() + body).hexdigest()


@pytest.mark.parametrize("n", [10, 128 * 1024, 300_000])
def test_fingerprint_matches_app(env, tmp_path, n):
    data = bytes((i * 7) % 251 for i in range(n))
    p = tmp_path / "f.m4b"
    p.write_bytes(data)
    assert user_archive.fingerprint_local(str(p)) == (_dart_fp(data), n)
    env.objects["k"] = data
    assert user_archive.fingerprint_cold("k") == (_dart_fp(data), n)


# ------------------------------------------------------------ create/finalize

def test_upload_flow_reserves_quota_and_finalizes(env):
    acct = _login()
    st, res = _create(acct)
    assert st == "upload"
    item = res["item"]
    assert item["state"] == "pending"
    assert item["r2_key"] == f"user_archive/{acct['id']}/{item['id']}.m4b"
    assert res["upload_url"].endswith(item["r2_key"])
    assert accounts.archive_usage(acct["id"])[0] == 100        # prenotata
    assert user_archive.finalize(acct, item["id"])[0] == "not_uploaded"
    env.objects[item["r2_key"]] = b"x" * 100
    st, ready = user_archive.finalize(acct, item["id"])
    assert st == "ready" and ready["state"] == "ready"
    assert user_archive.public(ready)["source"] == "upload"
    # Stesso fingerprint: gia' in archivio, nessun nuovo upload.
    assert _create(acct)[0] == "linked"
    assert accounts.archive_status(acct)["items"] == 1


def test_finalize_size_mismatch_drops_item(env):
    acct = _login()
    item = _create(acct)[1]["item"]
    env.objects[item["r2_key"]] = b"x" * 99
    assert user_archive.finalize(acct, item["id"])[0] == "size_mismatch"
    assert item["r2_key"] in env.deleted
    assert user_archive.get_item(acct["id"], item["id"]) is None
    assert accounts.archive_usage(acct["id"])[0] == 0


def test_retry_of_pending_reuses_item(env):
    acct = _login()
    first = _create(acct)[1]["item"]
    second = _create(acct, size=120)[1]["item"]
    assert first["id"] == second["id"] and second["size_bytes"] == 120
    assert accounts.archive_usage(acct["id"])[0] == 120


def test_quota_exceeded(env, monkeypatch):
    monkeypatch.setitem(accounts.ARCHIVE_PLANS, "archive_10", 1)
    acct = _login()
    accounts.record_job(acct["id"], "j1", kind="generate", status="done")
    accounts.mark_archived("j1", GIB - 50)
    st, res = _create(acct, size=51)
    assert st == "quota"
    assert res == {"quota_bytes": GIB, "used_bytes": GIB - 50, "needed_bytes": 51}
    assert _create(acct, size=50)[0] == "upload"


def test_inactive_and_bad_requests(env):
    free = _login("f@b.it", plan=None)
    assert _create(free)[0] == "inactive"
    acct = _login()
    assert _create(acct, fp="xyz")[0] == "bad_request"
    assert _create(acct, size=0)[0] == "bad_request"
    assert user_archive.create(acct, fingerprint=FP, size=10, filename="a.exe")[0] == "bad_request"


def test_too_large_and_unavailable(env, monkeypatch):
    acct = _login()
    monkeypatch.setenv("ABM_ARCHIVE_ITEM_MAX_BYTES", "10")
    assert _create(acct, size=11)[0] == "too_large"
    monkeypatch.delenv("ABM_ARCHIVE_ITEM_MAX_BYTES")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    assert _create(acct)[0] == "unavailable"


# ------------------------------------------------------------ collegamento ai job

def _job_file(monkeypatch, tmp, job_id, data):
    d = tmp / job_id / "output_1"
    d.mkdir(parents=True)
    p = d / "book.m4b"
    p.write_bytes(data)
    monkeypatch.setattr(user_archive.storage_tiering, "key_for_path",
                        lambda path: str(path).replace("\\", "/").split(str(tmp).replace("\\", "/") + "/", 1)[-1])
    return str(p)


def test_links_archived_job_with_same_content(env, tmp_path, monkeypatch):
    acct = _login()
    data = b"m4b-content" * 10
    path = _job_file(monkeypatch, tmp_path, "j1", data)
    accounts.record_job(acct["id"], "j1", kind="generate", status="done")
    cands = [(path, "m4b", "tok1")]
    # Job non ancora archiviato: si carica.
    assert _create(acct, fp=_dart_fp(data), size=len(data), job_candidates=cands)[0] == "upload"
    with db.tx() as c:
        c.execute("DELETE FROM archive_items")
    accounts.mark_archived("j1", 5000)
    st, item = _create(acct, fp=_dart_fp(data), size=len(data), job_candidates=cands)
    assert st == "linked"
    assert item["job_id"] == "j1" and item["link_token"] == "tok1" and item["r2_key"] == ""
    assert accounts.archive_usage(acct["id"]) == (5000, 1)   # nessun byte in piu'
    # Il job nascosto dall'area personale resta archiviato finche' collegato.
    assert accounts.hide_job(acct["id"], "j1") == "ok"
    assert accounts.archive_protects("j1")
    assert accounts.archive_usage(acct["id"]) == (5000, 1)
    assert user_archive.delete(acct, item["id"]) == "ok"
    accounts._archive_cache_clear()
    assert not accounts.archive_protects("j1")


def test_link_refuses_other_content_or_other_owner(env, tmp_path, monkeypatch):
    acct, other = _login(), _login("o@b.it")
    path = _job_file(monkeypatch, tmp_path, "j1", b"abc" * 50)
    accounts.record_job(other["id"], "j1", kind="generate", status="done")
    accounts.mark_archived("j1", 10)
    cands = [(path, "m4b", "tok1")]
    assert _create(acct, fp=_dart_fp(b"abc" * 50), size=150, job_candidates=cands)[0] == "upload"
    assert _create(other, fp=_dart_fp(b"zzz"), size=3, job_candidates=cands)[0] == "upload"


# ------------------------------------------------------------ delete/sweep/stato

def test_delete_keeps_row_when_r2_fails(env):
    acct = _login()
    item = _create(acct)[1]["item"]
    env.objects[item["r2_key"]] = b"x" * 100
    user_archive.finalize(acct, item["id"])
    env.fail_delete = True
    assert user_archive.delete(acct, item["id"]) == "storage_error"
    assert user_archive.get_item(acct["id"], item["id"]) is not None
    env.fail_delete = False
    assert user_archive.delete(acct, item["id"]) == "ok"
    assert user_archive.delete(acct, item["id"]) == "not_found"


def test_sweep_drops_stale_pending(env):
    acct = _login()
    item = _create(acct)[1]["item"]
    assert user_archive.sweep(now=T0 + 10, force=True)["pending"] == 0
    out = user_archive.sweep(now=T0 + user_archive.PENDING_TTL_SEC + 1, force=True)
    assert out["pending"] == 1
    assert user_archive.get_item(acct["id"], item["id"]) is None


def test_grace_status_then_sweep_deletes(env, monkeypatch):
    monkeypatch.setenv("ABM_ARCHIVE_GRACE_DAYS", "30")
    acct = _login()
    item = _create(acct)[1]["item"]
    env.objects[item["r2_key"]] = b"x" * 100
    user_archive.finalize(acct, item["id"], now=T0)
    accounts.set_plan(acct["id"], "free", now=T0 + 100)
    acct = accounts.get(acct["id"])
    st = accounts.archive_status(acct, now=T0 + 200)
    assert st["state"] == "grace" and st["grace_until"] == T0 + 100 + 30 * 86400
    assert st["items"] == 1
    assert _create(acct)[0] == "inactive"                    # niente nuovi ingressi
    assert user_archive.sweep(now=T0 + 200, force=True)["expired"] == 0
    out = user_archive.sweep(now=T0 + 100 + 30 * 86400, force=True)
    assert out["expired"] == 1 and item["r2_key"] in env.deleted
    assert accounts.archive_status(acct, now=T0 + 100 + 30 * 86400 + 1) is None


def test_sweep_purges_deleted_accounts_and_is_rate_limited(env):
    acct = _login()
    item = _create(acct)[1]["item"]
    accounts.delete_account(acct["id"], now=T0)
    assert user_archive.sweep(now=T0 + 1)["expired"] == 1
    assert user_archive.get_item(acct["id"], item["id"]) is None
    assert user_archive.sweep(now=T0 + 2) == {"pending": 0, "expired": 0, "errors": 0}


def test_active_status_shape(env):
    acct = _login()
    st = accounts.archive_status(acct)
    assert st == {"plan": "archive_10", "quota_bytes": 10 * GIB, "used_bytes": 0, "jobs": 0,
                  "items": 0, "state": "active", "grace_until": None}


# ------------------------------------------------------------ route

@pytest.fixture
def client(env, monkeypatch, tmp_path):
    import audiobook_app
    import routes_account
    # Il primo import della app apre il suo abm.db: si torna a quello del test.
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_ip_rl_check", lambda *a, **k: (True, 0))
    acct = _login()
    holder = {"acct": None}
    monkeypatch.setattr(routes_account, "_current_account", lambda: holder["acct"])
    return audiobook_app.app.test_client(), holder, acct


def test_routes_require_login(client):
    c, _holder, _acct = client
    assert c.get("/api/account/archive").status_code == 401
    assert c.post("/api/account/archive/create", json={}).status_code == 401
    assert c.get("/api/account/archive/download?id=x").status_code == 401


def test_routes_full_cycle(client, env):
    c, holder, acct = client
    holder["acct"] = acct
    body = {"fingerprint": FP, "size_bytes": 100, "filename": "Libro.m4b", "title": "T"}
    r = c.post("/api/account/archive/create", json=body)
    assert r.status_code == 200 and r.get_json()["mode"] == "upload"
    item_id = r.get_json()["item"]["id"]
    assert "r2_key" not in r.get_json()["item"]
    assert c.post("/api/account/archive/finalize", json={"item_id": item_id}).status_code == 400
    env.objects[f"user_archive/{acct['id']}/{item_id}.m4b"] = b"x" * 100
    r = c.post("/api/account/archive/finalize", json={"item_id": item_id})
    assert r.get_json()["item"]["state"] == "ready"
    r = c.get("/api/account/archive").get_json()
    assert [i["id"] for i in r["items"]] == [item_id]
    assert r["archive"]["state"] == "active" and r["archive"]["used_bytes"] == 100
    r = c.get(f"/api/account/archive/download?id={item_id}").get_json()
    assert r["url"].startswith("https://r2/get/user_archive/") and r["filename"] == "Libro.m4b"
    assert c.post("/api/account/archive/create", json=body).get_json()["mode"] == "linked"
    assert c.post("/api/account/archive/delete", json={"item_id": item_id}).status_code == 200
    assert c.get(f"/api/account/archive/download?id={item_id}").status_code == 404


def test_route_quota_and_inactive(client, monkeypatch):
    c, holder, acct = client
    holder["acct"] = acct
    monkeypatch.setitem(accounts.ARCHIVE_PLANS, "archive_10", 1)
    body = {"fingerprint": FP, "size_bytes": GIB + 1, "filename": "L.m4b"}
    r = c.post("/api/account/archive/create", json=body)
    assert r.status_code == 409
    j = r.get_json()
    assert j["error_code"] == "archive_quota_exceeded" and j["needed_bytes"] == GIB + 1
    holder["acct"] = _login("f@b.it", plan=None)
    r = c.post("/api/account/archive/create", json=body)
    assert r.status_code == 403 and r.get_json()["error_code"] == "archive_inactive"


def test_route_download_of_linked_job(client, tmp_path, monkeypatch):
    import token_store
    c, holder, acct = client
    holder["acct"] = acct
    data = b"job-audio" * 20
    path = _job_file(monkeypatch, tmp_path, "j1", data)
    accounts.record_job(acct["id"], "j1", kind="generate", status="done")
    accounts.mark_archived("j1", 1000)
    monkeypatch.setitem(token_store.download_tokens, "tok1", {"job_id": "j1", "output_m4b": path})
    body = {"fingerprint": _dart_fp(data), "size_bytes": len(data), "filename": "L.m4b",
            "job_id": "j1"}
    r = c.post("/api/account/archive/create", json=body).get_json()
    assert r["mode"] == "linked" and r["item"]["source"] == "job"
    d = c.get(f"/api/account/archive/download?id={r['item']['id']}").get_json()
    assert d["url"].endswith("/dl/tok1/m4b")


# ------------------------------------------------------------ condivisione

def _ready_item(client_fixture, env):
    c, holder, acct = client_fixture
    holder["acct"] = acct
    body = {"fingerprint": FP, "size_bytes": 100, "filename": "Libro.m4b", "title": "T"}
    item_id = c.post("/api/account/archive/create", json=body).get_json()["item"]["id"]
    env.objects[f"user_archive/{acct['id']}/{item_id}.m4b"] = b"x" * 100
    c.post("/api/account/archive/finalize", json={"item_id": item_id})
    return c, acct, item_id


def test_archive_share_link_downloads_from_archive(client, env, monkeypatch):
    import token_store
    monkeypatch.setattr(token_store, "share_tokens", {})
    monkeypatch.setattr(token_store, "save_share_tokens", lambda: None)
    c, acct, item_id = _ready_item(client, env)
    r = c.post("/api/account/archive/share", json={"item_id": item_id})
    assert r.status_code == 200
    j = r.get_json()
    assert j["mode"] == "ready" and j["link"] and j["ttl_sec"] > 0
    tok = j["share_token"]
    info = token_store.share_tokens[tok]
    assert info["kind"] == "archive" and info["archive_item_id"] == item_id
    # Seconda richiesta: stessa share, nessun token nuovo.
    assert c.post("/api/account/archive/share", json={"item_id": item_id}).get_json()["share_token"] == tok
    claim = c.get(f"/api/share/claim/{tok}").get_json()
    assert claim["download_url"].endswith(f"/s/{tok}/dl") and claim["filename"] == "Libro.m4b"
    r = c.get(f"/s/{tok}/dl")
    assert r.status_code == 302
    assert r.headers["Location"] == f"https://r2/get/user_archive/{acct['id']}/{item_id}.m4b"
    # Libro tolto dall'archivio: il link smette di funzionare.
    c.post("/api/account/archive/delete", json={"item_id": item_id})
    assert c.get(f"/s/{tok}/dl").status_code == 410


def test_archive_share_requires_owner_and_ready_item(client, env, monkeypatch):
    import token_store
    monkeypatch.setattr(token_store, "share_tokens", {})
    monkeypatch.setattr(token_store, "save_share_tokens", lambda: None)
    c, holder, acct = client
    assert c.post("/api/account/archive/share", json={"item_id": "x"}).status_code == 401
    holder["acct"] = acct
    pending = c.post("/api/account/archive/create",
                     json={"fingerprint": FP, "size_bytes": 1, "filename": "a.m4b"}).get_json()
    assert c.post("/api/account/archive/share",
                  json={"item_id": pending["item"]["id"]}).status_code == 404
    holder["acct"] = _login("o@b.it")
    assert c.post("/api/account/archive/share",
                  json={"item_id": pending["item"]["id"]}).status_code == 404


def test_expired_archive_share_keeps_archive_file(env, monkeypatch):
    import cleanup
    import token_store
    monkeypatch.setattr(token_store, "share_tokens", {"t": {
        "kind": "archive", "archive_item_id": "i", "account_id": "a",
        "s3_key": "user_archive/a/i.m4b", "created_at": 0, "ttl_sec": 1}})
    monkeypatch.setattr(token_store, "save_share_tokens", lambda: None)
    assert cleanup._cleanup_expired_shares(now=T0) == 1
    assert env.deleted == [] and token_store.share_tokens == {}


# ------------------------------------------------------------ job dell'area personale

def test_archive_jobs_listing_download_and_share(client, env, tmp_path, monkeypatch):
    import time as _t
    import token_store
    c, holder, acct = client
    holder["acct"] = acct
    monkeypatch.setattr(token_store, "share_tokens", {})
    monkeypatch.setattr(token_store, "save_share_tokens", lambda: None)
    data = b"job-audio-bytes" * 30
    path = _job_file(monkeypatch, tmp_path, "j1", data)
    now = _t.time()
    accounts.record_job(acct["id"], "j1", kind="generate", status="done", book_title="Libro J1",
                        output_format="m4b")
    accounts.record_job(acct["id"], "jr", kind="generate", status="running")
    accounts.record_job(acct["id"], "jt", kind="translate", status="done")
    monkeypatch.setitem(token_store.download_tokens, "tokJ1",
                        {"job_id": "j1", "output_m4b": path, "created_at": now})
    calls = []
    real_fp = user_archive.fingerprint_of
    monkeypatch.setattr(user_archive, "fingerprint_of", lambda p: calls.append(p) or real_fp(p))

    jobs = c.get("/api/account/archive/jobs").get_json()["jobs"]
    assert [j["job_id"] for j in jobs] == ["j1"]
    j = jobs[0]
    assert j["fingerprint"] == _dart_fp(data) and j["size_bytes"] == len(data)
    assert j["title"] == "Libro J1" and j["format"] == "m4b"
    assert j["archived"] is False and j["expires_at"] > now
    # Impronta in cache: secondo elenco senza ricalcolo.
    c.get("/api/account/archive/jobs")
    assert len(calls) == 1

    d = c.get("/api/account/archive/download?job_id=j1").get_json()
    assert d["url"].endswith("/dl/tokJ1/m4b") and d["filename"] == "Libro J1.m4b"
    assert c.get("/api/account/archive/download?job_id=nope").status_code == 410

    s = c.post("/api/account/archive/share", json={"job_id": "j1"}).get_json()
    info = token_store.share_tokens[s["share_token"]]
    assert info["kind"] == "ready" and info["download_token"] == "tokJ1"
    assert c.post("/api/account/archive/share", json={"job_id": "jt"}).status_code == 404

    # Job di un altro account: invisibile.
    holder["acct"] = _login("o@b.it")
    assert c.get("/api/account/archive/jobs").get_json()["jobs"] == []
    assert c.get("/api/account/archive/download?job_id=j1").status_code == 410
