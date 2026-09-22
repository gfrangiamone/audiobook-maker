#!/usr/bin/env python3
"""
translation_judge.py — Il capitolo e' stato tradotto, o ricopiato?

Sulla community e' gia' successo: l'LLM, invece di tradurre, ricopia il
verbatim sorgente nello slot di un'altra lingua. Nella traduzione di un libro
lo stesso inciampo non lascia traccia — `call_llm` vede una risposta piena,
il chunk si concatena, l'epub si scrive — e l'utente scopre pagando che un
capitolo e' rimasto nella lingua di partenza, o che meta' pagina e' sparita
in un riassunto.

Il volume qui e' per chunk, quindi il controllo e' **a campione**: il primo
chunk di ogni capitolo. E' il punto dove l'errore si manifesta — un modello
che ricopia lo fa dall'inizio — e costa un giudizio per capitolo, non per
pagina.

La copia identica non si chiede a nessuno: si riconosce con un confronto, ed
e' gratis. La domanda semantica serve per il resto — la lingua sbagliata, il
riassunto, il preambolo, il capitolo tagliato a meta'.

Modulo **foglia**: stdlib + `semantic_judge`, nessun import dal progetto.

Configurazione (env):
  ABM_TRJUDGE_MODE            off | observe | on       (default: observe)
  ABM_TRJUDGE_MIN_TRANSLATED  p sotto cui non e' tradotto  (default: 0.50)
  ABM_TRJUDGE_MIN_COMPLETE    p sotto cui manca del testo  (default: 0.35)
  ABM_TRJUDGE_MIN_CHARS       chunk piu' corto: nessun giudizio (default: 400)
"""

import json
import os
from datetime import datetime, timezone

import semantic_judge as sj

# Testa e coda del chunk: l'inizio mostra la copia e il preambolo, la fine
# mostra il taglio. Il centro non risponde a nessuna delle due domande.
_HEAD_CHARS = 900
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
    m = _env("ABM_TRJUDGE_MODE", _DEFAULT_MODE).lower()
    return m if m in _MODES else _DEFAULT_MODE


def enabled():
    return mode() != "off" and sj.is_available()


def applies():
    """True se l'esito fa davvero ritentare il chunk."""
    return mode() == "on"


def min_translated():
    """Probabilita' sotto cui il testo non e' nella lingua di destinazione.

    A meta' strada: un chunk ritentato costa una chiamata, un capitolo
    consegnato nella lingua sbagliata costa il libro."""
    return max(0.0, min(1.0, _env_float("ABM_TRJUDGE_MIN_TRANSLATED", 0.50)))


def min_complete():
    """Probabilita' sotto cui manca del testo.

    Piu' bassa: la traduzione legittima accorpa frasi, sposta incisi e cambia
    paragrafazione, e un giudice prudente lo legge come «qualcosa manca». Il
    caso da prendere e' il riassunto, che e' netto."""
    return max(0.0, min(1.0, _env_float("ABM_TRJUDGE_MIN_COMPLETE", 0.35)))


def min_chars():
    """Sotto questa taglia non si guarda: su poche righe (un titolo di
    sezione, una dedica) la domanda sulla completezza non significa nulla e
    i nomi propri possono coincidere in due lingue."""
    return max(1, _env_int("ABM_TRJUDGE_MIN_CHARS", 400))


# ---------------------------------------------------------------------------
# Pre-filtro deterministico
# ---------------------------------------------------------------------------

def _norm(text):
    return " ".join((text or "").split()).lower()


def looks_copied(source, output):
    """True se l'output ricopia il sorgente. Gratuito e certo: se i due testi
    coincidono non c'e' niente da chiedere a nessuno."""
    a, b = _norm(source), _norm(output)
    if not a or not b:
        return False
    if a == b:
        return True
    # Copia con una coda tagliata: l'inizio identico su un testo lungo non
    # capita per caso fra due lingue diverse.
    n = min(len(a), len(b), 400)
    return n >= 200 and a[:n] == b[:n]


# ---------------------------------------------------------------------------
# Domande
# ---------------------------------------------------------------------------

def _clip(text):
    t = (text or "").strip()
    if len(t) <= _HEAD_CHARS + _TAIL_CHARS:
        return t
    return t[:_HEAD_CHARS].rstrip() + "\n[...]\n" + t[-_TAIL_CHARS:].lstrip()


def _state(source, output, src_lang, dst_lang):
    return {
        "task": "A passage of a book was given to a model to translate. It "
                "was asked for the translation and nothing else: no preamble, "
                "no notes, no summary. Proper names, book titles and "
                "quotations in a third language may legitimately stay as they "
                "are.",
        "source_language": src_lang or "",
        "target_language": dst_lang or "",
        "source": {"chars": len(source or ""), "text": _clip(source)},
        "output": {"chars": len(output or ""), "text": _clip(output)},
    }


def _questions():
    if sj.Noul is None:
        return {}
    Noul, Crit = sj.Noul, sj.NoulCriteria
    return {
        "translated": Noul(
            instructions="Is `output` written in the language named by "
                         "`target_language` (an ISO 639-1 code)?",
            criteria=Crit(
                true="The prose of `output` is in the target language. "
                     "Proper names, titles and short quotations may keep "
                     "their original form.",
                false="`output` is still in the source language — copied "
                      "instead of translated — or in some third language, or "
                      "it mixes untranslated sentences of `source` into the "
                      "target language.",
            ),
        ),
        "complete": Noul(
            instructions="Does `output` render the whole of `source`?",
            criteria=Crit(
                true="Every statement and turn of dialogue in `source` has a "
                     "counterpart in `output`, in the same order, and the end "
                     "of `source` has an end in `output`. Sentences may be "
                     "merged or split and word order may change: that is what "
                     "translating is.",
                false="`output` condenses or summarizes `source`, drops "
                      "paragraphs, stops before `source` ends, or adds a "
                      "preamble, a note or a comment about the translation "
                      "that is not part of the text.",
            ),
        ),
    }


# ---------------------------------------------------------------------------
# Giudizio
# ---------------------------------------------------------------------------

def review(source, output, src_lang, dst_lang, *, timeout=None):
    """Probabilita' per domanda, `{}` se non c'e' giudizio (SDK assente,
    servizio giu', risposta monca). `{}` non significa mai «tradotto bene»."""
    if not enabled():
        return {}
    questions = _questions()
    if not questions:
        return {}
    resp = sj.ask(_state(source, output, src_lang, dst_lang), questions,
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
    """`""` oppure il motivo. Una domanda senza risposta non scarta niente."""
    if not probs:
        return ""
    tr = probs.get("translated")
    if tr is not None and tr < min_translated():
        return "untranslated"
    co = probs.get("complete")
    if co is not None and co < min_complete():
        return "incomplete"
    return ""


def _audit_path():
    d = _env("ABM_DATA_DIR")
    if not d or not os.path.isdir(d):
        return ""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return os.path.join(d, f"translation_judge_audit_{month}.jsonl")


def write_audit(source, output, probs, reason, *, src_lang="", dst_lang="",
                job_id="", chapter="", attempt=1, copied=False):
    """Una riga per chunk campionato, passato e non: e' il dataset con cui
    decidere se accendere `on`. Best-effort, mai fatale per la traduzione."""
    try:
        path = _audit_path()
        if not path:
            return
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": mode(),
            "job_id": str(job_id or "")[:40],
            "chapter": str(chapter or "")[:80],
            "source_lang": src_lang or "",
            "target_lang": dst_lang or "",
            "attempt": int(attempt),
            "copied": bool(copied),
            "chars_in": len(source or ""),
            "chars_out": len(output or ""),
            "probs": {k: round(float(v), 3) for k, v in (probs or {}).items()},
            "reason": reason,
            "applied": bool(reason) and applies(),
            "preview": (output or "")[:200],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: BLE001 - l'audit non ferma un capitolo
        print(f"[translation_judge] audit non scritto: "
              f"{type(e).__name__}: {e}", flush=True)


def check(source, output, src_lang, dst_lang, *, job_id="", chapter="",
          attempt=1, timeout=None):
    """Motivo per cui il chunk va ritentato, `""` se va tenuto.

    Si chiama sul primo chunk di ogni capitolo: e' il campione. Non solleva
    mai — qualunque inciampo vale «nessun giudizio», cioe' il comportamento
    che la traduzione aveva prima di questo modulo. In `observe` calcola e
    registra ma restituisce sempre `""`.
    """
    try:
        if len((source or "").strip()) < min_chars():
            return ""
        copied = looks_copied(source, output)
        if copied:
            # Certezza, non probabilita': non vale una chiamata.
            write_audit(source, output, {}, "untranslated", src_lang=src_lang,
                        dst_lang=dst_lang, job_id=job_id, chapter=chapter,
                        attempt=attempt, copied=True)
            if not applies():
                return ""
            print(f"  [translation_judge] {chapter}: l'output ricopia il "
                  f"sorgente", flush=True)
            return "untranslated"
        probs = review(source, output, src_lang, dst_lang, timeout=timeout)
        if not probs:
            return ""
        reason = verdict(probs)
        write_audit(source, output, probs, reason, src_lang=src_lang,
                    dst_lang=dst_lang, job_id=job_id, chapter=chapter,
                    attempt=attempt)
        if not reason or not applies():
            return ""
        detail = ", ".join(f"{k}={v:.2f}" for k, v in sorted(probs.items()))
        print(f"  [translation_judge] {chapter}: {reason} ({detail})",
              flush=True)
        return reason
    except Exception as e:      # noqa: BLE001 - fail-open, sempre
        print(f"[translation_judge] giudizio non applicato: "
              f"{type(e).__name__}: {e}", flush=True)
        return ""
