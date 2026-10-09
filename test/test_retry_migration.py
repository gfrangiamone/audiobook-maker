"""D2b: i loop dei motori su retry_util conservano tentativi e backoff.

Il numero di chiamate di rete per chunk resta quello di prima della
migrazione (gate del piano, passo 4): Speechify 3 tentativi HTTP dentro
`synthesize` x 3 del wrapper di chunk, VoxCPM 8 sottomissioni, push FCM 3,
offload cloud 3.
"""
import types

import pytest


class _Resp:
    def __init__(self, status, headers=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self.text = text


def test_speechify_synthesize_three_http_attempts_and_retry_after(monkeypatch, tmp_path):
    import speechify_tts as spx
    monkeypatch.setattr(spx, "is_available", lambda: True)
    monkeypatch.setattr(spx, "api_key", lambda: "k")
    monkeypatch.setattr(spx, "use_stream_api", lambda: False)
    waits = []
    monkeypatch.setattr(spx._retry, "retry_call",
                        lambda fn, **kw: _retry_recording(fn, kw, waits))
    posts = []
    session = types.SimpleNamespace(post=lambda *a, **k: posts.append(k) or _Resp(503, {"Retry-After": "0.5"}))
    with pytest.raises(RuntimeError, match="after 3 attempts: HTTP 503"):
        spx.synthesize("ciao", "speechify:simba-3.2:harper_32", str(tmp_path / "o.pcm"), session=session)
    assert len(posts) == 3 and waits == [0.5, 0.5]
    posts.clear(); waits.clear()
    session = types.SimpleNamespace(post=lambda *a, **k: posts.append(k) or _Resp(500))
    with pytest.raises(RuntimeError):
        spx.synthesize("ciao", "speechify:simba-3.2:harper_32", str(tmp_path / "o.pcm"), session=session)
    assert len(posts) == 3 and waits == [1.0, 2.0]                 # backoff 2**n, cap 30
    posts.clear()
    session = types.SimpleNamespace(post=lambda *a, **k: posts.append(k) or _Resp(400, text="bad ssml"))
    with pytest.raises(spx.SpeechifyFatalError):
        spx.synthesize("ciao", "speechify:simba-3.2:harper_32", str(tmp_path / "o.pcm"), session=session)
    assert len(posts) == 1                                          # 4xx: nessun retry


import retry_util as _ru

_REAL_RETRY_CALL = _ru.retry_call      # i moduli importano lo stesso oggetto modulo: si patcha quello


def _retry_recording(fn, kw, waits):
    """retry_call con sleep registrata (nessuna attesa reale)."""
    kw["sleep"] = waits.append
    return _REAL_RETRY_CALL(fn, **kw)


def test_speechify_chunk_wrapper_three_attempts_over_synthesize(monkeypatch, tmp_path):
    import tts_split, speechify_tts as spx
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("Read timed out")

    monkeypatch.setattr(spx, "synthesize", boom)
    monkeypatch.setattr(tts_split._retry, "retry_call",
                        lambda fn, **kw: _retry_recording(fn, kw, []))
    out = tts_split.generate_chunk_pcm_speechify("Testo abbastanza lungo.", "speechify:simba-3.2:harper_32",
                                                 str(tmp_path / "c.pcm"))
    assert len(calls) == 3 and not (isinstance(out, dict) and out.get("success"))
    calls.clear()

    def fatal(*a, **k):
        calls.append(1)
        raise spx.SpeechifyFatalError("ssml")

    monkeypatch.setattr(spx, "synthesize", fatal)
    out = tts_split.generate_chunk_pcm_speechify("Testo abbastanza lungo.", "speechify:simba-3.2:harper_32",
                                                 str(tmp_path / "c.pcm"))
    assert len(calls) == 1 and not (isinstance(out, dict) and out.get("success"))   # fatale: niente retry


def test_voxcpm_submit_eight_attempts_doubling_pause(monkeypatch):
    import voxcpm_tts as vx
    monkeypatch.setattr(vx, "_base", lambda: "https://ep")
    monkeypatch.setattr(vx, "_headers", lambda: {})
    posts, pauses = [], []
    session = types.SimpleNamespace(post=lambda *a, **k: posts.append(1) or _Resp(503))
    with pytest.raises(vx.VoxcpmSottomissioneFallita, match="HTTP 503"):
        vx._submit({"x": 1}, session, pauses.append)
    assert len(posts) == 8 and pauses == [2, 4, 8, 16, 32, 60, 60]
    posts.clear()
    session = types.SimpleNamespace(post=lambda *a, **k: posts.append(1) or _Resp(401, text="no"))
    with pytest.raises(vx.VoxcpmJobError):
        vx._submit({"x": 1}, session, pauses.append)
    assert len(posts) == 1


def test_voxcpm_scarica_retry_predicate_and_attempts(monkeypatch, tmp_path):
    import voxcpm_tts as vx
    import requests
    assert vx._scarica_ritentabile(None) and vx._scarica_ritentabile(503) and vx._scarica_ritentabile(429)
    assert not vx._scarica_ritentabile(403)
    calls, pauses = [], []

    def failing_get(*a, **k):
        calls.append(1)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(vx.requests, "get", failing_get)
    monkeypatch.setattr(vx, "_dormi", pauses.append)
    with pytest.raises(vx.VoxcpmConsegnaFallita, match="ConnectionError"):
        vx._scarica("https://r2/x", str(tmp_path / "cap.pcm"))
    assert len(calls) == 10 and pauses == [2, 4, 8, 16, 32, 60, 60, 60, 60]


def test_push_send_three_attempts(monkeypatch):
    import push_service as ps
    monkeypatch.setattr(ps, "is_available", lambda: True)
    monkeypatch.setattr(ps, "_get_credentials", lambda: types.SimpleNamespace(token="t"))
    monkeypatch.setattr(ps, "_load_project_id", lambda: "p")
    waits, posts = [], []
    monkeypatch.setattr(ps._retry, "retry_call", lambda fn, **kw: _retry_recording(fn, kw, waits))
    monkeypatch.setattr(ps.requests, "post", lambda *a, **k: posts.append(1) or _Resp(500, text="x"))
    assert ps.send_push("tok", "T", "B") == "error" and len(posts) == 3 and waits == [1.0, 2.0]
    posts.clear()
    monkeypatch.setattr(ps.requests, "post", lambda *a, **k: posts.append(1) or _Resp(404))
    assert ps.send_push("tok", "T", "B") == "unregistered" and len(posts) == 1


def test_gemini_parse_retry_after_delegates():
    import gemini_tts as g
    assert g._parse_retry_after(RuntimeError("retryDelay: 22371s")) == 22371.0
    assert g._parse_retry_after(RuntimeError("quota, retry in 6h12m51.7s")) == 6 * 3600 + 12 * 60 + 51.7
    assert g._parse_retry_after(RuntimeError("nothing")) is None
    assert g._parse_retry_after(types.SimpleNamespace(details=[{"retryDelay": "9s"}])) == 9.0
