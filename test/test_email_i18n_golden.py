"""Golden-test byte-per-byte delle email di notifica localizzate.

Fissa subject + corpo HTML delle 3 email (completamento, ottimizzazione,
traduzione — piu' la variante podcast del completamento) per tutte le
lingue supportate + fallback, contro lo snapshot
test/data/email_i18n_golden.json catturato PRIMA della centralizzazione
dei dizionari i18n: il refactor deve preservare i testi user-facing
verbatim (whitespace incluso).

Rigenerazione snapshot (solo se una modifica ai testi e' VOLUTA):
    python test/test_email_i18n_golden.py --regen
"""
import json
import types
from pathlib import Path
from unittest.mock import patch

import audiobook_app  # noqa: F401  (esegue configure() sui sub-moduli)
import email_service
import generation_engine as ge

GOLDEN_PATH = Path(__file__).parent / "data" / "email_i18n_golden.json"
LANGS = ["it", "en", "fr", "es", "de", "pt", "zh", "xx"]  # xx -> fallback en


def _base_job(lang):
    return {
        "status": "done",
        "client_id": "golden-cid-000001",
        "notify_email": "golden@example.test",
        "email_registered": True,
        "notify_lang": lang,
        "original_filename": "citta_perduta.epub",
        "voice": "it-IT-ElsaNeural",
        "rate": "+0%",
        "ai_optimized": True,
        "info": types.SimpleNamespace(title="Città Perduta", author="Autore",
                                      language="it"),
        "last_poll": 0,
    }


def _capture(send_fn, job):
    """Esegue la funzione email con side-effect neutralizzati e cattura
    (subject, html) dall'unica _send_email emessa."""
    job_id = "golden-job"
    sent = []
    ge._jobs[job_id] = job
    try:
        with patch.object(email_service, "_send_email",
                          side_effect=lambda to, subj, html: sent.append(
                              (subj, html)) or True), \
             patch.object(ge, "_save_tokens", lambda: None), \
             patch.object(ge, "_log_activity", lambda *a, **k: None), \
             patch.object(ge, "_write_email_marker", None), \
             patch.object(ge.pending_jobs, "finalize", lambda jid: None), \
             patch.object(ge.uuid, "uuid4", lambda: "GOLDEN-TOKEN"), \
             patch.object(ge, "BASE_URL", "https://example.test"), \
             patch.object(ge, "_retention_sec", 18 * 3600), \
             patch.object(ge, "_gemini_retention_sec", 48 * 3600):
            send_fn(job_id)
    finally:
        ge._jobs.pop(job_id, None)
        for t in list(ge._download_tokens):
            if isinstance(ge._download_tokens[t], dict) and \
                    ge._download_tokens[t].get("job_id") == job_id:
                ge._download_tokens.pop(t, None)
    assert len(sent) == 1, f"attese 1 email, inviate {len(sent)}"
    return {"subject": sent[0][0], "html": sent[0][1]}


def capture_all():
    out = {"completion": {}, "completion_podcast": {},
           "optimization": {}, "translation": {}}
    for lang in LANGS:
        job = _base_job(lang)
        job["notify_download_type"] = "audio"
        job["output_format"] = "m4b"
        out["completion"][lang] = _capture(ge._send_completion_email, job)

        job = _base_job(lang)
        job["notify_download_type"] = "podcast"
        job["notify_base_url"] = "https://pods.example.test"
        job["podcast_safe_name"] = "citta_perduta"
        job["podcast_ready"] = True
        out["completion_podcast"][lang] = _capture(ge._send_completion_email, job)

        job = _base_job(lang)
        job["optimized_abm_path"] = "/x/citta_perduta_optimized.abm"
        job["optimized_abm_name"] = "citta_perduta_optimized.abm"
        out["optimization"][lang] = _capture(ge._send_optimization_email, job)

        job = _base_job(lang)
        job["translated_path"] = "/x/citta_perduta_it.epub"
        job["translated_name"] = "citta_perduta_it.epub"
        job["tr_params"] = {"output_format": "epub"}
        job["translated_optimized"] = False
        out["translation"][lang] = _capture(ge._send_translation_email, job)
    return out


def test_email_i18n_matches_golden_snapshot():
    assert GOLDEN_PATH.exists(), (
        f"snapshot mancante: {GOLDEN_PATH} — genera con "
        f"'python test/test_email_i18n_golden.py --regen'")
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    current = capture_all()
    for kind in golden:
        for lang in golden[kind]:
            for field in ("subject", "html"):
                assert current[kind][lang][field] == golden[kind][lang][field], (
                    f"{kind}/{lang}/{field} divergente dal golden snapshot "
                    f"(i testi email vanno preservati verbatim)")
    assert set(current) == set(golden)


def test_fallback_lang_is_english():
    golden_free = capture_all()
    for kind in golden_free:
        assert golden_free[kind]["xx"] == golden_free[kind]["en"]


if __name__ == "__main__":
    import sys
    if "--regen" in sys.argv:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(
            json.dumps(capture_all(), ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"golden snapshot scritto: {GOLDEN_PATH}")
    else:
        print("uso: python test/test_email_i18n_golden.py --regen")
