#!/usr/bin/env python3
"""
section_judge.py — Decide quali sezioni di un libro sono testo da leggere.

Il parser separa il contenuto dall'apparato critico (indice, colophon,
bibliografia, note, ringraziamenti) con `epub_to_tts.is_content_chapter`:
una lista di ~90 frasi in sei lingue piu' sei soglie tarate a mano. Il TTS
legge in oltre cinquanta lingue, e su un EPUB polacco, turco o giapponese
nessuna di quelle frasi matcha: l'utente paga la sintesi della bibliografia
e si ascolta «Rossi, M., 1998, pp. 45-47». Nel verso opposto, una soglia
tarata su prosa italiana scarta in silenzio un epilogo scritto in versi.

Qui la stessa domanda viene posta in forma semantica, che non dipende dalla
lingua: una `Noul` per sezione, tutte in una sola richiesta. Le euristiche
restano dove sono e decidono da sole quando questo modulo tace.

Modulo **foglia**: stdlib + `semantic_judge`, nessun import dal progetto.

Configurazione (env):
  ABM_SECTION_JUDGE_MODE     off | observe | on          (default: observe)
  ABM_SECTION_MIN_RECOVER    p da cui in su si recupera   (default: 0.55)
  ABM_SECTION_MAX_DROP       p sotto cui si scarta        (default: 0.12)
  ABM_SECTION_MAX_DROP_RATIO quota max di caratteri scartabili (default: 0.25)
  ABM_SECTION_MIN_CHARS      sotto, la sezione non si chiede (default: 200)
  ABM_SECTION_MAX_KEPT_CHARS sopra, un capitolo tenuto non si chiede (20000)
  ABM_SECTION_MAX_QUESTIONS  cap di domande per libro     (default: 24)
"""

import json
import os
import time
from datetime import datetime, timezone

import semantic_judge as sj


# Estratto mandato al giudizio: l'inizio dice quasi sempre che cos'e' una
# sezione (un colophon apre con il copyright, un indice con voci e numeri,
# un capitolo con prosa). Mandare il testo intero di venti sezioni costerebbe
# molto e non aggiungerebbe nulla.
_EXCERPT_CHARS = 400

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
    """`off`, `observe` o `on`. Un valore ignoto vale il default, non `on`:
    un errore di battitura nell'unit systemd non deve accendere gli scarti."""
    m = _env("ABM_SECTION_JUDGE_MODE", _DEFAULT_MODE).lower()
    return m if m in _MODES else _DEFAULT_MODE


def enabled():
    return mode() != "off" and sj.is_available()


def applies():
    """True se il verdetto cambia davvero i capitoli del libro."""
    return mode() == "on"


def min_recover():
    """Probabilita' da cui in su una sezione scartata torna nel libro.

    Piu' bassa della soglia di scarto perche' i due errori non pesano uguale:
    leggere una pagina di ringraziamenti annoia, perdere un epilogo rovina il
    libro."""
    return max(0.0, min(1.0, _env_float("ABM_SECTION_MIN_RECOVER", 0.55)))


def max_drop():
    """Probabilita' sotto cui una sezione tenuta dalle euristiche esce."""
    return max(0.0, min(1.0, _env_float("ABM_SECTION_MAX_DROP", 0.12)))


def max_drop_ratio():
    """Quota massima di caratteri del libro che gli scarti possono togliere."""
    return max(0.0, min(1.0, _env_float("ABM_SECTION_MAX_DROP_RATIO", 0.25)))


def min_chars():
    return max(1, _env_int("ABM_SECTION_MIN_CHARS", 200))


def max_questions():
    return max(1, _env_int("ABM_SECTION_MAX_QUESTIONS", 24))


def max_kept_chars():
    """Oltre questa taglia un capitolo tenuto non si chiede piu'.

    Misurato sui libri di prova: senza il cap si finiva a domandare se una
    parte da 221.000 caratteri sia contenuto. L'apparato che sfugge alle
    liste e' corto per natura — «Newsletter», «Afterword», «Uber den Club» —
    e un capitolo lungo e' comunque protetto dal budget di scarto."""
    return max(1, _env_int("ABM_SECTION_MAX_KEPT_CHARS", 20000))


# ---------------------------------------------------------------------------
# Domande
# ---------------------------------------------------------------------------

def _key(sid):
    return f"sec::{sid}"


def _excerpt(text):
    t = (text or "").strip()
    if len(t) <= _EXCERPT_CHARS:
        return t
    return t[:_EXCERPT_CHARS].rstrip() + "…"


def _stats(text):
    """Le stesse misure su cui ragionano le euristiche, date al giudizio come
    fatti invece che come soglie: righe corte e numeri di pagina sono il
    profilo di un indice in qualunque lingua."""
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    n = len(lines)
    if not n:
        return {"lines": 0, "short_line_pct": 0, "digit_pct": 0}
    short = sum(1 for l in lines if len(l) < 15)
    digits = sum(1 for l in lines if any(c.isdigit() for c in l))
    return {
        "lines": n,
        "short_line_pct": round(100.0 * short / n),
        "digit_pct": round(100.0 * digits / n),
    }


def _state(book, sections):
    return {
        "book": {
            "title": book.get("title", ""),
            "author": book.get("author", ""),
            "language": book.get("language", ""),
            "sections_total": book.get("sections_total", len(sections)),
        },
        "sections": [
            {
                "id": s["id"],
                "position": s.get("position", ""),
                "title": s.get("title", ""),
                "chars": s.get("chars", 0),
                "excerpt": _excerpt(s.get("text", "")),
                **_stats(s.get("text", "")),
            }
            for s in sections
        ],
    }


def _questions(sections):
    if sj.Noul is None:
        return {}
    Noul, Crit = sj.Noul, sj.NoulCriteria
    questions = {}
    for s in sections:
        sid = s["id"]
        questions[_key(sid)] = Noul(
            instructions=f"Should section `sections.{sid}` be read aloud as "
                         f"part of the audiobook?",
            criteria=Crit(
                true=f"`sections.{sid}` is part of the work itself: narrative, "
                     f"argument, dialogue, verse, a preface or an afterword "
                     f"that is written to be read. A reader who skipped it "
                     f"would miss something the author wrote.",
                false=f"`sections.{sid}` is apparatus around the work: table of "
                      f"contents, copyright page or colophon, bibliography, "
                      f"index of names, endnotes, list of other titles by the "
                      f"publisher, acknowledgements, credits. Read aloud it "
                      f"would be a stream of names, numbers and references.",
            ),
        )
    return questions


# ---------------------------------------------------------------------------
# Selezione dei candidati
# ---------------------------------------------------------------------------

def _pick(dropped, kept, cap):
    """Sezioni da sottoporre, entro il cap.

    Gli scarti vanno per dimensione: la sezione grossa persa in silenzio e' il
    danno che si vuole intercettare. Fra i capitoli tenuti si guardano solo le
    estremita' del libro, perche' l'apparato sta in testa o in coda — un
    indice analitico in mezzo ai capitoli non esiste.
    """
    floor = min_chars()
    drops = sorted((s for s in dropped if s.get("chars", 0) >= floor),
                   key=lambda s: -s.get("chars", 0))
    edges = []
    if kept:
        ceiling = max_kept_chars()
        edges = kept[:3] + kept[-5:] if len(kept) > 8 else list(kept)
        edges = [s for s in edges
                 if floor <= s.get("chars", 0) <= ceiling]
        seen, uniq = set(), []
        for s in edges:
            if s["id"] not in seen:
                seen.add(s["id"])
                uniq.append(s)
        edges = uniq
    # Gli scarti hanno la precedenza sul budget: sono gia' fuori dal libro.
    picked = drops[:cap]
    return picked + edges[:max(0, cap - len(picked))]


# ---------------------------------------------------------------------------
# Giudizio
# ---------------------------------------------------------------------------

def review(book, dropped, kept, *, timeout=None):
    """Probabilita' di contenuto per le sezioni sottoposte.

    `dropped` e `kept` sono liste di dict con `id`, `title`, `text`, `chars` e
    `position`. Ritorna `{id: probabilita'}` per le sole sezioni giudicate,
    `{}` quando non c'e' giudizio (modo `off`, SDK assente, servizio muto,
    risposta monca). `{}` significa "nessun giudizio", mai "tutto apparato":
    il chiamante resta con quello che le euristiche avevano deciso.
    """
    if not enabled():
        return {}
    sections = _pick(dropped or [], kept or [], max_questions())
    if not sections:
        return {}
    questions = _questions(sections)
    if not questions:
        return {}
    resp = sj.ask(_state(book or {}, sections), questions, timeout=timeout)
    if resp is None:
        return {}
    out = {}
    for s in sections:
        p = sj.noul(resp, _key(s["id"]))
        if p is not None:
            out[s["id"]] = float(p)
    return out


def decide(verdicts, dropped, kept):
    """Da probabilita' a due liste: `recover` e `drop` (id di sezione).

    Qui stanno le guardie, fuori dal servizio e fuori dal prompt, perche' un
    libro mutilato non si recupera con un retry:

    - si scarta solo sotto `max_drop()`, si recupera da `min_recover()` in su:
      in mezzo non si tocca nulla;
    - gli scarti non possono togliere piu' di `max_drop_ratio()` dei caratteri
      del libro, e si applicano dal meno probabile in su: se il giudizio
      sbaglia in blocco, sbaglia su poco;
    - non si resta mai con zero capitoli.
    """
    if not verdicts:
        return [], []
    by_id = {s["id"]: s for s in list(dropped or []) + list(kept or [])}
    kept_ids = {s["id"] for s in (kept or [])}

    recover = [sid for sid, p in verdicts.items()
               if sid not in kept_ids and p >= min_recover()]
    candidates = sorted(((sid, p) for sid, p in verdicts.items()
                         if sid in kept_ids and p <= max_drop()),
                        key=lambda kv: kv[1])

    total_chars = sum(s.get("chars", 0) for s in (kept or [])) or 1
    budget = int(total_chars * max_drop_ratio())
    drop, spent = [], 0
    for sid, _p in candidates:
        c = by_id.get(sid, {}).get("chars", 0)
        if spent + c > budget:
            continue
        drop.append(sid)
        spent += c
    if len(kept_ids) - len(drop) < 1:
        drop = []
    return recover, drop


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def _audit_path():
    d = _env("ABM_DATA_DIR")
    if not d or not os.path.isdir(d):
        return ""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return os.path.join(d, f"section_judge_audit_{month}.jsonl")


def write_audit(book, verdicts, dropped, kept, recover, drop, *, elapsed=0.0):
    """Riga JSONL per libro: serve a tarare le soglie sui libri veri prima di
    passare da `observe` a `on`. Best-effort, mai fatale per il parsing."""
    try:
        path = _audit_path()
        if not path or not verdicts:
            return
        by_id = {s["id"]: s for s in list(dropped or []) + list(kept or [])}
        kept_ids = {s["id"] for s in (kept or [])}
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": mode(),
            "language": (book or {}).get("language", ""),
            "title": (book or {}).get("title", "")[:120],
            "sections_total": (book or {}).get("sections_total", 0),
            "elapsed_s": round(float(elapsed), 2),
            "recover": list(recover or []),
            "drop": list(drop or []),
            "sections": [
                {
                    "id": sid,
                    "p": round(float(p), 3),
                    "was": "kept" if sid in kept_ids else "dropped",
                    "chars": by_id.get(sid, {}).get("chars", 0),
                    "title": (by_id.get(sid, {}).get("title", "") or "")[:80],
                }
                for sid, p in sorted(verdicts.items(), key=lambda kv: kv[1])
            ],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: BLE001 - l'audit non ferma un libro
        print(f"[section_judge] audit non scritto: {type(e).__name__}: {e}",
              flush=True)


def review_and_decide(book, dropped, kept, *, timeout=None):
    """Giro completo: giudizio, guardie, audit. Ritorna `(recover, drop)`.

    In modo `observe` l'audit viene scritto e le liste tornano vuote: si
    misura su libri veri senza toccare quello che l'utente riceve.
    """
    t0 = time.monotonic()
    verdicts = review(book, dropped, kept, timeout=timeout)
    if not verdicts:
        return [], []
    recover, drop = decide(verdicts, dropped, kept)
    write_audit(book, verdicts, dropped, kept, recover, drop,
                elapsed=time.monotonic() - t0)
    if not applies():
        return [], []
    return recover, drop
