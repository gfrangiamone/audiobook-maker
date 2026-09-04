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


def test_lingua_dai_metadati():
    assert _derive("it", False) == "metadata"


def test_lingua_rilevata_dall_ia():
    assert _derive("sv", True) == "detected"


def test_lingua_assente():
    assert _derive("", False) == "unknown"


def test_lingua_assente_anche_se_solo_spazi():
    assert _derive("   ", False) == "unknown"


def test_language_source_nella_risposta_analyze():
    assert '"language_source"' in SORGENTE, (
        "la risposta di /api/analyze non espone language_source"
    )


def test_language_source_anche_sul_job_ripreso():
    """Riga 9243: il ramo del job gia' esistente non deve perdere la
    provenienza, altrimenti un job ripreso torna a sembrare `unknown`."""
    assert SORGENTE.count('"language_source"') >= 2, (
        "language_source emesso in un solo punto: il ramo del job ripreso "
        "lo perde"
    )
