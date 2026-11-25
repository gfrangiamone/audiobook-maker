# test/test_app_js_lang_confirm_before_payment.py
"""Regressione: la conferma della lingua ipotizzata arriva PRIMA del pagamento.

Job d-A3rrGjLJZ7MKXky_sVTg (24/11/2026, app Android): PayPal incassato alle
23:13:17, cinque secondi dopo `startCombinedGeneration` si ferma senza
chiamare il server (nessun optimize/generate), l'utente cambia opzioni e
abbandona; alle 23:46 il job viene smaltito come "stale analyzed" con la
cattura `used:false`. L'unica uscita silenziosa compatibile e' il modale della
lingua ipotizzata (`_validateLanguage`), che stava solo dopo il pagamento.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def _extract_fn(name):
    marker = "function %s(" % name
    start = APP.find(marker)
    assert start >= 0, "%s non trovata" % name
    if APP[max(0, start - 6):start] == "async ":
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


def test_onGenerateClick_conferma_la_lingua_prima_del_pagamento():
    fn = _extract_fn("onGenerateClick")
    pos_val = fn.find("_validateLanguage()")
    assert pos_val >= 0, "onGenerateClick deve confermare la lingua ipotizzata"
    for dopo in ("_doCombinedEstimate()", "openPaymentModal(", "startCombinedGeneration("):
        assert pos_val < fn.find(dopo), "la conferma lingua deve precedere %s" % dopo


def test_reset_del_job_azzera_la_conferma():
    assert "_langAssumedAck=false;previewListened=false;" in APP
    assert "_langAssumedAck=false" in _extract_fn("initBookLanguage")


JS = """
let bookData={}, bookLangState={code:'de',source:'assumed'}, previewListened=false, _langAssumedAck=false;
const risposte=%s; const domande=[];
async function _showLangWarning(){domande.push(1);return risposte.shift();}
%s
(async()=>{
  const out=[];
  out.push(await _validateLanguage());   // prima domanda (onGenerateClick)
  out.push(await _validateLanguage());   // seconda chiamata (startCombinedGeneration)
  console.log(JSON.stringify({out, domande:domande.length}));
})();
"""


def _run(risposte):
    node = shutil.which("node")
    if not node:
        pytest.skip("node non disponibile")
    src = JS % (json.dumps(risposte), _extract_fn("_validateLanguage"))
    r = subprocess.run([node, "-e", src], capture_output=True, text=True,
                       encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_conferma_data_non_riapre_il_modale_a_pagamento_avvenuto():
    assert _run([True]) == {"out": [True, True], "domande": 1}


def test_annullo_blocca_e_alla_prossima_richiede():
    assert _run([False, True]) == {"out": [False, True], "domande": 2}
