# test/test_app_js_transfer_target.py
"""Regressione: il bottone di trasferimento su app mostra il QR sui desktop.

Difetto osservato: su PC Windows con schermo touch compariva, durante la
generazione, il bottone "Sposta su AudioBook Maker & Player" (CTA mobile con
deep link, che porta via dalla pagina) invece del bottone che apre il QR da
inquadrare col telefono. Causa: `_isMobileLike()` aveva un ramo generico
`pointer:coarse && maxTouchPoints>1` che qualunque PC touch soddisfa.

L'app esiste solo su Android e iOS/iPadOS: il deep link ha senso solo li'.
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


def test_no_generic_touch_heuristic():
    fn = _extract_fn("_isMobileLike")
    assert "pointer:coarse" not in fn, \
        "un PC con schermo touch non e' un dispositivo mobile"
    assert "maxTouchPoints" not in fn


def test_delegates_to_platform_checks():
    fn = _extract_fn("_isMobileLike")
    assert "_isAndroidUA()" in fn
    assert "_isIOSUA()" in fn


def test_transfer_binding_gated_on_mobile():
    """Su desktop il bottone deve restare quello inline che apre il QR."""
    assert "if(!_isMobileLike() || !token) return;" in APP


CASES = [
    # (descrizione, userAgent, maxTouchPoints, atteso mobile)
    ("windows touch pc",
     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36", 10, False),
    ("windows desktop",
     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36", 0, False),
    ("macos desktop",
     "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.0 Safari/605.1.15", 0, False),
    ("android phone",
     "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36", 5, True),
    ("iphone",
     "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148", 5, True),
    ("ipad in ua-desktop",
     "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.0 Safari/605.1.15", 5, True),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_platform_detection_behavior(tmp_path):
    src = "\n".join(_extract_fn(n) for n in
                    ("_isMobileLike", "_isAndroidUA", "_isIOSUA"))
    cases = json.dumps([{"ua": ua, "tp": tp} for _d, ua, tp, _e in CASES])
    script = tmp_path / "check.js"
    # navigator e' read-only in Node: l'assegnazione semplice fallisce in
    # silenzio (sloppy mode) e i casi leggerebbero l'UA di Node.
    # window.matchMedia risponde sempre "coarse": cosi' il test fallirebbe se
    # tornasse un'euristica touch generica.
    script.write_text(
        src
        + "\nconst CASES=" + cases + ";"
        + "\nconst out=CASES.map(c=>{"
          "Object.defineProperty(globalThis,'navigator',"
          "{value:{userAgent:c.ua,maxTouchPoints:c.tp},configurable:true});"
          "globalThis.window={matchMedia:()=>({matches:true})};"
          "return _isMobileLike();});"
          "console.log(JSON.stringify(out));",
        encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout.strip())
    expected = [e for _d, _ua, _tp, e in CASES]
    labels = [d for d, _ua, _tp, _e in CASES]
    assert got == expected, "mismatch: %s" % list(zip(labels, got, expected))
