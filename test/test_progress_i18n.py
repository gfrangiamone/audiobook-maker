# -*- coding: utf-8 -*-
"""Le barre di avanzamento parlano una lingua sola.

Il pannello mostrava «Converting to M4B...» in inglese sopra «Conversione M4B»
in italiano, e nella fase di ottimizzazione mostrava frasi inglesi dentro
un'interfaccia per il resto tradotta: il server scriveva i messaggi e il client
ne traduceva solo qualcuno. Ora il server emette inglese canonico e il client
traduce, ma la catena regge finche' le tre estremita' restano allineate — le
costanti lato server, la mappa di app.js, le chiavi delle sette lingue. Queste
prove sono la cerniera che tiene insieme le tre.
"""
from pathlib import Path
import re

import audio_utils
import generation_engine

APP_JS = Path("static/js/app.js")
I18N = Path("templates/_fragments/i18n_data.js")
LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
# Chiavi che il client usa senza passare da SERVER_MSG_KEYS, e che quindi la
# mappa non basta a proteggere.
CHIAVI_FUORI_MAPPA = {"opt_chapter"}
# I buchi che il client riempie in opt_chapter: una traduzione che ne scrive
# uno diverso lo mostra all'utente cosi' com'e', graffe comprese.
BUCHI_OPT_CHAPTER = {"n", "tot", "title"}


def _mappa_client():
    """Coppie messaggio-canonico -> chiave i18n lette da SERVER_MSG_KEYS."""
    testo = APP_JS.read_text(encoding="utf-8")
    m = re.search(r"const SERVER_MSG_KEYS=\{(.*?)\n\};", testo, re.S)
    assert m, "SERVER_MSG_KEYS non trovata in app.js"
    return dict(re.findall(r'"([^"]*)"\s*:\s*"([^"]*)"', m.group(1)))


def _costanti_server():
    """Tutti i messaggi che il server puo' scrivere in una barra di avanzamento."""
    fuori = {n: getattr(audio_utils, n) for n in dir(audio_utils)
             if n.startswith("M4B_MSG_")}
    fuori.update({n: getattr(generation_engine, n) for n in dir(generation_engine)
                  if n.startswith("OPT_MSG_")})
    return fuori


def _regex_capitolo():
    """OPT_CHAPTER_RE letta da app.js, tradotta nella sintassi di Python."""
    testo = APP_JS.read_text(encoding="utf-8")
    m = re.search(r"const OPT_CHAPTER_RE=/(.*?)/;", testo)
    assert m, "OPT_CHAPTER_RE non trovata in app.js"
    return re.compile(m.group(1).replace(chr(92) + "/", "/"))


def test_ogni_messaggio_del_server_e_traducibile():
    mappa = _mappa_client()
    orfani = [f"{n}={v!r}" for n, v in _costanti_server().items()
              if v not in mappa and "{" not in v]
    assert not orfani, (
        "messaggi che il server manda e il client non sa tradurre: "
        + ", ".join(orfani))


def test_il_messaggio_del_capitolo_lo_riconosce_il_client():
    """L'unico messaggio con dei buchi dentro non passa dalla mappa: va riconosciuto.

    Se qualcuno riscrive OPT_MSG_CHAPTER e dimentica la regex di la', la frase
    del capitolo torna cruda in mezzo a un'interfaccia tradotta, e non se ne
    accorge nessuno finche' non lo vede un utente.
    """
    vera = generation_engine.OPT_MSG_CHAPTER.format(
        n=3, total=12, title="Il mondo di ieri")
    assert _regex_capitolo().match(vera), (
        f"OPT_CHAPTER_RE non riconosce il messaggio vero: {vera!r}")


def test_ogni_messaggio_con_i_buchi_ha_la_sua_chiave():
    """Un messaggio parametrico senza chiave i18n non e' traducibile da nessuno."""
    parametrici = [n for n, v in _costanti_server().items() if "{" in v]
    assert parametrici == ["OPT_MSG_CHAPTER"], (
        "nuovo messaggio parametrico senza traduzione prevista: " + ", ".join(parametrici))


def test_ogni_chiave_della_mappa_esiste_in_tutte_le_lingue():
    testo = I18N.read_text(encoding="utf-8")
    mancanti = []
    for chiave in sorted(set(_mappa_client().values()) | CHIAVI_FUORI_MAPPA):
        trovate = len(re.findall(rf"(?:^|[,{{]){re.escape(chiave)}\s*:", testo))
        if trovate != len(LANGS):
            mancanti.append(f"{chiave}: {trovate}/{len(LANGS)}")
    assert not mancanti, "chiavi non presenti in tutte le lingue: " + ", ".join(mancanti)


def test_le_traduzioni_del_capitolo_usano_i_buchi_giusti():
    testo = I18N.read_text(encoding="utf-8")
    valori = re.findall(r'opt_chapter:"([^"]*)"', testo)
    assert len(valori) == len(LANGS), f"opt_chapter in {len(valori)}/{len(LANGS)} lingue"
    for v in valori:
        buchi = set(re.findall(r"\{(\w+)\}", v))
        assert buchi == BUCHI_OPT_CHAPTER, f"buchi sbagliati in {v!r}: {sorted(buchi)}"


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
