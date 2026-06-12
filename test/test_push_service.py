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
