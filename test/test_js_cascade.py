"""Esegue i test della cascata JS dentro pytest.

La cascata e' logica pura in JavaScript: i test a grep su app.js — quelli
che verificano che il sorgente CONTENGA certe stringhe — passerebbero con la
cascata rotta. Qui si esegue davvero, con node:test (libreria standard di
Node, nessuna dipendenza aggiunta).

NOTA: `node --test test/js/` (argomento = directory) e' rotto su Node
v24.14.1 su Windows — il test runner non discende nella directory e prova a
`require()`-la come modulo, fallendo con MODULE_NOT_FOUND, indipendentemente
dal contenuto della directory (riprodotto anche fuori da questo repo). Il
pattern glob esplicito sotto usa lo stesso motore node:test ma non passa
per quel percorso di codice rotto.
"""
import pathlib
import shutil
import subprocess

import pytest

RADICE = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node non installato: la cascata JS non e' verificabile")
def test_cascata_audio_js():
    esito = subprocess.run(
        ["node", "--test", "test/js/**/*.test.js"],
        cwd=RADICE, capture_output=True, text=True, timeout=120,
    )
    assert esito.returncode == 0, (
        "test della cascata JS falliti:\n" + esito.stdout + esito.stderr
    )
