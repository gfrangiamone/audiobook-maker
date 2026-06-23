"""Test API condivisione audiolibro (share)."""
import time

import pytest

import audiobook_app
import storage_backend


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


HDR = {"X-ABM-Cid": "mobile-cid-12345"}


def test_presigned_put_url_builds_put(monkeypatch):
    class FakeClient:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            assert op == "put_object"
            return f"https://r2/{Params['Key']}?X-Amz-Expires={ExpiresIn}"

    monkeypatch.setattr(storage_backend, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(storage_backend, "_BUCKET", "b")
    monkeypatch.setattr(storage_backend, "_KEY_PREFIX", "")
    url = storage_backend.presigned_put_url("shares/abc/x.m4b", ttl=3600)
    assert "shares/abc/x.m4b" in url
    assert "3600" in url


def test_share_config_defaults():
    assert audiobook_app.ABM_SHARE_TTL_SEC == 7200
    assert audiobook_app.ABM_SHARE_MAX_BYTES == 524288000
    assert audiobook_app.ABM_SHARE_UPLOAD_TTL_SEC == 3600


def test_share_tokens_save_load_roundtrip(monkeypatch, tmp_path):
    import json
    import pathlib
    f = tmp_path / "_share_tokens.json"
    monkeypatch.setattr(audiobook_app, "_SHARE_TOKENS_FILE", pathlib.Path(f))
    monkeypatch.setattr(audiobook_app, "_share_tokens", {
        "STOK": {"kind": "upload", "s3_key": "shares/a/x.m4b",
                 "filename": "x.m4b", "client_id": "mobile-cid-12345",
                 "created_at": time.time(), "ttl_sec": 7200}
    })
    audiobook_app._save_share_tokens()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert "STOK" in data
    assert data["STOK"]["s3_key"] == "shares/a/x.m4b"
    # reload
    monkeypatch.setattr(audiobook_app, "_share_tokens", {})
    audiobook_app._load_share_tokens()
    assert audiobook_app._share_tokens["STOK"]["kind"] == "upload"


def test_find_available_download_token(monkeypatch):
    now = time.time()
    monkeypatch.setattr(audiobook_app, "_download_tokens", {
        "T1": {"job_id": "J1", "client_id": "mobile-cid-12345",
               "created_at": now - 60, "is_gemini": False},
        "T2": {"job_id": "J1", "client_id": "ALTRO",
               "created_at": now - 60, "is_gemini": False},
        "T3": {"job_id": "J2", "client_id": "mobile-cid-12345",
               "created_at": now - 10 * 365 * 86400, "is_gemini": False},
    })
    assert audiobook_app._find_available_download_token("J1", "mobile-cid-12345", now) == "T1"
    # job di altri / scaduto -> None
    assert audiobook_app._find_available_download_token("J1", "x", now) is None
    assert audiobook_app._find_available_download_token("J2", "mobile-cid-12345", now) is None


def test_safe_share_filename():
    assert audiobook_app._safe_share_filename("../../etc/passwd") == "passwd"
    assert audiobook_app._safe_share_filename("Il mio libro.m4b") == "Il_mio_libro.m4b"
    assert audiobook_app._safe_share_filename("") == "audiolibro.m4b"


def test_share_link_for(monkeypatch):
    monkeypatch.setenv("ABM_BASE_URL", "https://audiobook-maker.com")
    assert audiobook_app._share_link_for("ABC") == "https://audiobook-maker.com/s/ABC"


def test_share_create_ready_for_available_job(client, monkeypatch):
    now = time.time()
    monkeypatch.setattr(audiobook_app, "_download_tokens", {
        "DLT": {"job_id": "JOBA", "client_id": "mobile-cid-12345",
                "created_at": now - 30, "is_gemini": False,
                "output_m4b": "/x/out.m4b"},
    })
    monkeypatch.setattr(audiobook_app, "_share_tokens", {})
    monkeypatch.setattr(audiobook_app, "_save_share_tokens", lambda: None)
    monkeypatch.setenv("ABM_BASE_URL", "https://audiobook-maker.com")
    r = client.post("/api/share/create", headers=HDR, json={"job_id": "JOBA"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["mode"] == "ready"
    assert data["link"].startswith("https://audiobook-maker.com/s/")
    assert data["ttl_sec"] == 7200
    rec = audiobook_app._share_tokens[data["share_token"]]
    assert rec["kind"] == "ready"
    assert rec["download_token"] == "DLT"
    assert rec["client_id"] == "mobile-cid-12345"


def test_share_create_upload_when_no_job(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_download_tokens", {})
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: f"https://r2/PUT/{key}")
    monkeypatch.setenv("ABM_BASE_URL", "https://audiobook-maker.com")
    r = client.post("/api/share/create", headers=HDR,
                    json={"filename": "Il mio libro.m4b"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["mode"] == "upload"
    assert data["filename"] == "Il_mio_libro.m4b"
    assert "shares/" in data["upload_url"] and "Il_mio_libro.m4b" in data["upload_url"]
    assert data["max_bytes"] == 524288000


def test_share_create_requires_cid(client):
    r = client.post("/api/share/create", json={"job_id": "X"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "no_cid"


def test_share_create_upload_unavailable_without_s3(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_download_tokens", {})
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    r = client.post("/api/share/create", headers=HDR, json={"filename": "x.m4b"})
    assert r.status_code == 503
    assert r.get_json()["error_code"] == "upload_unavailable"


def test_share_finalize_ok(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_share_tokens", {})
    monkeypatch.setattr(audiobook_app, "_save_share_tokens", lambda: None)
    monkeypatch.setattr(storage_backend, "object_size", lambda key: 1234)
    monkeypatch.setenv("ABM_BASE_URL", "https://audiobook-maker.com")
    r = client.post("/api/share/finalize", headers=HDR,
                    json={"share_id": "SID1", "filename": "x.m4b"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["link"].startswith("https://audiobook-maker.com/s/")
    rec = audiobook_app._share_tokens[data["share_token"]]
    assert rec["kind"] == "upload"
    assert rec["s3_key"] == "shares/SID1/x.m4b"


def test_share_finalize_not_uploaded(client, monkeypatch):
    monkeypatch.setattr(storage_backend, "object_size", lambda key: None)
    r = client.post("/api/share/finalize", headers=HDR,
                    json={"share_id": "SID2", "filename": "x.m4b"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "not_uploaded"


def test_share_finalize_too_large_deletes(client, monkeypatch):
    deleted = []
    monkeypatch.setattr(storage_backend, "object_size",
                        lambda key: 600 * 1024 * 1024)
    monkeypatch.setattr(storage_backend, "delete_object", lambda key: deleted.append(key))
    r = client.post("/api/share/finalize", headers=HDR,
                    json={"share_id": "SID3", "filename": "big.m4b"})
    assert r.status_code == 413
    assert r.get_json()["error_code"] == "too_large"
    assert deleted == ["shares/SID3/big.m4b"]


def test_share_claim_expired_returns_410(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_share_tokens", {
        "S": {"kind": "upload", "s3_key": "shares/a/x.m4b", "filename": "x.m4b",
              "client_id": "c", "created_at": time.time() - 9999, "ttl_sec": 7200}
    })
    r = client.get("/api/share/claim/S")
    assert r.status_code == 410
    assert r.get_json()["error_code"] == "expired"


def test_share_claim_unknown_returns_404(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_share_tokens", {})
    r = client.get("/api/share/claim/NOPE")
    assert r.status_code == 404


def test_share_claim_ok_returns_dl_url(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_share_tokens", {
        "S": {"kind": "upload", "s3_key": "shares/a/x.m4b", "filename": "x.m4b",
              "client_id": "c", "created_at": time.time(), "ttl_sec": 7200}
    })
    monkeypatch.setenv("ABM_BASE_URL", "https://audiobook-maker.com")
    r = client.get("/api/share/claim/S")
    assert r.status_code == 200
    data = r.get_json()
    assert data["download_url"] == "https://audiobook-maker.com/s/S/dl"
    assert data["filename"] == "x.m4b"
    assert data["ttl_sec_remaining"] > 0


def test_share_dl_upload_redirects_presigned(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_share_tokens", {
        "S": {"kind": "upload", "s3_key": "shares/a/x.m4b", "filename": "x.m4b",
              "client_id": "c", "created_at": time.time(), "ttl_sec": 7200}
    })
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_exists", lambda key: True)
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, download_name=None, ttl=None: f"https://r2/GET/{key}")
    r = client.get("/s/S/dl")
    assert r.status_code in (302, 303)
    assert r.headers["Location"] == "https://r2/GET/shares/a/x.m4b"


def test_share_dl_ready_serves_file(client, tmp_path, monkeypatch):
    f = tmp_path / "out.m4b"
    f.write_bytes(b"0123456789")
    monkeypatch.setattr(audiobook_app, "_download_tokens", {
        "DLT": {"job_id": "J", "client_id": "c", "created_at": time.time(),
                "book_title": "Libro", "output_m4b": str(f), "output_format": "m4b",
                "is_gemini": False},
    })
    monkeypatch.setattr(audiobook_app, "_share_tokens", {
        "S": {"kind": "ready", "download_token": "DLT", "client_id": "c",
              "created_at": time.time(), "ttl_sec": 7200}
    })
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    r = client.get("/s/S/dl")
    assert r.status_code == 200
    assert r.data == b"0123456789"


def test_share_dl_expired_410(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_share_tokens", {
        "S": {"kind": "upload", "s3_key": "shares/a/x.m4b", "filename": "x.m4b",
              "client_id": "c", "created_at": time.time() - 9999, "ttl_sec": 7200}
    })
    r = client.get("/s/S/dl")
    assert r.status_code == 410


def test_share_landing_served(client):
    r = client.get("/s/ANYTOKEN")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")


def test_cleanup_expired_shares(monkeypatch):
    now = time.time()
    deleted = []
    monkeypatch.setattr(storage_backend, "delete_object", lambda key: deleted.append(key))
    monkeypatch.setattr(audiobook_app, "_save_share_tokens", lambda: None)
    monkeypatch.setattr(audiobook_app, "_share_tokens", {
        "OLD_UP": {"kind": "upload", "s3_key": "shares/a/x.m4b",
                   "created_at": now - 9999, "ttl_sec": 7200},
        "OLD_RD": {"kind": "ready", "download_token": "DLT",
                   "created_at": now - 9999, "ttl_sec": 7200},
        "FRESH": {"kind": "upload", "s3_key": "shares/b/y.m4b",
                  "created_at": now, "ttl_sec": 7200},
    })
    n = audiobook_app._cleanup_expired_shares(now)
    assert n == 2
    assert deleted == ["shares/a/x.m4b"]  # solo l'upload scaduto cancella su R2
    assert set(audiobook_app._share_tokens.keys()) == {"FRESH"}


def test_share_finalize_storage_error_returns_502(client, monkeypatch):
    def _boom(key):
        raise RuntimeError("r2 down")
    monkeypatch.setattr(storage_backend, "object_size", _boom)
    r = client.post("/api/share/finalize", headers=HDR,
                    json={"share_id": "SIDX", "filename": "x.m4b"})
    assert r.status_code == 502
    assert r.get_json()["error_code"] == "storage_error"


def test_share_dl_storage_error_returns_502(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_share_tokens", {
        "S": {"kind": "upload", "s3_key": "shares/a/x.m4b", "filename": "x.m4b",
              "client_id": "c", "created_at": __import__("time").time(), "ttl_sec": 7200}
    })
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    def _boom(key):
        raise RuntimeError("r2 down")
    monkeypatch.setattr(storage_backend, "object_exists", _boom)
    r = client.get("/s/S/dl")
    assert r.status_code == 502
