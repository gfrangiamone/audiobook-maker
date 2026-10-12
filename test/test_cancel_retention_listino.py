"""Il trattenuto di un cancel volontario Gemini dipende dal LISTINO del
lavoro consegnato (tariffa €/ora x secondi di audio prodotti), non dal costo
sostenuto dal backend che lo ha eseguito: un cancel su un chunk servito da
Cloudflare e uno andato in failover su Vertex trattengono la stessa cifra a
parita' di audio consegnato, per una scelta di infrastruttura invisibile
all'utente.

Esercita il vero ramo _CancelledError di run_generation cancellando il job
dopo il primo di due chunk pianificati, con `actual_cost_breakdown` (reale)
che varia per backend.
"""
import cancel_policy
import gemini_cost_audit
import gemini_tts
import generation_engine

# 1800 s di audio PCM 24 kHz s16le mono: mezz'ora -> 1,11 EUR a 2,22 EUR/h.
_BYTES_HALF_HOUR = 24000 * 2 * 1800


class _Info:
    title = "T"
    author = "A"
    language = "it"
    chapters = [type("C", (), {"index": 1, "title": "Cap 1", "text": "..."})()]


def _run_cancel_after_first_chunk(monkeypatch, tmp_path, job_id, backend_first_chunk,
                                  real_cost_eur):
    """Esegue run_generation su un piano di 2 chunk, cancellando il job subito
    dopo che il primo e' stato processato (side effect della fake TTS), e
    restituisce il job risultante."""
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: None)
    monkeypatch.setattr(generation_engine, "_refund_gemini_payment", lambda *a, **k: None)

    call_count = {"n": 0}

    def fake_chunk_gemini(text, voice_id, output_path, max_retries=3, style_instruction=None,
                          debug_prompt_path=None, rate="+0%", **kwargs):
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Cancellazione richiesta subito dopo il primo chunk: il prossimo
            # giro del loop la intercetta con _check_cancelled() PRIMA di
            # processare il secondo chunk.
            job["cancelled"] = True
        return {
            "success": True, "bytes_written": _BYTES_HALF_HOUR,
            "input_tokens": 100, "output_tokens": 500,
            "model_key": "flash31", "voice_name": "Zephyr", "attempts_used": 1,
            "backend": backend_first_chunk,
        }
    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_gemini", fake_chunk_gemini)

    def fake_actual_breakdown(in_t, out_t, model_key, backend):
        return {"total_eur": real_cost_eur}
    monkeypatch.setattr(generation_engine.gemini_tts, "actual_cost_breakdown",
                        fake_actual_breakdown, raising=False)

    plan = [
        {"chapter_index": 1, "chapter_title": "Cap 1", "chunk_index": 0,
         "chunks_in_chapter": 2, "text": "Hello world", "chars": 11},
        {"chapter_index": 1, "chapter_title": "Cap 1", "chunk_index": 1,
         "chunks_in_chapter": 2, "text": "Second chunk", "chars": 12},
    ]
    monkeypatch.setattr(generation_engine, "_plan_chunks",
                        lambda info, max_chars, max_bytes=None, **kw: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "gemini")
    monkeypatch.setattr(generation_engine, "_generate_silence_pcm",
                        lambda p, s=1, sample_rate=None: open(p, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_mp3",
                        lambda parts, out, **kw: open(out, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_aac_m4b", lambda *a, **k: True)
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)
    monkeypatch.setattr(generation_engine, "pcm_size_to_seconds", lambda b, **kw: 1.0)
    monkeypatch.setattr(generation_engine, "_prepare_m4b_cover_path", lambda *a, **k: None)

    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True,
           "payment": {"total_eur": 5.0, "method": "paypal", "token": "ORD-1"}}
    monkeypatch.setattr(generation_engine, "_jobs", {job_id: job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)

    generation_engine.run_generation(job_id, _Info(), "gemini:flash31:Zephyr", "+0%",
                                     single_file=True, output_format="mp3")
    return job


def test_cancel_retention_identical_across_backends_same_listino(monkeypatch, tmp_path):
    """Stesso audio consegnato, costo reale diverso (Cloudflare 0.10 vs Vertex
    dopo failover 0.50): il trattenuto/rimborso deve coincidere."""
    monkeypatch.delenv("ABM_GEMINI_31FLASH_EUR_PER_AUDIO_HOUR", raising=False)
    job_cf = _run_cancel_after_first_chunk(
        monkeypatch, tmp_path, "job-cf", backend_first_chunk="cloudflare",
        real_cost_eur=0.10)
    job_vertex = _run_cancel_after_first_chunk(
        monkeypatch, tmp_path, "job-vx", backend_first_chunk="vertex",
        real_cost_eur=0.50)

    assert job_cf["gemini_actual"]["google_cost_eur"] == 0.10
    assert job_vertex["gemini_actual"]["google_cost_eur"] == 0.50
    assert "pricing_cost_eur" not in job_cf["gemini_actual"]

    cm_cf = job_cf["cancel_meta"]
    cm_vx = job_vertex["cancel_meta"]
    assert cm_cf["retained_eur"] == cm_vx["retained_eur"]
    assert cm_cf["refund_eur"] == cm_vx["refund_eur"]

    # Prova positiva: il trattenuto e' il LISTINO della mezz'ora consegnata
    # (1,11 EUR a 2,22 EUR/h), col tetto del pagato.
    listino = gemini_tts.compute_user_price_eur(1800.0, "flash31")["list_price_eur"]
    expected = cancel_policy.compute_cancel_retention(listino, 5.0)
    assert cm_cf["retained_eur"] == expected["retained_eur"] == 1.11
    assert cm_cf["refund_eur"] == expected["refund_eur"] == 3.89

    # Prova negativa: non e' ne' il costo reale ne' un suo multiplo.
    assert cm_cf["retained_eur"] not in (0.10, 0.50)
