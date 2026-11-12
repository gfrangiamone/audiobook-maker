"""Motore Pocket TTS (worker abm-pocket-worker su VPS): client, chunk diretto,
pre-sintesi con i chunk riusati, audit, tag, gate di configurazione."""
import pathlib
import types

import pytest
import requests

import generation_engine as ge
import pocket_tts
import premium_chunk
import tts_engines
import voice_utils

VOICE = "pocket:v1:it-IT/Chiara"


@pytest.fixture
def worker_env(monkeypatch):
    monkeypatch.setenv("ABM_POCKET_URL", "https://pocket.example/")
    monkeypatch.setenv("ABM_POCKET_TOKEN", "tok")


class _Resp:
    def __init__(self, status, content=b"", text=""):
        self.status_code = status
        self.content = content
        self.text = text


class _Session:
    """Risposte in coda; registra le chiamate."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# --- voci e registro ----------------------------------------------------------

def test_voice_id_and_registry():
    assert voice_utils.engine_for_voice(VOICE) == "pocket"
    assert voice_utils.is_premium_voice(VOICE) and voice_utils.voice_id_shape_ok(VOICE)
    assert pocket_tts.parse_voice_id("pocket:v1:es-AR/Agustín") == ("v1", "es-AR", "Agustín")
    for bad in ("pocket:v2:it-IT/Chiara", "pocket:v1:it/Chiara", "pocket:v1:it-IT/", "voxcpm:v2:it-IT/Chiara"):
        with pytest.raises(ValueError):
            pocket_tts.parse_voice_id(bad)
    eng = tts_engines.ENGINES["pocket"]
    assert eng.direct and eng.sample_rate({}) == 24000 and "pocket" in tts_engines.DIRECT
    assert ge._friendly_voice_name(VOICE) == "Chiara"


def test_available_only_with_url_and_token(monkeypatch):
    monkeypatch.delenv("ABM_POCKET_URL", raising=False)
    monkeypatch.setenv("ABM_POCKET_TOKEN", "tok")
    assert not pocket_tts.is_available() and not tts_engines.ENGINES["pocket"].is_available()
    monkeypatch.setenv("ABM_POCKET_URL", "https://pocket.example")
    assert pocket_tts.is_available()


def test_price_is_zero_and_estimate_counts_chars():
    price = pocket_tts.compute_user_price_eur(1_000_000, "it")
    assert price["user_price_eur"] == price["list_price_eur"] == 0.0 and price["is_free"]
    chs = [types.SimpleNamespace(title="", text="Uno due tre."), types.SimpleNamespace(title="", text="Quattro.")]
    est = tts_engines.estimate("pocket", chs, language="it")
    assert est["chars_total"] == len("Uno due tre.") + len("Quattro.")
    assert est["user_price_eur"] == 0.0 and est["model_label"] == pocket_tts.MODEL_LABEL
    assert tts_engines.ENGINES["pocket"].consumed_list_price_eur({"pocket_actual": {"chars": 500}}) == 0.0


# --- client HTTP ---------------------------------------------------------------

def test_synthesize_writes_pcm_and_sends_worker_voice(worker_env, tmp_path):
    out = tmp_path / "c.pcm"
    sess = _Session(_Resp(200, b"\x01\x00" * 24000))
    res = pocket_tts.synthesize("Ciao a tutti.", VOICE, str(out), rate="+10%", session=sess)
    assert out.read_bytes() == b"\x01\x00" * 24000
    assert res["success"] and res["sample_rate"] == 24000 and res["bytes_written"] == 48000
    url, payload, headers = sess.calls[0]
    assert url == "https://pocket.example/v1/synthesize"
    assert payload == {"text": "Ciao a tutti.", "voice": "it-IT/Chiara", "lang": "it", "normalize": True}
    assert headers == {"Authorization": "Bearer tok"}


def test_synthesize_retries_restart_and_network_then_succeeds(worker_env, tmp_path):
    waits = []
    sess = _Session(_Resp(503, text="worker in riavvio"), requests.ConnectionError("giu'"),
                    _Resp(200, b"\x00\x00"))
    res = pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                                sleep=waits.append)
    assert res["success"] and len(sess.calls) == 3 and waits == [5.0, 10.0]


def test_synthesize_fatal_on_4xx_and_gives_up_after_attempts(worker_env, tmp_path):
    sess = _Session(_Resp(404, text="voce it-IT/Chiara non presente"))
    with pytest.raises(pocket_tts.PocketFatalError):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess)
    assert len(sess.calls) == 1
    sess = _Session(*[_Resp(502, text="chunk fallito")] * 2)
    with pytest.raises(RuntimeError, match="after 2 attempts"):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                              max_attempts=2, sleep=lambda s: None)


def test_synthesize_unavailable_without_config(monkeypatch, tmp_path):
    monkeypatch.delenv("ABM_POCKET_URL", raising=False)
    with pytest.raises(pocket_tts.PocketUnavailable):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"))


# --- wrapper di chunk -----------------------------------------------------------

def test_chunk_wrapper_silence_at_24k_on_fatal(worker_env, monkeypatch, tmp_path):
    def _fatal(*a, **k):
        raise pocket_tts.PocketFatalError("HTTP 404")
    monkeypatch.setattr(pocket_tts, "synthesize", _fatal)
    out, fi = tmp_path / "c.pcm", {}
    assert premium_chunk.generate_chunk_pcm_pocket("Un testo.", VOICE, str(out), failure_info=fi) is False
    assert out.stat().st_size == 24000 * 2 and fi["reason"] == "synthesize_failed"


def test_chunk_wrapper_reraises_unavailable(monkeypatch, tmp_path):
    monkeypatch.delenv("ABM_POCKET_URL", raising=False)
    with pytest.raises(pocket_tts.PocketUnavailable):
        premium_chunk.generate_chunk_pcm_pocket("Un testo.", VOICE, str(tmp_path / "c.pcm"))


# --- generazione -------------------------------------------------------------------

def test_presynth_skips_reused_chunks(monkeypatch, tmp_path):
    plan = [{"text": f"chunk {i}"} for i in range(5)]
    job, seen = {}, []

    def _fake(text, voice, path, emotion=None, rate="+0%", failure_info=None):
        seen.append(text)
        pathlib.Path(path).write_bytes(b"\x00\x00")
        return {"success": True, "bytes_written": 2, "sample_rate": 24000, "billable_chars": len(text)}

    monkeypatch.setattr(ge, "generate_chunk_pcm_pocket", _fake)
    out = ge._direct_presynth(job, "pocket", plan, tmp_path, VOICE, emotion=None, rate="+0%",
                              check_cancelled=lambda: False, start_time=0.0, skip={1, 3})
    assert sorted(out) == [0, 2, 4] and sorted(seen) == ["chunk 0", "chunk 2", "chunk 4"]
    assert job["progress_current"] == 2 + len(plan)       # i riusati contano come fatti
    assert "speechify_sample_rate" not in job


def test_actual_and_audit_record(monkeypatch):
    job = {"pocket_actual": ge._new_direct_actual()}
    ge._accumulate_direct_actual(job, "pocket", {"text": "ciao"},
                                 {"billable_chars": 4, "bytes_written": 48000, "sample_rate": 24000})
    assert job["pocket_actual"]["audio_seconds"] == 1.0 and job["pocket_actual"]["model_key"] == "v1"
    recs = []
    monkeypatch.setattr(ge.gemini_cost_audit, "append_record", recs.append)
    ge._write_pocket_audit("J", job, VOICE, "it", "completed")
    assert recs and recs[0]["provider"] == "pocket" and recs[0]["model_key"] == "v1"
    assert recs[0]["google_cost_eur_actual"] == 0.0 and recs[0]["chars_total"] == 4
    ge._write_pocket_audit("J", job, "gemini:flash31:Zephyr", "it", "completed")   # altra voce: no-op
    assert len(recs) == 1


def test_generation_tags_for_pocket_voice():
    info = types.SimpleNamespace(title="Libro", author="Autore", language="it")
    tags = ge._generation_tags({}, info, VOICE, "+0%")
    assert tags["abm_model"] == pocket_tts.MODEL_LABEL and tags["abm_voice"] == "Chiara"
    assert tags["abm_language"] == "it-IT" and tags["abm_voice_id"] == VOICE


def test_model_gate_rejects_pocket_without_worker(monkeypatch):
    import audiobook_app
    monkeypatch.delenv("ABM_POCKET_URL", raising=False)
    with audiobook_app.app.test_request_context():
        resp, status = audiobook_app._premium_model_gate(VOICE)
        assert status == 400 and resp.get_json()["error"] == "pocket_not_configured"
        monkeypatch.setenv("ABM_POCKET_URL", "https://pocket.example")
        monkeypatch.setenv("ABM_POCKET_TOKEN", "tok")
        assert audiobook_app._premium_model_gate(VOICE) is None
