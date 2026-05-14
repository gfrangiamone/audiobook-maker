"""
payment.py — Gestione pagamenti PayPal e voucher per Audiobook Maker.

Funzioni:
  - _paypal_available / _estimate_llm_cost_eur
  - _paypal_get_access_token / _paypal_create_order / _paypal_capture_order
  - _voucher_rl_check / _voucher_rl_record_result  (rate limiting)
  - _save_payments / _load_payments
  - _save_vouchers / _load_vouchers
  - _generate_voucher_code / _create_voucher
  - _voucher_remaining / _voucher_consume / _voucher_refund
  - _save_paid_opt_done / _load_paid_opt_done / _mark_paid_opt_done / _cleanup_paid_opt_done
  - _recover_orphaned_voucher_charges(jobs)  — jobs passato come parametro esplicito

Dipende solo dalla stdlib e da os.environ — nessun import da audiobook_app.
"""

import json
import os
import shutil
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# PayPal + payment config
# ---------------------------------------------------------------------------

PAYPAL_CLIENT_ID = os.environ.get("ABM_PAYPAL_CLIENT_ID", "").strip()
PAYPAL_SECRET = os.environ.get("ABM_PAYPAL_SECRET", "").strip()
PAYPAL_MODE = os.environ.get("ABM_PAYPAL_MODE", "sandbox").strip().lower()  # sandbox|live
PAYPAL_API_BASE = "https://api-m.sandbox.paypal.com" if PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com"
LLM_RATE_EUR_PER_MCHAR = float(os.environ.get("ABM_LLM_RATE_EUR_PER_MCHAR", "1.10").replace(",", "."))
LLM_FREE_THRESHOLD_EUR = float(os.environ.get("ABM_LLM_FREE_THRESHOLD_EUR", "0.50").replace(",", "."))
VOUCHER_EXPIRY_DAYS = int(os.environ.get("ABM_VOUCHER_EXPIRY_DAYS", "180"))
VOUCHER_BONUS_PERCENT = int(os.environ.get("ABM_VOUCHER_BONUS_PERCENT", "10"))
PAYMENT_RETENTION_DAYS = int(os.environ.get("ABM_PAYMENT_RETENTION_DAYS", "730"))  # 24 mesi GDPR

_paypal_token_cache = {"access_token": None, "expires_at": 0}


def _paypal_available():
    """True se PayPal e configurato."""
    return bool(PAYPAL_CLIENT_ID and PAYPAL_SECRET)


def _estimate_llm_cost_eur(char_count):
    """Stima il costo in EUR per ottimizzare N caratteri."""
    return round((char_count / 1_000_000.0) * LLM_RATE_EUR_PER_MCHAR, 2)


# ---------------------------------------------------------------------------
# File paths (derivati da ABM_DATA_DIR)
# ---------------------------------------------------------------------------

_DATA_DIR = Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data"))
_PAYMENTS_FILE = _DATA_DIR / "_payments.json"
_VOUCHERS_FILE = _DATA_DIR / "_vouchers.json"
_PAID_OPT_DONE_FILE = _DATA_DIR / "_paid_opt_done.json"
_PAID_JOBS_DONE_FILE = _DATA_DIR / "_paid_jobs_done.json"

# ---------------------------------------------------------------------------
# Payment/voucher state
# ---------------------------------------------------------------------------

_payments = {}   # order_id -> {amount_eur, email, job_id, captured_at, used, used_at?}
_vouchers = {}   # code -> {email, amount_eur, created_at, expires_at, used, used_at?, origin_order_id}
_payments_lock = threading.RLock()
_vouchers_lock = threading.RLock()

# Rate limit voucher_validate
# IP -> list[timestamps] (sliding window). Limiti: 5/min, 30/ora.
# Email -> (fail_count, lockout_until) dopo N fallimenti consecutivi.
_voucher_attempts_ip = {}
_voucher_attempts_email = {}
_voucher_rl_lock = threading.Lock()
VOUCHER_RL_PER_MIN = 5
VOUCHER_RL_PER_HOUR = 30
VOUCHER_EMAIL_FAIL_LIMIT = 10    # fallimenti consecutivi prima del lockout
VOUCHER_EMAIL_LOCKOUT_SEC = 900  # 15 minuti

# Tracking job pagati completati con successo (persistenza su disco)
_paid_opt_done: set = set()

# Unified paid jobs store (F4): list of {"job_id", "purpose", "ts"}
# All paid jobs (LLM optimization + Gemini TTS) are tracked here.
_paid_jobs_done: list = []
_paid_jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def _voucher_rl_check(ip, email):
    """Return (allowed, retry_after_sec, reason)."""
    now = time.time()
    with _voucher_rl_lock:
        # IP sliding window
        hits = _voucher_attempts_ip.get(ip, [])
        hits = [t for t in hits if now - t < 3600]
        last_min = [t for t in hits if now - t < 60]
        if len(last_min) >= VOUCHER_RL_PER_MIN:
            retry = 60 - int(now - last_min[0])
            _voucher_attempts_ip[ip] = hits
            return False, max(1, retry), "rate_limit_ip_minute"
        if len(hits) >= VOUCHER_RL_PER_HOUR:
            retry = 3600 - int(now - hits[0])
            _voucher_attempts_ip[ip] = hits
            return False, max(1, retry), "rate_limit_ip_hour"
        # Email lockout
        em = (email or "").lower().strip()
        if em:
            info = _voucher_attempts_email.get(em)
            if info and info.get("lockout_until", 0) > now:
                return False, int(info["lockout_until"] - now), "email_locked"
        # Record hit for IP — caller can trigger email-fail separately
        hits.append(now)
        _voucher_attempts_ip[ip] = hits
    return True, 0, None


def _voucher_rl_record_result(email, success):
    """Aggiorna contatore fallimenti per email; reset on success."""
    em = (email or "").lower().strip()
    if not em:
        return
    now = time.time()
    with _voucher_rl_lock:
        if success:
            _voucher_attempts_email.pop(em, None)
            return
        info = _voucher_attempts_email.get(em) or {"fail_count": 0, "lockout_until": 0}
        info["fail_count"] = info.get("fail_count", 0) + 1
        if info["fail_count"] >= VOUCHER_EMAIL_FAIL_LIMIT:
            info["lockout_until"] = now + VOUCHER_EMAIL_LOCKOUT_SEC
            info["fail_count"] = 0  # reset contatore dopo lockout
        _voucher_attempts_email[em] = info


# ---------------------------------------------------------------------------
# Persistence: payments
# ---------------------------------------------------------------------------

def _save_payments():
    try:
        with _payments_lock:
            with open(_PAYMENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(_payments, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[payments] Failed to save: {e}")


def _load_payments():
    global _payments
    if not _PAYMENTS_FILE.exists():
        return
    try:
        with open(_PAYMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Retention: drop payments older than PAYMENT_RETENTION_DAYS
        now = time.time()
        cutoff = now - PAYMENT_RETENTION_DAYS * 86400
        _payments = {k: v for k, v in data.items() if v.get("captured_at", 0) > cutoff}
        if len(data) != len(_payments):
            _save_payments()
        print(f"[payments] Loaded {len(_payments)} payment records")
    except Exception as e:
        print(f"[payments] Failed to load: {e}")


# ---------------------------------------------------------------------------
# Persistence: vouchers
# ---------------------------------------------------------------------------

def _save_vouchers():
    try:
        with _vouchers_lock:
            with open(_VOUCHERS_FILE, "w", encoding="utf-8") as f:
                json.dump(_vouchers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[vouchers] Failed to save: {e}")


def _load_vouchers():
    global _vouchers
    if not _VOUCHERS_FILE.exists():
        return
    try:
        with open(_VOUCHERS_FILE, "r", encoding="utf-8") as f:
            _vouchers = json.load(f)
        print(f"[vouchers] Loaded {len(_vouchers)} voucher records")
    except Exception as e:
        print(f"[vouchers] Failed to load: {e}")


# ---------------------------------------------------------------------------
# Voucher business logic
# ---------------------------------------------------------------------------

def _generate_voucher_code():
    """Generate a 12-char uppercase alphanumeric voucher code (no ambiguous chars)."""
    import secrets
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    while True:
        code = "-".join("".join(secrets.choice(chars) for _ in range(4)) for _ in range(3))
        if code not in _vouchers:
            return code


def _create_voucher(email, amount_eur, origin_order_id=None, origin_job_id=None,
                    kind="refund", note="", created_by="auto_refund",
                    expiry_days=None, apply_bonus=True, code=None):
    """Create a voucher.

    kind: "refund" (auto-emesso dopo fallimento pagato), "promo" (generato da admin),
          "gift" (regalo admin). Solo "refund" applica il bonus % predefinito.
    note: testo libero amministrativo (motivo/causale).
    created_by: "auto_refund" per l'emissione automatica, "admin" per CLI.
    expiry_days: None  ->  usa VOUCHER_EXPIRY_DAYS (refund). Gli admin possono passare un valore custom.
    apply_bonus: se False salva l'importo nominale (usato per promo/gift).
    code: se fornito, usa quel codice invece di generarne uno (utile per PROMO- prefix).
    """
    if code is None:
        code = _generate_voucher_code()
    now = time.time()
    if apply_bonus:
        bonus_amount = round(amount_eur * (1 + VOUCHER_BONUS_PERCENT / 100.0), 2)
    else:
        bonus_amount = round(float(amount_eur), 2)
    days = VOUCHER_EXPIRY_DAYS if expiry_days is None else int(expiry_days)
    _vouchers[code] = {
        "code": code,
        "email": (email or "").lower().strip(),
        "amount_eur": bonus_amount,
        "base_amount_eur": amount_eur,
        "remaining_eur": bonus_amount,   # Saldo residuo (decresce ad ogni uso)
        "uses": [],                       # list[{"job_id","amount_eur","at","remaining_after"}]
        "created_at": now,
        "expires_at": now + days * 86400,
        "used": False,                    # True solo quando saldo <= 0.01
        "used_at": None,
        "origin_order_id": origin_order_id,
        "origin_job_id": origin_job_id,
        "kind": kind,                # "refund" | "promo" | "gift"
        "note": (note or "")[:500],
        "created_by": created_by,    # "auto_refund" | "admin"
    }
    _save_vouchers()
    return code, bonus_amount


def _voucher_remaining(v: dict) -> float:
    """Saldo residuo del voucher. Gestisce record legacy privi di ``remaining_eur``:
    se esiste il flag ``used`` binario  ->  0 residuo; altrimenti l'importo originale.
    """
    if "remaining_eur" in v:
        try:
            return max(0.0, round(float(v["remaining_eur"]), 2))
        except (TypeError, ValueError):
            return 0.0
    # Legacy: nessun remaining_eur memorizzato
    if v.get("used"):
        return 0.0
    try:
        return round(float(v.get("amount_eur", 0) or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _voucher_consume(code: str, amount: float, job_id: str = "") -> float:
    """Scala ``amount`` EUR dal saldo del voucher ``code``. Ritorna il nuovo saldo
    residuo. Se il saldo scende sotto 0.01 EUR il voucher viene marcato ``used=True``.
    Solleva ``ValueError`` se il voucher non e spendibile o il saldo e insufficiente.

    Money-critical: the entire read-modify-write of ``remaining_eur`` must run
    under ``_vouchers_lock`` to prevent concurrent overspend of the pool.
    """
    with _vouchers_lock:
        v = _vouchers.get(code)
        if not v:
            raise ValueError("voucher not found")
        if v.get("expires_at", 0) <= time.time():
            raise ValueError("voucher expired")
        remaining = _voucher_remaining(v)
        # Arrotondamenti: se la differenza e <= 0.01 permettiamo lo spend (evita errori di 1 cent)
        if amount > remaining + 0.01:
            raise ValueError(f"insufficient balance: need {amount:.2f}, have {remaining:.2f}")
        spent = round(min(amount, remaining), 2)
        new_remaining = round(remaining - spent, 2)
        now = time.time()
        v["remaining_eur"] = new_remaining
        uses = v.get("uses")
        if not isinstance(uses, list):
            uses = []
        uses.append({
            "job_id": job_id,
            "amount_eur": spent,
            "at": now,
            "remaining_after": new_remaining,
        })
        v["uses"] = uses
        # Mark fully used solo quando il saldo e praticamente zero
        if new_remaining < 0.01:
            v["used"] = True
            v["used_at"] = now
        else:
            v["used"] = False
        _save_vouchers()
        return new_remaining


def _voucher_refund(code: str, amount: float, job_id: str = "", reason: str = "") -> float:
    """Ri-accredita ``amount`` EUR sul voucher ``code`` (operazione inversa a consume).
    Ritorna il nuovo saldo residuo. Se il voucher era marcato used, lo riattiva.
    Solleva ``ValueError`` se il voucher non esiste.
    """
    with _vouchers_lock:
        v = _vouchers.get(code)
        if not v:
            raise ValueError("voucher not found")
        remaining = _voucher_remaining(v)
        original = float(v.get("amount_eur", 0) or 0)
        new_remaining = round(min(remaining + amount, original), 2)
        now = time.time()
        v["remaining_eur"] = new_remaining
        uses = v.get("uses")
        if not isinstance(uses, list):
            uses = []
        uses.append({
            "job_id": job_id,
            "amount_eur": -round(amount, 2),  # negativo = refund
            "at": now,
            "remaining_after": new_remaining,
            "reason": reason,
        })
        v["uses"] = uses
        # Riattiva il voucher se aveva saldo e non e scaduto
        if new_remaining >= 0.01:
            v["used"] = False
            if "used_at" in v:
                del v["used_at"]
        _save_vouchers()
    print(f"[vouchers] Refund {amount:.2f} EUR -> {code} (new balance {new_remaining:.2f} EUR) reason={reason}")
    return new_remaining


# ---------------------------------------------------------------------------
# Paid optimization tracking
# ---------------------------------------------------------------------------

def _save_paid_opt_done():
    try:
        with open(_PAID_OPT_DONE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(_paid_opt_done), f)
    except Exception as e:
        print(f"[paid_opt_done] Failed to save: {e}")


def _load_paid_opt_done():
    global _paid_opt_done
    if not _PAID_OPT_DONE_FILE.exists():
        return
    try:
        with open(_PAID_OPT_DONE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _paid_opt_done = set(data) if isinstance(data, list) else set()
        print(f"[startup] Loaded {len(_paid_opt_done)} paid optimization completion record(s)")
    except Exception as e:
        print(f"[paid_opt_done] Failed to load: {e}")


def _mark_paid_opt_done(job_id: str):
    """DEPRECATED shim: routes legacy LLM opt completions to unified store."""
    _mark_paid_job_done(job_id, purpose="llm")


def _cleanup_paid_opt_done():
    """Rimuovi record se il set e troppo grande (non abbiamo timestamp nel set)."""
    if len(_paid_opt_done) > 1000:
        _paid_opt_done.clear()
        _save_paid_opt_done()


# ---------------------------------------------------------------------------
# F4: Unified paid jobs store with atomic migration
# ---------------------------------------------------------------------------

def _atomic_write_json(path, data):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)


def _migrate_paid_opt_to_paid_jobs():
    """One-shot startup migration: legacy _paid_opt_done.json -> _paid_jobs_done.json.
    Atomic + idempotent. All legacy records are tagged purpose='llm'.
    """
    if _PAID_JOBS_DONE_FILE.exists():
        return  # already migrated
    if not _PAID_OPT_DONE_FILE.exists():
        _atomic_write_json(_PAID_JOBS_DONE_FILE, [])
        return
    bak = _PAID_OPT_DONE_FILE.with_suffix(".json.pre_unify_bak")
    if not bak.exists():
        shutil.copy2(_PAID_OPT_DONE_FILE, bak)
    try:
        with open(_PAID_OPT_DONE_FILE, "r", encoding="utf-8") as f:
            legacy = json.load(f)
    except Exception as e:
        raise RuntimeError(f"FATAL migration: cannot read legacy _paid_opt_done.json: {e}")
    if not isinstance(legacy, list):
        raise RuntimeError(f"FATAL migration: legacy data not a list: {type(legacy)}")
    unified = [{"job_id": jid, "purpose": "llm", "ts": 0} for jid in legacy if jid]
    _atomic_write_json(_PAID_JOBS_DONE_FILE, unified)
    print(f"[startup] Migrated {len(unified)} record(s) to _paid_jobs_done.json")


def _load_paid_jobs_done():
    global _paid_jobs_done
    if not _PAID_JOBS_DONE_FILE.exists():
        _paid_jobs_done = []
        return
    try:
        with open(_PAID_JOBS_DONE_FILE, "r", encoding="utf-8") as f:
            _paid_jobs_done = json.load(f)
        print(f"[startup] Loaded {len(_paid_jobs_done)} paid job completion record(s)")
    except Exception as e:
        print(f"[paid_jobs_done] Load failed: {e}")
        _paid_jobs_done = []


def _save_paid_jobs_done():
    with _paid_jobs_lock:
        _atomic_write_json(_PAID_JOBS_DONE_FILE, list(_paid_jobs_done))


def _is_paid_job_done(job_id: str) -> bool:
    if not job_id:
        return False
    return any(r.get("job_id") == job_id for r in _paid_jobs_done)


def _recover_orphaned_voucher_charges(jobs):
    """Recovery all'avvio: cerca addebiti voucher recenti (ultime 2 ore) il cui
    job_id non e ne in memoria (``jobs``) ne tra quelli completati con successo
    (verificato via ``_is_paid_job_done`` sul nuovo store unificato
    ``_paid_jobs_done``, che copre sia LLM sia Gemini TTS). Questo copre il
    caso in cui il server e stato riavviato/crashato durante un'operazione a
    pagamento: il voucher era gia stato addebitato ma il job non e mai
    terminato.
    Ri-accredita automaticamente l'importo sul voucher.
    """
    cutoff = time.time() - 2 * 3600  # ultime 2 ore
    recovered = 0
    for code, v in _vouchers.items():
        uses = v.get("uses")
        if not isinstance(uses, list):
            continue
        for use in uses:
            # Solo addebiti (positivi), non refund (negativi)
            amt = float(use.get("amount_eur", 0) or 0)
            if amt <= 0:
                continue
            use_time = float(use.get("at", 0) or 0)
            if use_time < cutoff:
                continue
            use_job_id = use.get("job_id", "")
            if not use_job_id:
                continue
            # Se il job e completato con successo  ->  non rimborsare
            if _is_paid_job_done(use_job_id):
                continue
            # Se il job e ancora in memoria  ->  non rimborsare (non dovrebbe accadere al restart)
            if use_job_id in jobs:
                continue
            # Verifica che non sia gia stato rimborsato (cerca refund con stesso job_id)
            already_refunded = any(
                float(u.get("amount_eur", 0) or 0) < 0 and u.get("job_id") == use_job_id
                for u in uses
            )
            if already_refunded:
                continue
            try:
                _voucher_refund(
                    code, amt, job_id=use_job_id,
                    reason="Recovery avvio server: job orfano",
                )
                recovered += 1
            except Exception as e:
                print(f"[startup] Recovery failed for voucher {code} job {use_job_id}: {e}")
    if recovered:
        print(f"[startup] Recovered {recovered} orphaned voucher charge(s)")


# ---------------------------------------------------------------------------
# PayPal REST API v2
# ---------------------------------------------------------------------------

def _paypal_get_access_token():
    """Get OAuth2 access token (cached ~8h)."""
    import requests
    now = time.time()
    if _paypal_token_cache["access_token"] and _paypal_token_cache["expires_at"] > now + 60:
        return _paypal_token_cache["access_token"]
    if not _paypal_available():
        return None
    r = requests.post(
        f"{PAYPAL_API_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if r.status_code != 200:
        # Diagnostic info — don't leak the secret, but show ID prefix and mode
        cid_hint = (PAYPAL_CLIENT_ID[:6] + "\u2026" + PAYPAL_CLIENT_ID[-4:]) if len(PAYPAL_CLIENT_ID) > 12 else "(too short)"
        body = (r.text or "")[:300]
        raise RuntimeError(
            f"PayPal OAuth failed: HTTP {r.status_code} on {PAYPAL_API_BASE} "
            f"(mode={PAYPAL_MODE}, client_id={cid_hint}, secret_len={len(PAYPAL_SECRET)}). "
            f"Response: {body}. "
            f"Verifica che le credenziali siano dell'app {PAYPAL_MODE.upper()} "
            f"creata su https://developer.paypal.com/dashboard/applications/{PAYPAL_MODE}"
        )
    data = r.json()
    _paypal_token_cache["access_token"] = data["access_token"]
    _paypal_token_cache["expires_at"] = now + int(data.get("expires_in", 28800)) - 60
    return data["access_token"]


def _paypal_create_order(amount_eur, description, custom_id=None):
    """Create a PayPal Order. Returns dict with 'id' and 'status'."""
    import requests
    token = _paypal_get_access_token()
    if not token:
        raise RuntimeError("PayPal not configured")
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": "EUR", "value": f"{amount_eur:.2f}"},
            "description": description[:127],
        }],
        "application_context": {
            "brand_name": "Audiobook Maker",
            "user_action": "PAY_NOW",
            "shipping_preference": "NO_SHIPPING",
        },
    }
    if custom_id:
        payload["purchase_units"][0]["custom_id"] = custom_id[:127]
    r = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# F3: Payment token consumption (voucher or captured PayPal order)
# ---------------------------------------------------------------------------

def _paypal_order_is_captured(token: str) -> bool:
    """True if token is a captured PayPal order not yet consumed."""
    if not token:
        return False
    pay = _payments.get(token)
    return bool(pay) and not pay.get("used", False)


def _paypal_amount_matches(token: str, amount_eur: float, tolerance: float = 0.05) -> bool:
    """True if captured order amount >= amount_eur (with tolerance for rounding)."""
    pay = _payments.get(token)
    if not pay:
        return False
    return float(pay.get("amount_eur", 0) or 0) + tolerance >= float(amount_eur)


def _mark_paid_job_done(job_id: str, purpose: str = "gemini"):
    """Append a completion record. Persists to disk."""
    if not job_id:
        return
    with _paid_jobs_lock:
        _paid_jobs_done.append({"job_id": job_id, "purpose": purpose, "ts": time.time()})
    _save_paid_jobs_done()


def consume_payment_token(token: str, amount_eur: float, job_id: str,
                          purpose: str = "gemini") -> str:
    """Consume a payment token (voucher or captured PayPal order).

    Returns the method used ("voucher" or "paypal").
    Raises ValueError if invalid / insufficient.
    """
    if not token:
        raise ValueError("missing payment_token")
    # Try voucher first
    if token in _vouchers:
        _voucher_consume(token, amount_eur, job_id=job_id)
        _mark_paid_job_done(job_id, purpose=purpose)
        return "voucher"
    # Then PayPal captured order — atomic check-and-set under _payments_lock
    # to prevent double-spend under concurrent requests.
    with _payments_lock:
        pay = _payments.get(token)
        if pay and not pay.get("used", False):
            if not _paypal_amount_matches(token, amount_eur):
                raise ValueError("paypal amount mismatch")
            # Mark order as used INSIDE the lock so other threads see used=True
            pay["used"] = True
            pay["used_at"] = time.time()
            pay["used_for_job"] = job_id
            try:
                _save_payments()
            except Exception:
                pass  # best-effort persistence
            _mark_paid_job_done(job_id, purpose=purpose)
            return "paypal"
    raise ValueError("invalid payment_token")


def _paypal_capture_order(order_id):
    """Capture a previously-approved order. Returns captured order dict."""
    import requests
    token = _paypal_get_access_token()
    if not token:
        raise RuntimeError("PayPal not configured")
    r = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()
