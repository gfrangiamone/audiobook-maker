# -*- coding: utf-8 -*-
"""La conversione M4B parla una lingua sola.

Il pannello di avanzamento mostrava «Converting to M4B...» in inglese sopra
«Conversione M4B» in italiano: il server scriveva i messaggi in italiano fisso
e il client ne traduceva uno solo. Ora il server emette inglese canonico e il
client traduce, ma la catena regge finche' le tre estremita' restano allineate
— le costanti di audio_utils.py, la mappa di app.js, le chiavi delle sette
lingue. Queste prove sono la cerniera che tiene insieme le tre.
"""
from pathlib import Path
import re

import audio_utils

APP_JS = Path("static/js/app.js")
I18N = Path("templates/_fragments/i18n_data.js")
LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]


def _mappa_client():
    """Coppie messaggio-canonico -> chiave i18n lette da SERVER_MSG_KEYS."""
    testo = APP_JS.read_text(encoding="utf-8")
    m = re.search(r"const SERVER_MSG_KEYS=\{(.*?)\n\};", testo, re.S)
    assert m, "SERVER_MSG_KEYS non trovata in app.js"
    return dict(re.findall(r'"([^"]*)"\s*:\s*"([^"]*)"', m.group(1)))


def _costanti_server():
    return {n: getattr(audio_utils, n) for n in dir(audio_utils)
            if n.startswith("M4B_MSG_")}


def test_ogni_messaggio_del_server_e_traducibile():
    mappa = _mappa_client()
    orfani = [f"{n}={v!r}" for n, v in _costanti_server().items() if v not in mappa]
    assert not orfani, (
        "messaggi che il server manda e il client non sa tradurre: "
        + ", ".join(orfani))


def test_ogni_chiave_della_mappa_esiste_in_tutte_le_lingue():
    testo = I18N.read_text(encoding="utf-8")
    mancanti = []
    for chiave in sorted(set(_mappa_client().values())):
        trovate = len(re.findall(rf"(?:^|[,{{]){re.escape(chiave)}\s*:", testo))
        if trovate != len(LANGS):
            mancanti.append(f"{chiave}: {trovate}/{len(LANGS)}")
    assert not mancanti, "chiavi non presenti in tutte le lingue: " + ", ".join(mancanti)


def test_nessun_messaggio_m4b_italiano_fisso_lato_server():
    """Il server non sa in che lingua guarda l'utente: non puo' scrivere italiano."""
    colpevoli = []
    for nome in ("audio_utils.py", "generation_engine.py",
                 "templates/_fragments/html_head.html"):
        for i, riga in enumerate(Path(nome).read_text(encoding="utf-8").splitlines(), 1):
            if riga.lstrip().startswith("#"):
                continue
            if "Conversione M4B" in riga:
                colpevoli.append(f"{nome}:{i}")
    assert not colpevoli, "testo M4B italiano fisso in: " + ", ".join(colpevoli)
