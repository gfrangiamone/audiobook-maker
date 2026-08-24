# test/test_app_js_progress_resilience.py
"""Regressione: una caduta di rete all'avvio job non deve congelare la pagina.

Difetto osservato in produzione (job premium con ottimizzazione AI):
`_listenOptProgressWiz` era l'unico dei tre listener SSE senza ritentativi
(`es.onerror=function(){es.close()}`). Alla prima interruzione dello stream la
pagina restava a 0% per sempre mentre il job proseguiva lato server; nello
stesso istante falliva anche la fetch del QR di trasferimento, che essendo
"best-effort" senza retry faceva sparire il bottone per tutta la durata del
job; e l'unico canale di errore, `showPErr`, scriveva in `#pra`, che vive in un
blocco `display:none`. Risultato: pagina muta e apparentemente ferma.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path("static/js/app.js").read_text(encoding="utf-8")
HEAD = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")


def _extract_fn(name):
    marker = "function %s(" % name
    start = APP.find(marker)
    assert start >= 0, "%s non trovata" % name
    if APP[start - 6:start] == "async ":   # senza `async` il corpo non gira in node
        start -= 6
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


SSE_LISTENERS = ["_listenOptProgressWiz", "listenProgress", "_listenTranslateProgress"]


@pytest.mark.parametrize("name", SSE_LISTENERS)
def test_sse_listeners_reconnect(name):
    """Ogni listener SSE deve riconnettersi, non chiudersi in silenzio."""
    fn = _extract_fn(name)
    at = fn.find("es.onerror")
    assert at >= 0, "%s non gestisce affatto la caduta dello stream" % name
    handler = fn[at:at + 400]
    assert "setTimeout" in handler, "%s chiude lo stream senza ritentare" % name


@pytest.mark.parametrize("name", ["_listenOptProgressWiz", "listenProgress"])
def test_wizard_sse_retries_are_bounded(name):
    fn = _extract_fn(name)
    assert "maxRetries" in fn, "%s non ha un tetto ai ritentativi" % name
    assert "setTimeout(connect" in fn, "%s non riconnette con backoff" % name


def test_opt_listener_warns_when_retries_exhausted():
    fn = _extract_fn("_listenOptProgressWiz")
    assert "sse_lost" in fn, \
        "esauriti i ritentativi l'utente deve sapere che il canale e' caduto"


def test_sse_lost_message_translated_in_all_languages():
    assert I18N.count("sse_lost:") == 7, "chiave sse_lost mancante in qualche lingua"


def test_transfer_qr_retries():
    fn = _extract_fn("_showTransferQr")
    assert "MAX_ATTEMPTS" in fn and "setTimeout(" in fn, \
        "la fetch del QR deve ritentare sugli errori transitori"
    assert "best-effort: nessun QR, nessun errore visibile" not in fn


def test_showperr_targets_a_visible_container():
    fn = _extract_fn("showPErr")
    assert "progressErr" in fn and "panel5Err" in fn, \
        "showPErr deve scrivere in un contenitore visibile, non solo in #pra"
    for el_id in ("progressErr", "panel5Err"):
        assert 'id="%s"' % el_id in HEAD, "manca il contenitore #%s" % el_id
    # I contenitori devono stare FUORI dal blocco compatibilita' display:none.
    hidden = HEAD.index('<!-- Old progress elements (hidden')
    assert HEAD.index('id="progressErr"') < hidden


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_transfer_qr_retry_behavior(tmp_path):
    """Due errori di rete consecutivi: il QR deve comparire lo stesso."""
    script = tmp_path / "check.js"
    script.write_text(
        _extract_fn("_showTransferQr")
        + """
const img={src:''},box={hidden:true};
const delays=[];let bound=null,calls=0;
globalThis.document={getElementById:id=>({qrImg:img,qrBox:box}[id]||null)};
globalThis._bindTransferButtonForMobile=(b,t)=>{bound=t};
globalThis.setTimeout=(fn,ms)=>{delays.push(ms);Promise.resolve().then(fn)};
globalThis.fetch=async()=>{
  calls++;
  if(calls<3) throw new Error('network down');
  return {ok:true,status:200,json:async()=>({qr:'data:image/png;base64,AAA',token:'TK'})};
};
(async()=>{
  _showTransferQr('job1','qrImg','qrBox');
  for(let i=0;i<200;i++) await Promise.resolve();
  console.log(JSON.stringify({calls,delays,src:img.src,hidden:box.hidden,bound}));
})();
""",
        encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout.strip())
    assert got["calls"] == 3
    assert got["delays"] == [1000, 2000], "backoff esponenziale atteso"
    assert got["src"].startswith("data:image/png"), "QR non applicato all'immagine"
    assert got["hidden"] is False, "il bottone di trasferimento deve comparire"
    assert got["bound"] == "TK"


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_transfer_qr_gives_up_on_4xx(tmp_path):
    """Un 404 e' definitivo: ritentare non cambierebbe l'esito."""
    script = tmp_path / "check404.js"
    script.write_text(
        _extract_fn("_showTransferQr")
        + """
const delays=[];let calls=0;
globalThis.document={getElementById:()=>null};
globalThis.setTimeout=(fn,ms)=>{delays.push(ms);Promise.resolve().then(fn)};
globalThis.console={warn:()=>{}};
globalThis.fetch=async()=>{calls++;return {ok:false,status:404}};
(async()=>{
  _showTransferQr('job1','qrImg','qrBox');
  for(let i=0;i<200;i++) await Promise.resolve();
  process.stdout.write(JSON.stringify({calls,delays}));
})();
""",
        encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout.strip())
    assert got["calls"] == 1
    assert got["delays"] == []
