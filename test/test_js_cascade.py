"""Esegue i test della cascata JS dentro pytest.

La cascata e' logica pura in JavaScript: i test a grep su app.js — quelli
che verificano che il sorgente CONTENGA certe stringhe — passerebbero con la
cascata rotta. Qui si esegue davvero, con node:test (libreria standard di
Node, nessuna dipendenza aggiunta).

NOTA 1 — perche' un glob e non la directory: `node --test test/js/`
(argomento = directory) e' rotto su Node v24.14.1 su Windows — il test
runner non discende nella directory e prova a `require()`-la come modulo,
fallendo con MODULE_NOT_FOUND, indipendentemente dal contenuto della
directory (riprodotto anche fuori da questo repo). Il pattern glob
esplicito sotto usa lo stesso motore node:test ma non passa per quel
percorso di codice rotto.

NOTA 2 — perche' il solo returncode non basta: `node --test` con un glob
che non trova NESSUN file esce comunque con codice 0 (verificato:
`node --test "test/js/**/*.nonesistente.js"` stampa `tests 0`, `fail 0` ed
esce 0). Se `audio_cascade.test.js` venisse rinominato, spostato o
cancellato, questo wrapper resterebbe verde senza aver eseguito un solo
test — l'esatto scenario che il wrapper esiste per impedire. Per questo si
legge il riepilogo che node:test stampa su stdout (le righe `tests N` /
`fail N`) e si pretende che il numero di test eseguiti sia quello atteso,
non zero.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

RADICE = pathlib.Path(__file__).resolve().parents[1]

# Numero MINIMO di test attesi in test/js/audio_cascade.test.js. E' un
# pavimento, non un valore esatto: task futuri aggiungeranno altri test alla
# cascata e non devono rompere questo wrapper solo perche' il conteggio e'
# salito. Cio' che deve restare impossibile e' che il numero SCENDA sotto la
# protezione attuale (test spariti silenziosamente: rinominati, cancellati,
# glob che non fa piu' match) — di quello il wrapper deve accorgersi.
TEST_ATTESI = 18


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node non installato: la cascata JS non e' verificabile")
def test_cascata_audio_js():
    esito = subprocess.run(
        ["node", "--test", "test/js/**/*.test.js"],
        cwd=RADICE, capture_output=True, text=True, timeout=120,
    )
    output = esito.stdout + esito.stderr

    # `\S*` invece di `\W*` per l'icona di riepilogo: "ℹ" (U+2139) e'
    # classificato da Unicode come lettera minuscola (categoria Ll), quindi
    # \W non lo intercetta e la riga "ℹ tests 14" non farebbe match.
    m_tests = re.search(r"^\S*\s+tests\s+(\d+)\s*$", output, re.MULTILINE)
    m_fail = re.search(r"^\S*\s+fail\s+(\d+)\s*$", output, re.MULTILINE)
    eseguiti = int(m_tests.group(1)) if m_tests else 0
    falliti = int(m_fail.group(1)) if m_fail else -1  # -1: riepilogo non trovato

    assert esito.returncode == 0 and eseguiti >= TEST_ATTESI and falliti == 0, (
        f"cascata JS: attesi almeno {TEST_ATTESI} test eseguiti e 0 falliti, "
        f"trovati {eseguiti} eseguiti e {falliti} falliti "
        f"(returncode={esito.returncode}). Rotti o spariti? Vedi output:\n"
        + output
    )
