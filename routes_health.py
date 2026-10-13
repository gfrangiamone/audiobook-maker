"""routes_health — `/healthz` per il deploy e il monitoraggio (O2, 2026-10-13).

Blueprint senza autenticazione e senza dati sensibili: versione, secondi dal
boot, job in generazione, cartella dati scrivibile. Risponde 200 solo se la
cartella dati e' scrivibile: il deploy (`.github/workflows/deploy.yml`) lo
interroga dopo il riavvio e torna al commit precedente se non risponde.
Nessun import da `audiobook_app`: lo stato arriva con `configure()`.
"""
import os
import tempfile
import time

from flask import Blueprint, jsonify

from version import __version__

bp = Blueprint("health", __name__)
_cfg = {}
_STARTED_AT = time.time()


def configure(*, jobs, jobs_lock, data_dir):
    """`jobs`/`data_dir`: funzioni risolte a ogni richiesta (i test ribindano
    i globali della app); `jobs_lock`: il lock condiviso."""
    _cfg.update(jobs=jobs, jobs_lock=jobs_lock, data_dir=data_dir)


def _data_dir_writable():
    try:
        d = str(_cfg["data_dir"]())
        os.makedirs(d, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, prefix=".healthz-", delete=True):
            pass
        return True
    except Exception:      # noqa: BLE001 - qualunque errore vale "non scrivibile"
        return False


@bp.route("/healthz", methods=["GET"])
def healthz():
    try:
        with _cfg["jobs_lock"]:
            active = sum(1 for j in list(_cfg["jobs"]().values())
                         if isinstance(j, dict) and j.get("status") == "generating")
    except Exception:      # noqa: BLE001
        active = -1
    writable = _data_dir_writable()
    body = {"ok": bool(writable and active >= 0), "version": __version__,
            "uptime_s": int(time.time() - _STARTED_AT), "jobs_generating": active,
            "data_dir_writable": writable}
    resp = jsonify(body)
    resp.status_code = 200 if body["ok"] else 503
    resp.headers["Cache-Control"] = "no-store"
    return resp
