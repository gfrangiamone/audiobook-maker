"""Regressione incidente 04/09/2026 (job 6t4YV4oSBMbxAyxjLB6T3Q).

Il token di una traduzione consegnata sopravviveva al restart del servizio ma
DIMENTICAVA dove stava il file (`translated_path`/`translated_name` non erano
nella whitelist di `_save_tokens`). Risultato per l'utente: la pagina
`/dl/<token>` diceva "traduzione pronta" e non mostrava alcun bottone.

Tre invarianti coperte qui:
  1. il round-trip save/load del token conserva i campi della traduzione;
  2. la pagina /dl senza file disponibile non e' piu' un vicolo cieco muto;
  3. `run_translation` scrive `.generation_complete` PRIMA di lanciare
     l'offload cold (altrimenti il guard "quiet" di `_offload_to_cloud` salta
     sempre l'upload appena scritto).
"""
import json
import pathlib
import time

import audiobook_app


def _tokens_env(monkeypatch, tmp_path, tokens):
    f = tmp_path / "_download_tokens.json"
    monkeypatch.setattr(audiobook_app, "_TOKENS_FILE", pathlib.Path(f))
    monkeypatch.setattr(audiobook_app, "_download_tokens", dict(tokens))
    return f


def test_translated_fields_survive_save_load_roundtrip(monkeypatch, tmp_path):
    tok = "TRTOK"
    f = _tokens_env(monkeypatch, tmp_path, {
        tok: {
            "job_id": "trjob",
            "download_type": "translated",
            "created_at": time.time(),
            "book_title": "Malhechores",
            "translated_path": "/data/trjob/output_1/libro-es.epub",
            "translated_name": "libro-es.epub",
            "output_m4b_fallback_zip": "/data/trjob/output_1/kit.zip",
            "is_gemini": False,
        }
    })

    audiobook_app._save_tokens()
    data = json.loads(f.read_text(encoding="utf-8"))

    assert data[tok]["translated_path"] == "/data/trjob/output_1/libro-es.epub", \
        "translated_path non persistito: il link sopravvive al restart ma perde il file"
    assert data[tok]["translated_name"] == "libro-es.epub"
    assert data[tok]["output_m4b_fallback_zip"] == "/data/trjob/output_1/kit.zip"

    # Round-trip completo: _load_tokens deve ridarci i campi. La job dir deve
    # esistere, altrimenti il token viene giustamente scartato come invalido.
    (tmp_path / "trjob").mkdir()
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", pathlib.Path(tmp_path))
    monkeypatch.setattr(audiobook_app, "_download_tokens", {})
    audiobook_app._load_tokens()
    assert audiobook_app._download_tokens[tok]["translated_path"].endswith("libro-es.epub")


def test_dl_page_translated_unavailable_is_not_a_dead_end():
    html = audiobook_app._render_dl_page(
        "TOK", "Titolo", "10h", "translated", lang="en",
        translated_available=False)
    assert "/dl/TOK/translated" not in html, "bottone mostrato senza file disponibile"
    assert "no longer available" in html, \
        "pagina senza bottone e senza spiegazione: vicolo cieco per l'utente"


def test_dl_page_translated_available_shows_button():
    html = audiobook_app._render_dl_page(
        "TOK", "Titolo", "10h", "translated", lang="en",
        translated_available=True)
    assert "/dl/TOK/translated" in html


def test_run_translation_marks_generation_complete_before_offload():
    """L'ordine conta: senza il marker, il guard 'quiet' di _offload_to_cloud
    scarta l'upload perche' i file sono stati scritti da meno di 180s."""
    src = pathlib.Path("generation_engine.py").read_text(encoding="utf-8")
    i_end = src.index("translation offload spawn failed")
    # Blocco del ramo traduzione: dal marker fino allo spawn dell'offload.
    block = src[max(0, i_end - 900):i_end]
    i_mark = block.rindex("storage_tiering.mark_generation_complete(out_dir")
    i_spawn = block.rindex("_spawn_cloud_offload(job_id")
    msg = "offload lanciato prima del marker: il guard quiet scarta l'upload"
    assert i_mark < i_spawn, msg


def test_orphan_cleanup_treats_translated_path_as_referenced():
    """La output_<epoch> di una traduzione non deve risultare orfana."""
    src = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")
    i = src.index('for key in ("output_zip", "output_file", "output_m4b"')
    block = src[i:i + 400]
    for key in ("translated_path", "optimized_abm_path", "output_m4b_fallback_zip"):
        assert key in block, f"{key} non considerato referenziato dal cleanup orfani"


def test_cleanup_loop_has_translated_retention_branch():
    """Un job in stato "translated" senza ramo dedicato non lascia mai la RAM:
    i capitoli tradotti restano in `jobs` a tempo indeterminato."""
    src = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")
    i = src.index("def _cleanup_loop(")
    body = src[i:i + 12000]
    assert 'if status == "translated":' in body, "ramo translated assente dal cleanup loop"
    j = body.index('if status == "translated":')
    branch = body[j:j + 900]
    assert "_has_active_download_tokens" in branch, "manca il guard sui token attivi"
    assert "translated_at" in branch
