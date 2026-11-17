# Pagina /admin/audit-premium, tab Audit TTS: i job ABM TTS (batch) (voci
# Pocket, VPS a canone fisso) hanno costo zero. La colonna Modello mostrava la
# chiave grezza «v1» e il margine % a costo zero diventava «0.00%», letto come
# margine nullo.
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import pocket_catalog

ADMIN_HTML = pathlib.Path(__file__).resolve().parent.parent.joinpath(
    "templates", "pages", "admin_audit_premium.html")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")


def _html():
    return ADMIN_HTML.read_text(encoding="utf-8")


def _js_fn(html, name):
    start = html.index("function %s(" % name)
    depth = 0
    for j in range(html.index("{", start), len(html)):
        depth += {"{": 1, "}": -1}.get(html[j], 0)
        if depth == 0:
            return html[start:j + 1]
    raise AssertionError(name)


def _model_display(html):
    m = re.search(r"const MODEL_DISPLAY = (\{[^}]*\});", html)
    assert m, "MODEL_DISPLAY non trovato"
    return json.loads(m.group(1))


def test_la_chiave_pocket_si_legge_batch():
    # La chiave persistita e' il MODEL_ID del voice id (pocket:v1:...): se
    # cambia, l'etichetta della colonna deve seguirla.
    assert _model_display(_html())[pocket_catalog.MODEL_ID] == "Batch"


def test_filtro_modello_ha_abm_tts_batch():
    assert ('<option value="%s">ABM TTS (batch)</option>' % pocket_catalog.MODEL_ID) in _html()


def test_righe_e_aggregati_usano_il_margine_non_definito_a_costo_zero():
    html = _html()
    assert "${fmtMarginPct(netMarg, gCost)}" in html
    assert 'fmtMarginPct(agg.net_margin_eur, agg.google_cost_eur)' in html
    assert "fmtMarginPct(netTot, costTot)" in html


@needs_node
def test_fmt_margin_pct_in_node(tmp_path):
    html = _html()
    script = tmp_path / "pct.js"
    script.write_text(
        _js_fn(html, "fmtPct") + "\n" + _js_fn(html, "fmtMarginPct") + "\n"
        "console.log(JSON.stringify([fmtMarginPct(0.33, 0), fmtMarginPct(0.5, 1),"
        " fmtMarginPct(-0.2, 1), fmtMarginPct(0, null)]));\n",
        encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    zero_cost, pos, neg, none_cost = json.loads(res.stdout)
    assert "—" in zero_cost and "%" not in zero_cost
    assert "50.00%" in pos and "delta-positive" in pos
    assert "-20.00%" in neg and "delta-negative" in neg
    assert "—" in none_cost
