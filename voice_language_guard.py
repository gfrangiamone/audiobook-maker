#!/usr/bin/env python3
"""
voice_language_guard.py — Il libro e' nella lingua della voce scelta?

Oggi nessuno lo verifica. `<dc:language>` dell'EPUB dice quello che dice —
sulle traduzioni resta spessissimo quello dell'originale — e
`detect_book_language` interviene solo quando il metadato **manca**. Se il
metadato c'e' ed e' sbagliato, o se l'utente sceglie a mano una voce di
un'altra lingua, il libro viene letto con la fonetica sbagliata: spagnolo
letto da voce italiana, e il reclamo arriva a generazione pagata e finita.

Il controllo sta **prima del pagamento**: la domanda e' semantica («questo
testo e' scritto nella lingua che la voce legge?»), risponde in qualunque
lingua e non chiede nuove liste da mantenere. L'esito non blocca: avvisa, e
l'utente conferma. Un libro bilingue, o un testo con molte citazioni, deve
poter essere letto lo stesso.

Modulo **foglia**: stdlib + `semantic_judge`, nessun import dal progetto.

Configurazione (env):
  ABM_VOICELANG_MODE      off | observe | on        (default: observe)
  ABM_VOICELANG_MAX_MATCH p sotto cui si avvisa     (default: 0.15)
  ABM_VOICELANG_MIN_CHARS testo minimo per chiedere (default: 600)
  ABM_VOICELANG_SAMPLE    caratteri del campione    (default: 1500)
"""

import json
import os
from datetime import datetime, timezone

import semantic_judge as sj


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
    m = _env("ABM_VOICELANG_MODE", _DEFAULT_MODE).lower()
    return m if m in _MODES else _DEFAULT_MODE


def enabled():
    return mode() != "off" and sj.is_available()


def applies():
    """True se l'avviso arriva davvero all'utente."""
    return mode() == "on"


def max_match():
    """Probabilita' sotto cui il testo non e' nella lingua della voce.

    Bassa di proposito: un avviso di troppo fa fermare qualcuno che aveva
    ragione — un saggio pieno di citazioni inglesi resta un libro italiano —
    mentre l'avviso mancato costa soltanto la conferma che l'utente avrebbe
    dato comunque."""
    return max(0.0, min(1.0, _env_float("ABM_VOICELANG_MAX_MATCH", 0.15)))


def min_chars():
    return max(1, _env_int("ABM_VOICELANG_MIN_CHARS", 600))


def sample_chars():
    return max(200, _env_int("ABM_VOICELANG_SAMPLE", 1500))


# ---------------------------------------------------------------------------
# Campione
# ---------------------------------------------------------------------------

def sample_text(texts):
    """Campione preso dal **centro** dei capitoli scelti.

    In testa stanno frontespizio, dedica e citazione d'apertura, che sono
    spesso in un'altra lingua dell'opera: campionare l'inizio farebbe suonare
    l'allarme sul libro giusto.
    """
    chunks = [t for t in (texts or []) if (t or "").strip()]
    if not chunks:
        return ""
    middle = chunks[len(chunks) // 2]
    body = (middle or "").strip()
    want = sample_chars()
    if len(body) <= want:
        # Un capitolo corto da solo non basta: si continua con i successivi.
        out = [body]
        size = len(body)
        for t in chunks[len(chunks) // 2 + 1:]:
            if size >= want:
                break
            out.append((t or "").strip())
            size += len(out[-1])
        return "\n".join(out)[:want]
    start = max(0, (len(body) - want) // 2)
    return body[start:start + want]


# ---------------------------------------------------------------------------
# Domande
# ---------------------------------------------------------------------------

def _questions(voice_lang, declared_lang=""):
    if sj.Noul is None:
        return {}
    Noul, Crit, Choice = sj.Noul, sj.NoulCriteria, sj.Choice
    questions = {
        "matches": Noul(
            instructions=f"Is the text in `sample` written in the language "
                         f"`{voice_lang}` (ISO 639-1)?",
            criteria=Crit(
                true=f"The body of `sample` is written in `{voice_lang}`. "
                     f"Quotations, proper names, technical terms or a few "
                     f"foreign sentences do not change the language of a text.",
                false=f"The body of `sample` is written in some other "
                      f"language: a reader of `{voice_lang}` alone could not "
                      f"follow it.",
            ),
        ),
    }
    options = {
        voice_lang: f"The text is written in `{voice_lang}`.",
        "other": "The text is written in some other language.",
    }
    if declared_lang and declared_lang != voice_lang:
        options[declared_lang] = (f"The text is written in `{declared_lang}`, "
                                  f"the language declared in the book's "
                                  f"metadata.")
    questions["language"] = Choice(
        instructions="Which language is the body of `sample` written in?",
        criteria=options,
    )
    return questions


def _state(text, voice_lang, declared_lang=""):
    return {
        "sample": {"text": text or "", "chars": len(text or "")},
        "voice": {"language": voice_lang or ""},
        "metadata": {"language": declared_lang or ""},
    }


# ---------------------------------------------------------------------------
# Giudizio
# ---------------------------------------------------------------------------

def review(text, voice_lang, declared_lang="", *, timeout=None):
    """`{}` se non c'e' giudizio: SDK assente, servizio giu', testo troppo
    corto. `{}` non significa mai «lingua sbagliata» ne' «lingua giusta»."""
    if not enabled() or not (voice_lang or "").strip():
        return {}
    if len((text or "").strip()) < min_chars():
        return {}
    questions = _questions(voice_lang, declared_lang)
    if not questions:
        return {}
    resp = sj.ask(_state(text, voice_lang, declared_lang), questions,
                  timeout=timeout)
    if resp is None:
        return {}
    p = sj.noul(resp, "matches")
    if p is None:
        return {}
    guess, conf = sj.choice(resp, "language")
    return {"matches": float(p), "language": guess or "",
            "language_confidence": float(conf or 0.0)}


def _audit_path():
    d = _env("ABM_DATA_DIR")
    if not d or not os.path.isdir(d):
        return ""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return os.path.join(d, f"voice_language_audit_{month}.jsonl")


def write_audit(probs, voice_lang, declared_lang, mismatch, *, job_id="",
                voice="", chars=0):
    """Una riga per controllo. Serve a sapere quante volte l'avviso sarebbe
    partito, e su quali lingue, prima di accenderlo davvero."""
    try:
        path = _audit_path()
        if not path or not probs:
            return
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": mode(),
            "job_id": str(job_id or "")[:40],
            "voice": str(voice or "")[:60],
            "voice_language": voice_lang or "",
            "declared_language": declared_lang or "",
            "book_language": probs.get("language", ""),
            "matches": round(float(probs.get("matches", 0.0)), 3),
            "chars": chars,
            "mismatch": bool(mismatch),
            "applied": bool(mismatch) and applies(),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: BLE001 - l'audit non ferma un job
        print(f"[voicelang] audit non scritto: {type(e).__name__}: {e}",
              flush=True)


def check(texts, voice_lang, declared_lang="", *, job_id="", voice="",
          timeout=None):
    """`None` se si puo' procedere, altrimenti il dettaglio dell'avviso.

    Non solleva mai: qualunque inciampo vale «nessun giudizio», cioe' la
    generazione parte come prima di questo modulo. In `observe` registra e
    lascia passare.
    """
    try:
        voice_lang = (voice_lang or "").strip().split("-")[0].lower()
        declared_lang = (declared_lang or "").strip().split("-")[0].lower()
        if not voice_lang:
            return None
        text = sample_text(texts)
        probs = review(text, voice_lang, declared_lang, timeout=timeout)
        if not probs:
            return None
        mismatch = probs["matches"] <= max_match()
        write_audit(probs, voice_lang, declared_lang, mismatch,
                    job_id=job_id, voice=voice, chars=len(text))
        if not mismatch or not applies():
            return None
        guess = probs.get("language", "")
        return {
            "voice_language": voice_lang,
            "book_language": guess if guess and guess != "other" else "",
            "confidence": round(1.0 - probs["matches"], 3),
        }
    except Exception as e:      # noqa: BLE001 - fail-open, sempre
        print(f"[voicelang] controllo non applicato: "
              f"{type(e).__name__}: {e}", flush=True)
        return None
