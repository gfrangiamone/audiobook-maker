"""Pannello "Audiolibro pronto": dettagli di generazione nel payload done.

/api/progress/<job_id> al done espone gen_details_html con gli STESSI testi
localizzati del blocco email di completamento (fonte unica
generation_engine._generation_details_lines): lingua+tipo voce,
voce+velocita', modello per PREMIUM, ottimizzazione AI.
"""
import os

import audiobook_app


def _done_job(**over):
    job = {
        "status": "done",
        "output_name": "out",
        "podcast_ready": False,
        "ai_optimized": False,
        "voice": "it-IT-ElsaNeural",
        "rate": "+0%",
    }
    job.update(over)
    return job


def _progress_body(job_id, job, lang):
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = job
    try:
        client = audiobook_app.app.test_client()
        resp = client.get(f"/api/progress/{job_id}?lang={lang}")
        assert resp.status_code == 200
        return resp.get_data(as_text=True)
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(job_id, None)


def test_done_payload_has_details_standard_voice():
    body = _progress_body("gdp1", _done_job(), "it")
    assert "gen_details_html" in body
    assert "Voci Standard" in body          # lang_line (testo email)
    assert "Elsa" in body                    # voice_line (friendly name)
    assert "it-IT" in body                   # codice lingua della voce
    # opt_no (i testi email usano entity HTML: &egrave;)
    assert "non &egrave; stato ottimizzato" in body


def test_done_payload_has_model_for_premium_voice():
    job = _done_job(voice="gemini:flash25:Zephyr", gen_lang="it",
                    ai_optimized=True, gemini_style_instruction="tono calmo")
    body = _progress_body("gdp2", job, "it")
    assert "Voci PREMIUM" in body
    assert "Zephyr" in body
    assert "Gemini 2.5 Flash TTS" in body    # model_line (stessa label email)
    assert "tono calmo" in body              # style_line
    assert "ottimizzato con l'AI" in body


def test_done_payload_details_localized_en():
    body = _progress_body("gdp3", _done_job(voice="gemini:flash31:Kore",
                                            gen_lang="en"), "en")
    assert "PREMIUM Voices" in body
    assert "Gemini 3.1 Flash TTS" in body


def test_details_same_source_as_email():
    """Il payload usa la stessa fonte del blocco email (nessun fork di testi)."""
    import generation_engine as ge
    job = _done_job(voice="gemini:flash25:Zephyr", gen_lang="it", ai_optimized=True)
    lines = ge._generation_details_lines(job, "it")
    email_html = ge._email_generation_details(job, "it")
    for line in lines:
        assert line in email_html


def test_frontend_renders_gen_details():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    html = open(os.path.join(root, "templates", "_fragments", "html_head.html"),
                encoding="utf-8").read()
    js = open(os.path.join(root, "static", "js", "app.js"), encoding="utf-8").read()
    assert 'id="genDetails"' in html
    assert "gen_details_html" in js
    # Il titolo del libro viene inserito escaped lato client
    assert "gen-details-title" in js and "esc(bookData.title)" in js
