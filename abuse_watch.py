"""Moderazione LLM dell'abuso della quota voci standard.

Dossier comportamentale per gruppo (IP /24 hashato, fallback cid) con
ripartizione per cid, segnali S1-S4, giudizio DeepSeek e verdetto persistito
in `ABM_DATA_DIR/_abuse_dossiers.json`. Modulo foglia: stdlib +
`community_store.atomic_write_json`; il client LLM arriva da
`generation_engine` come in `community_moderator`.

Ogni funzione e' fail-open: un errore qui non deve mai fermare /api/generate,
il cleanup o il digest. Nessun testo utente, IP o email in chiaro: solo
contatori e hash salati con ABM_IP_SALT.

Spec: docs/superpowers/specs/2026-09-03-quota-containment-design.md
"""
import hashlib
import json
import os
import queue
import re
import threading
import time
from pathlib import Path

from community_store import atomic_write_json

_lock = threading.RLock()

KINDS = ("generate", "quota_gate", "quota_block", "email")
VERDICTS = ("abuse", "clean", "inconclusive")

_DAY_SEC = 86400
_RETENTION_SEC = 60 * _DAY_SEC        # dossier senza eventi da 60 giorni: via
_QUOTA_S1_WINDOW_SEC = 31 * _DAY_SEC  # S1: quota esaurita nell'ultimo mese
_RECENT_KEEP = 20
_RECENT_GEN_KEEP = 200
_RECENT_GATE_KEEP = 100
_FILES_KEEP = 300
_EMAILS_KEEP = 50
_JUDGEMENTS_KEEP = 20
_KILLS_KEEP = 50
_BLOCKS_KEEP = 200
_DEFAULT_SALT = "abm-default-salt-v1"
_PII_RE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+|\b\d{1,3}(?:\.\d{1,3}){3}\b"
    r"|\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b"
)
_GROUP_SCOPE_ACTIVE_SEC = 7 * _DAY_SEC  # scope="group": solo i cid attivi negli ultimi 7 giorni


# ---------------------------------------------------------------------------
# Configurazione (letta a ogni chiamata: i test cambiano l'env)
# ---------------------------------------------------------------------------

def _env_int(name, default, floor=0):
    try:
        return max(floor, int(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        raw = str(os.environ.get(name, str(default)) or default).replace(",", ".")
        return float(raw)
    except (TypeError, ValueError):
        return default


def kill_enabled():
    """Kill e 403 attivi solo con ABM_ABUSE_KILL_ENABLE=1 E un admin da avvisare
    (ABM_ADMIN_EMAIL): nessuna azione distruttiva senza audit nel digest."""
    flag = (os.environ.get("ABM_ABUSE_KILL_ENABLE", "0") or "0").strip().lower()
    admin = (os.environ.get("ABM_ADMIN_EMAIL") or "").strip()
    return flag in ("1", "true", "yes", "on") and bool(admin)


def confidence_threshold():
    return _env_float("ABM_ABUSE_LLM_CONFIDENCE", 0.9)


def keep_hours():
    return _env_int("ABM_ABUSE_KEEP_HOURS", 24, floor=1)


def verdict_ttl_sec():
    """In osservazione (kill spenta) il TTL e' forzato a 1 giorno: un prompt
    tarato male non lascia verdetti validi due settimane."""
    if not kill_enabled():
        return _DAY_SEC
    return _env_int("ABM_ABUSE_VERDICT_TTL_DAYS", 14, floor=1) * _DAY_SEC


def _gate_daily():
    return _env_int("ABM_ABUSE_GATE_DAILY", 5, floor=1)


def _chars_daily():
    return _env_int("ABM_ABUSE_CHARS_DAILY", 2_500_000, floor=1)


def _max_cids_per_group():
    return _env_int("ABM_ABUSE_MAX_CIDS_PER_GROUP", 25, floor=2)


def _data_dir():
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data"))


def _dossier_file():
    return _data_dir() / "_abuse_dossiers.json"


# ---------------------------------------------------------------------------
# Identita' e persistenza
# ---------------------------------------------------------------------------

def _hash(value):
    salt = os.environ.get("ABM_IP_SALT", _DEFAULT_SALT) or _DEFAULT_SALT
    return hashlib.sha256((salt + str(value)).encode("utf-8")).hexdigest()[:16]


def group_key(ip, cid=""):
    """`net:<hash(/24)>` per IPv4, `net:<hash(/64)>` per IPv6, altrimenti
    `cid:<cid>`. Raggruppa, non giudica: un /24 mobile ospita migliaia di
    utenti e il giudice lo sa (marker di innocenza nel prompt)."""
    ip = (ip or "").strip()
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return "net:" + _hash(".".join(parts[:3]) + ".0/24")
    if ":" in ip:
        hextets = ip.split(":")
        if 3 <= len(hextets) <= 8:
            return "net:" + _hash(":".join(hextets[:4]) + "::/64")
    return "cid:" + str(cid or "")


def _load():
    try:
        with open(_dossier_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or not isinstance(d.get("groups"), dict):
            return {"groups": {}, "meta": {}}
        if not isinstance(d.get("meta"), dict):
            d["meta"] = {}
        return d
    except Exception:
        return {"groups": {}, "meta": {}}


def _save(d):
    now = time.time()
    groups = d.setdefault("groups", {})
    for key in [k for k, g in groups.items()
                if now - float(g.get("updated", now) or now) > _RETENTION_SEC]:
        groups.pop(key, None)
    try:
        atomic_write_json(_dossier_file(), d)
    except Exception:
        pass


def _new_bucket():
    return {"generate": 0, "quota_gate": 0, "quota_block": 0, "email": 0,
            "chars": 0, "emails": [], "files": [], "voices": {}, "langs": {},
            "recent": [], "recent_generate": [], "recent_gate": [],
            "quota_exhausted_ts": 0, "first_ts": 0, "last_ts": 0}


def _new_group(now):
    return {"created": now, "updated": now, "all": _new_bucket(), "cids": {},
            "verdict": None, "judgements": [], "kills": [], "blocks": []}


def _push(lst, item, keep):
    lst.append(item)
    del lst[:-keep]


def _add_unique(lst, item, keep):
    if item and item not in lst:
        lst.append(item)
        del lst[:-keep]


def _apply(bucket, kind, data, now):
    bucket[kind] = int(bucket.get(kind, 0)) + 1
    bucket["first_ts"] = bucket.get("first_ts") or now
    bucket["last_ts"] = now
    _push(bucket["recent"], now, _RECENT_KEEP)
    try:
        chars = int(data.get("chars") or 0)
    except (TypeError, ValueError):
        chars = 0
    if kind == "generate":
        bucket["chars"] = int(bucket.get("chars", 0)) + chars
        _push(bucket["recent_generate"], [now, chars], _RECENT_GEN_KEEP)
        voice = str(data.get("voice") or "")
        if voice:
            bucket["voices"][voice] = int(bucket["voices"].get(voice, 0)) + 1
    if kind == "quota_gate":
        _push(bucket["recent_gate"], now, _RECENT_GATE_KEEP)
    if kind in ("quota_gate", "quota_block"):
        bucket["quota_exhausted_ts"] = now
    if kind == "email":
        email = str(data.get("email") or "").strip().lower()
        if email:
            _add_unique(bucket["emails"], _hash(email), _EMAILS_KEEP)
    fn = str(data.get("filename") or "")
    if fn:
        _add_unique(bucket["files"], _hash(fn), _FILES_KEEP)
    lang = str(data.get("lang") or "").strip().lower()[:2]
    if lang:
        bucket["langs"][lang] = int(bucket["langs"].get(lang, 0)) + 1


def record_event(group, cid, kind, data=None):
    """Aggiorna il dossier del gruppo e del cid. `kind` fuori da KINDS: no-op.
    Ritorna il dizionario del gruppo aggiornato (per evitare una seconda
    lettura sul chiamante), `None` se non applicabile o su errore."""
    if kind not in KINDS or not group:
        return None
    data = data if isinstance(data, dict) else {}
    cid = str(cid or "")
    with _lock:
        d = _load()
        now = time.time()
        g = d["groups"].setdefault(group, _new_group(now))
        g["updated"] = now
        _apply(g["all"], kind, data, now)
        if cid:
            _apply(g["cids"].setdefault(cid, _new_bucket()), kind, data, now)
            _evict_stale_cids(g, keep=cid)
        _save(d)
        return json.loads(json.dumps(g))


def _evict_stale_cids(g, keep=""):
    """Se il gruppo supera ABM_ABUSE_MAX_CIDS_PER_GROUP cid, elimina i meno
    attivi di recente (per `last_ts`), senza mai evictare `keep` (il cid
    appena registrato)."""
    cids = g.get("cids") or {}
    limit = _max_cids_per_group()
    if len(cids) <= limit:
        return
    order = sorted(
        (c for c in cids if c != keep),
        key=lambda c: float(cids[c].get("last_ts") or 0),
    )
    n_to_evict = len(cids) - limit
    for c in order[:n_to_evict]:
        cids.pop(c, None)


def dossier(group):
    with _lock:
        g = _load()["groups"].get(group)
    return json.loads(json.dumps(g)) if g is not None else None


# ---------------------------------------------------------------------------
# Segnali S1-S4 e trigger del giudizio
# ---------------------------------------------------------------------------

def _events_total(g):
    b = g.get("all", {})
    return sum(int(b.get(k, 0)) for k in KINDS)


def _in_window(items, now, window, index=None):
    out = []
    for it in items or []:
        ts = it[index] if index is not None else it
        try:
            if now - float(ts) < window:
                out.append(it)
        except (TypeError, ValueError, IndexError):
            continue
    return out


def _signals(g, now):
    """S1 quota esaurita (gate/block nell'ultimo mese); S2 >=2 cid; S3 >=N
    QUOTA_GATE/24h; S4 >=M caratteri/24h. S4 e' il segnale che la rotazione
    del cookie non elude: il volume del gruppo resta."""
    b = g.get("all", {})
    qts = float(b.get("quota_exhausted_ts") or 0)
    s1 = qts > 0 and (now - qts) < _QUOTA_S1_WINDOW_SEC
    s2 = len(g.get("cids", {})) >= 2
    s3 = len(_in_window(b.get("recent_gate"), now, _DAY_SEC)) >= _gate_daily()
    chars_24h = sum(int(c) for _ts, c in _in_window(b.get("recent_generate"), now, _DAY_SEC, index=0))
    s4 = chars_24h >= _chars_daily()
    return {"S1": bool(s1), "S2": bool(s2), "S3": bool(s3), "S4": bool(s4)}


def signals_for(group):
    g = dossier(group)
    if not g:
        return {"S1": False, "S2": False, "S3": False, "S4": False}
    return _signals(g, time.time())


def _valid_verdict(g, now):
    v = g.get("verdict")
    if not isinstance(v, dict) or v.get("verdict") not in VERDICTS:
        return None
    try:
        if now - float(v.get("ts", 0)) > verdict_ttl_sec():
            return None
    except (TypeError, ValueError):
        return None
    return v


def verdict_for(group):
    g = dossier(group)
    return _valid_verdict(g, time.time()) if g else None


def needs_judgement(group, cid="", group_data=None):
    """Vero con >=2 segnali e nessun verdetto valido; con verdetto `abuse` se
    `cid` e' fuori dallo scope (rotazione post-verdetto); con `clean` solo se
    compare un segnale nuovo; altrimenti se gli eventi sono cresciuti del 25%.

    `group_data`, se fornito (es. dal ritorno di `record_event`), evita una
    seconda lettura del dossier sul percorso caldo di /api/generate."""
    g = group_data if group_data is not None else dossier(group)
    if not g:
        return False
    now = time.time()
    sig = _signals(g, now)
    n_sig = sum(1 for x in sig.values() if x)
    v = _valid_verdict(g, now)
    if v is None:
        return n_sig >= 2
    if v["verdict"] == "abuse" and cid and cid not in (v.get("cids") or []):
        return True
    if v["verdict"] == "clean":
        old = v.get("signals") or {}
        return any(sig[k] and not old.get(k) for k in sig)
    grown = _events_total(g) * 4 >= int(v.get("events_at_verdict", 0) or 0) * 5
    return n_sig >= 2 and grown


# ---------------------------------------------------------------------------
# Verdetti, blocco, ripristino
# ---------------------------------------------------------------------------

def set_verdict(group, verdict):
    """Normalizza e persiste il verdetto. `scope=group` allarga `cids` a tutti
    i cid noti al momento del verdetto; `scope=cids` tiene solo cid noti."""
    verdict = verdict if isinstance(verdict, dict) else {}
    with _lock:
        d = _load()
        now = time.time()
        g = d["groups"].setdefault(group, _new_group(now))
        known = list(g.get("cids", {}).keys())
        scope = "group" if verdict.get("scope") == "group" else "cids"
        if scope == "group":
            active = [c for c in known
                      if now - float(g["cids"][c].get("last_ts") or 0) <= _GROUP_SCOPE_ACTIVE_SEC]
            cids = active or known
        else:
            cids = [c for c in (verdict.get("cids") or []) if isinstance(c, str) and c in known]
        try:
            conf = min(1.0, max(0.0, float(verdict.get("confidence") or 0)))
        except (TypeError, ValueError):
            conf = 0.0
        kind = verdict.get("verdict")
        if kind not in VERDICTS:
            kind = "inconclusive"
        reason = _PII_RE.sub("[redacted]", str(verdict.get("reason") or ""))[:500]
        v = {"verdict": kind, "confidence": conf, "scope": scope, "cids": cids,
             "reason": reason, "ts": now,
             "signals": _signals(g, now), "events_at_verdict": _events_total(g)}
        g["verdict"] = v
        _push(g["judgements"], {"ts": now, "outcome": kind, "confidence": conf,
                                "scope": scope, "cids_n": len(cids), "reason": v["reason"]},
              _JUDGEMENTS_KEEP)
        g["updated"] = now
        _save(d)
        return json.loads(json.dumps(v))


def record_judgement_failed(group, reason=""):
    """Fail-open: nessun verdetto; il caso resta nel digest come 'non giudicato'."""
    with _lock:
        d = _load()
        now = time.time()
        g = d["groups"].setdefault(group, _new_group(now))
        _push(g["judgements"], {"ts": now, "outcome": "unjudged", "confidence": 0.0,
                                "scope": "", "cids_n": 0, "reason": str(reason)[:200]},
              _JUDGEMENTS_KEEP)
        g["updated"] = now
        _save(d)


def is_blocked(group, cid):
    """Vero solo con kill accesa, verdetto `abuse` valido sopra soglia e cid nello scope."""
    if not cid or not kill_enabled():
        return False
    v = verdict_for(group)
    return bool(v and v["verdict"] == "abuse"
                and float(v.get("confidence") or 0) >= confidence_threshold()
                and cid in (v.get("cids") or []))


def clear_verdict(group):
    """Ripristino da console admin (e azzeramento all'accensione)."""
    with _lock:
        d = _load()
        g = d["groups"].get(group)
        if not g or not g.get("verdict"):
            return False
        g["verdict"] = None
        _push(g["judgements"], {"ts": time.time(), "outcome": "cleared", "confidence": 0.0,
                                "scope": "", "cids_n": 0, "reason": "admin"},
              _JUDGEMENTS_KEEP)
        _save(d)
        return True


def record_kill(group, cid, job_id):
    with _lock:
        d = _load()
        now = time.time()
        g = d["groups"].setdefault(group, _new_group(now))
        _push(g["kills"], {"ts": now, "cid": str(cid or ""), "job_id": str(job_id or "")}, _KILLS_KEEP)
        _save(d)


def record_block(group, cid):
    with _lock:
        d = _load()
        now = time.time()
        g = d["groups"].setdefault(group, _new_group(now))
        _push(g["blocks"], {"ts": now, "cid": str(cid or "")}, _BLOCKS_KEEP)
        _save(d)


def arm_on_startup():
    """Al primo avvio con kill accesa azzera i verdetti maturati in osservazione:
    le kill partono solo da giudizi emessi con il prompt definitivo. Con kill
    spenta disarma, cosi' la prossima accensione azzera di nuovo. Ritorna il
    numero di verdetti azzerati."""
    with _lock:
        d = _load()
        armed = bool(d["meta"].get("kill_armed"))
        enabled = kill_enabled()
        if enabled and not armed:
            n = 0
            for g in d["groups"].values():
                if g.get("verdict"):
                    g["verdict"] = None
                    n += 1
            d["meta"]["kill_armed"] = True
            d["meta"]["kill_armed_ts"] = time.time()
            _save(d)
            return n
        if not enabled and armed:
            d["meta"]["kill_armed"] = False
            _save(d)
        return 0


# ---------------------------------------------------------------------------
# Dati per il digest admin
# ---------------------------------------------------------------------------

def digest_data(window_sec=_DAY_SEC):
    """Righe della sezione «Casi di abuso»: solo gruppi con giudizio, kill o
    403 nella finestra. Solo hash e contatori: mai IP, email o titoli."""
    with _lock:
        d = _load()
    now = time.time()
    since = now - window_sec
    rows = []
    for key, g in d.get("groups", {}).items():
        kills = [k for k in g.get("kills", []) if float(k.get("ts", 0) or 0) >= since]
        blocks = [b for b in g.get("blocks", []) if float(b.get("ts", 0) or 0) >= since]
        judg = [j for j in g.get("judgements", []) if float(j.get("ts", 0) or 0) >= since]
        if not (kills or blocks or judg):
            continue
        v = _valid_verdict(g, now) or {}
        b = g.get("all", {})
        gen_24h = _in_window(b.get("recent_generate"), now, _DAY_SEC, index=0)
        rows.append({
            "group": key,
            "signals": _signals(g, now),
            "cids_n": len(g.get("cids", {})),
            "verdict": v.get("verdict", ""),
            "confidence": float(v.get("confidence", 0.0) or 0.0),
            "scope": v.get("scope", ""),
            "reason": v.get("reason", ""),
            "kills": len(kills),
            "blocks": len(blocks),
            "unjudged": sum(1 for j in judg if j.get("outcome") == "unjudged"),
            "generate_24h": len(gen_24h),
            "chars_24h": sum(int(c) for _ts, c in gen_24h),
        })
    rows.sort(key=lambda r: (r["kills"], r["blocks"], r["chars_24h"]), reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Giudice LLM (pattern di community_moderator: client riusato da generation_engine)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the abuse moderator of a free web service that converts e-books into audiobooks with standard neural voices. Standard voices have a monthly free character quota per browser cookie ("cid"). Some users evade the quota by rotating cookies, registering fresh throwaway emails and switching networks, converting hundreds of books at zero revenue.

You receive ONLY aggregated behavioural features for one network group (same hashed /24 subnet) with a breakdown per cid alias (cid_1, cid_2, ...). No text, no identities.

Signals: S1 = quota exhausted this month; S2 = two or more cids in the group; S3 = many quota-gate acceptances in 24h; S4 = very high character volume in 24h.

Judge VOLUME and SPEED, not identities:
- Innocent: a handful of books per month across two cookies (device change), varied voices/languages/hours across cids. Diversity of voices, languages, active hours and emails between cids is the signature of a SHARED NETWORK (home NAT, mobile carrier-grade NAT hosting thousands of users), not of a single actor. S2 and S4 fire routinely on mobile /24 ranges: this alone is never abuse.
- Abuse: dozens of distinct files in a day or two, one voice and one language across cids, new emails appearing right after quota blocks, cids created minutes after a block, continuous activity at machine-like pace.

Be conservative: when in doubt answer "inconclusive". Use "scope": "group" ONLY if the cids share voice, language and hour pattern AND new emails/cids appear in bursts right after blocks; otherwise use "scope": "cids" and list only the guilty aliases.

Answer with a single JSON object and nothing else:
{"verdict": "abuse" | "clean" | "inconclusive", "confidence": 0.0-1.0, "scope": "cids" | "group", "cids": ["cid_1", ...], "reason": "one short sentence"}"""


def _bucket_features(b, now):
    gen_24h = _in_window(b.get("recent_generate"), now, _DAY_SEC, index=0)
    recent = sorted(float(t) for t in (b.get("recent") or []))
    gaps = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
    first, last = float(b.get("first_ts") or 0), float(b.get("last_ts") or 0)
    voices = sorted(b.get("voices", {}).items(), key=lambda kv: -kv[1])[:3]
    langs = sorted(b.get("langs", {}).items(), key=lambda kv: -kv[1])[:3]
    return {
        "generate_total": int(b.get("generate", 0)),
        "generate_24h": len(gen_24h),
        "chars_total": int(b.get("chars", 0)),
        "chars_24h": sum(int(c) for _ts, c in gen_24h),
        "quota_gate_total": int(b.get("quota_gate", 0)),
        "quota_gate_24h": len(_in_window(b.get("recent_gate"), now, _DAY_SEC)),
        "quota_block_total": int(b.get("quota_block", 0)),
        "email_registrations": int(b.get("email", 0)),
        "distinct_emails": len(b.get("emails") or []),
        "distinct_files": len(b.get("files") or []),
        "top_voices": [[v, int(n)] for v, n in voices],
        "top_languages": [[l, int(n)] for l, n in langs],
        "quota_exhausted": bool(b.get("quota_exhausted_ts")),
        "active_hours_utc": sorted({time.gmtime(t).tm_hour for t in recent}),
        "span_hours": round((last - first) / 3600, 1) if first and last else 0,
        "median_gap_minutes": round(sorted(gaps)[len(gaps) // 2] / 60, 1) if gaps else None,
    }


def build_prompt(group):
    """(json_utente, alias_map) da sole feature; None se il gruppo non esiste."""
    g = dossier(group)
    if not g:
        return None
    now = time.time()
    alias = {f"cid_{i + 1}": cid for i, cid in enumerate(sorted(g.get("cids", {}).keys()))}
    feats = {
        "signals": _signals(g, now),
        "group": dict(_bucket_features(g["all"], now), distinct_cids=len(alias)),
        "cids": {a: _bucket_features(g["cids"][cid], now) for a, cid in alias.items()},
    }
    return json.dumps(feats, ensure_ascii=True, separators=(",", ":")), alias


def _parse_verdict(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip markdown fence if present (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) > 2 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except Exception:
            return None
    return None


def _call_llm(user, timeout):
    import generation_engine as ge
    client = ge._llm_client
    if client is None:
        raise RuntimeError("LLM client not configured")
    resp = client.chat.completions.create(
        model=ge.LLM_MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user}],
        max_tokens=400,
        temperature=0.0,
        timeout=timeout,
        extra_body=ge.THINKING_OFF_BODY,
    )
    return (resp.choices[0].message.content or "").strip()


def judge(group, timeout=20.0, attempts=2):
    """Verdetto del giudice, gia' persistito con set_verdict. None = fail-open
    (LLM assente, timeout, risposta malformata): registrato come 'unjudged'."""
    try:
        import generation_engine as ge
        try:
            available = bool(ge._llm_available())
        except Exception:
            available = False
        if not available:
            record_judgement_failed(group, "llm_unavailable")
            return None
        built = build_prompt(group)
        if built is None:
            return None
        user, alias = built
        last_err = "malformed"
        for i in range(max(1, attempts)):
            try:
                raw = _parse_verdict(_call_llm(user, timeout))
                if isinstance(raw, dict) and raw.get("verdict") in VERDICTS:
                    cids = [alias[c] for c in (raw.get("cids") or [])
                            if isinstance(c, str) and c in alias]
                    scope = "group" if raw.get("scope") == "group" else "cids"
                    kind = raw["verdict"]
                    if kind == "abuse" and scope == "cids" and not cids:
                        kind = "inconclusive"
                    return set_verdict(group, {"verdict": kind, "confidence": raw.get("confidence"),
                                               "scope": scope, "cids": cids,
                                               "reason": raw.get("reason")})
                last_err = "malformed"
            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)[:120]}"
            if i + 1 < attempts:
                time.sleep(1.0)
        record_judgement_failed(group, last_err)
        return None
    except Exception:
        try:
            record_judgement_failed(group, "judge_error")
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Coda a giudice singolo
# ---------------------------------------------------------------------------

_queue = queue.Queue()
_queued = set()
_worker_started = False


def enqueue(group, cid=""):
    """Accoda il gruppo (dedup finche' non viene processato). True se accodato."""
    if not group:
        return False
    with _lock:
        if group in _queued:
            return False
        _queued.add(group)
    _queue.put((group, str(cid or "")))
    return True


def _process(group, cid, on_verdict):
    """Un giro del worker, sincrono: rigiudica solo se serve ancora, poi
    consegna il verdetto al callback (errori del callback non fermano il worker).
    Il dedup (`_queued`) si chiude a fine giudizio, non all'inizio: un evento
    arrivato durante i 20-40s della chiamata LLM non deve rimettere in coda
    lo stesso gruppo per un secondo giudizio identico."""
    try:
        if not needs_judgement(group, cid):
            return None
        v = judge(group)
        print(f"[abuse] judge {group}: "
              f"{(v or {}).get('verdict', 'unjudged')} "
              f"conf={(v or {}).get('confidence', 0):.2f} scope={(v or {}).get('scope', '-')}",
              flush=True)
        if v is not None and on_verdict is not None:
            try:
                on_verdict(group, v)
            except Exception as e:
                print(f"[abuse] on_verdict failed (non-fatal): {e}", flush=True)
        return v
    except Exception as e:
        print(f"[abuse] judge worker error (non-fatal): {e}", flush=True)
        return None
    finally:
        with _lock:
            _queued.discard(group)


def _worker(on_verdict):
    while True:
        group, cid = _queue.get()
        try:
            _process(group, cid, on_verdict)
        finally:
            _queue.task_done()


def start_worker(on_verdict):
    """Avvia (una volta) il thread del giudice. `on_verdict(group, verdict)`."""
    global _worker_started
    try:
        with _lock:
            if _worker_started:
                return
            _worker_started = True
            threading.Thread(target=_worker, args=(on_verdict,), daemon=True,
                             name="abuse-judge").start()
    except Exception:
        pass
