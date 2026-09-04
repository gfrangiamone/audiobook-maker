"""Provenienza della lingua del libro nella risposta di /api/analyze.

Tre valori: `metadata` (scritta nel file), `detected` (dedotta dall'IA
leggendo il testo), `unknown` (nessuna delle due). Il client li distingue
per decidere se avvisare l'utente prima di generare.
"""
import pathlib

SORGENTE = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")


def _derive(language, language_detected):
    """Copia della regola, per testarla senza montare l'app intera."""
    from audiobook_app import _derive_language_source
    return _derive_language_source(language, language_detected)


def _block(marker, source=SORGENTE):
    """Ritaglia il dizionario `{...}` che contiene `marker`.

    Cerca `marker` nel sorgente, poi risale al primo `{` non bilanciato che
    lo precede (l'apertura del dict che lo racchiude) e ne ritorna il testo
    fino alla `}` corrispondente. Cosi' un assert puo' ancorarsi al singolo
    blocco di emissione invece che a tutto `audiobook_app.py`: cancellare
    una riga dentro quel dict fa sparire il campo dal ritaglio, non solo
    dal conteggio globale.
    """
    start = source.index(marker)
    depth = 0
    open_idx = None
    i = start - 1
    while i >= 0:
        c = source[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                open_idx = i
                break
            depth -= 1
        i -= 1
    assert open_idx is not None, f"nessuna '{{' di apertura trovata prima di {marker!r}"
    depth = 0
    j = open_idx
    while j < len(source):
        c = source[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[open_idx:j + 1]
        j += 1
    raise AssertionError(f"nessuna '}}' di chiusura trovata per il blocco di {marker!r}")


def test_lingua_dai_metadati():
    assert _derive("it", False) == "metadata"


def test_lingua_rilevata_dall_ia():
    assert _derive("sv", True) == "detected"


def test_lingua_assente():
    assert _derive("", False) == "unknown"


def test_lingua_assente_anche_se_solo_spazi():
    assert _derive("   ", False) == "unknown"


def test_language_source_nella_risposta_analyze():
    """Risposta finale di /api/analyze (dopo il parsing): il blocco che
    inizia con "job_id": job_id, "title": info.title, ... deve esporre
    language_source, altrimenti il client di un'analisi appena fatta non
    sa da dove viene la lingua del libro."""
    blocco = _block('"job_id": job_id, "title": info.title,')
    assert '"language_source"' in blocco, (
        "la risposta finale di /api/analyze non espone language_source"
    )


def test_language_source_nel_job_dict():
    """Dizionario jobs[job_id] creato durante l'analisi: il blocco che
    inizia con "status": "analyzed", "epub_path" deve salvare
    language_source, altrimenti non c'e' nulla da riproporre quando lo
    stesso job viene ripreso (vedi test successivo)."""
    blocco = _block('"status": "analyzed", "epub_path"')
    assert '"language_source"' in blocco, (
        "jobs[job_id] non salva language_source: il job analizzato non ha "
        "da dove recuperarlo in seguito"
    )


def test_language_source_anche_sul_job_ripreso():
    """Ramo del job gia' esistente (~riga 9150): il blocco che inizia con
    "job_id": existing_jid, deve esporre language_source, altrimenti un
    job ripreso torna a sembrare `unknown`."""
    blocco = _block('"job_id": existing_jid,')
    assert '"language_source"' in blocco, (
        "il ramo del job gia' esistente non riespone language_source: un "
        "job ripreso perde la provenienza della lingua"
    )
