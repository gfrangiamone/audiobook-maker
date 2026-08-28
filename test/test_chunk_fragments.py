"""Frammenti di testo (titoli numerali, dediche) lungo il percorso TTS.

Questi test fissano il **comportamento reale** del codice sui chunk brevi, e
sono il residuo eseguibile di una fase di lavoro che si e' chiusa senza
introdurre il rimedio che aveva pianificato (chunking degenere, 2026-08). Due
misure hanno smontato la premessa di quella fase:

1. **Un frammento rifiutato non lascia un buco.** Dal v3.35.0 un chunk che i
   backend Gemini rifiutano per moderazione contenuti (codice `2017`, tipico
   di "XIV." o "1793.") non viene silenziato: `generate_chunk_pcm_gemini` lo
   fa narrare da una voce edge-tts dello stesso genere e accento, e il chunk
   NON conta come fallito. Silenziarlo a monte "per risparmiare la chiamata"
   sarebbe stato un peggioramento: avrebbe cancellato testo che oggi si sente.
2. **Lo splitter aggrega gia' i frammenti al vicino.** Un passo di fusione a
   valle dello split non ha nulla da fondere: un frammento resta isolato solo
   quando il vicino non ha spazio residuo, e in quel caso nemmeno la fusione
   potrebbe rispettare i cap. Misurato su 6000 input casuali (italiano e
   cinese, cap 60-2000 char, byte-cap 200-1800): zero casi in cui la fusione
   cambiava l'esito.

Il caso che resta scoperto e' il capitolo il cui corpo e' vuoto o coincide col
titolo: li' il chunk e' unico, non ha vicini, e la risposta corretta e'
quella del punto 1 — narrarlo con la voce di ripiego, non cancellarlo.

Se un domani lo splitter cambiasse e cominciasse a isolare i frammenti pur
avendo spazio, `test_the_splitter_absorbs_a_fragment_when_there_is_room`
diventa rosso: e' il segnale per riaprire il tema.
"""
import pytest

import tts_split


# --- 2. Lo splitter aggrega i frammenti, non li isola ----------------------

_PARA = ("Il mattino dopo la nave lascio' il porto con il vento a favore e "
         "nessuno a bordo sapeva quanto sarebbe durata la traversata.")


@pytest.mark.parametrize("fragment", ["XIV.", "1793.", "Cap. 12", "Fine."])
def test_the_splitter_absorbs_a_fragment_when_there_is_room(fragment):
    # Titolo davanti al corpo, cap ampio: il frammento non esce mai da solo.
    chunks = tts_split.split_text_into_chunks(
        f"{fragment}\n\n{_PARA}", max_chars=2000, max_bytes=None)
    assert len(chunks) == 1
    assert chunks[0].startswith(fragment)


def test_a_fragment_is_isolated_only_when_the_neighbour_has_no_room():
    # L'unico caso in cui il frammento resta solo: il vicino riempie il cap.
    # Nessun passo di fusione potrebbe recuperarlo senza sforare (150 + 4 + 2
    # supera il cap), ed e' la ragione per cui la fase non ha aggiunto quel
    # passo. Il chunk isolato prosegue verso il backend, dove il ripiego edge
    # lo copre.
    cap = len(_PARA)
    chunks = tts_split.split_text_into_chunks(
        f"XIV.\n\n{_PARA}", max_chars=cap, max_bytes=None)
    assert chunks == ["XIV.", _PARA]
    assert len("XIV.") + len(_PARA) + 2 > cap


# --- 1. Nessun chunk viene cancellato prima della chiamata ----------------
#
# NOTA sul monkeypatch: `generate_chunk_pcm_gemini` fa un late import locale
# `import gemini_tts as _gemini` (per tenere il modulo opzionale). Un
# monkeypatch su `tts_split._gemini` non lo vedrebbe MAI: la variabile locale
# viene rilegata al modulo reale a ogni chiamata. Il punto di aggancio corretto
# e' `gemini_tts.synthesize` (stesso pattern di test_tts_split_pcm.py).

def _ok_synth(recorder):
    def _synth(text, voice_id, output_path=None, **kw):
        recorder.append(text)
        with open(output_path, "wb") as f:
            f.write(bytes(100))
        return {"success": True, "bytes_written": 100, "audio_seconds_real": 1.0,
                "input_tokens": 5, "output_tokens": 25, "model_key": "flash25",
                "voice_name": "Kore", "attempts_used": 1}
    return _synth


@pytest.mark.parametrize("text", [
    "XIV.",              # frammento senza parole: il caso del codice 2017
    "1793",
    "A mia madre.",      # dedica: prosa vera, piu' corta di qualunque soglia
    "Fine.",
    "CIVIL",             # titolo maiuscolo fatto di lettere romane
])
def test_every_chunk_reaches_the_api(text, tmp_path, monkeypatch):
    # Regressione della decisione di fondo: nessuna euristica a monte decide
    # che un chunk "non vale una chiamata". Cancellare testo e' irreversibile e
    # invisibile all'ascoltatore; spendere una chiamata su un titolo no.
    called = []
    monkeypatch.setattr("gemini_tts.synthesize", _ok_synth(called))

    res = tts_split.generate_chunk_pcm_gemini(
        text, "gemini:flash25:Kore", str(tmp_path / "chunk.pcm"))

    assert called == [text]
    assert res["success"] is True


def test_a_rejected_fragment_is_narrated_by_the_edge_fallback(tmp_path, monkeypatch):
    # Il percorso che rende superflua qualunque cancellazione a monte: se il
    # backend rifiuta il frammento fino all'ultimo tentativo, la voce di
    # ripiego lo narra e il chunk non conta come fallito.
    def _rejected(text, voice_id, output_path=None, **kw):
        raise RuntimeError("422 content moderation (2017)")

    recovered = []

    def _fake_edge(text, fallback_lang, rate, output_path, gender=None,
                   accent_code=None):
        recovered.append(text)
        with open(output_path, "wb") as f:
            f.write(bytes(100))
        return {"success": True, "bytes_written": 100, "audio_seconds_real": 1.0,
                "input_tokens": 0, "output_tokens": 0, "model_key": "flash25",
                "voice_name": "edge", "attempts_used": 1,
                "fallback_engine": "edge"}

    monkeypatch.setattr("gemini_tts.synthesize", _rejected)
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", _fake_edge)
    info = {}

    res = tts_split.generate_chunk_pcm_gemini(
        "XIV.", "gemini:flash25:Kore", str(tmp_path / "chunk.pcm"),
        max_retries=1, failure_info=info, fallback_lang="it")

    assert recovered == ["XIV."], "il frammento va narrato, non silenziato"
    assert res is not False and res["success"] is True
    assert info["fallback_engine"] == "edge"


def test_the_plan_no_longer_carries_a_degenerate_flag():
    # La chiave informativa introdotta e poi rimossa: nessun consumatore la
    # leggeva, e restava a suggerire una classificazione che il codice non fa
    # piu'.
    from types import SimpleNamespace

    ch = SimpleNamespace(index=0, title="XIV", text=_PARA, synthetic_title=False)
    plan = tts_split._plan_chunks(SimpleNamespace(chapters=[ch], language="it"))
    assert plan and all("degenerate" not in b for b in plan)
