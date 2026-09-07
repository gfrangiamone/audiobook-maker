#!/usr/bin/env python3
"""
admin_voucher.py — CLI amministrativa per generare/gestire voucher promozionali.

Zero esposizione web: opera DIRETTAMENTE sul file _vouchers.json dentro ABM_DATA_DIR.
Da eseguire sul server con accesso filesystem (solitamente come utente del servizio).

ATTENZIONE - le scritture (create/revoke) sono RIFIUTATE se il servizio e' acceso:
audiobook_app carica _vouchers.json una sola volta all'avvio e lo riscrive dalla
memoria a ogni salvataggio, quindi una modifica fatta qui a servizio vivo e'
invisibile all'app e viene persa. A servizio acceso usa il pannello
/admin/vouchers. Dettagli in _guard_running_app().

Uso:
    python scripts/admin_voucher.py create --email user@example.com --amount 2.00 --days 180 --kind promo --note "Regalo lancio"
    python scripts/admin_voucher.py list [--email user@example.com] [--kind promo]
    python scripts/admin_voucher.py revoke --code PROMO-XXXX-XXXX-XXXX [--reason "abuso"]
    python scripts/admin_voucher.py show --code XXXX-XXXX-XXXX

Variabili d'ambiente:
    ABM_DATA_DIR   directory dati (default: /var/lib/audiobook-maker/data)

Tutte le operazioni sono loggate in voucher_admin.log accanto a _vouchers.json.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data"))
VOUCHERS_FILE = DATA_DIR / "_vouchers.json"
LOG_FILE = DATA_DIR / "voucher_admin.log"

# Stesso alphabet di audiobook_app.py (no 0/O/1/I)
_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _load() -> dict:
    if not VOUCHERS_FILE.exists():
        return {}
    with open(VOUCHERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(vouchers: dict) -> None:
    VOUCHERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VOUCHERS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(vouchers, f, indent=2, ensure_ascii=False)
    os.replace(tmp, VOUCHERS_FILE)


def _log(op: str, detail: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "?"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} # {user} # {op} # {detail}\n")
    except OSError as e:
        print(f"[warn] cannot write log: {e}", file=sys.stderr)


def _gen_code(prefix: str = "") -> str:
    core = "-".join("".join(secrets.choice(_ALPHA) for _ in range(4)) for _ in range(3))
    return f"{prefix}{core}" if prefix else core


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ─────────────────────────────────────────────────────────────
# Guardia: nessuna scrittura mentre il servizio e' vivo
# ─────────────────────────────────────────────────────────────
# audiobook_app chiama _load_vouchers() UNA SOLA VOLTA all'avvio e da li' tiene
# tutto in RAM; ogni _save_vouchers() riscrive _vouchers.json dalla memoria.
# Una scrittura fatta da qui a servizio acceso e' quindi: invisibile al
# pannello /admin/vouchers (legge la RAM), inutilizzabile dal cliente (anche la
# validazione legge la RAM) e destinata a sparire al primo salvataggio fatto
# dall'app. Incidente 07/09/2026: voucher di rimborso creato da CLI, mai
# esistito per il servizio. A servizio acceso l'unica via corretta e' il
# pannello admin, che passa dal processo vivo e sa anche mandare l'email.
_SERVICE_UNIT = os.environ.get("ABM_SERVICE_UNIT", "audiobook-maker.service")
_APP_PROCESS_HINT = "audiobook_app.py"

def _detect_running_app():
    """Descrizione del processo app vivo, oppure None.

    Best effort: se gli strumenti di sistema mancano (es. sviluppo su Windows)
    la funzione NON inventa un rilevamento e lascia passare la scrittura."""
    import shutil
    import subprocess

    systemctl = shutil.which("systemctl")
    if systemctl:
        try:
            r = subprocess.run([systemctl, "is-active", _SERVICE_UNIT],
                               capture_output=True, text=True, timeout=10)
            if (r.stdout or "").strip() == "active":
                return f"unita systemd {_SERVICE_UNIT} attiva"
        except (OSError, subprocess.SubprocessError):
            pass

    pgrep = shutil.which("pgrep")
    if pgrep:
        try:
            r = subprocess.run([pgrep, "-f", _APP_PROCESS_HINT],
                               capture_output=True, text=True, timeout=10)
            pids = " ".join((r.stdout or "").split())
            if pids:
                return f"processo {_APP_PROCESS_HINT} vivo (PID {pids})"
        except (OSError, subprocess.SubprocessError):
            pass

    return None


def _warn_if_running():
    """Lettura: nessun blocco, ma il file su disco puo' essere piu' vecchio dello
    stato in RAM del servizio (che salva solo quando cambia qualcosa)."""
    where = _detect_running_app()
    if where:
        print(f"[nota] {where}: questi dati vengono dal file su disco e possono "
              f"divergere da quelli del servizio. Fonte autorevole: /admin/vouchers.",
              file=sys.stderr)


def _guard_running_app(force):
    """0 se si puo' scrivere, codice di uscita != 0 se la scrittura va rifiutata."""
    where = _detect_running_app()
    if not where:
        return 0
    if force:
        print(f"[warn] {where}: procedo per --force. La modifica NON sara' vista "
              f"dal servizio finche' non lo riavvii, e verra' persa al primo "
              f"salvataggio dei voucher fatto dall'app.", file=sys.stderr)
        _log("FORCE", where)
        return 0
    print(f"""error: {where}.
Questa CLI scrive direttamente su _vouchers.json, ma il servizio tiene i voucher
in memoria e riscrive il file a ogni salvataggio. Un voucher creato o revocato
adesso:
  - non comparirebbe in /admin/vouchers,
  - verrebbe rifiutato al cliente che prova a usarlo,
  - sparirebbe al primo salvataggio fatto dall'app.
Usa il pannello /admin/vouchers: crea il voucher e mandalo via email col pulsante
di notifica.
Solo se il servizio e' davvero fermo (rilevamento sbagliato): ripeti con --force.""",
          file=sys.stderr)
    return 4


# ─────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────

def cmd_create(args) -> int:
    rc = _guard_running_app(getattr(args, "force", False))
    if rc:
        return rc
    vouchers = _load()
    email = (args.email or "").lower().strip()
    if not email or "@" not in email:
        print("error: --email obbligatoria e valida", file=sys.stderr)
        return 2
    amount = float(args.amount)
    if amount <= 0:
        print("error: --amount deve essere > 0", file=sys.stderr)
        return 2
    days = int(args.days)
    if days <= 0:
        print("error: --days deve essere > 0", file=sys.stderr)
        return 2
    kind = args.kind
    prefix = "PROMO-" if kind == "promo" else ("GIFT-" if kind == "gift" else "")

    # Genera codice unico
    for _ in range(20):
        code = _gen_code(prefix)
        if code not in vouchers:
            break
    else:
        print("error: impossibile generare codice univoco", file=sys.stderr)
        return 3

    now = time.time()
    vouchers[code] = {
        "code": code,
        "email": email,
        "amount_eur": round(amount, 2),
        "base_amount_eur": round(amount, 2),
        "remaining_eur": round(amount, 2),
        "uses": [],
        "created_at": now,
        "expires_at": now + days * 86400,
        "used": False,
        "used_at": None,
        "origin_order_id": None,
        "origin_job_id": None,
        "kind": kind,
        "note": (args.note or "")[:500],
        "created_by": "admin",
    }
    _save(vouchers)
    _log("CREATE", f"code={code} email={email} amount={amount:.2f} days={days} kind={kind} note={args.note!r}")
    print(f"OK — creato voucher {code}")
    print(f"    email     : {email}")
    print(f"    importo   : {amount:.2f} EUR")
    print(f"    scadenza  : {_fmt_ts(vouchers[code]['expires_at'])}  ({days} giorni)")
    print(f"    kind      : {kind}")
    if args.note:
        print(f"    note      : {args.note}")
    return 0


def _remaining(v: dict) -> float:
    if "remaining_eur" in v:
        try:
            return max(0.0, round(float(v["remaining_eur"]), 2))
        except (TypeError, ValueError):
            return 0.0
    if v.get("used"):
        return 0.0
    try:
        return round(float(v.get("amount_eur", 0) or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def cmd_list(args) -> int:
    _warn_if_running()
    vouchers = _load()
    rows = []
    for code, v in vouchers.items():
        if args.email and v.get("email", "").lower() != args.email.lower():
            continue
        if args.kind and v.get("kind", "refund") != args.kind:
            continue
        rem = _remaining(v)
        expired = v.get("expires_at", 0) < time.time()
        if args.active_only and (rem < 0.01 or expired):
            continue
        rows.append((code, v))
    rows.sort(key=lambda r: r[1].get("created_at", 0), reverse=True)
    if not rows:
        print("(nessun voucher corrispondente)")
        return 0
    print(f"{'CODE':<26} {'KIND':<7} {'REMAIN':>7} {'/TOT':>7}  {'EMAIL':<32} {'EXPIRES':<17} {'STATUS':<8} NOTE")
    print("-" * 130)
    for code, v in rows:
        rem = _remaining(v)
        tot = float(v.get("amount_eur", 0) or 0)
        expired = v.get("expires_at", 0) < time.time()
        if rem < 0.01:
            status = "USED"
        elif expired:
            status = "EXPIRED"
        elif rem < tot - 0.01:
            status = "PARTIAL"
        else:
            status = "ACTIVE"
        print(f"{code:<26} {v.get('kind','refund'):<7} {rem:>7.2f} {tot:>7.2f}  "
              f"{v.get('email',''):<32} {_fmt_ts(v.get('expires_at')):<17} {status:<8} {v.get('note','')}")
    print(f"\nTotale: {len(rows)}")
    return 0


def cmd_revoke(args) -> int:
    rc = _guard_running_app(getattr(args, "force", False))
    if rc:
        return rc
    vouchers = _load()
    code = args.code.strip().upper()
    if code not in vouchers:
        print(f"error: voucher {code} non trovato", file=sys.stderr)
        return 1
    v = vouchers[code]
    if v.get("used"):
        print(f"info: voucher {code} era già stato usato il {_fmt_ts(v.get('used_at'))}")
    v["used"] = True
    v["used_at"] = time.time()
    v["remaining_eur"] = 0.0
    v["revoked"] = True
    v["revoke_reason"] = (args.reason or "admin revoke")[:200]
    _save(vouchers)
    _log("REVOKE", f"code={code} reason={args.reason!r}")
    print(f"OK — voucher {code} revocato")
    return 0


def cmd_show(args) -> int:
    _warn_if_running()
    vouchers = _load()
    code = args.code.strip().upper()
    v = vouchers.get(code)
    if not v:
        print(f"error: voucher {code} non trovato", file=sys.stderr)
        return 1
    print(json.dumps(v, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Admin CLI per voucher Audiobook Maker")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("create", help="crea un nuovo voucher")
    pc.add_argument("--email", required=True)
    pc.add_argument("--amount", type=float, required=True, help="importo in EUR")
    pc.add_argument("--days", type=int, default=180, help="validità in giorni (default 180)")
    pc.add_argument("--kind", choices=["promo", "gift", "refund"], default="promo")
    pc.add_argument("--note", default="", help="nota libera (causale)")
    pc.add_argument("--force", action="store_true",
                    help="scrivi anche a servizio apparentemente acceso (vedi _guard_running_app)")
    pc.set_defaults(func=cmd_create)

    pl = sub.add_parser("list", help="elenca voucher")
    pl.add_argument("--email")
    pl.add_argument("--kind", choices=["promo", "gift", "refund"])
    pl.add_argument("--active-only", action="store_true")
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("revoke", help="revoca un voucher (marca come usato)")
    pr.add_argument("--code", required=True)
    pr.add_argument("--reason", default="")
    pr.add_argument("--force", action="store_true",
                    help="scrivi anche a servizio apparentemente acceso (vedi _guard_running_app)")
    pr.set_defaults(func=cmd_revoke)

    ps = sub.add_parser("show", help="mostra il record JSON completo di un voucher")
    ps.add_argument("--code", required=True)
    ps.set_defaults(func=cmd_show)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
