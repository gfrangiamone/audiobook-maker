# test/test_app_js_cold_redirect.py
"""Regressione: "Download error: Failed to fetch" sui file passati a cold.

Difetto osservato in produzione (job f9ov74kpPpJpTuKmA75xFw, 14/09/2026): dopo
l'hot-evict il file locale non esiste piu' e `/api/download` risponde 302 verso
un presigned URL cross-origin. La SPA lo recuperava con `fetch()`: il redirect
veniva seguito, ma la risposta dello storage non porta
`Access-Control-Allow-Origin`, il browser la scartava e sollevava
`TypeError: Failed to fetch`. Il link via email, che e' una navigazione e non e'
soggetto al CORS, scaricava lo stesso identico file.

Il fix chiede il redirect in forma opaca (`redirect:'manual'`) e, quando arriva,
rinaviga sullo stesso endpoint lasciando seguire il redirect al browser. Vale per
tutti e tre i punti in cui la SPA scarica un file di output: il bottone primario
e i due percorsi podcast.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path("static/js/app.js").read_text(encoding="utf-8")

FETCH_SITES = ["downloadFile", "downloadPodcast", "downloadPodcastZip"]


def _extract_fn(name):
    marker = "function %s(" % name
    start = APP.find(marker)
    assert start >= 0, "%s non trovata" % name
    depth = 0
    i = APP.index("{", start)
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError("parentesi non bilanciate in %s" % name)


@pytest.mark.parametrize("fn_name", FETCH_SITES)
def test_download_fetch_asks_for_the_redirect_instead_of_following_it(fn_name):
    fn = _extract_fn(fn_name)
    assert "redirect:'manual'" in fn, \
        "%s segue il redirect: su cold storage fallisce per CORS" % fn_name


@pytest.mark.parametrize("fn_name", FETCH_SITES)
def test_every_download_fetch_handles_the_cold_redirect(fn_name):
    fn = _extract_fn(fn_name)
    assert "_coldRedirect(r)" in fn
    assert "_coldNavigate(" in fn


def test_no_download_fetch_left_without_the_manual_redirect():
    # Rete di sicurezza: un quarto punto di download aggiunto in futuro senza
    # l'opzione ricadrebbe nello stesso difetto, in silenzio e solo dopo la
    # finestra calda (cioe' mai durante i test manuali del giorno stesso).
    for riga in APP.splitlines():
        if "fetch('/api/download" in riga:
            assert "redirect:'manual'" in riga, riga.strip()


def test_the_cold_check_comes_before_the_generic_error_branch():
    # Una risposta opaqueredirect ha ok=false e status 0: se il controllo
    # arrivasse dopo `if(!r.ok)` il redirect finirebbe nel ramo d'errore
    # generico e l'utente vedrebbe "Download failed" invece del file.
    fn = _extract_fn("downloadFile")
    assert fn.index("_coldRedirect(r)") < fn.index("if(!r.ok)")


def test_cold_navigation_uses_the_same_endpoint_not_a_parsed_location():
    # La Location di una risposta opaca non e' leggibile da JS: il fix deve
    # rinavigare sull'endpoint, non provare a estrarre il presigned URL.
    fn = _extract_fn("downloadFile")
    assert "_coldNavigate(dlUrl)" in fn
    assert "headers.get('Location')" not in APP


CASES = [
    # (descrizione, risposta simulata, atteso)
    ("redirect opaco verso cold", {"type": "opaqueredirect", "status": 0,
                                   "ok": False}, True),
    ("file servito da locale", {"type": "basic", "status": 200, "ok": True},
     False),
    ("job non trovato", {"type": "basic", "status": 404, "ok": False}, False),
    ("cooldown", {"type": "basic", "status": 429, "ok": False}, False),
    ("risposta assente", None, False),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_cold_redirect_detection_behavior(tmp_path):
    src = _extract_fn("_coldRedirect")
    script = tmp_path / "check.js"
    script.write_text(
        src
        + "\nconst CASES=" + json.dumps([c for _d, c, _e in CASES]) + ";"
        + "\nconsole.log(JSON.stringify(CASES.map(_coldRedirect)));",
        encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout.strip())
    expected = [e for _d, _c, e in CASES]
    labels = [d for d, _c, _e in CASES]
    assert got == expected, "mismatch: %s" % list(zip(labels, got, expected))
