#!/usr/bin/env python3
"""Fotografia dei job vivi in produzione, classificati per rischio di perdita.

Usato durante il drenaggio pre-cutover (migrazione server): dice quali job si
possono interrompere senza perdere lavoro TTS gia' pagato e quali no.

Criteri (vedi docs/superpowers/plans/2026-08-21-migrazione-server-prod.md, Task 8):

  - Un job e' RECUPERABILE se e' registrato in _pending_jobs.json (batch, con
    email) E il suo motore e' fra quelli con riuso chunk (chunk_reuse.
    REUSABLE_ENGINES = gemini, edge, google). Al riavvio riparte dai chunk gia'
    sintetizzati: si perde al piu' l'ultimo chunk scritto, che viene scartato
    per prudenza (possibile troncamento al crash).
  - Un job e' BLOCCANTE se interromperlo distrugge lavoro a pagamento:
      * motore speechify (qualunque): escluso dal riuso -> il recovery
        risintetizza da zero e RI-PAGA l'intero job;
      * motore gemini/google NON registrato: nessun recovery affatto, i chunk
        gia' pagati restano su disco senza che nessuno li riprenda.
  - Un job e' SACRIFICABILE se e' edge (free) e non registrato: l'utente perde
    la sessione ma non c'e' costo ne' lavoro pagato da salvare.
  - Un job con PAGAMENTO CONSUMATO e non ancora concluso e' BLOCCANTE anche
    senza alcun chunk TTS: e' il caso dell'ottimizzazione AI interattiva, che
    non produce chunk ma e' stata pagata. Il pagamento risulta consumato da
    `_payments.json` (used=true) o da un addebito voucher in `_vouchers.json`;
    risulta concluso da `_paid_jobs_done.json`, scritto da
    `payment._mark_paid_job_done()` al completamento.

Sola lettura: non modifica nulla. Exit code 0 se non ci sono job BLOCCANTI
(il freeze puo' partire), 2 se ce ne sono ancora.

Uso:
    python3 migration_live_jobs.py [--data-dir DIR] [--window-min N] [--quiet]
"""
import argparse
import glob
import json
import os
import sys
import time

# Motori con riuso dei chunk (allineato a chunk_reuse.REUSABLE_ENGINES).
REUSABLE_ENGINES = ("gemini", "edge", "google")
# Motori il cui lavoro e' pagato (dall'utente o dal gestore): perderlo costa.
PAID_ENGINES = ("gemini", "speechify", "google")

RECOVERABLE = "RECUPERABILE"
BLOCKING = "BLOCCANTE"
SACRIFICEABLE = "SACRIFICABILE"


def load_registry(data_dir):
    """job_id -> descrittore, per i soli descrittori non 'failed'."""
    path = os.path.join(data_dir, "_pending_jobs.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("ATTENZIONE: _pending_jobs.json illeggibile (%s); "
              "tutti i job risulteranno non registrati." % e, file=sys.stderr)
        return {}
    items = data.get("items", []) if isinstance(data, dict) else data
    return {it.get("id"): it for it in items if str(it.get("state")) != "failed"}


def _load_json(data_dir, name):
    try:
        with open(os.path.join(data_dir, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("ATTENZIONE: %s illeggibile (%s): il controllo sui pagamenti in "
              "corso e' incompleto." % (name, e), file=sys.stderr)
        return None


def load_paid_pending(data_dir):
    """job_id con un pagamento gia' consumato ma nessun record di completamento.

    Serve a intercettare il lavoro pagato che non lascia chunk su disco
    (ottimizzazione AI, traduzione): senza questo controllo un job del genere
    verrebbe classificato 'nessuna sintesi in corso' e quindi sacrificabile."""
    done = set()
    recs = _load_json(data_dir, "_paid_jobs_done.json")
    if isinstance(recs, list):
        for r in recs:
            if isinstance(r, dict) and r.get("job_id"):
                done.add(str(r["job_id"]))
            elif isinstance(r, str):   # formato legacy: lista di job_id
                done.add(r)

    pending = set()
    payments = _load_json(data_dir, "_payments.json")
    if isinstance(payments, dict):
        for rec in payments.values():
            if not isinstance(rec, dict) or not rec.get("used"):
                continue
            job_id = str(rec.get("job_id") or "")
            if job_id and job_id not in done:
                pending.add(job_id)

    vouchers = _load_json(data_dir, "_vouchers.json")
    if isinstance(vouchers, dict):
        for v in vouchers.values():
            uses = v.get("uses") if isinstance(v, dict) else None
            if not isinstance(uses, list):
                continue
            # Un addebito (importo positivo) annullato da un riaccredito
            # (importo negativo con lo stesso job_id) non e' piu' pendente.
            refunded = {str(u.get("job_id") or "") for u in uses
                        if isinstance(u, dict)
                        and float(u.get("amount_eur", 0) or 0) < 0}
            for u in uses:
                if not isinstance(u, dict):
                    continue
                if float(u.get("amount_eur", 0) or 0) <= 0:
                    continue
                job_id = str(u.get("job_id") or "")
                if job_id and job_id not in done and job_id not in refunded:
                    pending.add(job_id)
    return pending


def job_engine(work_dir):
    """(engine, voice) dal manifest di riuso, scritto da run_generation per ogni
    job in sintesi. Fallback sull'estensione dei chunk quando il manifest manca
    (job partito con una versione precedente o interrotto prima di scriverlo):
    .pcm => gemini o speechify, .mp3 => edge o google. In quel caso il motore
    resta ignoto e il job viene trattato in modo prudenziale."""
    try:
        with open(os.path.join(work_dir, ".chunks_manifest.json"), "r",
                  encoding="utf-8") as f:
            fp = json.load(f)
        if isinstance(fp, dict) and fp.get("engine"):
            return str(fp["engine"]), str(fp.get("voice", ""))
    except Exception:
        pass
    if glob.glob(os.path.join(work_dir, "chunk_*.pcm")):
        return "?pcm", ""      # gemini o speechify: prudenza -> bloccante
    if glob.glob(os.path.join(work_dir, "chunk_*.mp3")):
        return "?mp3", ""      # edge o google
    return "", ""


def newest_mtime(work_dir):
    """mtime del file piu' recente nella job dir. Piu' affidabile del mtime
    della directory: un job in fase di assembly FFmpeg non crea nuovi file ma
    continua a scrivere l'output."""
    newest = 0.0
    try:
        for name in os.listdir(work_dir):
            try:
                m = os.path.getmtime(os.path.join(work_dir, name))
            except OSError:
                continue
            if m > newest:
                newest = m
    except OSError:
        pass
    try:
        newest = max(newest, os.path.getmtime(work_dir))
    except OSError:
        pass
    return newest


def classify(engine, registered, paid_pending=False):
    """Verdetto sul singolo job. Il motore ignoto (?pcm/?mp3) e' trattato come
    il caso peggiore compatibile con quell'estensione."""
    if engine in ("speechify", "?pcm"):
        # Nessun riuso possibile (o non dimostrabile): interrompere = ri-pagare.
        return BLOCKING, "nessun riuso chunk: il recovery risintetizza da zero"
    if paid_pending and not registered:
        # Copre l'ottimizzazione AI interattiva: pagata, senza chunk su disco,
        # senza descrittore di recovery. Interromperla perde soldi veri.
        return BLOCKING, "pagamento consumato e job non concluso: nessun recovery"
    if engine in PAID_ENGINES and not registered:
        return BLOCKING, "job a pagamento non registrato: nessun recovery"
    if registered and engine in REUSABLE_ENGINES:
        return RECOVERABLE, "batch + riuso chunk: riparte dov'era"
    if engine == "edge" and not registered:
        return SACRIFICEABLE, "free interattivo: perdita accettabile"
    if engine == "?mp3":
        if registered:
            return RECOVERABLE, "batch, motore mp3 (edge/google): riuso disponibile"
        return BLOCKING, "motore ignoto non registrato: potrebbe essere google"
    if not engine:
        # Nessun chunk: job in analisi/ottimizzazione o appena creato.
        if registered:
            return RECOVERABLE, "registrato, sintesi non ancora iniziata"
        if paid_pending:
            return BLOCKING, "pagamento consumato e job non concluso: nessun recovery"
        return SACRIFICEABLE, "nessuna sintesi in corso"
    return RECOVERABLE, "riuso disponibile"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="/opt/audiobook-maker/data")
    ap.add_argument("--window-min", type=float, default=10.0,
                    help="un job e' 'vivo' se un suo file e' stato scritto "
                         "negli ultimi N minuti (default: 10)")
    ap.add_argument("--quiet", action="store_true",
                    help="stampa solo il riepilogo finale")
    args = ap.parse_args()

    data_dir = args.data_dir
    if not os.path.isdir(data_dir):
        print("ERRORE: data dir inesistente: %s" % data_dir, file=sys.stderr)
        return 1

    registry = load_registry(data_dir)
    paid_pending = load_paid_pending(data_dir)
    now = time.time()
    rows = []
    for name in os.listdir(data_dir):
        work_dir = os.path.join(data_dir, name)
        if not os.path.isdir(work_dir):
            continue
        age_min = max(0.0, (now - newest_mtime(work_dir)) / 60.0)
        if age_min > args.window_min:
            continue
        engine, voice = job_engine(work_dir)
        registered = name in registry
        verdict, why = classify(engine, registered, name in paid_pending)
        n_chunk = (len(glob.glob(os.path.join(work_dir, "chunk_*.pcm")))
                   + len(glob.glob(os.path.join(work_dir, "chunk_*.mp3"))))
        rows.append({"job": name, "age": age_min, "engine": engine or "-",
                     "voice": voice, "batch": registered, "chunks": n_chunk,
                     "verdict": verdict, "why": why})

    order = {BLOCKING: 0, RECOVERABLE: 1, SACRIFICEABLE: 2}
    rows.sort(key=lambda r: (order[r["verdict"]], r["age"]))

    if not args.quiet:
        print("%-14s %-24s %-10s %-6s %6s %8s  nota"
              % ("verdetto", "job_id", "motore", "batch", "chunk", "eta_min"))
        for r in rows:
            print("%-14s %-24s %-10s %-6s %6d %8.1f  %s"
                  % (r["verdict"], r["job"], r["engine"], str(r["batch"]),
                     r["chunks"], r["age"], r["why"]))
        print()

    n_block = sum(1 for r in rows if r["verdict"] == BLOCKING)
    n_rec = sum(1 for r in rows if r["verdict"] == RECOVERABLE)
    n_sac = sum(1 for r in rows if r["verdict"] == SACRIFICEABLE)
    print("[%s] vivi=%d  BLOCCANTI=%d  recuperabili=%d  sacrificabili=%d"
          % (time.strftime("%H:%M:%S"), len(rows), n_block, n_rec, n_sac))
    if n_block:
        print("  -> NON fermare il servizio: c'e' lavoro a pagamento che "
              "andrebbe perso.")
        for r in rows:
            if r["verdict"] == BLOCKING:
                print("     %s  %s  %d chunk  (%s)"
                      % (r["job"], r["engine"], r["chunks"], r["why"]))
        return 2
    print("  -> nessun job bloccante: il freeze puo' partire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
