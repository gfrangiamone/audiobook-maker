#!/usr/bin/env python3
"""Igiene del registro dei job orfani prima del primo avvio sul nuovo server.

Va eseguito SUL NUOVO SERVER, a servizio fermo, dopo la delta rsync e prima di
`systemctl start`. Al boot `_recover_orphan_jobs()` rilancia ogni descrittore di
`_pending_jobs.json` che non sia in stato 'failed'. Dopo una migrazione quel
file contiene tre categorie che vanno trattate diversamente:

  1. Job GIA' CONSEGNATI. `pending_jobs.finalize()` viene chiamato subito dopo
     l'invio dell'email di consegna (generation_engine.py, `_send_completion_email`
     e `_send_optimization_email`). Se lo stop del servizio cade fra l'invio e il
     finalize, il descrittore sopravvive a un job completo: al boot verrebbe
     rigenerato da capo e l'utente riceverebbe una seconda email. Si riconoscono
     dall'evento EMAIL_SENT / OPT_EMAIL_SENT negli activity log.
     Azione: state='failed' (nessuna rigenerazione, nessun rimborso).

  2. Job al CAP TENTATIVI. `_recover_orphan_jobs()` confronta gli attempts con
     ABM_RECOVER_MAX_ATTEMPTS (default 2) e, oltre il cap, chiama
     `_orphan_fallback()`: rimborso + email "interrotto" + mark failed. Un job
     interrotto DA NOI per la migrazione non deve consumare quel budget, o
     rimborseremmo job perfettamente sani.
     Azione: attempts=0.

  3. Job con INPUT MANCANTE. `_reenqueue_orphan()` solleva FileNotFoundError se
     ne' input_path ne' abm_path esistono; l'eccezione risale in
     `_recover_orphan_jobs()` e interrompe il ciclo, lasciando non recuperati
     tutti i descrittori successivi.
     Azione: state='failed'.

Default: DRY-RUN. Serve `--apply` per scrivere. La scrittura e' atomica
(tmp+rename) e lascia una copia in `_pending_jobs.json.premigration.bak`.

Uso:
    python3 migration_recover_prep.py [--data-dir DIR] [--script-dir DIR]
                                      [--max-attempts N] [--apply]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

REGISTRY_NAME = "_pending_jobs.json"
BACKUP_SUFFIX = ".premigration.bak"
DELIVERED_EVENTS = ("EMAIL_SENT", "OPT_EMAIL_SENT", "TR_EMAIL_SENT")


def service_is_running():
    """True se un processo audiobook_app.py e' vivo. Modificare il registro
    sotto un processo attivo significa perdere le sue scritture concorrenti."""
    try:
        out = subprocess.run(["pgrep", "-f", "audiobook_app.py"],
                             capture_output=True, text=True, timeout=10)
        return bool(out.stdout.strip())
    except Exception:
        # pgrep assente o non eseguibile: non si puo' escludere il rischio.
        return True


def delivered_job_ids(script_dir):
    """job_id che hanno un evento di consegna negli activity log.

    Gli activity log stanno in SCRIPT_DIR (non nella data dir), un file per mese
    `activity_YYYY-MM.log`. Formato di riga scritto da `_log_activity`:

        {job_id} # {ts} # "{filename}" # {operation} # {client_id} # {client_ip}
                 # {voice} # {browser_lang} # {platform}

    Il job_id e' il campo 0; l'operazione e' normalmente il campo 3, ma un
    filename contenente ' # ' farebbe slittare le colonne. Si confronta quindi
    ogni campo dal terzo in poi con l'elenco degli eventi, per uguaglianza
    esatta: un match parziale marcherebbe come 'gia' consegnato' un job che
    invece va ripreso, cioe' lo perderebbe."""
    ids = set()
    try:
        names = [n for n in os.listdir(script_dir)
                 if n.startswith("activity_") and n.endswith(".log")]
    except OSError as e:
        print("ATTENZIONE: activity log non leggibili in %s (%s): il controllo "
              "'gia' consegnato' viene saltato." % (script_dir, e),
              file=sys.stderr)
        return ids
    for name in sorted(names):
        path = os.path.join(script_dir, name)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    fields = [p.strip() for p in line.rstrip("\n").split(" # ")]
                    if len(fields) < 4:
                        continue
                    if any(fld in DELIVERED_EVENTS for fld in fields[3:]):
                        ids.add(fields[0])
        except OSError:
            continue
    return ids


def input_exists(rec):
    """True se il job ha ancora un input da cui ripartire (file originale o
    .abm ottimizzato), come verificato da `_reenqueue_orphan`."""
    for key in ("abm_path", "input_path"):
        path = rec.get(key) or ""
        if path and os.path.exists(path):
            return True
    return False


def atomic_write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="/opt/audiobook-maker/data")
    ap.add_argument("--script-dir", default="/opt/audiobook-maker",
                    help="dove stanno gli activity_*.log (default: /opt/audiobook-maker)")
    ap.add_argument("--max-attempts", type=int,
                    default=int(os.environ.get("ABM_RECOVER_MAX_ATTEMPTS", "2")))
    ap.add_argument("--apply", action="store_true",
                    help="scrive le modifiche (senza, e' una simulazione)")
    args = ap.parse_args()

    registry_path = os.path.join(args.data_dir, REGISTRY_NAME)
    if not os.path.isfile(registry_path):
        print("ERRORE: registro assente: %s" % registry_path, file=sys.stderr)
        return 1

    if args.apply and service_is_running():
        print("ERRORE: un processo audiobook_app.py e' in esecuzione. Fermare il "
              "servizio prima di applicare le modifiche.", file=sys.stderr)
        return 1

    with open(registry_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        print("ERRORE: formato inatteso del registro (atteso {'items': [...]})",
              file=sys.stderr)
        return 1

    delivered = delivered_job_ids(args.script_dir)
    print("activity log: %d job con evento di consegna" % len(delivered))

    actions = {"delivered": [], "reset": [], "no_input": [], "keep": []}
    for rec in data["items"]:
        if str(rec.get("state")) == "failed":
            continue
        job_id = rec.get("id") or "?"
        if job_id in delivered:
            rec["state"] = "failed"
            actions["delivered"].append(job_id)
            continue
        if not input_exists(rec):
            rec["state"] = "failed"
            actions["no_input"].append(job_id)
            continue
        attempts = int(rec.get("attempts", 0) or 0)
        if attempts >= args.max_attempts:
            rec["attempts"] = 0
            actions["reset"].append((job_id, attempts))
        actions["keep"].append(job_id)

    print()
    print("gia' consegnati -> failed : %d" % len(actions["delivered"]))
    for j in actions["delivered"]:
        print("    %s" % j)
    print("input mancante  -> failed : %d" % len(actions["no_input"]))
    for j in actions["no_input"]:
        print("    %s" % j)
    print("attempts azzerati         : %d" % len(actions["reset"]))
    for j, n in actions["reset"]:
        print("    %s (era %d, cap %d)" % (j, n, args.max_attempts))
    print()
    print("DA RIPRENDERE AL BOOT     : %d" % len(actions["keep"]))
    for j in actions["keep"]:
        print("    %s" % j)
    print()
    print("tempo di avvio stimato del recovery: ~%d s (throttle 2 s/job)"
          % (2 * len(actions["keep"])))

    if not args.apply:
        print()
        print("SIMULAZIONE: nessuna modifica scritta. Rieseguire con --apply.")
        return 0

    backup = registry_path + BACKUP_SUFFIX
    shutil.copy2(registry_path, backup)
    atomic_write_json(registry_path, data)
    with open(registry_path, "r", encoding="utf-8") as f:
        json.load(f)  # rilettura: il file deve restare JSON valido
    print()
    print("Scritto %s (backup: %s)" % (registry_path, backup))
    return 0


if __name__ == "__main__":
    sys.exit(main())
