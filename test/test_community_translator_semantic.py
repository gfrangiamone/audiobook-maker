"""Controllo semantico delle traduzioni community (System One).

`_looks_untranslated` riconosce solo la copia IDENTICA dell'originale. Il
commento riscritto a meta', o finito nella lingua sbagliata senza essere un
verbatim, passava indisturbato; e con `source_lang` vuoto l'intero controllo
si spegneva. Questi test coprono il giudizio per slot e il recupero della
lingua sorgente.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import community_translator as ct
import semantic_judge as sj


# Senza `typesafe-sdk` installato le classi delle domande sono None e il
# motore System One non parte: questi test non hanno nulla da esercitare.
# I test del fail-open (servizio assente, ripiego sull'LLM) restano attivi:
# sono proprio quelli che coprono l'ambiente senza SDK.
requires_sdk = pytest.mark.skipif(
    sj.Noul is None, reason="typesafe-sdk non installato")


DE = ("Ich habe seit letzter Woche wann immer ich ein Hoerbuch erstellen lassen "
      "will mit Premium Sprache Deutsch eine Fehlermeldung erhalten")
IT = ("Da settimana scorsa ogni volta che provo a creare un audiolibro con voce "
      "premium tedesca ricevo un messaggio di errore")
EN = ("Since last week, every time I try to create an audiobook with a German "
      "premium voice I get an error message")


def response(nouls=None, src=None, conf=1.0):
    return SimpleNamespace(
        nouls={k: SimpleNamespace(noul=v) for k, v in (nouls or {}).items()},
        choices=({"source_lang": SimpleNamespace(choice=src, confidence=conf)}
                 if src is not None else {}),
        scores={},
    )


def data_all(text, **overrides):
    d = {lg: {"comment": text} for lg in ct.LANGS}
    for lg, t in overrides.items():
        d[lg] = {"comment": t}
    return d


# --------------------------------------------------------------------------
# costruzione delle domande
# --------------------------------------------------------------------------

@requires_sdk
def test_questions_cover_long_slots_only():
    data = data_all(IT, en="ok!", fr="")
    qs = ct._semantic_questions(data, {"comment": ""})
    assert "source_lang" in qs
    assert ct._slot_key("it", "comment") in qs
    # Slot troppo corto o vuoto: la lingua non e' determinabile, non si chiede.
    assert ct._slot_key("en", "comment") not in qs
    assert ct._slot_key("fr", "comment") not in qs


@requires_sdk
def test_questions_restricted_by_only():
    data = data_all(IT)
    qs = ct._semantic_questions(data, {"comment": ""},
                                only={("de", "comment")}, detect_src=False)
    assert set(qs) == {ct._slot_key("de", "comment")}


def test_empty_slots():
    data = data_all(IT, fr="", zh="   ")
    assert ct._empty_slots(data, {"comment": ""}) == {("fr", "comment"),
                                                      ("zh", "comment")}


# --------------------------------------------------------------------------
# scarto degli slot nella lingua sbagliata
# --------------------------------------------------------------------------

@requires_sdk
def test_drops_slot_in_wrong_language():
    """Il caso dell'incidente, ma senza copia identica: tedesco *riscritto*
    nello slot italiano. `_looks_untranslated` non lo vede, il giudizio si."""
    data = data_all(EN, de=DE, it=DE.replace("Hoerbuch", "Hörbuch"))
    probs = {ct._slot_key(lg, "comment"): 0.98 for lg in ct.LANGS}
    probs[ct._slot_key("it", "comment")] = 0.02
    with patch.object(sj, "ask", return_value=response(probs, src="de")):
        src = ct._semantic_review(data, {"comment": DE}, "de")
    assert src == "de"
    assert data["it"]["comment"] == ""
    assert data["de"]["comment"] == DE       # lo slot sorgente resta
    assert data["fr"]["comment"] == EN       # gli altri non si toccano


@requires_sdk
def test_uncertain_slot_is_kept():
    """Si apre un buco solo sul caso netto: l'incertezza non basta, perche'
    lo slot vuoto costa all'utente una lingua."""
    data = data_all(IT)
    probs = {ct._slot_key(lg, "comment"): 0.40 for lg in ct.LANGS}
    with patch.object(sj, "ask", return_value=response(probs, src="it")):
        ct._semantic_review(data, {"comment": IT}, "it")
    assert all(data[lg]["comment"] == IT for lg in ct.LANGS)


@requires_sdk
def test_review_limited_to_refilled_slots():
    data = data_all(IT)
    probs = {ct._slot_key(lg, "comment"): 0.01 for lg in ct.LANGS}
    with patch.object(sj, "ask", return_value=response(probs)):
        ct._semantic_review(data, {"comment": IT}, "it",
                            only={("hi", "comment")})
    assert data["hi"]["comment"] == ""
    assert data["fr"]["comment"] == IT


# --------------------------------------------------------------------------
# lingua sorgente
# --------------------------------------------------------------------------

@requires_sdk
def test_source_lang_recovered_when_missing():
    """Senza sorgente `_drop_copied_slots` non fa nulla: la Choice le
    restituisce il presupposto che le mancava."""
    data = data_all(IT)
    with patch.object(sj, "ask", return_value=response({}, src="it", conf=0.95)):
        assert ct._semantic_review(data, {"comment": IT}, "") == "it"


@requires_sdk
def test_declared_source_lang_overridden_only_when_confident():
    data = data_all(IT)
    with patch.object(sj, "ask", return_value=response({}, src="de", conf=0.55)):
        assert ct._semantic_review(data, {"comment": IT}, "it") == "it"
    with patch.object(sj, "ask", return_value=response({}, src="de", conf=0.95)):
        assert ct._semantic_review(data, {"comment": IT}, "it") == "de"


def test_review_is_a_noop_without_service():
    """Non configurato o servizio giu': si torna al comportamento di prima,
    nessuno slot toccato."""
    data = data_all(IT)
    with patch.object(sj, "ask", return_value=None):
        assert ct._semantic_review(data, {"comment": IT}, "it") == "it"
    assert all(data[lg]["comment"] == IT for lg in ct.LANGS)


# --------------------------------------------------------------------------
# integrazione in translate()
# --------------------------------------------------------------------------

def _llm_payload(it_text):
    return json.dumps({
        "source_lang": "de",
        **{lg: {"comment": EN} for lg in ct.LANGS},
        "de": {"comment": DE},
        "it": {"comment": it_text},
    })


@requires_sdk
def test_translate_drops_wrong_language_slot_end_to_end():
    calls = []

    def fake_llm(payload, **kw):
        calls.append(kw)
        if len(calls) == 1:
            return _llm_payload(DE.replace("Hoerbuch", "Hörbuch"))
        # retry mirato sullo slot italiano rimasto vuoto
        return json.dumps({"it": {"comment": IT}})

    probs = {ct._slot_key(lg, "comment"): 0.97 for lg in ct.LANGS}
    bad = dict(probs)
    bad[ct._slot_key("it", "comment")] = 0.03

    with patch.object(ct, "is_available", return_value=True), \
         patch.object(ct, "_call_llm", side_effect=fake_llm), \
         patch.object(sj, "ask", side_effect=[response(bad, src="de"),
                                              response(probs)]):
        out = ct.translate({"comment": DE})

    assert out is not None
    assert out["source_lang"] == "de"
    # Lo slot italiano e' stato scartato dal giudizio e ricostruito dal retry.
    assert out["it"]["comment"] == IT
    assert len(calls) == 2


def test_translate_unchanged_without_service():
    """Con il giudizio spento `translate()` si comporta esattamente come
    prima: nessuna richiesta in piu', nessuno slot scartato."""
    def fake_llm(payload, **kw):
        return _llm_payload(IT)

    with patch.object(ct, "is_available", return_value=True), \
         patch.object(ct, "_call_llm", side_effect=fake_llm), \
         patch.object(sj, "ask", return_value=None):
        out = ct.translate({"comment": DE})

    assert out is not None
    assert out["it"]["comment"] == IT
    assert out["de"]["comment"] == DE
