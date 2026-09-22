"""free_tts_quota.py — Quota mensile di caratteri per client sulle voci STANDARD.

Le voci standard (edge-tts, Google) sono gratuite e illimitate: l'analisi di
agosto 2026 ha mostrato che l'1.4% dei client (>30 libri/mese) produce ~40% del
volume sintetizzato. Questa quota mette un tetto mensile per client ai caratteri
sintetizzati con voce standard; oltre il tetto il job resta possibile ma SOLO in
modalita' batch con email registrata (gate email, vedi /api/generate).

Struttura del file `ABM_DATA_DIR/_free_tts_quota.json`:
    {"YYYY-MM": {"<client_id>": {"chars": 1234, "jobs": {"<job_id>": 1234},
                                 "gated": 2}}}
`gated` conta i job accettati oltre quota (solo osservabilita').

Oltre la quota c'e' un secondo tetto, questa volta duro: `cap_chars()`
(`ABM_FREE_TTS_CAP_CHARS_PER_MONTH`, default 25 Mchars). Il gate email non lo
supera: il caso di settembre 2026 (42 Mchars in un mese con una sola email
registrata, identita' stabile e quindi nessun segnale di abuso) ha mostrato che
senza soffitto il gate e' solo un rallentamento. Il cap e' contato sia
sull'identita' di quota sia sull'hash dell'email del gate (chiavi `mail:<h>`
nello stesso file del mese), cosi' cancellare il cookie non azzera il contatore.
Nessun dato personale oltre al client_id (cookie anonimo abm_cid) e all'hash
irreversibile dell'email (salato con ABM_IP_SALT).
Best-effort, thread-safe, scrittura atomica: nessuna eccezione propagata.
Modulo foglia: solo stdlib + community_store.atomic_write_json.

Identita' di quota (`link_device`/`canonical`): l'app mobile porta il proprio
identificativo in un header e lo rigenera a ogni pulizia dei dati, quindi il
contatore ripartirebbe da zero come per un cookie cancellato. Il token push,
invece, e' legato all'installazione. `ABM_DATA_DIR/_free_tts_quota_ids.json`
tiene la corrispondenza installazione -> primo client_id visto (canonico) e la
lista degli alias: tutte le letture e i consumi del mese passano dal canonico.
"""
import hashlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from community_store import atomic_write_json

_lock = threading.RLock()
_KEEP_MONTHS = 3
_IDS_KEEP_DAYS = 120  # retention dei legami installazione->identita di quota
_ANON = "_anon"
DEFAULT_LIMIT_CHARS = 10_000_000
DEFAULT_CAP_CHARS = 25_000_000
_MAIL_PREFIX = "mail:"  # prefisso delle chiavi per-email nel bucket del mese


def _quota_file():
    # Letto a ogni chiamata: ABM_DATA_DIR e' definito all'avvio del processo,
    # ma i test lo cambiano per isolare lo stato.
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")) / "_free_tts_quota.json"


def _month():
    return datetime.now().strftime("%Y-%m")


def limit_chars():
    """Tetto mensile di caratteri per client sulle voci standard. 0 = feature off."""
    raw = str(os.environ.get("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", DEFAULT_LIMIT_CHARS))
    try:
        return max(0, int(float(raw.replace("_", "").replace(",", "."))))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT_CHARS


def cap_chars():
    """Tetto duro mensile di caratteri sulle voci standard. 0 = nessun cap.

    Diverso da `limit_chars()`: oltre la quota il job passa comunque con il
    gate email, oltre il cap non passa in alcun modo.
    """
    raw = str(os.environ.get("ABM_FREE_TTS_CAP_CHARS_PER_MONTH", DEFAULT_CAP_CHARS))
    try:
        return max(0, int(float(raw.replace("_", "").replace(",", "."))))
    except (TypeError, ValueError):
        return DEFAULT_CAP_CHARS


def mail_key(email):
    """Chiave di quota derivata dall'email del gate ("" se assente o non valida).

    Hash salato con ABM_IP_SALT e troncato: non consente di risalire
    all'indirizzo, ma e' stabile fra un cookie e il successivo.
    """
    e = (email or "").strip().lower()
    if not e or "@" not in e:
        return ""
    salt = str(os.environ.get("ABM_IP_SALT", ""))
    return _MAIL_PREFIX + hashlib.sha256((salt + e).encode("utf-8")).hexdigest()[:16]


def _ids_file():
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")) / "_free_tts_quota_ids.json"


def _load_ids():
    """{"devices": {hash: {"cid", "ts"}}, "aliases": {cid: {"cid", "ts"}}}."""
    try:
        with open(_ids_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    for k in ("devices", "aliases"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def _save_ids(d):
    """Scrive il registro, scartando i legami piu' vecchi di `_IDS_KEEP_DAYS`."""
    cutoff = time.time() - _IDS_KEEP_DAYS * 86400
    for section in ("devices", "aliases"):
        bucket = d.get(section) or {}
        for key, rec in list(bucket.items()):
            if not isinstance(rec, dict) or not rec.get("cid"):
                bucket.pop(key, None)
                continue
            try:
                if float(rec.get("ts") or 0) < cutoff:
                    bucket.pop(key, None)
            except (TypeError, ValueError):
                bucket.pop(key, None)
    try:
        atomic_write_json(_ids_file(), d)
    except Exception:
        pass


def _resolve(ids, cid):
    """Segue la catena degli alias (profondita' 1 per costruzione, con guardia)."""
    aliases = ids.get("aliases") or {}
    seen = set()
    cur = cid
    while cur and cur not in seen:
        seen.add(cur)
        rec = aliases.get(cur)
        nxt = (rec or {}).get("cid") if isinstance(rec, dict) else None
        if not nxt or nxt == cur:
            break
        cur = nxt
    return cur


def canonical(client_id):
    """Identita' di quota sotto cui e' contabilizzato questo client_id."""
    cid = (client_id or "").strip() or _ANON
    with _lock:
        return _resolve(_load_ids(), cid)


def _merge_month_bucket(src, dst):
    """Sposta il consumo del mese corrente da `src` a `dst`. Caller sotto `_lock`."""
    if src == dst:
        return
    d = _load()
    month_bucket = d.get(_month())
    if not isinstance(month_bucket, dict) or not isinstance(month_bucket.get(src), dict):
        return
    s = month_bucket.pop(src)
    t = _bucket(d, dst, create=True)
    s_jobs = s.get("jobs") if isinstance(s.get("jobs"), dict) else {}
    moved = 0
    for jid, amt in s_jobs.items():
        if jid in t["jobs"]:
            continue
        try:
            a = max(0, int(amt or 0))
        except (TypeError, ValueError):
            a = 0
        t["jobs"][jid] = a
        t["chars"] += a
        moved += a
    try:
        s_chars = max(0, int(s.get("chars", 0) or 0))
    except (TypeError, ValueError):
        s_chars = 0
    if s_chars > moved:  # residuo senza job (schema legacy): non si perde
        t["chars"] += s_chars - moved
    t["gated"] = int(t.get("gated", 0) or 0) + int(s.get("gated", 0) or 0)
    _save(d)


def link_device(device_hash, client_id):
    """Lega un'installazione (hash del token push) a un'identita' di quota.

    Il primo client_id che registra quel device resta canonico; i successivi
    diventano suoi alias e il loro consumo del mese in corso viene fuso nel
    bucket canonico. Cosi' rigenerare l'identificativo in app non azzera il
    contatore mensile. Ritorna il cid canonico; mai solleva.
    """
    try:
        th = (device_hash or "").strip()
        cid = (client_id or "").strip()
        if not th or not cid:
            return _norm_client(client_id)
        with _lock:
            ids = _load_ids()
            devices, aliases = ids["devices"], ids["aliases"]
            now = time.time()
            cur = _resolve(ids, cid)
            rec = devices.get(th)
            owner = _resolve(ids, (rec or {}).get("cid") or "") if isinstance(rec, dict) else ""
            if not owner:
                devices[th] = {"cid": cur, "ts": now}
                _save_ids(ids)
                return cur
            devices[th] = {"cid": owner, "ts": now}
            if owner != cur:
                aliases[cur] = {"cid": owner, "ts": now}
                for k, v in list(aliases.items()):  # invariante: profondita' 1
                    if k != cur and isinstance(v, dict) and v.get("cid") == cur:
                        aliases[k] = {"cid": owner, "ts": v.get("ts", now)}
                _merge_month_bucket(cur, owner)
            _save_ids(ids)
            return owner
    except Exception:
        return (client_id or "").strip() or _ANON


def _norm_client(client_id):
    """Identita' di quota del client: canonico se e' alias di un'installazione."""
    cid = (client_id or "").strip() or _ANON
    return _resolve(_load_ids(), cid)


def _load():
    try:
        with open(_quota_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    for old in sorted(d.keys())[:-_KEEP_MONTHS]:
        d.pop(old, None)
    try:
        atomic_write_json(_quota_file(), d)
    except Exception:
        pass


def _bucket(d, cid, create=False):
    """Bucket del client nel mese corrente (schema riparato se corrotto)."""
    month = _month()
    if not isinstance(d.get(month), dict):
        if not create:
            return None
        d[month] = {}
    month_bucket = d[month]
    if not isinstance(month_bucket.get(cid), dict):
        if not create:
            return None
        month_bucket[cid] = {"chars": 0, "jobs": {}}
    b = month_bucket[cid]
    if not isinstance(b.get("jobs"), dict):
        b["jobs"] = {}
    try:
        b["chars"] = max(0, int(b.get("chars", 0) or 0))
    except (TypeError, ValueError):
        b["chars"] = 0
    return b


def _used_key(key):
    """Caratteri del mese corrente sotto una chiave grezza (cid canonico o `mail:`)."""
    if not key:
        return 0
    with _lock:
        b = _bucket(_load(), key)
    return int(b["chars"]) if b else 0


def used_chars(client_id):
    """Caratteri gia' sintetizzati con voce standard dal client nel mese corrente."""
    return _used_key(_norm_client(client_id))


def _job_charged_key(key, job_id):
    jid = (job_id or "").strip()
    if not jid or not key:
        return False
    with _lock:
        b = _bucket(_load(), key)
    return bool(b) and jid in b["jobs"]


def job_charged(client_id, job_id):
    """True se `job_id` ha gia' consumato quota per questo client nel mese
    (idempotenza al retry della stessa generazione)."""
    return _job_charged_key(_norm_client(client_id), job_id)


def _consume_into(d, key, amount, jid, gated):
    """Somma su una chiave grezza. Caller sotto `_lock`, con `d` da salvare."""
    b = _bucket(d, key, create=True)
    if jid and jid in b["jobs"]:
        return b["chars"]
    b["chars"] += amount
    if jid:
        b["jobs"][jid] = amount
    if gated:
        b["gated"] = int(b.get("gated", 0) or 0) + 1
    return b["chars"]


def consume(client_id, chars, job_id, gated=False, email=""):
    """Somma `chars` al bucket del mese. Idempotente per `job_id`.

    `gated=True` marca un job accettato OLTRE quota (gate email superato):
    conta comunque i caratteri, cosi' il totale del mese resta veritiero.
    `email` (quella del gate, se c'e') fa sommare gli stessi caratteri anche
    sulla chiave `mail:<hash>`: e' il contatore che regge il cap quando il
    cookie cambia. Ritorna il totale del mese sull'identita' di quota.
    """
    cid = _norm_client(client_id)
    mkey = mail_key(email)
    jid = (job_id or "").strip()
    try:
        amount = max(0, int(chars or 0))
    except (TypeError, ValueError):
        amount = 0
    with _lock:
        d = _load()
        total = _consume_into(d, cid, amount, jid, gated)
        if mkey:
            _consume_into(d, mkey, amount, jid, gated)
        _save(d)
        return total


def _refund_from(d, key, jid):
    """Storna `jid` da una chiave grezza. Caller sotto `_lock`."""
    b = _bucket(d, key)
    if not b or jid not in b["jobs"]:
        return 0
    try:
        amount = max(0, int(b["jobs"].pop(jid) or 0))
    except (TypeError, ValueError):
        amount = 0
    b["chars"] = max(0, b["chars"] - amount)
    return amount


def refund(client_id, job_id, email=""):
    """Storna il contributo di `job_id` (errore server: il job non ha prodotto
    nulla), sull'identita' di quota e sulla chiave email se passata. No-op se
    il job non risulta addebiato. Ritorna i chars stornati."""
    cid = _norm_client(client_id)
    mkey = mail_key(email)
    jid = (job_id or "").strip()
    if not jid:
        return 0
    with _lock:
        d = _load()
        amount = _refund_from(d, cid, jid)
        moved = _refund_from(d, mkey, jid) if mkey else 0
        if amount or moved:
            _save(d)
        return amount


def snapshot(client_id):
    """Stato quota per UI/admin."""
    lim = limit_chars()
    cap = cap_chars()
    used = used_chars(client_id)
    return {
        "used_chars": used,
        "limit_chars": lim,
        "remaining_chars": max(0, lim - used),
        "exhausted": bool(lim > 0 and used >= lim),
        "cap_chars": cap,
        "cap_remaining_chars": max(0, cap - used) if cap > 0 else 0,
        "cap_reached": bool(cap > 0 and used >= cap),
    }


def decision(client_id, chars, job_id=None):
    """Esito della quota per un job a voce standard di `chars` caratteri.

    Non consuma nulla: il consumo e' esplicito via `consume()` dove il job
    parte davvero. `allowed=True` quando la feature e' spenta, quando il job
    ha gia' addebitato quota (retry della stessa generazione) o quando
    `used + chars <= limit`. Altrimenti `allowed=False, exhausted=True`: il
    chiamante decide se accettare comunque il job tramite il gate email.
    """
    try:
        need = max(0, int(chars or 0))
    except (TypeError, ValueError):
        need = 0
    limit = limit_chars()
    used = used_chars(client_id) if limit > 0 else 0
    out = {
        "allowed": True,
        "exhausted": False,
        "used_chars": used,
        "limit_chars": limit,
        "chars": need,
        "remaining_chars": max(0, limit - used) if limit > 0 else 0,
    }
    if limit <= 0:
        return out
    if job_id and job_charged(client_id, job_id):
        return out
    if used + need <= limit:
        return out
    out["allowed"] = False
    out["exhausted"] = True
    return out


def cap_decision(client_id, chars, job_id=None, email=""):
    """Esito del tetto duro mensile per un job a voce standard di `chars`.

    Non consuma nulla. Blocca se il mese sfonderebbe il cap su almeno una
    delle due chiavi: identita' di quota canonica oppure hash dell'email del
    gate. La seconda e' quella che regge alla cancellazione del cookie.
    `allowed=True` se il cap e' spento, se il job ha gia' addebitato (retry
    della stessa generazione) o se nessuna delle due chiavi sfonda.
    `key` dice quale chiave porta il consumo piu' alto ("cid" o "mail"): e'
    quella che fa scattare il blocco, utile nei log.
    """
    try:
        need = max(0, int(chars or 0))
    except (TypeError, ValueError):
        need = 0
    cap = cap_chars()
    out = {"allowed": True, "cap_reached": False, "cap_chars": cap,
           "used_chars": 0, "chars": need, "remaining_chars": 0, "key": ""}
    if cap <= 0:
        return out
    keys = [("cid", _norm_client(client_id))]
    mkey = mail_key(email)
    if mkey:
        keys.append(("mail", mkey))
    if job_id and any(_job_charged_key(k, job_id) for _, k in keys):
        return out
    worst_kind, worst_used = "", 0
    for kind, key in keys:
        used = _used_key(key)
        if kind == "cid" or used > worst_used:
            worst_kind, worst_used = kind, used
    out["used_chars"] = worst_used
    out["remaining_chars"] = max(0, cap - worst_used)
    out["key"] = worst_kind
    if worst_used + need > cap:
        out["allowed"] = False
        out["cap_reached"] = True
    return out


def month_table():
    """{client_id: {"chars", "jobs": n, "gated": n}} del mese corrente (digest admin)."""
    with _lock:
        d = _load()
    month_data = d.get(_month())
    if not isinstance(month_data, dict):
        return {}
    out = {}
    for cid, b in month_data.items():
        if not isinstance(b, dict) or cid.startswith(_MAIL_PREFIX):
            continue  # le chiavi per-email sono contatori del cap, non client
        try:
            chars = max(0, int(b.get("chars", 0) or 0))
        except (TypeError, ValueError):
            chars = 0
        jobs = b.get("jobs") if isinstance(b.get("jobs"), dict) else {}
        out[cid] = {"chars": chars, "jobs": len(jobs),
                    "gated": int(b.get("gated", 0) or 0)}
    return out
