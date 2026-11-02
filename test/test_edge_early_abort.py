"""Libro uzbeko in cirillico (02/11/2026): le voci uz-UZ di edge-tts leggono
solo l'alfabeto latino, 65 chunk su 65 finivano in silenzio dopo ~75 minuti di
tentativi. Il testo per le voci uz-UZ si traslittera in latino, e un job edge i
cui primi chunk falliscono tutti mentre il servizio serve gli altri si chiude
subito con rimborso invece di macinare l'intero libro."""
import asyncio
import os

import edge_engine
import edge_health
import generation_engine
import text_reflow


# ------------------------- uzbek_cyrillic_to_latin --------------------------

def test_uzbek_transliteration_letters_and_digraphs():
    t = text_reflow.uzbek_cyrillic_to_latin
    assert t("Инсон ўз меҳнати") == "Inson o'z mehnati"
    assert t("Ғалаба, чой, шаҳар, қишлоқ, ёшлик, юлдуз, янги") == \
        "G'alaba, choy, shahar, qishloq, yoshlik, yulduz, yangi"
    assert t("эътибор, мактабь") == "e'tibor, maktab"


def test_uzbek_transliteration_contextual_e_and_ts():
    t = text_reflow.uzbek_cyrillic_to_latin
    # е: ye a inizio parola e dopo vocale/ъ, altrimenti e
    assert t("еди келди оила ъе") == "yedi keldi oila 'ye"
    assert t("поезд") == "poyezd"
    # ц: s a inizio parola e dopo consonante, ts dopo vocale
    assert t("цирк лицей концерт") == "sirk litsey konsert"


def test_uzbek_transliteration_case():
    t = text_reflow.uzbek_cyrillic_to_latin
    assert t("ЎЗИМ БИЛАН СУҲБАТ") == "O'ZIM BILAN SUHBAT"
    assert t("Шаҳар Чорсу") == "Shahar Chorsu"
    assert t("ШАҲАР") == "SHAHAR"
    assert t("А") == "A"


def test_uzbek_transliteration_leaves_other_text_alone():
    t = text_reflow.uzbek_cyrillic_to_latin
    assert t("") == ""
    assert t(None) is None
    latin = "Inson o'z mehnati, 2026 — «ok»!"
    assert t(latin) is latin
    assert t("Bob: Салом!") == "Bob: Salom!"


# --------------------- generate_chunk_mp3 per voce uz-UZ --------------------

def _capture_calls(monkeypatch):
    seen = []

    async def fake_call(text, voice, rate, output_path, max_retries=3):
        seen.append(text)
        return True
    monkeypatch.setattr(edge_engine, "_edge_tts_call", fake_call)
    return seen


def test_uz_voice_receives_latin_text(monkeypatch, tmp_path):
    seen = _capture_calls(monkeypatch)
    out = str(tmp_path / "c.mp3")
    asyncio.run(edge_engine.generate_chunk_mp3("Муқаддима", "uz-UZ-MadinaNeural", "+0%", out))
    assert seen == ["Muqaddima"]


def test_other_voices_keep_cyrillic(monkeypatch, tmp_path):
    seen = _capture_calls(monkeypatch)
    out = str(tmp_path / "c.mp3")
    asyncio.run(edge_engine.generate_chunk_mp3("Привет", "ru-RU-DmitryNeural", "+0%", out))
    assert seen == ["Привет"]


# ------------------------------ service_ok ----------------------------------

def _calls(n_ok, n_fail, now):
    for _ in range(n_ok):
        edge_health.record_call(True, now=now)
    for _ in range(n_fail):
        edge_health.record_call(False, now=now)


def test_service_ok_needs_enough_calls_and_low_failures(monkeypatch):
    monkeypatch.setenv("ABM_EDGE_ALERT_MIN_CALLS", "10")
    monkeypatch.setenv("ABM_EDGE_ALERT", "0")
    edge_health.reset()
    now = 1_800_000_000.0
    _calls(5, 0, now)
    assert edge_health.service_ok(now=now) is False      # troppo poche chiamate
    _calls(10, 0, now)
    assert edge_health.service_ok(now=now) is True
    _calls(0, 20, now)                                    # 20/35 in silenzio
    assert edge_health.service_ok(now=now) is False
    edge_health.reset()


# ----------------------------- should_abort_job -----------------------------

def test_should_abort_job_rules(monkeypatch):
    monkeypatch.setattr(edge_health, "service_ok", lambda now=None: True)
    monkeypatch.delenv("ABM_EDGE_EARLY_ABORT_CHUNKS", raising=False)
    assert edge_engine.early_abort_chunks() == 8
    assert edge_engine.should_abort_job(7, 7) is False    # campione troppo piccolo
    assert edge_engine.should_abort_job(8, 8) is True
    assert edge_engine.should_abort_job(8, 9) is False    # un chunk e' riuscito
    monkeypatch.setenv("ABM_EDGE_EARLY_ABORT_CHUNKS", "0")
    assert edge_engine.should_abort_job(50, 50) is False  # spento
    monkeypatch.setenv("ABM_EDGE_EARLY_ABORT_CHUNKS", "3")
    monkeypatch.setattr(edge_health, "service_ok", lambda now=None: False)
    assert edge_engine.should_abort_job(10, 10) is False  # guasto del servizio


# ------------------------- interruzione nel job ------------------------------

def _setup_job(monkeypatch, tmp_path, n_chunks):
    calls = []

    async def failing_chunk(text, voice, rate, output_path, max_retries=3, **kwargs):
        calls.append(text)
        raise RuntimeError("No audio was received.")
    monkeypatch.setattr(generation_engine, "generate_chunk_mp3", failing_chunk)
    plan = [{"chapter_index": 1, "chapter_title": "Cap 1", "chunk_index": k,
             "chunks_in_chapter": n_chunks, "text": f"c{k}", "chars": 2}
            for k in range(n_chunks)]
    monkeypatch.setattr(generation_engine, "_plan_chunks",
                        lambda info, max_chars, max_bytes=None, **kw: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "edge")
    monkeypatch.setattr(generation_engine, "_generate_silence_mp3",
                        lambda p, duration_sec=1: open(p, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 10)
    monkeypatch.setattr(generation_engine, "_concatenate_mp3",
                        lambda parts, out, **kw: open(out, "wb").write(b"\x00") > 0)
    monkeypatch.setattr(generation_engine, "_include_cover_in_dir", lambda *a, **k: None)
    refunds, pending = [], []
    monkeypatch.setattr(generation_engine, "_refund_job_payment",
                        lambda job_id, job, reason="error": refunds.append(reason))
    monkeypatch.setattr(generation_engine, "_mark_pending_failed",
                        lambda job_id, reason="": pending.append(reason))
    monkeypatch.setenv("ABM_FAILED_CHUNK_RETRY_ROUNDS", "2")
    monkeypatch.setenv("ABM_FAILED_CHUNK_RETRY_PAUSE_SEC", "0")
    monkeypatch.setenv("ABM_EDGE_EARLY_ABORT_CHUNKS", "4")

    class _Info:
        title = "T"
        author = "A"
        language = "uz"
        chapters = [type("C", (), {"index": 1, "title": "Cap 1", "text": "..."})()]
    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True}
    monkeypatch.setattr(generation_engine, "_jobs", {"ja": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)
    return job, calls, refunds, pending, _Info


def _run(info):
    generation_engine.run_generation(
        "ja", info(), "uz-UZ-MadinaNeural", "+0%",
        single_file=True, output_format="mp3")


def test_job_stops_after_first_failed_chunks_when_service_is_up(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_health, "service_ok", lambda now=None: True)
    job, calls, refunds, pending, info = _setup_job(monkeypatch, tmp_path, 12)
    _run(info)
    assert calls == ["c0", "c1", "c2", "c3"]           # niente resto del libro, niente ripasso
    assert job["status"] == "error"
    assert job["failed_chunks"] == 4 and job["total_chunks"] == 12
    assert refunds == ["all_chunks_failed: 4/4"]
    assert pending == ["failed_all_chunks_refunded"]
    assert not any(f.endswith(".mp3") and "output" in r
                   for r, _d, fs in os.walk(tmp_path) for f in fs)


def test_job_runs_to_the_end_when_service_is_down(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_health, "service_ok", lambda now=None: False)
    job, calls, refunds, pending, info = _setup_job(monkeypatch, tmp_path, 6)
    _run(info)
    assert len(calls) == 6 * 3                           # sintesi + 2 round di ripasso
    assert job["status"] == "error"
    assert refunds == ["all_chunks_failed: 6/6"]
    assert pending == ["failed_all_chunks_refunded"]
