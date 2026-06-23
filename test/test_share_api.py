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
