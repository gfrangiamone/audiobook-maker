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
  ABM_SECTION_JUDGE_MODE     off | observe | recover | on  (default: observe)
  ABM_SECTION_MIN_RECOVER    p da cui in su si recupera   (default: 0.55)
  ABM_SECTION_MAX_DROP       p sotto cui si scarta        (default: 0.12)
  ABM_SECTION_MAX_DROP_RATIO quota max di caratteri scartabili (default: 0.25)
  ABM_SECTION_MIN_CHARS      sotto, la sezione non si chiede (default: 200)
  ABM_SECTION_MIN_DROP_CHARS sotto, un capitolo tenuto non si scarta (600)
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

# Oltre questa taglia l'inizio non basta piu'. Misurato in `recover` il
# 24/09/2026: due volumi di Karl May avevano la sezione `Inhalt` da 115.000 e
# 161.000 caratteri — il sommario stampato in testa e poi il romanzo, nello
# stesso file. L'estratto iniziale era un indice e il giudizio ha visto un
# indice: p=0,42, e un sesto del libro e' rimasto fuori. L'apparato vero e'
# corto per natura, quindi una sezione lunga si giudica anche da dentro.
# Vale in ogni lingua: nessuna lista di titoli «da indice».
_BODY_SAMPLE_FROM_CHARS = 20000
_BODY_SAMPLES = 2

_DEFAULT_MODE = "observe"
# La rampa e' in quattro gradini, non un interruttore: i due errori non
# pesano uguale. `recover` rimette nel libro le sezioni che le euristiche
# avevano perso e **ignora** gli scarti: il peggio che puo' fare e' leggere
# una pagina di ringraziamenti in piu' — che l'utente vede nella lista dei
# capitoli — mentre uno scarto sbagliato e' invisibile e definitivo.
_MODES = ("off", "observe", "recover", "on")


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
    """`off`, `observe`, `recover` o `on`. Un valore ignoto vale il default,
    non `on`: un errore di battitura nell'unit systemd non deve accendere gli
    scarti."""
    m = _env("ABM_SECTION_JUDGE_MODE", _DEFAULT_MODE).lower()
    return m if m in _MODES else _DEFAULT_MODE


def enabled():
    return mode() != "off" and sj.is_available()


def applies():
    """True se il verdetto cambia davvero i capitoli del libro.

    Vero in `recover` e in `on`: in entrambi i modi le sezioni recuperate
    rientrano nel libro."""
    return mode() in ("recover", "on")


def drops_apply():
    """True solo in `on`: togliere un capitolo e' l'unica mossa irreversibile
    e invisibile all'utente, quindi ha un gradino tutto suo."""
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


def min_drop_chars():
    """Caratteri minimi perche' un capitolo tenuto possa essere scartato.

    Misurato in `observe` su 302 libri veri: 121 dei 171 scarti proposti
    stavano sotto i mille caratteri e valevano 59.000 caratteri in tutto,
    mentre i diciotto sopra i tremila ne valevano 134.000. Le briciole sono
    quasi tutte occhielli e pagine di apertura: togliendole si rischia il
    titolo di un capitolo vero per guadagnare qualche secondo di lettura.

    Il recupero non ha questa soglia e resta su `min_chars`: `Epigraph` (233
    caratteri) e `Author's Note` (261) sono corti e sono opera dell'autore."""
    return max(1, _env_int("ABM_SECTION_MIN_DROP_CHARS", 600))


def max_kept_chars():
    """Oltre questa taglia un capitolo tenuto non si chiede piu'.

    Misurato sui libri di prova: senza il cap si finiva a domandare se una
    parte da 221.000 caratteri sia contenuto. L'apparato che sfugge alle
    liste e' corto per natura — «Newsletter», «Afterword», «Uber den Club» —
    e un capitolo lungo e' comunque protetto dal budget di scarto."""
    return max(1, _env_int("ABM_SECTION_MAX_KEPT_CHARS", 20000))


def thresholds():
    """Le soglie attive, da registrare nell'audit: due finestre di misura non
    sono confrontabili se non si sa con quali numeri sono nate."""
    return {
        "min_recover": min_recover(),
        "max_drop": max_drop(),
        "max_drop_ratio": max_drop_ratio(),
        "min_chars": min_chars(),
        "min_drop_chars": min_drop_chars(),
        "max_kept_chars": max_kept_chars(),
        "max_questions": max_questions(),
    }


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


def _body_sampled(s):
    return len((s.get("text") or "").strip()) >= _BODY_SAMPLE_FROM_CHARS


def _body_excerpts(text):
    """Estratti presi dall'interno della sezione, a 1/3 e 2/3, allineati a un
    inizio di parola. Vuoto sotto `_BODY_SAMPLE_FROM_CHARS`."""
    t = (text or "").strip()
    if len(t) < _BODY_SAMPLE_FROM_CHARS:
        return []
    out = []
    for i in range(1, _BODY_SAMPLES + 1):
        start = len(t) * i // (_BODY_SAMPLES + 1)
        ws = t.find(" ", start, start + 80)
        if ws != -1:
            start = ws + 1
        out.append("…" + t[start:start + _EXCERPT_CHARS].strip() + "…")
    return out


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
                "title_generated": bool(s.get("synthetic_title")),
                "excerpt": _excerpt(s.get("text", "")),
                **({"body_excerpts": _body_excerpts(s.get("text", ""))}
                   if _body_sampled(s) else {}),
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
        # Misurato in `observe`: le sezioni che il parser numera da se'
        # («Sezione 4», titolo assente nel file) prendevano p mediana 0,58
        # contro 0,93 delle altre, e una su tre finiva sotto la soglia di
        # scarto. Il titolo mancante e' un fatto del file, non del libro:
        # va detto, altrimenti pesa come indizio di apparato.
        synth = "" if not s.get("synthetic_title") else (
            f" The title of `sections.{sid}` was generated by the parser "
            f"because the file carries none: that is a fact about the file "
            f"and no evidence either way — judge the excerpt alone."
        )
        body = "" if not _body_sampled(s) else (
            f" `sections.{sid}` is long: its title and opening may be a table "
            f"of contents or a front page printed at the head of the work "
            f"itself. Judge it by `sections.{sid}.body_excerpts`, taken from "
            f"inside the section; if they are running text, the section is "
            f"the work."
        )
        questions[_key(sid)] = Noul(
            instructions=f"Should section `sections.{sid}` be read aloud as "
                         f"part of the audiobook?" + body,
            criteria=Crit(
                true=f"`sections.{sid}` is part of the work itself: narrative, "
                     f"argument, dialogue, verse, a preface or an afterword "
                     f"that is written to be read. A reader who skipped it "
                     f"would miss something the author wrote.",
                false=f"`sections.{sid}` is apparatus around the work: table of "
                      f"contents, copyright page or colophon, bibliography, "
                      f"index of names, endnotes, list of other titles by the "
                      f"publisher, acknowledgements, credits. Read aloud it "
                      f"would be a stream of names, numbers and references."
                      + synth,
            ),
        )
    return questions


# ---------------------------------------------------------------------------
# Selezione dei candidati
# ---------------------------------------------------------------------------

def _pick(dropped, kept, cap, stats=None):
    """Sezioni da sottoporre, entro il cap.

    Gli scarti vanno per dimensione: la sezione grossa persa in silenzio e' il
    danno che si vuole intercettare. Fra i capitoli tenuti si guardano solo le
    estremita' del libro, perche' l'apparato sta in testa o in coda — un
    indice analitico in mezzo ai capitoli non esiste. Un capitolo tenuto sotto
    `min_drop_chars()` non si chiede affatto: la domanda si paga e la risposta
    non potrebbe comunque toglierlo dal libro.

    `stats`, se passato, riceve quante sezioni sono state chieste e quante il
    cap ha tagliato: senza quel numero l'audit non dice se `max_questions`
    stringe.
    """
    floor = min_chars()
    drops = sorted((s for s in dropped if s.get("chars", 0) >= floor),
                   key=lambda s: -s.get("chars", 0))
    edges = []
    if kept:
        ceiling = max_kept_chars()
        kept_floor = max(floor, min_drop_chars())
        edges = kept[:3] + kept[-5:] if len(kept) > 8 else list(kept)
        edges = [s for s in edges
                 if kept_floor <= s.get("chars", 0) <= ceiling]
        seen, uniq = set(), []
        for s in edges:
            if s["id"] not in seen:
                seen.add(s["id"])
                uniq.append(s)
        edges = uniq
    # Gli scarti hanno la precedenza sul budget: sono gia' fuori dal libro.
    picked = drops[:cap]
    tail = edges[:max(0, cap - len(picked))]
    if stats is not None:
        stats["asked"] = len(picked) + len(tail)
        stats["asked_dropped"] = len(picked)
        stats["asked_kept"] = len(tail)
        stats["skipped_by_cap"] = ((len(drops) - len(picked))
                                   + (len(edges) - len(tail)))
    return picked + tail


# ---------------------------------------------------------------------------
# Giudizio
# ---------------------------------------------------------------------------

def review(book, dropped, kept, *, timeout=None, stats=None):
    """Probabilita' di contenuto per le sezioni sottoposte.

    `dropped` e `kept` sono liste di dict con `id`, `title`, `text`, `chars` e
    `position`. Ritorna `{id: probabilita'}` per le sole sezioni giudicate,
    `{}` quando non c'e' giudizio (modo `off`, SDK assente, servizio muto,
    risposta monca). `{}` significa "nessun giudizio", mai "tutto apparato":
    il chiamante resta con quello che le euristiche avevano deciso.
    """
    if not enabled():
        return {}
    sections = _pick(dropped or [], kept or [], max_questions(),
                     stats=stats)
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


def decide(verdicts, dropped, kept, stats=None):
    """Da probabilita' a due liste: `recover` e `drop` (id di sezione).

    Qui stanno le guardie, fuori dal servizio e fuori dal prompt, perche' un
    libro mutilato non si recupera con un retry:

    - si scarta solo sotto `max_drop()`, si recupera da `min_recover()` in su:
      in mezzo non si tocca nulla;
    - un capitolo il cui titolo e' stato inventato dal parser non si scarta
      mai: senza titolo il giudizio sbaglia una volta su tre (misurato in
      `observe`), e qui l'errore costa un capitolo vero;
    - non si scartano capitoli sotto `min_drop_chars()`: sono briciole, e il
      rischio non vale i secondi di lettura risparmiati;
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
    below = [(sid, p) for sid, p in verdicts.items()
             if sid in kept_ids and p <= max_drop()]
    floor = min_drop_chars()
    candidates = sorted(((sid, p) for sid, p in below
                         if by_id.get(sid, {}).get("chars", 0) >= floor
                         and not by_id.get(sid, {}).get("synthetic_title")),
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
    if stats is not None:
        stats["drop_below_threshold"] = len(below)
        stats["drop_blocked"] = len(below) - len(drop)
        stats["drop_budget_chars"] = budget
        stats["drop_chars"] = sum(by_id.get(sid, {}).get("chars", 0)
                                  for sid in drop)
        stats["recover_chars"] = sum(by_id.get(sid, {}).get("chars", 0)
                                     for sid in recover)
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


def write_audit(book, verdicts, dropped, kept, recover, drop, *, elapsed=0.0,
                stats=None):
    """Riga JSONL per libro: serve a tarare le soglie sui libri veri prima di
    passare da `observe` a `on`. Best-effort, mai fatale per il parsing.

    Registra anche le soglie attive, i totali del libro e come sono andate
    selezione e guardie: senza quei campi una riga non dice se uno scarto e'
    stato fermato dal budget o dal verdetto, e due finestre di misura con
    soglie diverse non si possono confrontare."""
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
            "applied": ("recover+drop" if drops_apply()
                        else "recover" if applies() else "none"),
            "thresholds": thresholds(),
            "kept_total": len(kept or []),
            "dropped_total": len(dropped or []),
            "kept_chars_total": sum(s.get("chars", 0) for s in (kept or [])),
            "dropped_chars_total": sum(s.get("chars", 0)
                                       for s in (dropped or [])),
            "picks": dict(stats or {}),
            "recover": list(recover or []),
            "drop": list(drop or []),
            "sections": [
                {
                    "id": sid,
                    "p": round(float(p), 3),
                    "was": "kept" if sid in kept_ids else "dropped",
                    "chars": by_id.get(sid, {}).get("chars", 0),
                    "position": by_id.get(sid, {}).get("position", ""),
                    "synthetic_title": bool(
                        by_id.get(sid, {}).get("synthetic_title")),
                    "body_sampled": _body_sampled(by_id.get(sid, {})),
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
    misura su libri veri senza toccare quello che l'utente riceve. In modo
    `recover` tornano i soli recuperi: gli scarti restano una proposta
    registrata nell'audit, dove si continuano a tarare.
    """
    t0 = time.monotonic()
    stats = {}
    verdicts = review(book, dropped, kept, timeout=timeout, stats=stats)
    if not verdicts:
        return [], []
    recover, drop = decide(verdicts, dropped, kept, stats=stats)
    write_audit(book, verdicts, dropped, kept, recover, drop,
                elapsed=time.monotonic() - t0, stats=stats)
    if not applies():
        return [], []
    if not drops_apply():
        return recover, []
    return recover, drop
