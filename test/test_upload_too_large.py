"""Upload oltre MAX_CONTENT_LENGTH: /api/analyze deve rispondere 413 JSON, non HTML.

Bug riprodotto in prod: Werkzeug rifiuta il body con la pagina HTML standard
"413 Request Entity Too Large" e il frontend fa r.json() alla cieca ->
"JSON.parse: unexpected character at line 1 column 1".
"""
import io
from unittest.mock import patch

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def test_oversized_upload_returns_json_413(client):
    old = audiobook_app.app.config["MAX_CONTENT_LENGTH"]
    audiobook_app.app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB
    try:
        with patch("audiobook_app._ip_rl_check", return_value=(True, 0)):
            data = {"epub": (io.BytesIO(b"PK" + b"\x00" * (3 * 1024 * 1024)), "big.epub")}
            r = client.post("/api/analyze", data=data,
                            content_type="multipart/form-data")
    finally:
        audiobook_app.app.config["MAX_CONTENT_LENGTH"] = old
    assert r.status_code == 413
    assert r.is_json, f"risposta non JSON: {r.data[:120]!r}"
    body = r.get_json()
    assert body["error"] == "file_too_large"
    assert body["max_mb"] == 2
