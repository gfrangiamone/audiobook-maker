import base64
import io
import wave
import pytest
import speechify_tts


def _make_wav_bytes(sample_rate=48000, n_frames=2400):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x01\x00" * n_frames)
    return buf.getvalue()


class _Resp:
    def __init__(self, status, json_data=None, headers=None):
        self.status_code = status
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = "err"

    def json(self):
        return self._json


class _Session:
    """Finto requests.Session: restituisce risposte da una coda."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


def test_build_ssml_includes_emotion():
    ssml = speechify_tts.build_ssml("Hello", emotion="cheerful")
    assert "cheerful" in ssml
    assert "Hello" in ssml


def test_build_ssml_ignores_unknown_emotion():
    ssml = speechify_tts.build_ssml("Hi", emotion="not_an_emotion")
    assert "not_an_emotion" not in ssml


def test_synthesize_writes_pcm(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "2")
    speechify_tts._reset_gate_for_test()
    wav = _make_wav_bytes()
    resp = _Resp(200, {"audio_data": base64.b64encode(wav).decode(),
                       "billable_characters_count": 5})
    sess = _Session([resp])
    out = tmp_path / "chunk.pcm"
    res = speechify_tts.synthesize("Hello", "speechify:simba-3.2:harper_32",
                                   str(out), emotion="calm", session=sess)
    assert res["success"] is True
    assert res["sample_rate"] == 48000
    assert res["channels"] == 1
    assert res["billable_chars"] == 5
    assert out.read_bytes() == b"\x01\x00" * 2400
    # gate rilasciato a fine chiamata
    assert speechify_tts.active_slots() == 0
    # language derivato dalla voce (en-US)
    assert sess.calls[0]["json"].get("language") == "en-US"


def test_synthesize_retries_on_429(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    speechify_tts._reset_gate_for_test()
    monkeypatch.setattr(speechify_tts.time, "sleep", lambda *_: None)
    wav = _make_wav_bytes()
    ok = _Resp(200, {"audio_data": base64.b64encode(wav).decode(),
                     "billable_characters_count": 1})
    sess = _Session([_Resp(429, headers={"Retry-After": "0"}), ok])
    out = tmp_path / "c.pcm"
    res = speechify_tts.synthesize("Hi", "speechify:simba-3.2:dominic_32",
                                   str(out), session=sess, max_attempts=3)
    assert res["success"] is True
    assert len(sess.calls) == 2


def test_synthesize_fatal_on_400(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    speechify_tts._reset_gate_for_test()
    sess = _Session([_Resp(400)])
    out = tmp_path / "c.pcm"
    with pytest.raises(RuntimeError):
        speechify_tts.synthesize("Hi", "speechify:simba-3.2:dominic_32",
                                 str(out), session=sess, max_attempts=3)
    assert len(sess.calls) == 1  # nessun retry su 4xx
    assert speechify_tts.active_slots() == 0


def test_synthesize_unavailable_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ABM_SPEECHIFY_API_KEY", raising=False)
    with pytest.raises(speechify_tts.SpeechifyUnavailable):
        speechify_tts.synthesize("Hi", "speechify:simba-3.2:dominic_32",
                                 str(tmp_path / "c.pcm"))


import tts_split


def test_generate_chunk_speechify_success(monkeypatch, tmp_path):
    calls = {}

    def _fake_synth(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        calls["text"] = text
        calls["emotion"] = emotion
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00" * 100)
        return {"success": True, "bytes_written": 200, "sample_rate": 48000,
                "channels": 1, "billable_chars": len(text), "voice_name": "harper_32"}

    monkeypatch.setattr("speechify_tts.synthesize", _fake_synth)
    out = tmp_path / "c.pcm"
    res = tts_split.generate_chunk_pcm_speechify(
        "Hello world", "speechify:simba-3.2:harper_32", str(out), emotion="warm")
    assert res["success"] is True
    assert calls["emotion"] == "warm"
    assert out.exists()


def test_generate_chunk_speechify_reraises_unavailable(monkeypatch, tmp_path):
    import speechify_tts

    def _boom(*a, **k):
        raise speechify_tts.SpeechifyUnavailable("no key")

    monkeypatch.setattr("speechify_tts.synthesize", _boom)
    with pytest.raises(speechify_tts.SpeechifyUnavailable):
        tts_split.generate_chunk_pcm_speechify(
            "Hi", "speechify:simba-3.2:harper_32", str(tmp_path / "c.pcm"))


def test_generate_chunk_speechify_empty_text_silence(monkeypatch, tmp_path):
    out = tmp_path / "c.pcm"
    res = tts_split.generate_chunk_pcm_speechify(
        "   ", "speechify:simba-3.2:harper_32", str(out))
    assert res is False
    assert out.exists()  # silenzio PCM scritto
