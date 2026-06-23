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
