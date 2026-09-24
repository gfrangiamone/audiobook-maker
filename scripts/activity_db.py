#!/usr/bin/env python3
"""Attrezzi per activity.db (fasi 2-3 del business log su SQLite).

    python3 scripts/activity_db.py parity [--dir DIR] [--month YYYY-MM ...]
    python3 scripts/activity_db.py sync   [--dir DIR] [--force]
    python3 scripts/activity_db.py bench  [--dir DIR] [-n N]

--dir: cartella di activity_*.log e activity.db. Default: ABM_ACTIVITY_LOG_DIR,
poi /opt/audiobook-maker/data. Nella shell ssh di prod le ABM_* dell'unit
systemd non ci sono: passare --dir esplicito.

parity  conteggi per op e mese fra file e DB; exit 1 se qualcosa differisce.
sync    ricostruisce dal file i mesi CHIUSI che non tornano. Il mese corrente
        lo allinea l'app all'avvio, sotto il suo lock di scrittura.
bench   latenza di activity_log.log() nei modi off e dual, su una cartella
        temporanea dentro --dir (stesso disco dei log), poi rimossa.
"""
import argparse
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import activity_log  # noqa: E402

DEFAULT_DIR = "/opt/audiobook-maker/data"


def _ym_arg(value):
    if not activity_log._YM_RE.match(value):
        raise argparse.ArgumentTypeError(f"mese non valido: {value!r} (YYYY-MM)")
    return value


def _parity(args):
    bad = 0
    for ym in sorted(args.month or activity_log.months()):
        try:
            diff = activity_log.parity(ym)
        except Exception as e:
            print(f"{ym} errore: {e}")
            bad += 1
            continue
        if not diff:
            print(f"{ym} ok")
            continue
        bad += 1
        for op, (in_file, in_db) in sorted(diff.items()):
            print(f"{ym} {op}: file={in_file} db={in_db}")
    return 1 if bad else 0


def _sync(args):
    current = datetime.now().strftime("%Y-%m")
    bad = 0
    for ym in sorted(activity_log.months()):
        if ym == current:
            print(f"{ym} saltato: mese corrente, lo allinea l'app all'avvio")
            continue
        try:
            done = activity_log.sync_month(ym, force=args.force)
        except Exception as e:
            print(f"{ym} errore: {e}")
            bad += 1
            continue
        print(f"{ym} {'ricostruito' if done else 'gia allineato'}")
    return 1 if bad else 0


def _pct(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))]


def _bench(args):
    prev_mode = os.environ.get("ABM_ACTIVITY_DB")
    work = Path(tempfile.mkdtemp(prefix="activity_bench_", dir=args.dir))
    try:
        for m in ("off", "dual"):
            os.environ["ABM_ACTIVITY_DB"] = m
            d = work / m
            d.mkdir()
            activity_log.configure(lambda d=d: d)
            activity_log.reset()
            times = []
            for i in range(args.n):
                t0 = time.perf_counter()
                activity_log.log(f"J{i}", "bench.epub", "GENERATE", client_id="c",
                                 ip="127.0.0.1", voice="v", lang="it", platform="web")
                times.append((time.perf_counter() - t0) * 1000.0)
            print(f"{m}: n={args.n} p50={_pct(times, 50):.2f} p95={_pct(times, 95):.2f}"
                  f" p99={_pct(times, 99):.2f} max={max(times):.2f} ms")
            activity_log.reset()      # chiude activity.db prima di rimuovere la cartella
    finally:
        if prev_mode is None:
            os.environ.pop("ABM_ACTIVITY_DB", None)
        else:
            os.environ["ABM_ACTIVITY_DB"] = prev_mode
        shutil.rmtree(work, ignore_errors=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("parity", "sync", "bench"))
    ap.add_argument("--dir", default=os.environ.get("ABM_ACTIVITY_LOG_DIR") or DEFAULT_DIR)
    ap.add_argument("--month", action="append", type=_ym_arg)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("-n", type=int, default=2000)
    args = ap.parse_args(argv)
    log_dir = Path(args.dir)
    activity_log.configure(lambda: log_dir)
    return {"parity": _parity, "sync": _sync, "bench": _bench}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
