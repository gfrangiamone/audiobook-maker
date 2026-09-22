#!/usr/bin/env python3
"""
transcript_judge.py — L'utente ha letto la frase, o un'altra?

Il gate del voice cloning confronta la frase guidata con quel che whisper
sente e scarta il campione sopra un CER (`ABM_VOICE_CLONE_MAX_CER`, 0.25).
Il CER pero' non distingue le due cose che stanno sopra soglia: chi legge
**un altro testo** — il caso da fermare, perche' la frase guidata e' la prova
del consenso — e chi legge **la frase giusta** con un accento marcato, una
cadenza regionale o un microfono mediocre, che whisper trascrive a modo suo.
Il secondo se ne va con «Transcript does not match» e non capisce perche':
ha letto esattamente quello che c'era scritto.

Qui la domanda si pone **solo sopra soglia** — sotto, il campione e' gia'
accettato e non c'e' niente da chiedere — e puo' solo *recuperare*: un
giudizio mancante, ambiguo o negativo lascia il rifiuto dov'era. Volume
minimo (i soli campioni respinti), e nessuna possibilita' di allentare il
gate per un inciampo tecnico.

Sopra `ABM_TRANSCRIPT_MAX_CER` non si chiede nulla: a quella distanza non
c'e' accento che tenga, e' un altro testo.

Modulo **foglia**: stdlib + `semantic_judge`, nessun import dal progetto.

Configurazione (env):
  ABM_TRANSCRIPT_JUDGE_MODE  off | observe | on        (default: observe)
  ABM_TRANSCRIPT_MIN_SAME    p da cui in su e' la stessa frase (default: 0.85)
  ABM_TRANSCRIPT_MIN_WHOLE   p da cui in su e' letta intera    (default: 0.70)
  ABM_TRANSCRIPT_MAX_CER     CER oltre cui non si chiede       (default: 0.60)
  ABM_TRANSCRIPT_MIN_CHARS   frase piu' corta: nessun giudizio (default: 20)
"""

import json
import os
from datetime import datetime, timezone

import semantic_judge as sj

_MAX_CHARS = 1200        # le frasi guidate sono corte; il taglio e' una rete

_DEFAULT_MODE = "observe"
_MODES = ("off", "observe", "on")


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def _env_float(name, default):
    try:
        return float(_env(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(name, default):
    try:
        return int(float(_env(name, "") or default))
    except (TypeError, ValueError):
        return default


def mode():
    """`off`, `observe` o `on`. Un valore ignoto vale il default, non `on`."""
    m = _env("ABM_TRANSCRIPT_JUDGE_MODE", _DEFAULT_MODE).lower()
    return m if m in _MODES else _DEFAULT_MODE


def enabled():
    return mode() != "off" and sj.is_available()


def applies():
    """True se il recupero cambia davvero l'esito del gate."""
    return mode() == "on"


def min_same():
    """Probabilita' da cui in su il campione contiene la frase guidata.

    Alta di proposito: qui si scavalca un gate anti-abuso, e il costo di un
    recupero sbagliato (il campione di una voce altrui accettato) non e'
    paragonabile a quello di un recupero mancato (l'utente rilegge)."""
    return max(0.0, min(1.0, _env_float("ABM_TRANSCRIPT_MIN_SAME", 0.85)))


def min_whole():
    """Probabilita' da cui in su la frase e' letta per intero.

    Piu' bassa della precedente: qui l'incertezza nasce quasi sempre dalla
    trascrizione, che mangia l'ultima parola o la prima sillaba, non dal
    lettore. Un campione davvero mozzo cade comunque sulle misure di durata,
    che sono deterministiche."""
    return max(0.0, min(1.0, _env_float("ABM_TRANSCRIPT_MIN_WHOLE", 0.70)))


def max_cer():
    """CER oltre cui non si chiede: a quella distanza non e' un accento."""
    return max(0.0, _env_float("ABM_TRANSCRIPT_MAX_CER", 0.60))


def min_chars():
    """Sotto questa lunghezza la frase e' troppo corta perche' il giudizio
    valga piu' del CER: due parole sbagliate su cinque sono meta' frase."""
    return max(1, _env_int("ABM_TRANSCRIPT_MIN_CHARS", 20))


# ---------------------------------------------------------------------------
# Domande
# ---------------------------------------------------------------------------

def _clip(text):
    t = (text or "").strip()
    return t if len(t) <= _MAX_CHARS else t[:_MAX_CHARS].rstrip() + " [...]"


def _state(expected, heard, cer, lang=""):
    return {
        "task": "A person recorded themselves reading a sentence shown on "
                "screen, to register their own voice. The recording was then "
                "transcribed automatically. The transcript is what the "
                "software heard, not what was said: it mangles accents, "
                "regional pronunciation, proper names and numbers, and it "
                "writes down homophones.",
        "language": lang or "",
        "expected": _clip(expected),
        "transcript": _clip(heard),
        "character_error_rate": round(float(cer or 0.0), 3),
    }


def _questions():
    if sj.Noul is None:
        return {}
    Noul, Crit = sj.Noul, sj.NoulCriteria
    return {
        "same": Noul(
            instructions="Was the person reading `expected`?",
            criteria=Crit(
                true="`transcript` follows `expected` word by word, in the "
                     "same order. The differences are what a transcriber "
                     "makes of a marked accent or a poor microphone: similar "
                     "sounding words, homophones, a name spelled wrong, a "
                     "number written in digits, missing or added punctuation, "
                     "a word split in two.",
                false="`transcript` says something else: other words, another "
                      "subject, a different sentence, improvised speech, or a "
                      "sentence that merely resembles `expected` in topic "
                      "without following it.",
            ),
        ),
        "whole": Noul(
            instructions="Does `transcript` cover `expected` from beginning "
                         "to end?",
            criteria=Crit(
                true="Something in `transcript` corresponds to the opening "
                     "words of `expected` and something corresponds to its "
                     "closing words, however mangled.",
                false="`transcript` starts partway through `expected` or "
                      "stops before its end: a whole clause of `expected` has "
                      "no counterpart.",
            ),
        ),
    }


# ---------------------------------------------------------------------------
# Giudizio
# ---------------------------------------------------------------------------

def review(expected, heard, cer, *, lang="", timeout=None):
    """Probabilita' per domanda, `{}` se non c'e' giudizio (SDK assente,
    servizio giu', risposta monca). `{}` non significa mai «recupera»."""
    if not enabled():
        return {}
    questions = _questions()
    if not questions:
        return {}
    resp = sj.ask(_state(expected, heard, cer, lang), questions,
                  timeout=timeout)
    if resp is None:
        return {}
    probs = {}
    for key in questions:
        p = sj.noul(resp, key)
        if p is not None:
            probs[key] = float(p)
    return probs


def verdict(probs):
    """True solo se **entrambe** le domande hanno risposto, e hanno risposto
    bene. Una domanda rimasta senza risposta non recupera niente."""
    if not probs:
        return False
    same = probs.get("same")
    whole = probs.get("whole")
    if same is None or whole is None:
        return False
    return same >= min_same() and whole >= min_whole()


def _audit_path():
    d = _env("ABM_DATA_DIR")
    if not d or not os.path.isdir(d):
        return ""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return os.path.join(d, f"transcript_judge_audit_{month}.jsonl")


def write_audit(expected, heard, cer, probs, rescued, *, lang="",
                client_id=""):
    """Una riga per campione giudicato. E' il dataset con cui decidere se
    accendere `on`: quante letture corrette il CER stava buttando via, e
    quante volte il giudice ha detto di no. Best-effort."""
    try:
        path = _audit_path()
        if not path or not probs:
            return
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": mode(),
            "client_id": str(client_id or "")[:40],
            "language": lang or "",
            "cer": round(float(cer or 0.0), 3),
            "probs": {k: round(float(v), 3) for k, v in probs.items()},
            "rescued": bool(rescued),
            "applied": bool(rescued) and applies(),
            "expected": (expected or "")[:200],
            "heard": (heard or "")[:200],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: BLE001 - l'audit non decide niente
        print(f"[transcript_judge] audit non scritto: "
              f"{type(e).__name__}: {e}", flush=True)


def rescues(expected, heard, cer, *, lang="", client_id="", timeout=None):
    """True se il campione va accettato nonostante il CER sopra soglia.

    Si chiama **solo** quando il gate sta per rifiutare: sotto soglia non
    c'e' niente da recuperare. Non solleva mai e, nel dubbio, risponde False
    — cioe' il rifiuto che il gate aveva gia' deciso. In `observe` calcola e
    registra ma restituisce sempre False.
    """
    try:
        if len((expected or "").strip()) < min_chars():
            return False
        if not (heard or "").strip():
            return False      # silenzio o audio illeggibile: niente da salvare
        if float(cer or 0.0) > max_cer():
            return False
        probs = review(expected, heard, cer, lang=lang, timeout=timeout)
        if not probs:
            return False
        ok = verdict(probs)
        write_audit(expected, heard, cer, probs, ok, lang=lang,
                    client_id=client_id)
        if not ok or not applies():
            return False
        print(f"[transcript_judge] campione recuperato (cer {float(cer):.2f}, "
              f"same={probs.get('same', 0):.2f}, "
              f"whole={probs.get('whole', 0):.2f})", flush=True)
        return True
    except Exception as e:      # noqa: BLE001 - fail-close sul recupero
        print(f"[transcript_judge] giudizio non applicato: "
              f"{type(e).__name__}: {e}", flush=True)
        return False
