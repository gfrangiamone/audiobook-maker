#!/usr/bin/env python3
"""
llm_output_judge.py — Il testo tornato dall'LLM e' davvero il capitolo?

`generation_engine._is_prompt_leak` confronta l'output con il system prompt
carattere per carattere: prende l'eco verbatim e nient'altro. Restano fuori
la parafrasi delle istruzioni, il preambolo («Ecco il testo ottimizzato:»),
il rifiuto, e soprattutto il caso peggiore — il capitolo che torna
**riassunto** invece che ottimizzato. Quel testo passa ogni controllo, viene
sintetizzato e fatturato, e nessuno si accorge che meta' pagina non c'e' piu':
l'utente lo scopre ascoltando.

Qui la domanda e' semantica e si pone **solo sui sospetti**: il rapporto fra
caratteri in ingresso e in uscita e' un pre-filtro gratuito, e dentro la banda
normale non si chiede nulla. L'ottimizzazione per il TTS riscrive, espande
numeri e abbreviazioni, non accorcia di meta'.

Modulo **foglia**: stdlib + `semantic_judge`, nessun import dal progetto.

Configurazione (env):
  ABM_OUTPUT_JUDGE_MODE   off | observe | on           (default: observe)
  ABM_OUTPUT_MIN_META     p da cui in su e' meta-testo  (default: 0.65)
  ABM_OUTPUT_MAX_FAITHFUL p sotto cui e' infedele       (default: 0.35)
  ABM_OUTPUT_RATIO_LOW    sotto, output sospetto corto  (default: 0.60)
  ABM_OUTPUT_RATIO_HIGH   sopra, output sospetto lungo  (default: 1.80)
  ABM_OUTPUT_MIN_CHARS    sotto, nessun controllo       (default: 400)
"""

import json
import os
from datetime import datetime, timezone

import semantic_judge as sj


# Testa e coda di ogni testo: l'inizio mostra il preambolo, la fine mostra il
# troncamento. Il centro non serve a rispondere a nessuna delle due domande e
# moltiplicherebbe il costo per ogni chunk sospetto.
_HEAD_CHARS = 700
_TAIL_CHARS = 300

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
    m = _env("ABM_OUTPUT_JUDGE_MODE", _DEFAULT_MODE).lower()
    return m if m in _MODES else _DEFAULT_MODE


def enabled():
    return mode() != "off" and sj.is_available()


def applies():
    """True se il verdetto fa davvero scartare l'output."""
    return mode() == "on"


def min_meta():
    """Probabilita' da cui in su l'output contiene qualcosa che non e' il
    testo: preambolo, scuse, istruzioni, rifiuto."""
    return max(0.0, min(1.0, _env_float("ABM_OUTPUT_MIN_META", 0.65)))


def max_faithful():
    """Probabilita' sotto cui l'output non e' piu' lo stesso passo riscritto.

    Non troppo alta: lo scarto costa un altro giro di LLM e, se persiste, il
    capitolo va in sintesi non ottimizzato — fastidioso ma integro. Un
    riassunto consegnato, invece, e' testo perso in silenzio."""
    return max(0.0, min(1.0, _env_float("ABM_OUTPUT_MAX_FAITHFUL", 0.35)))


def ratio_low():
    return max(0.0, _env_float("ABM_OUTPUT_RATIO_LOW", 0.60))


def ratio_high():
    return max(0.0, _env_float("ABM_OUTPUT_RATIO_HIGH", 1.80))


def min_chars():
    """Sotto questa taglia non si guarda: su un frammento di poche righe il
    rapporto oscilla da solo e ogni chunk finirebbe sotto giudizio."""
    return max(1, _env_int("ABM_OUTPUT_MIN_CHARS", 400))


# ---------------------------------------------------------------------------
# Pre-filtro deterministico
# ---------------------------------------------------------------------------

def ratio(source, output):
    src = len(source or "")
    if not src:
        return 0.0
    return len(output or "") / float(src)


def suspicious(source, output):
    """`""` se l'output e' nella banda normale, altrimenti il motivo.

    Gratuito e conservativo: decide solo *se vale la pena chiedere*, mai se
    l'output vada scartato."""
    if len(source or "") < min_chars():
        return ""
    r = ratio(source, output)
    if r < ratio_low():
        return "short"
    if r > ratio_high():
        return "long"
    return ""


# ---------------------------------------------------------------------------
# Domande
# ---------------------------------------------------------------------------

def _clip(text):
    t = (text or "").strip()
    if len(t) <= _HEAD_CHARS + _TAIL_CHARS:
        return t
    return t[:_HEAD_CHARS].rstrip() + "\n[...]\n" + t[-_TAIL_CHARS:].lstrip()


def _state(source, output, lang=""):
    return {
        "task": "The model was asked to rewrite a passage of a book so that a "
                "text-to-speech engine reads it well: expanding numbers and "
                "abbreviations, fixing punctuation for the ear. It was not "
                "asked to summarize, shorten or comment.",
        "language": lang or "",
        "source": {"chars": len(source or ""), "text": _clip(source)},
        "output": {"chars": len(output or ""), "text": _clip(output)},
        "length_ratio": round(ratio(source, output), 3),
    }


def _questions():
    if sj.Noul is None:
        return {}
    Noul, Crit = sj.Noul, sj.NoulCriteria
    return {
        "meta": Noul(
            instructions="Does `output` contain anything that is not the "
                         "passage itself?",
            criteria=Crit(
                true="`output` opens with a preamble or closes with a remark "
                     "about the work done, repeats or paraphrases the "
                     "instructions it was given, apologises, refuses, asks a "
                     "question, or adds headings and notes that are not in "
                     "`source`.",
                false="`output` is only the passage: the first words belong to "
                      "the text and nothing frames it. A passage may start "
                      "mid-sentence, or contain dialogue and stage directions, "
                      "when `source` does too.",
            ),
        ),
        "faithful": Noul(
            instructions="Is `output` the same passage as `source`, rewritten "
                         "to be read aloud, with nothing left out?",
            criteria=Crit(
                true="Every event, statement and turn of dialogue in `source` "
                     "is still there, in the same order. The wording may "
                     "change: numbers and abbreviations spelled out, "
                     "punctuation adapted for the ear, a long sentence split "
                     "in two. The ending of `output` corresponds to the ending "
                     "of `source`.",
                false="`output` condenses, summarizes or describes `source` "
                      "instead of rewriting it, drops passages or turns of "
                      "dialogue, or stops before `source` ends — the last "
                      "sentence of `source` has no counterpart.",
            ),
        ),
    }


# ---------------------------------------------------------------------------
# Giudizio
# ---------------------------------------------------------------------------

def review(source, output, *, lang="", timeout=None):
    """Probabilita' per domanda, `{}` se non c'e' giudizio (SDK assente,
    servizio giu', risposta monca). `{}` non significa mai «buono»."""
    if not enabled():
        return {}
    questions = _questions()
    if not questions:
        return {}
    resp = sj.ask(_state(source, output, lang), questions, timeout=timeout)
    if resp is None:
        return {}
    probs = {}
    for key in questions:
        p = sj.noul(resp, key)
        if p is not None:
            probs[key] = float(p)
    return probs


def verdict(probs):
    """`("", "")` oppure `(motivo, dettaglio)`. Serve una risposta esplicita:
    una domanda rimasta senza risposta non scarta niente."""
    if not probs:
        return "", ""
    meta = probs.get("meta")
    if meta is not None and meta >= min_meta():
        return "meta", "meta=%.2f" % meta
    faithful = probs.get("faithful")
    if faithful is not None and faithful <= max_faithful():
        return "unfaithful", "faithful=%.2f" % faithful
    return "", ""


def _audit_path():
    d = _env("ABM_DATA_DIR")
    if not d or not os.path.isdir(d):
        return ""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return os.path.join(d, f"llm_output_judge_audit_{month}.jsonl")


def write_audit(source, output, probs, reason, *, lang="", job_id="",
                chapter="", flag=""):
    """Una riga per chunk giudicato: e' il dataset con cui tarare le soglie
    prima di passare a `on`. Best-effort, mai fatale per la generazione."""
    try:
        path = _audit_path()
        if not path or not probs:
            return
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": mode(),
            "job_id": str(job_id or "")[:40],
            "chapter": str(chapter or "")[:80],
            "language": lang or "",
            "flag": flag,
            "chars_in": len(source or ""),
            "chars_out": len(output or ""),
            "ratio": round(ratio(source, output), 3),
            "probs": {k: round(float(v), 3) for k, v in probs.items()},
            "reason": reason,
            "applied": bool(reason) and applies(),
            "preview": (output or "")[:200],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: BLE001 - l'audit non ferma un capitolo
        print(f"[output_judge] audit non scritto: {type(e).__name__}: {e}",
              flush=True)


def check(source, output, *, lang="", job_id="", chapter="", timeout=None):
    """Motivo per cui l'output va rifiutato, `""` se va tenuto.

    Non solleva mai: qualunque inciampo vale «nessun giudizio», cioe' il
    comportamento che l'app aveva prima di questo modulo. In `observe`
    calcola e registra ma restituisce sempre `""`.
    """
    try:
        flag = suspicious(source, output)
        if not flag:
            return ""
        probs = review(source, output, lang=lang, timeout=timeout)
        if not probs:
            return ""
        reason, detail = verdict(probs)
        write_audit(source, output, probs, reason, lang=lang, job_id=job_id,
                    chapter=chapter, flag=flag)
        if not reason or not applies():
            return ""
        print(f"  [output_judge] output rifiutato ({reason}, {detail}, "
              f"ratio {ratio(source, output):.2f})", flush=True)
        return reason
    except Exception as e:      # noqa: BLE001 - fail-open, sempre
        print(f"[output_judge] giudizio non applicato: "
              f"{type(e).__name__}: {e}", flush=True)
        return ""
