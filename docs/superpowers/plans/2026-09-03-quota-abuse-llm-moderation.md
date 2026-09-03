# Moderazione LLM dell'abuso della quota voci standard — Piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un giudice LLM valuta il dossier comportamentale di chi aggira la quota mensile delle voci standard (rotazione cookie/email/IP) e, sopra soglia di confidenza, i job non pagati di quel gruppo vengono terminati in corsa e rifiutati in ingresso; l'admin riceve i casi nel digest quotidiano.

**Architecture:** Nuovo modulo foglia `abuse_watch.py` (dossier JSON a due livelli gruppo/cid, segnali S1-S4, verdetto persistito, giudice DeepSeek, coda a giudice singolo). `audiobook_app.py` aggancia `record_event` ai punti `QUOTA_GATE`/`QUOTA_BLOCK`/`GENERATE`/`register_email`, rifiuta con 403 pre-claim i cid bloccati e applica i verdetti con la meccanica di cancel esistente (`job["cancelled"]` + marcatore `abuse_terminated`). `generation_engine` cambia solo la pulizia del ramo `_CancelledError` (work_dir conservata 24h). `email_service` aggiunge la sezione «Casi di abuso» al digest.

**Tech Stack:** Python 3 / Flask, stdlib (`json`, `hashlib`, `threading`, `queue`), `community_store.atomic_write_json`, client OpenAI-compatible DeepSeek già configurato in `generation_engine`, pytest, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-09-03-quota-containment-design.md`

## Global Constraints

- Ogni funzione di `abuse_watch` è **fail-open**: nessuna eccezione deve mai propagarsi a `/api/generate`, al cleanup o al digest.
- Kill e 403 solo se `ABM_ABUSE_KILL_ENABLE=1` **e** `ABM_ADMIN_EMAIL` non vuoto; solo `verdict=abuse ∧ confidence ≥ ABM_ABUSE_LLM_CONFIDENCE (0.9) ∧ cid nello scope ∧ job non premium/pagato` (`generation_engine.is_premium_job`).
- Il job ucciso chiude sul path cancel esistente: status `analyzed` + `cancelled=True`, **mai** `error` (`error` storna la quota in `_set_job_status`).
- Al provider LLM e nel digest email vanno **solo feature numeriche, hash e alias**: mai IP, email, titoli o filename in chiaro.
- Messaggio utente neutro, senza nome di provider né riferimento a quota/moderazione: «Elaborazione interrotta. Se pensi che sia un errore, contattaci.» Fallback non localizzato in inglese.
- Stringhe UI solo in `templates/_fragments/i18n_data.js` (7 lingue: it/en/fr/es/de/zh/hi).
- Commit: Conventional Commits `type(scope): summary`, **nessun trailer** di attribuzione. `git add` solo con path espliciti. Mai `git push` senza conferma esplicita dell'utente.
- Shell di sviluppo: PowerShell, un comando per volta, niente `&&`.
- I test esistenti `test/test_free_tts_quota*.py`, `test/test_free_quota_*.py`, `test/test_cancel_endpoint_lock.py`, `test/test_power_users_digest.py`, `test/test_digest_funnel.py` devono restare verdi **invariati**.
- Env var nuove: `ABM_ABUSE_KILL_ENABLE` (0), `ABM_ABUSE_LLM_CONFIDENCE` (0.9), `ABM_ABUSE_KEEP_HOURS` (24), `ABM_ABUSE_GATE_DAILY` (5), `ABM_ABUSE_CHARS_DAILY` (2500000), `ABM_ABUSE_VERDICT_TTL_DAYS` (14, forzato a 1 con kill spenta).

## Mappa dei file

| File | Ruolo |
|---|---|
| `abuse_watch.py` (nuovo) | dossier, segnali, verdetti, giudice LLM, coda del worker, dati per il digest |
| `test/test_abuse_watch.py` (nuovo) | dossier, segnali, trigger, verdetti, blocco, TTL, arm |
| `test/test_abuse_judge.py` (nuovo) | prompt da sole feature, parsing verdetto, fail-open, worker |
| `test/test_abuse_generate_enforcement.py` (nuovo) | 403 pre-claim, kill in corsa, ramo cancel, progress, cleanup, endpoint admin |
| `generation_engine.py` | `_cancel_cleanup_workdir` estratta dal ramo `_CancelledError` |
| `audiobook_app.py` | import, `_abuse_note`, 403 pre-claim, marcatori, `_abuse_apply_verdict`, worker, cleanup, endpoint admin, provider digest |
| `email_service.py` | `set_abuse_provider`, `_abuse_block_html`, `{abuse_block}` nel digest |
| `user_stats.py` | contatore `abuse_24h` (op `QUOTA_ABUSE_KILL`/`QUOTA_ABUSE_BLOCK`) nei power user |
| `static/js/app.js`, `templates/_fragments/i18n_data.js` | `job_terminated` nel 403 e nel progress, chiave `job_terminated_msg` |
| `md_files/PARAMETRI_CONFIGURAZIONE.md`, `CLAUDE.md` | env var, modulo, op di log |

Ordine di esecuzione: i task sono sequenziali (ognuno usa le interfacce del precedente).

---

### Task 1: `abuse_watch.py` — dossier a due livelli

**Files:**
- Create: `abuse_watch.py`
- Test: `test/test_abuse_watch.py`

**Interfaces:**
- Consumes: `community_store.atomic_write_json(path, data)` (già esistente, scrittura tmp+rename).
- Produces (usate dai task 2-8):
  - `KINDS = ("generate", "quota_gate", "quota_block", "email")`
  - `group_key(ip: str, cid: str = "") -> str` — `net:<hash>` per IPv4 (/24) e IPv6 (/64), altrimenti `cid:<cid>`.
  - `record_event(group: str, cid: str, kind: str, data: dict | None) -> None` — `data` accetta `chars`, `voice`, `lang`, `filename`, `email`.
  - `dossier(group: str) -> dict | None` — copia del gruppo (`all`, `cids`, `verdict`, `judgements`, `kills`, `blocks`, `created`, `updated`).
  - `_hash(value) -> str` (16 hex, salato con `ABM_IP_SALT`).
  - `_load() -> dict`, `_save(d) -> None`, `_lock`.

- [ ] **Step 1: Scrivi i test del dossier**

```python
# test/test_abuse_watch.py
"""abuse_watch: dossier a due livelli, segnali S1-S4, verdetti e blocco."""
import json
import time

import pytest

import abuse_watch as aw


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "admin@example.com")
    for k in ("ABM_ABUSE_LLM_CONFIDENCE", "ABM_ABUSE_KEEP_HOURS", "ABM_ABUSE_GATE_DAILY",
              "ABM_ABUSE_CHARS_DAILY", "ABM_ABUSE_VERDICT_TTL_DAYS"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _gen(group, cid, chars=1000, voice="zh-CN-XiaoxiaoNeural", fn="book.epub", lang="zh"):
    aw.record_event(group, cid, "generate",
                    {"chars": chars, "voice": voice, "filename": fn, "lang": lang})


def test_group_key_hashes_the_slash24(env):
    a = aw.group_key("1.2.3.4", "c1")
    assert a.startswith("net:") and len(a) == 4 + 16
    assert a == aw.group_key("1.2.3.250", "c2")
    assert a != aw.group_key("1.2.4.4", "c1")
    assert "1.2.3" not in a
    assert aw.group_key("", "cidX") == "cid:cidX"
    assert aw.group_key("not-an-ip", "cidY") == "cid:cidY"
    assert aw.group_key("2001:db8:1:2:3:4:5:6", "c") == aw.group_key("2001:db8:1:2:ffff::1", "c")


def test_record_event_two_levels_and_hashed_identifiers(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a", chars=100, fn="Secret Title.epub")
    _gen(g, "b", chars=50, fn="Other.epub")
    aw.record_event(g, "a", "email", {"email": "Someone@Example.com"})
    aw.record_event(g, "a", "quota_block", {"chars": 100})
    d = aw.dossier(g)
    assert d["all"]["generate"] == 2 and d["all"]["chars"] == 150
    assert d["all"]["quota_block"] == 1 and d["all"]["email"] == 1
    assert set(d["cids"]) == {"a", "b"}
    assert d["cids"]["a"]["chars"] == 100 and d["cids"]["b"]["generate"] == 1
    assert len(d["all"]["files"]) == 2 and len(d["all"]["emails"]) == 1
    assert d["all"]["voices"] == {"zh-CN-XiaoxiaoNeural": 2}
    assert d["all"]["langs"] == {"zh": 2}
    raw = (env / "_abuse_dossiers.json").read_text(encoding="utf-8")
    assert "Secret Title" not in raw and "example.com" not in raw.lower()


def test_unknown_kind_and_corrupt_file_are_fail_open(env):
    (env / "_abuse_dossiers.json").write_text("{not json", encoding="utf-8")
    g = aw.group_key("9.9.9.9", "a")
    aw.record_event(g, "a", "bogus", {})
    assert aw.dossier(g) is None
    _gen(g, "a")
    assert aw.dossier(g)["all"]["generate"] == 1
    assert aw.dossier("net:missing") is None


def test_retention_prunes_old_groups(env, monkeypatch):
    g_old = aw.group_key("1.1.1.1", "a")
    _gen(g_old, "a")
    real_time = time.time
    monkeypatch.setattr(aw.time, "time", lambda: real_time() + 61 * 86400)
    g_new = aw.group_key("2.2.2.2", "b")
    _gen(g_new, "b")
    assert aw.dossier(g_old) is None and aw.dossier(g_new) is not None
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_abuse_watch.py -v --tb=short`
Expected: FAIL con `ModuleNotFoundError: No module named 'abuse_watch'`

- [ ] **Step 3: Crea `abuse_watch.py` con dossier, hash e retention**

```python
# abuse_watch.py
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
    atomic_write_json(_dossier_file(), d)


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
    """Aggiorna il dossier del gruppo e del cid. `kind` fuori da KINDS: no-op."""
    if kind not in KINDS or not group:
        return
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
        _save(d)


def dossier(group):
    with _lock:
        g = _load()["groups"].get(group)
    return json.loads(json.dumps(g)) if g is not None else None
```

- [ ] **Step 4: Esegui i test**

Run: `pytest test/test_abuse_watch.py -v --tb=short`
Expected: 4 PASS

- [ ] **Step 5: Verifica sintassi e commit**

Run: `python -m py_compile abuse_watch.py`

```powershell
git add abuse_watch.py test/test_abuse_watch.py
git commit -m "feat(abuse): dossier comportamentale a due livelli per la moderazione quota"
```

---

### Task 2: Segnali, verdetti, blocco, arm e dati digest

**Files:**
- Modify: `abuse_watch.py` (append)
- Test: `test/test_abuse_watch.py` (append)

**Interfaces:**
- Consumes: Task 1 (`_load`, `_save`, `_lock`, `_new_group`, `_push`, `dossier`, config helpers).
- Produces:
  - `signals_for(group) -> {"S1": bool, "S2": bool, "S3": bool, "S4": bool}`
  - `needs_judgement(group, cid="") -> bool`
  - `set_verdict(group, verdict: dict) -> dict` — normalizza e persiste `{verdict, confidence, scope, cids, reason, ts, signals, events_at_verdict}`; con `scope="group"` `cids` = tutti i cid noti.
  - `verdict_for(group) -> dict | None` (solo verdetti entro TTL)
  - `record_judgement_failed(group, reason="") -> None`
  - `is_blocked(group, cid) -> bool`
  - `clear_verdict(group) -> bool`
  - `record_kill(group, cid, job_id) -> None`, `record_block(group, cid) -> None`
  - `arm_on_startup() -> int` (verdetti azzerati al primo avvio con kill accesa)
  - `digest_data(window_sec=86400) -> list[dict]` con chiavi `group, signals, cids_n, verdict, confidence, scope, reason, kills, blocks, unjudged, generate_24h, chars_24h`.

- [ ] **Step 1: Aggiungi i test**

```python
# append a test/test_abuse_watch.py

def test_signals_s1_to_s4(env, monkeypatch):
    monkeypatch.setenv("ABM_ABUSE_GATE_DAILY", "3")
    monkeypatch.setenv("ABM_ABUSE_CHARS_DAILY", "5000")
    g = aw.group_key("9.9.9.9", "a")
    assert aw.signals_for(g) == {"S1": False, "S2": False, "S3": False, "S4": False}
    _gen(g, "a", chars=1000)
    assert not any(aw.signals_for(g).values())
    aw.record_event(g, "a", "quota_block", {"chars": 1000})
    assert aw.signals_for(g)["S1"] is True
    _gen(g, "b", chars=1000)
    assert aw.signals_for(g)["S2"] is True
    for _ in range(3):
        aw.record_event(g, "b", "quota_gate", {"chars": 1000})
    assert aw.signals_for(g)["S3"] is True
    assert aw.signals_for(g)["S4"] is False
    _gen(g, "b", chars=3000)
    assert aw.signals_for(g)["S4"] is True


def test_needs_judgement_from_second_signal(env):
    g = aw.group_key("9.9.9.9", "a")
    aw.record_event(g, "a", "quota_block", {"chars": 10})
    assert aw.needs_judgement(g, "a") is False          # solo S1
    _gen(g, "b", chars=10)
    assert aw.needs_judgement(g, "b") is True           # S1 + S2
    aw.set_verdict(g, {"verdict": "clean", "confidence": 0.8, "scope": "cids",
                       "cids": ["a", "b"], "reason": "shared network"})
    assert aw.needs_judgement(g, "a") is False          # clean valido
    _gen(g, "c", chars=10)
    assert aw.needs_judgement(g, "c") is False          # nessun segnale nuovo
    for _ in range(5):
        aw.record_event(g, "c", "quota_gate", {"chars": 10})
    assert aw.needs_judgement(g, "c") is True           # S3 e' nuovo rispetto al verdetto


def test_verdict_scope_cids_vs_group_and_new_cid(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a"); _gen(g, "b")
    v = aw.set_verdict(g, {"verdict": "abuse", "confidence": "0.95", "scope": "cids",
                           "cids": ["a", "ghost"], "reason": "bot"})
    assert v["cids"] == ["a"] and v["confidence"] == 0.95
    assert aw.is_blocked(g, "a") is True and aw.is_blocked(g, "b") is False
    assert aw.needs_judgement(g, "a") is False
    assert aw.needs_judgement(g, "b") is True           # cid fuori scope -> rigiudizio
    v = aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.99, "scope": "group",
                           "cids": [], "reason": "same actor"})
    assert sorted(v["cids"]) == ["a", "b"]
    assert aw.is_blocked(g, "b") is True
    _gen(g, "c")
    assert aw.is_blocked(g, "c") is False and aw.needs_judgement(g, "c") is True


def test_low_confidence_or_inconclusive_never_blocks(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.7, "scope": "cids", "cids": ["a"]})
    assert aw.is_blocked(g, "a") is False
    aw.set_verdict(g, {"verdict": "inconclusive", "confidence": 1.0, "scope": "group", "cids": []})
    assert aw.is_blocked(g, "a") is False
    aw.set_verdict(g, {"verdict": "nonsense", "confidence": 1.0, "scope": "group"})
    assert aw.verdict_for(g)["verdict"] == "inconclusive"


def test_verdict_ttl_and_growth_reevaluation(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    for _ in range(4):
        _gen(g, "a")
    aw.record_event(g, "a", "quota_block", {})
    _gen(g, "b")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.95, "scope": "group", "cids": []})
    assert aw.needs_judgement(g, "a") is False
    for _ in range(2):
        _gen(g, "a")                                    # +25% eventi (6 -> 8)
    assert aw.needs_judgement(g, "a") is True
    real_time = time.time
    monkeypatch.setattr(aw.time, "time", lambda: real_time() + 15 * 86400)
    assert aw.verdict_for(g) is None and aw.is_blocked(g, "a") is False


def test_kill_switch_and_admin_email_gate(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": []})
    assert aw.is_blocked(g, "a") is True
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    assert aw.kill_enabled() is False and aw.is_blocked(g, "a") is False
    assert aw.verdict_ttl_sec() == 86400                # osservazione: TTL 1 giorno
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "")
    assert aw.kill_enabled() is False and aw.is_blocked(g, "a") is False


def test_clear_verdict_and_arm_on_startup(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": []})
    assert aw.clear_verdict(g) is True and aw.verdict_for(g) is None
    assert aw.clear_verdict(g) is False
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    assert aw.arm_on_startup() == 0
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": []})
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    assert aw.arm_on_startup() == 1                     # primo avvio con kill: azzera
    assert aw.verdict_for(g) is None
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": []})
    assert aw.arm_on_startup() == 0                     # gia' armato: non tocca
    assert aw.verdict_for(g) is not None


def test_digest_data_only_hashes_and_counts(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a", chars=500, fn="Secret.epub")
    aw.record_event(g, "a", "email", {"email": "who@example.com"})
    assert aw.digest_data() == []                       # nessun giudizio/kill/403
    aw.record_judgement_failed(g, "timeout")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.93, "scope": "cids",
                       "cids": ["a"], "reason": "103 files in 2 days"})
    aw.record_kill(g, "a", "job-1")
    aw.record_block(g, "a")
    rows = aw.digest_data()
    assert len(rows) == 1
    r = rows[0]
    assert r["group"] == g and r["verdict"] == "abuse" and r["scope"] == "cids"
    assert r["kills"] == 1 and r["blocks"] == 1 and r["unjudged"] == 1
    assert r["cids_n"] == 1 and r["generate_24h"] == 1 and r["chars_24h"] == 500
    blob = json.dumps(rows)
    assert "9.9.9" not in blob and "example.com" not in blob and "Secret" not in blob
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_abuse_watch.py -v --tb=short`
Expected: i nuovi 8 test FAIL con `AttributeError: module 'abuse_watch' has no attribute 'signals_for'` (o simili)

- [ ] **Step 3: Implementa segnali, verdetti e blocco**

```python
# append a abuse_watch.py

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


def needs_judgement(group, cid=""):
    """Vero con >=2 segnali e nessun verdetto valido; con verdetto `abuse` se
    `cid` e' fuori dallo scope (rotazione post-verdetto); con `clean` solo se
    compare un segnale nuovo; altrimenti se gli eventi sono cresciuti del 25%."""
    g = dossier(group)
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
    grown = _events_total(g) >= int(v.get("events_at_verdict", 0)) * 1.25 + 1
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
            cids = known
        else:
            cids = [c for c in (verdict.get("cids") or []) if isinstance(c, str) and c in known]
        try:
            conf = min(1.0, max(0.0, float(verdict.get("confidence") or 0)))
        except (TypeError, ValueError):
            conf = 0.0
        kind = verdict.get("verdict")
        if kind not in VERDICTS:
            kind = "inconclusive"
        v = {"verdict": kind, "confidence": conf, "scope": scope, "cids": cids,
             "reason": str(verdict.get("reason") or "")[:500], "ts": now,
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
```

- [ ] **Step 4: Esegui i test**

Run: `pytest test/test_abuse_watch.py -v --tb=short`
Expected: 12 PASS

- [ ] **Step 5: Verifica sintassi e commit**

Run: `python -m py_compile abuse_watch.py`

```powershell
git add abuse_watch.py test/test_abuse_watch.py
git commit -m "feat(abuse): segnali S1-S4, verdetti persistiti, blocco per cid e dati digest"
```

---

### Task 3: Giudice LLM e coda del worker

**Files:**
- Modify: `abuse_watch.py` (append)
- Test: `test/test_abuse_judge.py`

**Interfaces:**
- Consumes: `generation_engine._llm_client` (client OpenAI-compatible o `None`), `generation_engine.LLM_MODEL`, `generation_engine.THINKING_OFF_BODY`, `generation_engine._llm_available()`; Task 2 (`set_verdict`, `record_judgement_failed`, `needs_judgement`, `_signals`, `_in_window`).
- Produces:
  - `build_prompt(group) -> tuple[str, dict] | None` — `(user_json, alias_map)` con `alias_map = {"cid_1": "<cid reale>", ...}`.
  - `judge(group, timeout=20.0, attempts=2) -> dict | None` — verdetto normalizzato e già persistito, `None` = fail-open (registrato come `unjudged`).
  - `enqueue(group, cid="") -> bool`, `start_worker(on_verdict) -> None`, `_process(group, cid, on_verdict) -> dict | None` (sincrono, usato dal worker e dai test). `on_verdict(group: str, verdict: dict)`.
  - `SYSTEM_PROMPT: str`.

- [ ] **Step 1: Scrivi i test del giudice**

```python
# test/test_abuse_judge.py
"""Giudice LLM: prompt da sole feature, parsing del verdetto, fail-open, worker."""
import json

import pytest

import abuse_watch as aw
import generation_engine as ge


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _FakeClient:
    """Risponde in sequenza con i testi passati; registra le chiamate."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kw):
                outer.calls.append(kw)
                if not outer.answers:
                    raise RuntimeError("no more answers")
                a = outer.answers.pop(0)
                if isinstance(a, Exception):
                    raise a
                return _Resp(a)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(ge, "_llm_available", lambda: True)
    monkeypatch.setattr(ge, "LLM_MODEL", "deepseek-chat")
    monkeypatch.setattr(aw.time, "sleep", lambda *_a, **_k: None)
    return tmp_path


def _suspicious_group():
    g = aw.group_key("9.9.9.9", "a")
    for i in range(6):
        aw.record_event(g, "a", "generate", {"chars": 400_000, "voice": "zh-CN-XiaoxiaoNeural",
                                             "filename": f"Secret Book {i}.epub", "lang": "zh"})
    aw.record_event(g, "a", "email", {"email": "first@gmail.com"})
    aw.record_event(g, "a", "quota_block", {"chars": 400_000})
    aw.record_event(g, "b", "email", {"email": "second@outlook.com"})
    for i in range(3):
        aw.record_event(g, "b", "quota_gate", {"chars": 400_000})
        aw.record_event(g, "b", "generate", {"chars": 400_000, "voice": "zh-CN-XiaoxiaoNeural",
                                             "filename": f"Other {i}.epub", "lang": "zh"})
    return g


def test_prompt_contains_only_features(env):
    g = _suspicious_group()
    user, alias = aw.build_prompt(g)
    assert set(alias) == {"cid_1", "cid_2"} and set(alias.values()) == {"a", "b"}
    for secret in ("9.9.9", "gmail", "outlook", "Secret", "Other", "first@", "@"):
        assert secret not in user
    feats = json.loads(user)
    assert feats["signals"]["S1"] and feats["signals"]["S2"]
    assert feats["group"]["distinct_cids"] == 2
    assert feats["group"]["distinct_emails"] == 2 and feats["group"]["distinct_files"] == 9
    assert feats["cids"]["cid_1"]["generate_total"] == 6
    assert feats["cids"]["cid_2"]["quota_gate_total"] == 3
    assert feats["group"]["top_voices"] == [["zh-CN-XiaoxiaoNeural", 9]]
    assert aw.build_prompt("net:unknown") is None


def test_judge_parses_verdict_with_cids_scope(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient(json.dumps({"verdict": "abuse", "confidence": 0.95, "scope": "cids",
                                   "cids": ["cid_1", "cid_9"], "reason": "one voice, many files"}))
    monkeypatch.setattr(ge, "_llm_client", fake)
    v = aw.judge(g)
    assert v["verdict"] == "abuse" and v["confidence"] == 0.95 and v["cids"] == ["a"]
    assert aw.is_blocked(g, "a") is True and aw.is_blocked(g, "b") is False
    call = fake.calls[0]
    assert call["model"] == "deepseek-chat" and call["temperature"] == 0.0
    assert call["extra_body"] == ge.THINKING_OFF_BODY and call["timeout"] == 20.0
    assert call["messages"][0]["role"] == "system" and "inconclusive" in call["messages"][0]["content"]


def test_judge_scope_group_and_json_in_prose(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient('Here is my verdict: {"verdict": "abuse", "confidence": 0.92, '
                       '"scope": "group", "cids": [], "reason": "same actor"} thanks')
    monkeypatch.setattr(ge, "_llm_client", fake)
    v = aw.judge(g)
    assert v["scope"] == "group" and sorted(v["cids"]) == ["a", "b"]


def test_judge_abuse_without_known_cids_becomes_inconclusive(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient(json.dumps({"verdict": "abuse", "confidence": 0.99, "scope": "cids",
                                   "cids": ["cid_42"], "reason": "x"}))
    monkeypatch.setattr(ge, "_llm_client", fake)
    v = aw.judge(g)
    assert v["verdict"] == "inconclusive" and aw.is_blocked(g, "a") is False


def test_judge_fail_open_on_malformed_and_errors(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient("not json at all", RuntimeError("boom"))
    monkeypatch.setattr(ge, "_llm_client", fake)
    assert aw.judge(g) is None
    assert len(fake.calls) == 2                          # 1 retry
    assert aw.verdict_for(g) is None
    rows = aw.digest_data()
    assert rows and rows[0]["unjudged"] == 1


def test_judge_skips_when_llm_unavailable(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient("{}")
    monkeypatch.setattr(ge, "_llm_client", fake)
    monkeypatch.setattr(ge, "_llm_available", lambda: False)
    assert aw.judge(g) is None and fake.calls == []
    assert aw.digest_data()[0]["unjudged"] == 1


def test_worker_process_calls_back_and_dedups_queue(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient(json.dumps({"verdict": "abuse", "confidence": 0.95, "scope": "group",
                                   "cids": [], "reason": "r"}))
    monkeypatch.setattr(ge, "_llm_client", fake)
    assert aw.enqueue(g, "a") is True
    assert aw.enqueue(g, "b") is False                   # gia' in coda
    seen = []
    v = aw._process(g, "a", lambda grp, verdict: seen.append((grp, verdict["verdict"])))
    assert v["verdict"] == "abuse" and seen == [(g, "abuse")]
    assert aw.enqueue(g, "a") is True                    # sganciato dopo _process
    assert aw._process(g, "a", lambda *_: seen.append("again")) is None   # verdetto valido: no rigiudizio
    assert seen == [(g, "abuse")] and len(fake.calls) == 1


def test_worker_process_survives_callback_error(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient(json.dumps({"verdict": "clean", "confidence": 0.9, "scope": "group",
                                   "cids": [], "reason": "shared NAT"}))
    monkeypatch.setattr(ge, "_llm_client", fake)

    def _boom(*_a):
        raise RuntimeError("callback failed")

    v = aw._process(g, "a", _boom)
    assert v["verdict"] == "clean" and aw.verdict_for(g)["verdict"] == "clean"
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_abuse_judge.py -v --tb=short`
Expected: FAIL con `AttributeError: module 'abuse_watch' has no attribute 'build_prompt'`

- [ ] **Step 3: Implementa prompt, giudice e worker**

```python
# append a abuse_watch.py

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
    consegna il verdetto al callback (errori del callback non fermano il worker)."""
    with _lock:
        _queued.discard(group)
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
    if _worker_started:
        return
    _worker_started = True
    threading.Thread(target=_worker, args=(on_verdict,), daemon=True,
                     name="abuse-judge").start()
```

- [ ] **Step 4: Esegui i test**

Run: `pytest test/test_abuse_judge.py test/test_abuse_watch.py -v --tb=short`
Expected: 20 PASS

- [ ] **Step 5: Verifica sintassi e commit**

Run: `python -m py_compile abuse_watch.py`

```powershell
git add abuse_watch.py test/test_abuse_judge.py
git commit -m "feat(abuse): giudice DeepSeek su sole feature e coda a giudice singolo"
```

---

### Task 4: `generation_engine` — work_dir conservata sulla kill

**Files:**
- Modify: `generation_engine.py` (import in testa; ramo `_CancelledError` ~riga 6326-6348, blocco `if still_current:` dopo `_set_job_status(job, "analyzed")`)
- Test: `test/test_abuse_generate_enforcement.py` (nuovo, prima parte)

**Interfaces:**
- Consumes: `abuse_watch.keep_hours()`.
- Produces: `generation_engine._cancel_cleanup_workdir(job: dict, job_id: str, work_dir: Path, partial_audio_delivered: bool) -> None`; marcatore `job["abuse_kept_until"]` (epoch float).

- [ ] **Step 1: Scrivi il test del ramo cancel**

```python
# test/test_abuse_generate_enforcement.py
"""Enforcement anti-abuso: ramo cancel, 403 pre-claim, kill in corsa, progress,
cleanup e ripristino admin."""
import time

import pytest

import abuse_watch as aw
import audiobook_app
import free_tts_quota as ftq
import generation_engine
import payment
from epub_to_tts import BookInfo, Chapter

CID = "cid_abuse_enf_test"
OTHER = "cid_abuse_enf_other"
IP = "7.7.7.7"
VOICE = "en-US-AriaNeural"


class _SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "1000")
    monkeypatch.delenv("ABM_OUTPUT_REUSE", raising=False)
    run_calls, log_calls = [], []

    def _fake_run(job_id, info, voice, rate, single_file, **kw):
        run_calls.append((job_id, voice, kw))

    monkeypatch.setattr(audiobook_app, "run_generation", _fake_run)
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(audiobook_app, "_log_activity",
                         lambda *a, **k: log_calls.append((a, k)))
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    yield {"run": run_calls, "log": log_calls, "dir": tmp_path}
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("abz-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(job_id, n_chars=100, client_id=CID, status="analyzed"):
    ch = Chapter(index=0, title="Cap0", text="A" * n_chars)
    info = BookInfo(title="T", author="A", language="en", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": status, "client_id": client_id,
                                      "client_ip": IP, "original_filename": "book.epub"}
    return audiobook_app.jobs[job_id]


def _ops(env):
    return [a[2] for a, _k in env["log"]]


def _abuse_verdict(cids, scope="cids", confidence=0.95):
    g = aw.group_key(IP, CID)
    for c in cids:
        aw.record_event(g, c, "generate", {"chars": 10})
    aw.set_verdict(g, {"verdict": "abuse", "confidence": confidence, "scope": scope,
                       "cids": cids, "reason": "test"})
    return g


# ---------------------------------------------------------------------------
# Ramo cancel (generation_engine._cancel_cleanup_workdir)
# ---------------------------------------------------------------------------

def _work_dir(tmp_path):
    wd = tmp_path / "job-wd"
    wd.mkdir()
    (wd / "chunk_0001.pcm").write_bytes(b"x" * 10)
    (wd / "prompt_1.txt").write_text("p", encoding="utf-8")
    (wd / "_silence.pcm").write_bytes(b"s")
    return wd


def test_cancel_cleanup_removes_workdir_on_user_cancel(env, tmp_path):
    wd = _work_dir(tmp_path)
    job = {}
    generation_engine._cancel_cleanup_workdir(job, "j1", wd, partial_audio_delivered=False)
    assert not wd.exists() and "abuse_kept_until" not in job


def test_cancel_cleanup_keeps_pcm_only_with_partial_audio(env, tmp_path):
    wd = _work_dir(tmp_path)
    generation_engine._cancel_cleanup_workdir({}, "j1", wd, partial_audio_delivered=True)
    assert wd.exists() and not list(wd.glob("chunk_*.pcm")) and not (wd / "_silence.pcm").exists()


def test_cancel_cleanup_keeps_everything_on_abuse_kill(env, tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_ABUSE_KEEP_HOURS", "2")
    wd = _work_dir(tmp_path)
    job = {"abuse_terminated": True}
    t0 = time.time()
    generation_engine._cancel_cleanup_workdir(job, "j1", wd, partial_audio_delivered=False)
    assert (wd / "chunk_0001.pcm").exists() and (wd / "prompt_1.txt").exists()
    assert 2 * 3600 - 5 <= job["abuse_kept_until"] - t0 <= 2 * 3600 + 5


def test_cancel_cleanup_missing_workdir_sets_no_marker(env, tmp_path):
    job = {"abuse_terminated": True}
    generation_engine._cancel_cleanup_workdir(job, "j1", tmp_path / "nope", partial_audio_delivered=False)
    assert "abuse_kept_until" not in job


def test_analyzed_status_does_not_refund_quota(env):
    """La kill chiude su `analyzed` + cancelled: la quota resta addebitata.
    Solo `error` storna (_set_job_status)."""
    ftq.consume(CID, 400, "abz-q:1")
    job = {"status": "generating", "_free_tts_quota_ref": (CID, "abz-q:1"),
           "cancelled": True, "abuse_terminated": True}
    generation_engine._set_job_status(job, "analyzed")
    assert ftq.month_table().get(CID, {}).get("chars") == 400
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_abuse_generate_enforcement.py -v --tb=short`
Expected: i primi 4 FAIL con `AttributeError: module 'generation_engine' has no attribute '_cancel_cleanup_workdir'`; `test_analyzed_status_does_not_refund_quota` PASS (documenta l'invariante esistente).

- [ ] **Step 3: Estrai la pulizia in `_cancel_cleanup_workdir`**

In `generation_engine.py`, accanto agli altri import di moduli foglia (dopo `import free_tts_quota` o equivalente in testa al file), aggiungi:

```python
import abuse_watch
```

Aggiungi la funzione subito prima di `def _refund_gemini_payment(` (riga ~2387):

```python
def _cancel_cleanup_workdir(job, job_id, work_dir, partial_audio_delivered):
    """Pulizia della work_dir dopo un cancel.

    Job ucciso dalla moderazione anti-abuso (`abuse_terminated`): chunk e
    work_dir restano al loro posto per `ABM_ABUSE_KEEP_HOURS` (marcatore
    `abuse_kept_until`, letto dal cleanup loop di audiobook_app): il
    ripristino da console e' un rilancio con riuso dei chunk. Altrimenti:
    via i PCM/prompt intermedi e, se non e' stato consegnato audio parziale,
    tutta la work_dir (comportamento storico del ramo _CancelledError).
    """
    try:
        if not work_dir.exists():
            return
        if job.get("abuse_terminated"):
            job["abuse_kept_until"] = time.time() + abuse_watch.keep_hours() * 3600
            print(f"[{job_id}] abuse kill: work_dir conservata fino a "
                  f"{job['abuse_kept_until']:.0f}", flush=True)
            return
        # Conserva l'MP3 parziale finche' il token download e' vivo:
        # rimuoviamo solo i PCM/sub-dir intermedi, non output_dir.
        for p in work_dir.glob("chunk_*.pcm"):
            try: p.unlink()
            except OSError: pass
        for p in work_dir.glob("prompt*.txt"):
            try: p.unlink()
            except OSError: pass
        sil = work_dir / "_silence.pcm"
        if sil.exists():
            try: sil.unlink()
            except OSError: pass
        # Se NON e' stato consegnato audio parziale, rimuovi tutta la work_dir.
        if not partial_audio_delivered:
            shutil.rmtree(str(work_dir), ignore_errors=True)
    except Exception:
        pass
```

Nel ramo `_CancelledError` di `run_generation` sostituisci il blocco:

```python
            _mark_pending_failed(job_id, "cancelled")
            _set_job_status(job, "analyzed")
            job["progress_message"] = "Cancelled"
            try:
                if work_dir.exists():
                    # Conserva l'MP3 parziale finche' il token download e' vivo:
                    # rimuoviamo solo i PCM/sub-dir intermedi, non output_dir.
                    for p in work_dir.glob("chunk_*.pcm"):
                        try: p.unlink()
                        except OSError: pass
                    for p in work_dir.glob("prompt*.txt"):
                        try: p.unlink()
                        except OSError: pass
                    sil = work_dir / "_silence.pcm"
                    if sil.exists():
                        try: sil.unlink()
                        except OSError: pass
                    # Se NON e' stato consegnato audio parziale, rimuovi tutta la work_dir.
                    if not partial_audio_delivered:
                        shutil.rmtree(str(work_dir), ignore_errors=True)
            except Exception:
                pass
```

con:

```python
            _mark_pending_failed(job_id, "cancelled")
            _set_job_status(job, "analyzed")
            job["progress_message"] = "Cancelled"
            _cancel_cleanup_workdir(job, job_id, work_dir, partial_audio_delivered)
```

- [ ] **Step 4: Esegui i test (nuovi + cancel esistenti)**

Run: `pytest test/test_abuse_generate_enforcement.py test/test_cancel_endpoint_lock.py test/test_cancel_policy.py test/test_email_cancel_partial.py -v --tb=short`
Expected: tutti PASS

- [ ] **Step 5: Verifica sintassi e commit**

Run: `python -m py_compile generation_engine.py`

```powershell
git add generation_engine.py test/test_abuse_generate_enforcement.py
git commit -m "feat(abuse): il ramo cancel conserva chunk e work_dir dei job uccisi per abuso"
```

---

### Task 5: `/api/generate` — 403 pre-claim, dossier, marcatori, progress

**Files:**
- Modify: `audiobook_app.py`
  - import moduli foglia (riga ~127, dopo `import free_tts_quota`)
  - helper nuovi accanto a `_power_users_data()` (riga ~3977)
  - `api_generate()`: regione pre-claim (~11118-11170), ramo `QUOTA_BLOCK` (~11306), consumo `QUOTA_GATE` (~11380), dopo `thread.start()` + log `GENERATE` (~11389)
  - `api_register_email()`: dopo `job["email_registered"] = True` (~11810)
  - `api_progress()`: ramo `cancelled` (~11510)
- Test: `test/test_abuse_generate_enforcement.py` (append)

**Interfaces:**
- Consumes: Task 2 (`group_key`, `record_event`, `needs_judgement`, `enqueue`, `is_blocked`, `record_block`).
- Produces: `audiobook_app._abuse_group_of(job) -> str`, `audiobook_app._abuse_note(job_id, job, kind, **data) -> None`; campi job `abuse_group`, `abuse_terminated`, `abuse_kept_until`; op di log `QUOTA_ABUSE_BLOCK`; risposta `403 {"error": "Processing interrupted.", "error_code": "job_terminated"}`; progress `error_code: "job_terminated"`.

- [ ] **Step 1: Aggiungi i test degli agganci**

```python
# append a test/test_abuse_generate_enforcement.py

# ---------------------------------------------------------------------------
# /api/generate: 403 pre-claim, dossier, marcatori, progress
# ---------------------------------------------------------------------------

def _post(client, job_id, **extra):
    payload = {"job_id": job_id, "voice": VOICE, "rate": "+0%", "single_file": True,
               "output_format": "mp3"}
    payload.update(extra)
    return client.post("/api/generate", json=payload)


def test_403_only_for_cid_in_scope(env, client):
    g = _abuse_verdict([CID])
    job = _mk_job("abz-1")
    r = _post(client, "abz-1")
    assert r.status_code == 403 and r.get_json()["error_code"] == "job_terminated"
    assert "quota" not in r.get_json()["error"].lower()
    assert job["status"] == "analyzed" and env["run"] == []
    assert "QUOTA_ABUSE_BLOCK" in _ops(env)
    assert aw.digest_data()[0]["blocks"] == 1
    # altro cid dello stesso /24, fuori scope: passa
    _mk_job("abz-2", client_id=OTHER)
    client.set_cookie("abm_cid", OTHER)
    r = _post(client, "abz-2")
    assert r.status_code == 200 and [c[0] for c in env["run"]] == ["abz-2"]
    assert audiobook_app.jobs["abz-2"]["abuse_group"] == g


def test_paid_or_premium_job_never_blocked(env, client):
    _abuse_verdict([CID])
    job = _mk_job("abz-3")
    job["payment_amount_eur"] = 1.0
    r = _post(client, "abz-3")
    assert r.status_code == 200 and "QUOTA_ABUSE_BLOCK" not in _ops(env)


def test_kill_disabled_means_no_403(env, client, monkeypatch):
    _abuse_verdict([CID])
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    _mk_job("abz-4")
    assert _post(client, "abz-4").status_code == 200


def test_generate_records_dossier_and_resets_markers(env, client):
    job = _mk_job("abz-5")
    job["abuse_terminated"] = True
    job["abuse_kept_until"] = time.time() + 100
    r = _post(client, "abz-5")
    assert r.status_code == 200
    assert "abuse_terminated" not in job and "abuse_kept_until" not in job
    d = aw.dossier(aw.group_key(IP, CID))
    assert d["cids"][CID]["generate"] == 1 and d["cids"][CID]["chars"] == 100
    assert d["all"]["voices"] == {VOICE: 1} and d["all"]["langs"] == {"en": 1}
    assert len(d["all"]["files"]) == 1


def test_quota_block_and_gate_feed_the_dossier(env, client):
    _mk_job("abz-6", n_chars=1500)
    r = _post(client, "abz-6")
    assert r.status_code == 402
    d = aw.dossier(aw.group_key(IP, CID))
    assert d["cids"][CID]["quota_block"] == 1 and aw.signals_for(aw.group_key(IP, CID))["S1"]
    job = audiobook_app.jobs["abz-6"]
    job["notify_email"] = "u@example.com"
    job["email_registered"] = True
    r = _post(client, "abz-6", quota_ack=True)
    assert r.status_code == 200
    d = aw.dossier(aw.group_key(IP, CID))
    assert d["cids"][CID]["quota_gate"] == 1 and d["cids"][CID]["generate"] == 1


def test_register_email_feeds_the_dossier(env, client):
    _mk_job("abz-7")
    r = client.post("/api/register_email", json={"job_id": "abz-7", "email": "Who@Example.com"})
    assert r.status_code == 200
    d = aw.dossier(aw.group_key(IP, CID))
    assert d["cids"][CID]["email"] == 1 and len(d["all"]["emails"]) == 1
    raw = (env["dir"] / "_abuse_dossiers.json").read_text(encoding="utf-8")
    assert "example.com" not in raw.lower()


def test_second_signal_enqueues_judgement(env, client, monkeypatch):
    queued = []
    monkeypatch.setattr(aw, "enqueue", lambda g, c="": queued.append((g, c)) or True)
    g = aw.group_key(IP, CID)
    aw.record_event(g, OTHER, "quota_block", {})           # S1 (+ S2 col cid del test)
    _mk_job("abz-8")
    assert _post(client, "abz-8").status_code == 200
    assert queued == [(g, CID)]


def test_progress_reports_job_terminated(env, client):
    job = _mk_job("abz-9")
    job["cancelled"] = True
    job["abuse_terminated"] = True
    r = client.get("/api/progress/abz-9")
    body = r.get_data(as_text=True)
    assert '"status": "cancelled"' in body and '"error_code": "job_terminated"' in body
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_abuse_generate_enforcement.py -v --tb=short`
Expected: i nuovi 8 FAIL (403 non emesso, `abuse_group` assente, dossier vuoto, progress senza `error_code`).

- [ ] **Step 3: Import e helper**

In `audiobook_app.py`, dopo `import free_tts_quota` (riga ~127):

```python
import abuse_watch
```

Subito dopo la funzione `_power_users_data()` (prima del blocco `# Register funnel + power user providers`):

```python
# ---------------------------------------------------------------------------
# Moderazione anti-abuso della quota voci standard (abuse_watch)
# ---------------------------------------------------------------------------

def _abuse_group_of(job):
    return abuse_watch.group_key(job.get("client_ip", ""), job.get("client_id", ""))


def _abuse_note(job_id, job, kind, **data):
    """Aggiorna il dossier anti-abuso e, al secondo segnale, accoda il giudizio.
    Best-effort: mai bloccante per il chiamante."""
    try:
        cid = job.get("client_id", "")
        group = _abuse_group_of(job)
        data.setdefault("filename", job.get("original_filename", ""))
        data.setdefault("lang", getattr(job.get("info"), "language", "") or "")
        abuse_watch.record_event(group, cid, kind, data)
        if abuse_watch.needs_judgement(group, cid):
            abuse_watch.enqueue(group, cid)
    except Exception as e:
        print(f"[{job_id}] abuse_watch {kind} failed (non-fatal): {e}", flush=True)
```

- [ ] **Step 4: 403 pre-claim e marcatori in `api_generate`**

Individua nella regione pre-claim (~11118):

```python
    _premium_req = (_is_gemini_voice(voice) or _is_speechify_voice(voice)
                    or generation_engine.is_premium_job(job))
    with _jobs_lock:
        if job["status"] not in ("analyzed", "optimized"):
```

Inserisci fra `_premium_req = ...` e `with _jobs_lock:`:

```python
    # Moderazione anti-abuso: cid nello scope di un verdetto `abuse` valido
    # (abuse_watch). Mai su job premium/pagati. Il messaggio non spiega il
    # perche': spiegare le feature insegnerebbe al bot come aggirarle.
    _abuse_group = _abuse_group_of(job)
    if not _premium_req:
        try:
            _abuse_blocked = abuse_watch.is_blocked(_abuse_group, client_id)
        except Exception:
            _abuse_blocked = False
        if _abuse_blocked:
            try:
                abuse_watch.record_block(_abuse_group, client_id)
            except Exception:
                pass
            _log_activity(job_id, job.get("original_filename", ""), "QUOTA_ABUSE_BLOCK",
                          client_id, client_ip, voice,
                          browser_lang=job.get("browser_lang", ""))
            print(f"[{job_id}] abuse_watch: job rifiutato (gruppo {_abuse_group})", flush=True)
            return jsonify({"error": "Processing interrupted.",
                            "error_code": "job_terminated"}), 403
```

Dentro il claim, subito dopo `job["gen_owner_cid"] = client_id`:

```python
        job["abuse_group"] = _abuse_group
        job.pop("abuse_terminated", None)
        job.pop("abuse_kept_until", None)
```

- [ ] **Step 5: Eventi del dossier**

Nel ramo `QUOTA_BLOCK` (~11306), subito dopo la chiamata:

```python
                _log_activity(job_id, job.get("original_filename", ""), "QUOTA_BLOCK",
                              client_id, client_ip, voice,
                              browser_lang=job.get("browser_lang", ""))
```

aggiungi:

```python
                _abuse_note(job_id, job, "quota_block", chars=selected_chars, voice=voice)
```

Nel blocco di consumo (~11380), subito dopo:

```python
            if _ftq_gated:
                _log_activity(job_id, job.get("original_filename", ""), "QUOTA_GATE",
                              client_id, client_ip, voice,
                              browser_lang=job.get("browser_lang", ""))
```

aggiungi (stesso livello di indentazione della `_log_activity`, dentro l'`if _ftq_gated:`):

```python
                _abuse_note(job_id, job, "quota_gate", chars=_ftq_chars, voice=voice)
```

Dopo `thread.start()` e la `_log_activity(job_id, ..., "GENERATE", ...)` (~11389) aggiungi:

```python
    _abuse_note(job_id, job, "generate", chars=selected_chars, voice=voice)
```

In `api_register_email()`, subito dopo `job["email_registered"] = True` (~11810):

```python
    _abuse_note(job_id, job, "email", email=email)
```

- [ ] **Step 6: Progress SSE**

In `api_progress()`, nel ramo:

```python
            if job.get("status") == "cancelled" or job.get("cancelled"):
                payload["status"] = "cancelled"
```

aggiungi subito dopo `payload["status"] = "cancelled"`:

```python
                if job.get("abuse_terminated"):
                    # Kill della moderazione anti-abuso: il frontend mostra il
                    # messaggio neutro invece di "Generazione annullata".
                    payload["error_code"] = "job_terminated"
```

- [ ] **Step 7: Esegui i test**

Run: `pytest test/test_abuse_generate_enforcement.py test/test_free_tts_quota_gate.py -v --tb=short`
Expected: tutti PASS

- [ ] **Step 8: Verifica sintassi e commit**

Run: `python -m py_compile audiobook_app.py`

```powershell
git add audiobook_app.py test/test_abuse_generate_enforcement.py
git commit -m "feat(abuse): 403 pre-claim, dossier da generate/gate/block/email e progress job_terminated"
```

---

### Task 6: Worker di giudizio e kill in corsa

**Files:**
- Modify: `audiobook_app.py` (helper accanto a `_abuse_note`; `_ensure_background_threads()` ~17632)
- Test: `test/test_abuse_generate_enforcement.py` (append)

**Interfaces:**
- Consumes: Task 3 (`start_worker`, `arm_on_startup`, `kill_enabled`, `confidence_threshold`, `record_kill`), `generation_engine.is_premium_job`.
- Produces: `audiobook_app._abuse_apply_verdict(group: str, verdict: dict) -> int` (job uccisi); op di log `QUOTA_ABUSE_KILL`.

- [ ] **Step 1: Aggiungi i test della kill**

```python
# append a test/test_abuse_generate_enforcement.py

# ---------------------------------------------------------------------------
# Kill in corsa (_abuse_apply_verdict)
# ---------------------------------------------------------------------------

def _running(job_id, client_id=CID, group=None):
    job = _mk_job(job_id, client_id=client_id, status="generating")
    job["abuse_group"] = group or aw.group_key(IP, CID)
    job["voice"] = VOICE
    return job


def test_apply_verdict_kills_only_unpaid_in_scope_running(env):
    g = aw.group_key(IP, CID)
    verdict = {"verdict": "abuse", "confidence": 0.95, "scope": "cids", "cids": [CID]}
    victim = _running("abz-k1")
    other_cid = _running("abz-k2", client_id=OTHER)
    paid = _running("abz-k3"); paid["payment_token"] = "tok"
    idle = _mk_job("abz-k4"); idle["abuse_group"] = g
    other_group = _running("abz-k5", group="net:elsewhere")
    assert audiobook_app._abuse_apply_verdict(g, verdict) == 1
    assert victim["abuse_terminated"] is True and victim["cancelled"] is True
    for j in (other_cid, paid, idle, other_group):
        assert not j.get("abuse_terminated") and not j.get("cancelled")
    assert _ops(env).count("QUOTA_ABUSE_KILL") == 1
    assert aw.digest_data()[0]["kills"] == 1
    assert audiobook_app._abuse_apply_verdict(g, verdict) == 0      # idempotente


def test_apply_verdict_respects_confidence_switch_and_kind(env, monkeypatch):
    g = aw.group_key(IP, CID)
    job = _running("abz-k6")
    low = {"verdict": "abuse", "confidence": 0.5, "scope": "group", "cids": [CID]}
    assert audiobook_app._abuse_apply_verdict(g, low) == 0
    clean = {"verdict": "clean", "confidence": 1.0, "scope": "group", "cids": [CID]}
    assert audiobook_app._abuse_apply_verdict(g, clean) == 0
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    high = {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": [CID]}
    assert audiobook_app._abuse_apply_verdict(g, high) == 0
    assert not job.get("cancelled") and "QUOTA_ABUSE_KILL" not in _ops(env)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_abuse_generate_enforcement.py -k apply_verdict -v --tb=short`
Expected: FAIL con `AttributeError: module 'audiobook_app' has no attribute '_abuse_apply_verdict'`

- [ ] **Step 3: Implementa `_abuse_apply_verdict` e avvia il worker**

Subito dopo `_abuse_note` (Task 5):

```python
def _abuse_apply_verdict(group, verdict):
    """Callback del worker di giudizio: su verdetto `abuse` sopra soglia uccide
    i job IN CORSO dei cid nello scope, non pagati e a voce standard, con la
    meccanica di cancel esistente (`cancelled` + marcatore `abuse_terminated`,
    letto da _check_cancelled e dal ramo _CancelledError). Ritorna il numero
    di job uccisi."""
    if not isinstance(verdict, dict) or verdict.get("verdict") != "abuse":
        return 0
    try:
        conf = float(verdict.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    if not abuse_watch.kill_enabled() or conf < abuse_watch.confidence_threshold():
        print(f"[abuse] verdetto abuse su {group} senza kill "
              f"(enable={abuse_watch.kill_enabled()}, conf={conf:.2f})", flush=True)
        return 0
    scope_cids = set(verdict.get("cids") or [])
    killed = []
    with _jobs_lock:
        for jid, job in list(jobs.items()):
            if job.get("status") != "generating" or job.get("abuse_terminated"):
                continue
            if job.get("abuse_group") != group or job.get("client_id") not in scope_cids:
                continue
            if generation_engine.is_premium_job(job):
                continue
            job["abuse_terminated"] = True
            job["cancelled"] = True
            killed.append((jid, job))
    for jid, job in killed:
        _log_activity(jid, job.get("original_filename", ""), "QUOTA_ABUSE_KILL",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), browser_lang=job.get("browser_lang", ""))
        try:
            abuse_watch.record_kill(group, job.get("client_id", ""), jid)
        except Exception:
            pass
        print(f"[{jid}] abuse kill (gruppo {group}, conf {conf:.2f})", flush=True)
    return len(killed)
```

In `_ensure_background_threads()`, dopo `threading.Thread(target=_recover_orphan_jobs, daemon=True).start()`:

```python
    # Moderazione anti-abuso: worker di giudizio a giudice singolo. All'avvio
    # con kill accesa i verdetti maturati in osservazione vengono azzerati.
    try:
        _cleared = abuse_watch.arm_on_startup()
        if _cleared:
            print(f"[startup] abuse_watch: kill armata, {_cleared} verdetti azzerati", flush=True)
        abuse_watch.start_worker(_abuse_apply_verdict)
    except Exception as _aw_err:
        print(f"[startup] abuse_watch init failed (non-fatal): {_aw_err}", flush=True)
```

E fra le righe `print(f"[startup] ...")` finali:

```python
    print(f"[startup] Abuse moderation: "
          f"{'kill ON' if abuse_watch.kill_enabled() else 'observation only'} "
          f"(confidence >= {abuse_watch.confidence_threshold():.2f}, "
          f"keep {abuse_watch.keep_hours()}h)")
```

- [ ] **Step 4: Esegui i test**

Run: `pytest test/test_abuse_generate_enforcement.py test/test_abuse_judge.py -v --tb=short`
Expected: tutti PASS

- [ ] **Step 5: Verifica sintassi e commit**

Run: `python -m py_compile audiobook_app.py`

```powershell
git add audiobook_app.py test/test_abuse_generate_enforcement.py
git commit -m "feat(abuse): worker di giudizio e kill in corsa dei job non pagati nello scope"
```

---

### Task 7: Cleanup della work_dir conservata e ripristino admin

**Files:**
- Modify: `audiobook_app.py` (helper accanto a `_abuse_apply_verdict`; `_cleanup_loop()` ramo `if status == "analyzed":` ~17322; nuova route accanto alle altre `/admin/api/*`)
- Test: `test/test_abuse_generate_enforcement.py` (append)

**Interfaces:**
- Consumes: `abuse_watch.clear_verdict`, `_admin_auth_ok(_admin_auth_from_request())`, `_has_active_download_tokens(jid, now)`.
- Produces: `audiobook_app._abuse_keep_state(job, now) -> "hold" | "expired" | None`; `POST /admin/api/abuse/clear/<group>` → `{"ok": true, "group": ..., "cleared": bool}` (403 senza auth).

- [ ] **Step 1: Aggiungi i test**

```python
# append a test/test_abuse_generate_enforcement.py

# ---------------------------------------------------------------------------
# Cleanup della retention e ripristino admin
# ---------------------------------------------------------------------------

def test_abuse_keep_state(env):
    now = time.time()
    assert audiobook_app._abuse_keep_state({}, now) is None
    assert audiobook_app._abuse_keep_state({"abuse_kept_until": "junk"}, now) is None
    assert audiobook_app._abuse_keep_state({"abuse_kept_until": now + 60}, now) == "hold"
    assert audiobook_app._abuse_keep_state({"abuse_kept_until": now - 1}, now) == "expired"


def test_admin_clear_endpoint(env, client, monkeypatch):
    g = _abuse_verdict([CID])
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-test")
    r = client.post(f"/admin/api/abuse/clear/{g}")
    assert r.status_code == 403 and aw.verdict_for(g) is not None
    r = client.post(f"/admin/api/abuse/clear/{g}", headers={"X-Admin-Token": "tok-test"})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "group": g, "cleared": True}
    assert aw.verdict_for(g) is None
    r = client.post(f"/admin/api/abuse/clear/{g}", headers={"X-Admin-Token": "tok-test"})
    assert r.get_json()["cleared"] is False
    # dopo il ripristino il cid rigenera normalmente
    _mk_job("abz-c1")
    assert _post(client, "abz-c1").status_code == 200
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_abuse_generate_enforcement.py -k "keep_state or admin_clear" -v --tb=short`
Expected: FAIL (`_abuse_keep_state` assente; route 404)

- [ ] **Step 3: Helper, cleanup e route**

Dopo `_abuse_apply_verdict`:

```python
def _abuse_keep_state(job, now):
    """'hold' finche' la work_dir del job ucciso va conservata, 'expired'
    oltre `abuse_kept_until`, None se il job non e' stato ucciso per abuso."""
    kept = job.get("abuse_kept_until")
    if not kept:
        return None
    try:
        kept = float(kept)
    except (TypeError, ValueError):
        return None
    return "hold" if now < kept else "expired"
```

In `_cleanup_loop()`, nel ramo `if status == "analyzed":`, **prima** di `last_poll = job.get("last_poll", ...)`:

```python
                    # Job ucciso dalla moderazione anti-abuso: la work_dir
                    # resta per il ripristino da console (ABM_ABUSE_KEEP_HOURS),
                    # poi via come un analyzed qualunque.
                    _ak = _abuse_keep_state(job, now)
                    if _ak == "hold":
                        continue
                    if _ak == "expired":
                        if not _has_active_download_tokens(jid, now):
                            to_remove.append((jid, "abuse retention expired"))
                        continue
```

Route, accanto alle altre `/admin/api/*` (ad esempio subito dopo la route `/api/admin/google_tts_status`):

```python
@app.route("/admin/api/abuse/clear/<group>", methods=["POST"])
def admin_abuse_clear(group):
    """Ripristino di un gruppo bloccato dalla moderazione anti-abuso: azzera il
    verdetto. L'utente rilancia dal job in `analyzed` con riuso dei chunk.
    Nessun refund: il job non era pagato."""
    if not _admin_auth_ok(_admin_auth_from_request()):
        return jsonify({"error": "forbidden"}), 403
    try:
        cleared = bool(abuse_watch.clear_verdict(group))
    except Exception as e:
        return jsonify({"error": f"clear failed: {e}"}), 500
    print(f"[admin] abuse_watch clear {group}: {'ok' if cleared else 'no verdict'}", flush=True)
    return jsonify({"ok": True, "group": group, "cleared": cleared})
```

- [ ] **Step 4: Esegui i test**

Run: `pytest test/test_abuse_generate_enforcement.py -v --tb=short`
Expected: tutti PASS

- [ ] **Step 5: Verifica sintassi e commit**

Run: `python -m py_compile audiobook_app.py`

```powershell
git add audiobook_app.py test/test_abuse_generate_enforcement.py
git commit -m "feat(abuse): retention della work_dir dei job uccisi e ripristino da console admin"
```

---

### Task 8: Sezione «Casi di abuso» nel digest admin e op nei power user

**Files:**
- Modify: `email_service.py` (provider accanto a `_power_users_provider` riga ~87; `_abuse_block_html()` dopo `_power_users_block_html()`; inserimento `{abuse_block}` nel template del digest ~riga 453-475)
- Modify: `audiobook_app.py` (provider accanto a `_power_users_data()` e registrazione nel blocco `set_power_users_provider`)
- Modify: `user_stats.py` (`power_users()`: contatore `abuse_24h`)
- Test: `test/test_abuse_digest.py` (nuovo), `test/test_power_users_digest.py` (append)

**Interfaces:**
- Consumes: `abuse_watch.digest_data(window_sec)`, `abuse_watch.kill_enabled()`, `email_service._esc_html(value, max_len=None)`, `ADMIN_DIGEST_INTERVAL_SEC`.
- Produces: `email_service.set_abuse_provider(fn)`, `email_service._abuse_block_html() -> str`, `audiobook_app._abuse_digest_data() -> dict | None` (`{"rows", "window_hours", "kill_enabled"}`), campo `abuse_24h` nelle righe di `user_stats.power_users`.

- [ ] **Step 1: Scrivi i test**

```python
# test/test_abuse_digest.py
"""Sezione «Casi di abuso» del digest admin: solo hash e contatori."""
import email_service as es


def _rows():
    return [{"group": "net:abcdef0123456789", "signals": {"S1": True, "S2": True, "S3": False, "S4": True},
             "cids_n": 2, "verdict": "abuse", "confidence": 0.93, "scope": "cids",
             "reason": "one voice, 103 files in 2 days", "kills": 3, "blocks": 12,
             "unjudged": 0, "generate_24h": 40, "chars_24h": 9_500_000},
            {"group": "net:ffff000011112222", "signals": {"S1": True, "S2": False, "S3": True, "S4": False},
             "cids_n": 1, "verdict": "", "confidence": 0.0, "scope": "", "reason": "",
             "kills": 0, "blocks": 0, "unjudged": 2, "generate_24h": 3, "chars_24h": 12_000}]


def test_abuse_block_html_renders_rows_and_mode():
    es.set_abuse_provider(lambda: {"rows": _rows(), "window_hours": 24, "kill_enabled": True})
    html = es._abuse_block_html()
    assert "Casi di abuso" in html and "kill attiva" in html
    assert "net:abcdef0123456789" in html and "S1 S2 S4" in html
    assert "abuse (0.93, cids)" in html and "103 files" in html
    assert ">3<" in html and ">12<" in html and "non giudicat" in html
    assert "/admin/api/abuse/clear/" in html
    es.set_abuse_provider(None)


def test_abuse_block_html_observation_mode_and_empty():
    es.set_abuse_provider(lambda: {"rows": _rows()[:1], "window_hours": 24, "kill_enabled": False})
    assert "solo osservazione" in es._abuse_block_html()
    es.set_abuse_provider(lambda: {"rows": [], "window_hours": 24, "kill_enabled": True})
    assert es._abuse_block_html() == ""
    es.set_abuse_provider(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert es._abuse_block_html() == ""
    es.set_abuse_provider(None)
    assert es._abuse_block_html() == ""


def test_abuse_block_escapes_reason():
    rows = _rows()[:1]
    rows[0]["reason"] = "<script>alert(1)</script>"
    es.set_abuse_provider(lambda: {"rows": rows, "window_hours": 24, "kill_enabled": True})
    html = es._abuse_block_html()
    assert "<script>" not in html and "&lt;script&gt;" in html
    es.set_abuse_provider(None)


def test_audiobook_app_provider_wraps_abuse_watch(monkeypatch, tmp_path):
    import abuse_watch as aw
    import audiobook_app
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    assert audiobook_app._abuse_digest_data() is None
    g = aw.group_key("3.3.3.3", "z")
    aw.record_event(g, "z", "generate", {"chars": 5})
    aw.record_judgement_failed(g, "timeout")
    d = audiobook_app._abuse_digest_data()
    assert d["rows"][0]["group"] == g and d["kill_enabled"] is False and d["window_hours"] == 24
```

```python
# append a test/test_power_users_digest.py

def test_power_users_counts_abuse_ops(tmp_path):
    since = datetime(2026, 8, 30, 12, 0, 0)
    lines = [_line(f"g{i}", f"2026-08-30 {13 + i}:00:00", "b.epub", "GENERATE", "bad", "5.5.5.5")
             for i in range(5)]
    lines.append(_line("k1", "2026-08-30 19:00:00", "b.epub", "QUOTA_ABUSE_KILL", "bad", "5.5.5.5"))
    lines.append(_line("k2", "2026-08-30 19:05:00", "b.epub", "QUOTA_ABUSE_BLOCK", "bad", "5.5.5.5"))
    lines.append(_line("k3", "2026-08-01 19:05:00", "b.epub", "QUOTA_ABUSE_BLOCK", "bad", "5.5.5.5"))
    p = _write_log(tmp_path, lines)
    rows = user_stats.power_users([p], since, min_jobs=5)
    assert rows[0]["client_id"] == "bad" and rows[0]["abuse_24h"] == 2
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_abuse_digest.py test/test_power_users_digest.py -v --tb=short`
Expected: FAIL (`set_abuse_provider` assente, `_abuse_digest_data` assente, `KeyError: 'abuse_24h'`)

- [ ] **Step 3: `email_service` — provider e blocco HTML**

Dopo `set_power_users_provider` / `_power_users_block_html()`:

```python
_abuse_provider = None  # callable() -> {"rows": [...], "window_hours": int, "kill_enabled": bool} | None


def set_abuse_provider(fn):
    global _abuse_provider
    _abuse_provider = fn


def _abuse_block_html():
    """Sezione «Casi di abuso quota» del digest: gruppi con giudizio, kill o
    rifiuto 403 nella finestra (abuse_watch.digest_data). Solo hash di rete e
    contatori: mai IP, email o titoli nel canale email. '' se il provider
    manca, fallisce o non ha righe."""
    fn = _abuse_provider
    if not fn:
        return ""
    try:
        d = fn() or {}
    except Exception:
        return ""
    rows = d.get("rows") or []
    if not rows:
        return ""
    hours = int(d.get("window_hours") or 24)
    mode = "kill attiva" if d.get("kill_enabled") else "solo osservazione"
    th = "padding:6px 8px;text-align:left;font-size:12px;color:#555;white-space:nowrap"
    td = "padding:6px 8px;border-bottom:1px solid #eee;font-size:12px;vertical-align:top"
    trs = ""
    for r in rows:
        sig = " ".join(k for k, v in sorted((r.get("signals") or {}).items()) if v) or "-"
        verd = str(r.get("verdict") or "")
        if verd:
            verd += f" ({float(r.get('confidence') or 0):.2f}, {r.get('scope') or '-'})"
        else:
            verd = "-"
        unj = int(r.get("unjudged") or 0)
        if unj:
            verd += f" &middot; non giudicato x{unj}"
        chars = int(r.get("chars_24h") or 0)
        trs += (
            f"<tr><td style='{td};font-family:monospace'>{_esc_html(r.get('group', ''), 40)}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('cids_n') or 0)}</td>"
            f"<td style='{td};text-align:center'>{_esc_html(sig)}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('generate_24h') or 0)} / {chars:,}</td>"
            f"<td style='{td}'>{_esc_html(verd)}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('kills') or 0)}</td>"
            f"<td style='{td};text-align:center'>{int(r.get('blocks') or 0)}</td>"
            f"<td style='{td};color:#666'>{_esc_html(r.get('reason', ''), 160)}</td></tr>"
        )
    return f"""
<h3 style="margin:24px 0 8px;font-size:15px;color:#1a3c5e">Casi di abuso quota ({mode}, ultime {hours}h)</h3>
<table style="width:100%;border-collapse:collapse;background:white;border:1px solid #ddd">
<thead><tr style="background:#f0f5fa">
<th style="{th}">Gruppo</th><th style="{th};text-align:center">cid</th>
<th style="{th};text-align:center">Segnali</th><th style="{th};text-align:center">Avvii / caratteri 24h</th>
<th style="{th}">Verdetto</th><th style="{th};text-align:center">Kill</th>
<th style="{th};text-align:center">Rifiuti</th><th style="{th}">Motivazione</th>
</tr></thead><tbody>{trs}</tbody></table>
<p style="color:#888;font-size:11px;margin:6px 0 0">Solo hash di rete e contatori: nessun IP, email o titolo.
Ripristino di un gruppo: <code>POST /admin/api/abuse/clear/&lt;gruppo&gt;</code> con header X-Admin-Token.</p>"""
```

Nel template del digest, subito dopo `power_block = _power_users_block_html()`:

```python
    abuse_block = _abuse_block_html()
```

e nel f-string HTML, subito dopo la riga `{power_block}`:

```
{abuse_block}
```

- [ ] **Step 4: `audiobook_app` — provider**

Dopo `_abuse_keep_state` (Task 7):

```python
def _abuse_digest_data():
    """Righe per la sezione «Casi di abuso» del digest admin (24h)."""
    try:
        rows = abuse_watch.digest_data(ADMIN_DIGEST_INTERVAL_SEC)
    except Exception:
        return None
    if not rows:
        return None
    return {"rows": rows, "window_hours": max(1, int(ADMIN_DIGEST_INTERVAL_SEC // 3600)),
            "kill_enabled": abuse_watch.kill_enabled()}
```

Nel blocco di registrazione dei provider (dopo `_email_service.set_power_users_provider(_power_users_data)`):

```python
    _email_service.set_abuse_provider(_abuse_digest_data)
```

Nota: `_abuse_digest_data` deve essere definita **prima** di quel blocco `try:`; le funzioni del Task 5-7 vanno inserite fra `_power_users_data()` e il blocco `# Register funnel + power user providers`.

- [ ] **Step 5: `user_stats.power_users` — contatore `abuse_24h`**

Nel dizionario di inizializzazione dell'utente (dove compare `"gate_24h": 0, "block_24h": 0`) aggiungi `"abuse_24h": 0`. Nel parsing delle op, dopo il ramo `elif op == "QUOTA_BLOCK":`:

```python
                elif op in ("QUOTA_ABUSE_KILL", "QUOTA_ABUSE_BLOCK"):
                    if recent:
                        u["abuse_24h"] += 1
```

Nelle righe di output, dopo `"block_24h": u["block_24h"],`:

```python
            "abuse_24h": u["abuse_24h"],
```

In `email_service._power_users_block_html()`, la colonna gate/block mostra anche le kill se presenti: sostituisci

```python
        gate_txt = f"{int(r.get('gate_24h') or 0)} / {int(r.get('block_24h') or 0)}"
```

con

```python
        gate_txt = f"{int(r.get('gate_24h') or 0)} / {int(r.get('block_24h') or 0)}"
        if int(r.get("abuse_24h") or 0):
            gate_txt += f" &middot; abuso {int(r['abuse_24h'])}"
```

- [ ] **Step 6: Esegui i test**

Run: `pytest test/test_abuse_digest.py test/test_power_users_digest.py test/test_digest_funnel.py -v --tb=short`
Expected: tutti PASS

- [ ] **Step 7: Verifica sintassi e commit**

Run: `python -m py_compile email_service.py`
Run: `python -m py_compile user_stats.py`
Run: `python -m py_compile audiobook_app.py`

```powershell
git add email_service.py user_stats.py audiobook_app.py test/test_abuse_digest.py test/test_power_users_digest.py
git commit -m "feat(abuse): sezione casi di abuso nel digest admin e contatore nei power user"
```

---

### Task 9: Frontend — messaggio neutro `job_terminated`

**Files:**
- Modify: `static/js/app.js` (rami errore di `/api/generate` ~3194 e ~3625; ramo `cancelled` del progress ~4010)
- Modify: `templates/_fragments/i18n_data.js` (chiave `job_terminated_msg` in 7 lingue)

**Interfaces:**
- Consumes: `t(key)` (ritorna la chiave stessa o `undefined` se assente), `showErr(id, msg)`, `unlockUI()`, `_hideJobRunningModal(flag, jobId)`; risposte del Task 5.
- Produces: chiave i18n `job_terminated_msg`.

- [ ] **Step 1: Aggiungi la chiave i18n con uno script**

Esegui dalla root del repo:

```powershell
python - <<'EOF'
import io
p = "templates/_fragments/i18n_data.js"
s = io.open(p, encoding="utf-8").read()
msgs = {
    "it": "Elaborazione interrotta. Se pensi che sia un errore, contattaci.",
    "en": "Processing interrupted. If you think this is a mistake, please contact us.",
    "fr": "Traitement interrompu. Si vous pensez qu'il s'agit d'une erreur, contactez-nous.",
    "es": "Procesamiento interrumpido. Si crees que se trata de un error, contáctanos.",
    "de": "Verarbeitung unterbrochen. Wenn Sie glauben, dass es sich um einen Fehler handelt, kontaktieren Sie uns.",
    "zh": "处理已中断。如果您认为这是一个错误，请联系我们。",
    "hi": "प्रोसेसिंग रोक दी गई। अगर आपको लगता है कि यह एक गलती है, तो हमसे संपर्क करें।",
}
assert "job_terminated_msg" not in s
for lang, msg in msgs.items():
    marker = f"\n{lang}:{{"
    assert s.count(marker) == 1, lang
    s = s.replace(marker, marker + f'job_terminated_msg:"{msg}",', 1)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("ok")
EOF
```

(In PowerShell salva lo script in un file `.py` nello scratchpad ed eseguilo con `python <file>`; l'heredoc è mostrato per leggibilità.)

Verifica: `grep -o 'job_terminated_msg:"[^"]*"' templates/_fragments/i18n_data.js | wc -l` → 7. In PowerShell: `(Select-String -Path templates/_fragments/i18n_data.js -Pattern 'job_terminated_msg:' -AllMatches).Matches.Count` → 7.

- [ ] **Step 2: Rami 403 in `app.js`**

Nel primo blocco (~3194), subito **prima** di:

```javascript
        if(gd.error_code==='free_tts_quota_exhausted'){_handleTtsQuotaGate(gd);return;}
```

inserisci:

```javascript
        if(gd.error_code==='job_terminated'){
          const gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
          const pf=document.getElementById('panel4Footer');if(pf)pf.style.display='';
          showErr('s3err',t('job_terminated_msg')||'Processing interrupted. If you think this is a mistake, please contact us.');
          unlockUI();generating=false;return;
        }
```

Nel secondo blocco (~3625), subito **prima** di:

```javascript
      if(d.error_code==='free_tts_quota_exhausted'){_handleTtsQuotaGate(d);return;}
```

inserisci:

```javascript
      if(d.error_code==='job_terminated'){
        const gp=document.getElementById('generationProgress');if(gp)gp.style.display='none';
        const pf=document.getElementById('panel4Footer');if(pf)pf.style.display='';
        showErr('s3err',t('job_terminated_msg')||'Processing interrupted. If you think this is a mistake, please contact us.');
        unlockUI();generating=false;return;
      }
```

- [ ] **Step 3: Ramo `cancelled` del progress (~4010)**

Sostituisci la riga:

```javascript
      if(d.status==='cancelled'){es.close();_hideJobRunningModal(true,myJobId);document.getElementById('pMsg').textContent=t('cancelled_msg');document.getElementById('pMsg').style.color='var(--err)';document.getElementById('cnA').style.display='none';unlockUI();generating=false;_renderGeminiCancelSummary(d);return}
```

con:

```javascript
      if(d.status==='cancelled'){
        es.close();_hideJobRunningModal(true,myJobId);
        // Kill della moderazione anti-abuso: messaggio neutro, mai il perche'.
        const _cmsg=d.error_code==='job_terminated'
          ?(t('job_terminated_msg')||'Processing interrupted. If you think this is a mistake, please contact us.')
          :t('cancelled_msg');
        document.getElementById('pMsg').textContent=_cmsg;document.getElementById('pMsg').style.color='var(--err)';
        document.getElementById('cnA').style.display='none';unlockUI();generating=false;
        if(d.error_code!=='job_terminated')_renderGeminiCancelSummary(d);
        return
      }
```

- [ ] **Step 4: Verifica sintassi JS e test i18n esistenti**

Run: `node --check static/js/app.js` (se `node` è disponibile; altrimenti apri la SPA in locale e controlla la console)
Run: `node --check templates/_fragments/i18n_data.js`
Run: `pytest test/ -k "i18n or seo" -q --tb=short`
Expected: nessun errore di sintassi; test verdi

- [ ] **Step 5: Verifica manuale (locale)**

Avvia `python audiobook_app.py` con `ABM_DATA_DIR` locale e, in un'altra shell, forza un verdetto:

```powershell
python -c "import os; os.environ['ABM_DATA_DIR']=r'<data dir locale>'; import abuse_watch as aw; g=aw.group_key('127.0.0.1','<cid del browser>'); aw.record_event(g,'<cid del browser>','generate',{'chars':1}); print(aw.set_verdict(g,{'verdict':'abuse','confidence':0.99,'scope':'group','cids':[]}))"
```

Con `ABM_ABUSE_KILL_ENABLE=1` e `ABM_ADMIN_EMAIL` valorizzata: avviare una generazione a voce standard deve mostrare «Elaborazione interrotta. Se pensi che sia un errore, contattaci.» senza altre indicazioni. Il cid del browser è il cookie `abm_cid` (DevTools → Application → Cookies).

- [ ] **Step 6: Commit**

```powershell
git add static/js/app.js templates/_fragments/i18n_data.js
git commit -m "feat(abuse): messaggio neutro job_terminated nel 403 e nel progress, 7 lingue"
```

---

### Task 10: Documentazione

**Files:**
- Modify: `md_files/PARAMETRI_CONFIGURAZIONE.md` (nuova sezione env var + op di log)
- Modify: `CLAUDE.md` (tabella moduli, rate limiting, non tracciato da git: solo modifica locale)

- [ ] **Step 1: `PARAMETRI_CONFIGURAZIONE.md`**

Aggiungi una sezione (numerata in coda alle esistenti, stesso stile delle altre tabelle) con questo contenuto:

```markdown
## Moderazione anti-abuso della quota voci standard (`abuse_watch.py`)

Design: `docs/superpowers/specs/2026-09-03-quota-containment-design.md`. Dossier
comportamentale per gruppo (IP /24 hashato con `ABM_IP_SALT`, fallback cid) in
`ABM_DATA_DIR/_abuse_dossiers.json` (retention 60 giorni). Segnali: S1 quota
esaurita, S2 ≥2 cid, S3 ≥`ABM_ABUSE_GATE_DAILY` QUOTA_GATE/24h, S4
≥`ABM_ABUSE_CHARS_DAILY` caratteri/24h. Dal secondo segnale il giudice DeepSeek
(client di `generation_engine`, timeout 20s, 1 retry, fail-open) emette un
verdetto per cid. Kill in corsa e 403 pre-claim solo con
`verdict=abuse ∧ confidence ≥ soglia ∧ cid nello scope ∧ job non pagato ∧ voce
standard`. Op di log: `QUOTA_ABUSE_KILL`, `QUOTA_ABUSE_BLOCK`. Ripristino:
`POST /admin/api/abuse/clear/<gruppo>` (header `X-Admin-Token`).

| Variabile | Descrizione | Default | Sorgente |
|---|---|---|---|
| `ABM_ABUSE_KILL_ENABLE` | Interruttore di kill e 403 (`0` = solo giudizio in log e digest). Richiede anche `ABM_ADMIN_EMAIL` non vuoto. Al primo avvio con `1` i verdetti maturati in osservazione vengono azzerati. | `0` | `abuse_watch.kill_enabled` |
| `ABM_ABUSE_LLM_CONFIDENCE` | Soglia minima di confidenza del verdetto per kill e 403 | `0.9` | `abuse_watch.confidence_threshold` |
| `ABM_ABUSE_KEEP_HOURS` | Conservazione della work_dir (chunk inclusi) dei job uccisi, per il ripristino con riuso chunk. Floor 1. | `24` | `abuse_watch.keep_hours` |
| `ABM_ABUSE_GATE_DAILY` | Soglia `QUOTA_GATE`/24h del segnale S3. Floor 1. | `5` | `abuse_watch._gate_daily` |
| `ABM_ABUSE_CHARS_DAILY` | Soglia caratteri/24h del segnale S4 (quota mensile / 4). Floor 1. | `2500000` | `abuse_watch._chars_daily` |
| `ABM_ABUSE_VERDICT_TTL_DAYS` | Validità del verdetto persistito. Con kill spenta è forzata a 1 giorno. Floor 1. | `14` | `abuse_watch.verdict_ttl_sec` |
```

Aggiorna anche l'elenco delle op del business log (se presente nel file) con `QUOTA_ABUSE_KILL` e `QUOTA_ABUSE_BLOCK`.

- [ ] **Step 2: `CLAUDE.md`**

Nella tabella «Backend Modules» aggiungi la riga:

```markdown
| `abuse_watch.py` | Moderazione LLM dell'abuso della quota voci standard (modulo foglia). Dossier per gruppo IP /24 hashato con ripartizione per cid in `ABM_DATA_DIR/_abuse_dossiers.json`, segnali S1-S4, giudice DeepSeek (client di `generation_engine`, sole feature numeriche, fail-open), verdetto persistito per cid, coda a giudice singolo. `audiobook_app` rifiuta con 403 `job_terminated` i cid bloccati e uccide i job in corso via `cancelled` + `abuse_terminated` (work_dir conservata `ABM_ABUSE_KEEP_HOURS`); sezione «Casi di abuso» nel digest admin; ripristino `POST /admin/api/abuse/clear/<gruppo>`. Kill attiva solo con `ABM_ABUSE_KILL_ENABLE=1` e `ABM_ADMIN_EMAIL`. Spec: `docs/superpowers/specs/2026-09-03-quota-containment-design.md`. |
```

Nella tabella «Rate Limiting & Concurrency» aggiungi:

```markdown
| Moderazione anti-abuso quota standard | giudizio LLM dal 2° segnale; kill/403 solo `abuse ∧ conf ≥ 0.9 ∧ non pagato` (`ABM_ABUSE_KILL_ENABLE`, default 0) |
```

Nella tabella «Key Configuration» → «Limits & concurrency» aggiungi la riga `ABM_ABUSE_KILL_ENABLE | Kill e 403 della moderazione anti-abuso (0 = solo osservazione) | 0`.

- [ ] **Step 3: Suite completa e commit**

Run: `pytest test/ -q --tb=short`
Expected: tutti PASS (i test lenti/di rete già marcati skip restano skip)

```powershell
git add md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "docs(abuse): variabili ABM_ABUSE_* e modulo abuse_watch"
```

(`CLAUDE.md` non è tracciato: la modifica resta locale, mai `git add -f`.)

---

## Rollout (dopo il merge, fuori dal piano)

1. Deploy con `ABM_ABUSE_KILL_ENABLE=0`: dossier e giudizi in log e digest, nessuna kill. TTL verdetti forzato a 1 giorno.
2. Dopo alcuni digest senza `abuse` su client legittimi: `ABM_ABUSE_KILL_ENABLE=1` nell'unit systemd e restart (i verdetti di osservazione vengono azzerati all'avvio).
3. Blocklist manuale per i gruppi che insistono.

## Self-review

- **Copertura spec** — §1 API del modulo: Task 1-3 (`group_key`, `record_event` con `distinct_files`, `signals_for`, `needs_judgement` con cid nuovo, `set_verdict`/`verdict_for` con TTL e rivalutazione 25%, `is_blocked` con scope, `clear_verdict`, prompt con marker di innocenza e JSON con `scope`). §2 agganci: 403 pre-claim (Task 5), `record_event` dopo gate/block/claim/email (Task 5), worker in `_ensure_background_threads` con timeout 20s + 1 retry (Task 3/6), kill via flag (Task 6), ramo `_CancelledError` (Task 4), progress `job_terminated` (Task 5), digest (Task 8), cleanup `abuse_kept_until` (Task 7), ripristino admin (Task 7), kill disattivata senza `ABM_ADMIN_EMAIL` (Task 2 `kill_enabled`). §3 frontend (Task 9). §4 quota invariata: `free_tts_quota.py` non è toccato. Gestione errori: fail-open in ogni funzione (Task 1-3), `inconclusive`/bassa confidenza senza kill (Task 2/6), premium mai toccato (Task 5/6), work_dir già rimossa senza marcatore (Task 4). Rollout: `arm_on_startup` (Task 2/6), TTL 1 giorno in osservazione (Task 2). Test: i tre file della spec più `test_abuse_digest.py`.
- **Placeholder** — nessun TBD/TODO; ogni step di codice ha il codice.
- **Coerenza dei nomi** — `group_key(ip, cid)`, `record_event(group, cid, kind, data)`, `needs_judgement(group, cid)`, `is_blocked(group, cid)`, `set_verdict(group, verdict)`, `record_kill(group, cid, job_id)`, `record_block(group, cid)`, `digest_data(window_sec)`, `_process(group, cid, on_verdict)`, `start_worker(on_verdict)`, `_cancel_cleanup_workdir(job, job_id, work_dir, partial_audio_delivered)`, `_abuse_note(job_id, job, kind, **data)`, `_abuse_apply_verdict(group, verdict)`, `_abuse_keep_state(job, now)`, `_abuse_digest_data()`, `set_abuse_provider(fn)`, `_abuse_block_html()` usati con la stessa firma in tutti i task.
