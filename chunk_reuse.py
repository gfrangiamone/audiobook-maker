"""Riuso dei chunk TTS gia' sintetizzati su disco (resume dopo crash/restart).

Un job interrotto a meta' lascia in `data/<job_id>/` i file `chunk_XXXXXX.pcm`
(o `.mp3`) gia' sintetizzati e — per le voci PREMIUM — gia' PAGATI. Rigenerarli
da zero al recovery butta via ore di TTS e ri-addebita il costo Google.

Il riuso non e' pero' incondizionato: gli indici dei chunk sono posizionali e
dipendono dal piano di chunking, quindi riusare i file di un piano diverso
consegnerebbe audio sbagliato (voce precedente, testo di un altro capitolo,
parentesi lette/non lette). Il manifest registra l'impronta del piano e dei
parametri di sintesi: si riusa SOLO se l'impronta corrente coincide byte per byte.

Invariante di sicurezza: al cambio di voce/rate/stile/accento/flag parentesi, o
a qualunque variazione del testo dei blocchi, l'impronta cambia e il riuso non
avviene (nessuna cache silenziosa fra voci diverse).
"""
from __future__ import annotations

import hashlib
import json
import os

MANIFEST_NAME = ".chunks_manifest.json"

# Versione dello schema: un bump invalida tutti i manifest esistenti (utile se
# cambia il modo in cui i chunk vengono scritti su disco).
SCHEMA_VERSION = 1

# Motori per cui il riuso e' abilitato. Speechify e' escluso di proposito: la
# pre-sintesi parallela popola `speechify_sample_rate` dal primo risultato API,
# che un chunk riusato non produrrebbe (rischio di assembly a sample rate errato).
REUSABLE_ENGINES = ("gemini", "edge", "google")


def plan_sha(plan) -> str:
    """SHA-256 del testo di tutti i blocchi del piano, nell'ordine del piano.

    Ancora l'impronta al contenuto reale: se il chunking cambia (anche solo per
    un capitolo deselezionato) l'hash cambia e i file su disco non sono piu'
    allineati agli indici."""
    h = hashlib.sha256()
    for block in plan:
        h.update((block.get("text") or "").encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def fingerprint(voice, rate, engine, plan, style_instruction=None, accent=None,
                strip_round=True, strip_square=True) -> dict:
    """Impronta completa del run: parametri di sintesi + hash del piano."""
    return {
        "schema": SCHEMA_VERSION,
        "engine": engine or "",
        "voice": voice or "",
        "rate": rate or "",
        "style_instruction": style_instruction or "",
        "accent": accent or "",
        "strip_round": bool(strip_round),
        "strip_square": bool(strip_square),
        "n_chunks": len(plan),
        "plan_sha": plan_sha(plan),
    }


def manifest_path(work_dir) -> str:
    return os.path.join(str(work_dir), MANIFEST_NAME)


def read_manifest(work_dir):
    try:
        with open(manifest_path(work_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_manifest(work_dir, fp: dict) -> bool:
    """Scrive il manifest (tmp+rename). Non solleva: il riuso e' best-effort."""
    path = manifest_path(work_dir)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(fp, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False


def matches(work_dir, fp: dict) -> bool:
    saved = read_manifest(work_dir)
    return bool(saved) and saved == fp


def reusable_indices(work_dir, fp: dict, total_chunks: int, ext: str) -> set:
    """Indici dei chunk gia' su disco che e' lecito riusare.

    Un chunk e' riusabile se: (a) il manifest coincide con l'impronta corrente,
    (b) il file esiste, non e' vuoto e — per il PCM 16 bit — ha dimensione pari,
    (c) non e' quello di indice massimo fra i presenti. La condizione (c) scarta
    l'ULTIMO file scritto, l'unico che al momento del crash poteva essere
    troncato a meta' senza che si possa rilevarlo: costa una risintesi sola.
    I chunk vengono scritti in ordine crescente, quindi un eventuale buco nella
    sequenza (sweep parziale) non rende sospetti quelli che lo precedono."""
    if (fp or {}).get("engine") not in REUSABLE_ENGINES:
        return set()
    if not matches(work_dir, fp):
        return set()
    base = str(work_dir)
    present = {}
    for i in range(total_chunks):
        p = os.path.join(base, f"chunk_{i:06d}.{ext}")
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if size > 0:
            present[i] = size
    if not present:
        return set()
    last_written = max(present)
    out = set()
    for i, size in present.items():
        if i == last_written:
            continue  # possibile troncamento al crash -> risintetizza
        if ext == "pcm" and size % 2 != 0:
            continue  # PCM 16-bit: dimensione dispari = scrittura incompleta
        out.add(i)
    return out
