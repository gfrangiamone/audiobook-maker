"""Upload mai partito: niente barra ferma all'85% e messaggio comprensibile.

Ticket 14/11/2026: utente Android, 10 tentativi in due giorni, nessuna POST
/api/analyze arrivata a nginx (solo il pre-check /api/admin/suspend). Chrome non
leggeva il file scelto da Drive/«Recenti»/allegati: fetch rifiutata, la barra
simulata restava all'85% e l'unico segnale era un "Error: Failed to fetch".
"""
import pathlib
import re

JS = pathlib.Path("static/js/app.js").read_text(encoding="utf-8")
I18N = pathlib.Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")


def _analyze_fn():
    i = JS.index("async function analyzeEpub(file)")
    j = JS.index("\n}\n", i)
    return JS[i:j]


def test_fetch_rejection_is_localised_and_resets_bar():
    fn = _analyze_fn()
    m = re.search(r"try\{r=await fetch\('/api/analyze'[^\n]*\}\s*\n\s*catch\(\w+\)\{([^\n]*)\}", fn)
    assert m, "la fetch di /api/analyze deve avere un catch dedicato"
    body = m.group(1)
    assert "t('err_upload_unreadable')" in body
    assert "resetUploadProgress()" in body
    assert "return" in body


def test_every_failure_path_clears_the_bar():
    fn = _analyze_fn()
    # manutenzione + catch generico + catch della fetch
    assert fn.count("resetUploadProgress()") >= 3


def test_reset_hides_without_fake_100():
    i = JS.index("function resetUploadProgress()")
    body = JS[i:JS.index("\n}\n", i)]
    assert "clearInterval" in body
    assert "display='none'" in body
    assert "100%" not in body


def test_message_present_in_all_seven_languages():
    found = re.findall(r'err_upload_unreadable:"([^"]*)"', I18N)
    assert len(found) == 7, f"chiave presente in {len(found)} lingue su 7"
    assert all(len(m) > 60 for m in found)
    assert len(set(found)) == 7, "due lingue condividono lo stesso testo"
    for m in found:
        assert "Download" in m or "Descargas" in m or "Téléchargements" in m
