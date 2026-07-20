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

Dipende solo dalla stdlib, da os.environ e dal modulo foglia community_store
(primitivo atomic_write_json) — nessun import da audiobook_app.
"""

import json
import os
import shutil
import threading
import time
from pathlib import Path

# Primitivo condiviso di scrittura JSON atomica (tmp + fsync + os.replace).
# L'alias conserva il nome storico usato da call-site e test.
from community_store import atomic_write_json as _atomic_write_json

# ---------------------------------------------------------------------------
# PayPal + payment config
# ---------------------------------------------------------------------------

PAYPAL_CLIENT_ID = os.environ.get("ABM_PAYPAL_CLIENT_ID", "").strip()
PAYPAL_SECRET = os.environ.get("ABM_PAYPAL_SECRET", "").strip()
# Fail-fast: quando PayPal e' configurato, ABM_PAYPAL_MODE deve essere esplicito
# (sandbox|live). Un default "sandbox" silenzioso in produzione dirotterebbe
# pagamenti reali su test endpoint con conseguente perdita di revenue.
_PAYPAL_MODE_RAW = os.environ.get("ABM_PAYPAL_MODE", "").strip().lower()
if PAYPAL_CLIENT_ID and not _PAYPAL_MODE_RAW:
    raise RuntimeError(
        "ABM_PAYPAL_MODE non impostato. Quando ABM_PAYPAL_CLIENT_ID e' "
        "configurato, devi settare esplicitamente ABM_PAYPAL_MODE=sandbox "
        "oppure ABM_PAYPAL_MODE=live."
    )
if _PAYPAL_MODE_RAW and _PAYPAL_MODE_RAW not in ("sandbox", "live"):
    raise RuntimeError(
        f"ABM_PAYPAL_MODE invalido: {_PAYPAL_MODE_RAW!r} "
        f"(valori ammessi: 'sandbox', 'live')"
    )
PAYPAL_MODE = _PAYPAL_MODE_RAW or "sandbox"
PAYPAL_API_BASE = "https://api-m.sandbox.paypal.com" if PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com"
if PAYPAL_CLIENT_ID:
    print(f"[payment] PayPal configured: mode={PAYPAL_MODE} base={PAYPAL_API_BASE}")
LLM_RATE_EUR_PER_MCHAR = float(os.environ.get("ABM_LLM_RATE_EUR_PER_MCHAR", "1.10").replace(",", "."))
LLM_FREE_THRESHOLD_EUR = float(os.environ.get("ABM_LLM_FREE_THRESHOLD_EUR", "0.50").replace(",", "."))
# Costo provider LLM per l'OTTIMIZZAZIONE AI del testo (base costo audit
# /admin/audit-premium tab "AI Optimization"). Coppia unica input/output EUR
# per 1M token. Default = listino DeepSeek deepseek-chat (cache-miss):
# BASE DA VERIFICARE/AGGIORNARE se il modello o il listino cambiano.
# Accettano virgola decimale.
LLM_COST_IN_EUR_PER_MTOK = float(
    os.environ.get("ABM_LLM_COST_IN_EUR_PER_MTOK", "0.26").replace(",", "."))
LLM_COST_OUT_EUR_PER_MTOK = float(
    os.environ.get("ABM_LLM_COST_OUT_EUR_PER_MTOK", "1.04").replace(",", "."))
# Traduzione libro: €/M caratteri input e costo minimo (floor sul totale,
# applicato solo quando si paga). Accettano virgola decimale.
TRANSLATE_RATE_EUR_PER_MCHAR = float(
    os.environ.get("ABM_TRANSLATE_COST", "3.0").replace(",", "."))
TRANSLATE_MIN_COST_EUR = float(
    os.environ.get("ABM_TRANSLATE_MIN_COST", "1.5").replace(",", "."))
# Costo provider LLM per la traduzione (base costo audit /admin/audit-translations).
# Coppia unica input/output EUR per 1M token, valida a prescindere dal backend
# (Vertex/DeepSeek). Default = listino Gemini 2.5 Flash (backend Vertex di
# prod): BASE DA VERIFICARE/AGGIORNARE se il modello o il listino cambiano.
# Accettano virgola decimale.
TRANSLATE_COST_IN_EUR_PER_MTOK = float(
    os.environ.get("ABM_TRANSLATE_COST_IN_EUR_PER_MTOK", "0.28").replace(",", "."))
TRANSLATE_COST_OUT_EUR_PER_MTOK = float(
    os.environ.get("ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK", "2.30").replace(",", "."))
VOUCHER_EXPIRY_DAYS = int(os.environ.get("ABM_VOUCHER_EXPIRY_DAYS", "180"))
VOUCHER_BONUS_PERCENT = int(os.environ.get("ABM_VOUCHER_BONUS_PERCENT", "10"))
PAYMENT_RETENTION_DAYS = int(os.environ.get("ABM_PAYMENT_RETENTION_DAYS", "730"))  # 24 mesi GDPR
# Auto-refund di capture PayPal incassati ma MAI consumati (used=False): quando il
# job pagato viene smaltito senza che la traduzione/ottimizzazione sia mai partita
# (es. capture-senza-avvio per redirect mobile interrotto), emette un voucher di
# rimborso all'email del pagante. Se False, marca solo `needs_manual_refund` e
# lascia all'admin il rimborso PayPal manuale.
AUTO_REFUND_UNUSED_CAPTURES = (
    os.environ.get("ABM_AUTO_REFUND_UNUSED_CAPTURES", "true").strip().lower()
    in ("1", "true", "yes", "on"))
# Età minima di un capture non consumato prima di considerarlo "abbandonato"
# (per detection/alert/auto-refund). Un capture appena fatto può essere ancora
# in attesa che parta /api/translate: non va toccato subito.
UNUSED_CAPTURE_MIN_AGE_SEC = int(
    os.environ.get("ABM_UNUSED_CAPTURE_MIN_AGE_SEC", "1800"))  # 30 min

_paypal_token_cache = {"access_token": None, "expires_at": 0}


def _paypal_available():
    """True se PayPal e configurato."""
    return bool(PAYPAL_CLIENT_ID and PAYPAL_SECRET)


def _estimate_llm_cost_eur(char_count):
    """Stima il costo in EUR per ottimizzare N caratteri."""
    return round((char_count / 1_000_000.0) * LLM_RATE_EUR_PER_MCHAR, 2)


def _estimate_translation_cost_eur(char_count, optimize=False):
    """Stima costo traduzione (+ eventuale ottimizzazione AI integrata).

    raw = chars/1M × TRANSLATE_RATE (+ chars/1M × LLM_RATE se optimize).
    Se raw ≤ LLM_FREE_THRESHOLD_EUR → gratis (due=0).
    Altrimenti due = max(raw, TRANSLATE_MIN_COST_EUR) — floor sul totale.
    """
    raw = (char_count / 1_000_000.0) * TRANSLATE_RATE_EUR_PER_MCHAR
    if optimize:
        raw += (char_count / 1_000_000.0) * LLM_RATE_EUR_PER_MCHAR
    raw = round(raw, 2)
    requires = raw > LLM_FREE_THRESHOLD_EUR
    due = round(max(raw, TRANSLATE_MIN_COST_EUR), 2) if requires else 0.0
    return {
        "chars": char_count,
        "raw_eur": raw,
        "due_eur": due,
        "requires_payment": requires,
        "rate_eur_per_mchar": TRANSLATE_RATE_EUR_PER_MCHAR,
        "min_cost_eur": TRANSLATE_MIN_COST_EUR,
        "free_threshold_eur": LLM_FREE_THRESHOLD_EUR,
        "optimize": bool(optimize),
    }


def _translation_provider_cost_eur(prompt_tokens, completion_tokens):
    """Costo LLM stimato (EUR) dai token reali di una traduzione.

    costo = in/1M × RATE_IN + out/1M × RATE_OUT. Coppia unica in/out; il
    backend effettivo (vertex/apikey) e' registrato a parte nel record audit.
    """
    ci = (prompt_tokens or 0) / 1_000_000.0 * TRANSLATE_COST_IN_EUR_PER_MTOK
    co = (completion_tokens or 0) / 1_000_000.0 * TRANSLATE_COST_OUT_EUR_PER_MTOK
    return round(ci + co, 6)


def _optimization_provider_cost_eur(prompt_tokens, completion_tokens):
    """Costo LLM stimato (EUR) dai token reali di un'ottimizzazione AI del testo.

    costo = in/1M × LLM_COST_IN + out/1M × LLM_COST_OUT. Speculare a
    _translation_provider_cost_eur ma con le tariffe dell'ottimizzazione.
    """
    ci = (prompt_tokens or 0) / 1_000_000.0 * LLM_COST_IN_EUR_PER_MTOK
    co = (completion_tokens or 0) / 1_000_000.0 * LLM_COST_OUT_EUR_PER_MTOK
    return round(ci + co, 6)


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

# Pending orders: tracker in-memory degli ordini PayPal creati ma non ancora
# capturati. Serve per amount reconciliation (confronto fra l'amount con cui
# l'ordine e' stato creato e quello restituito da PayPal alla cattura).
# Cleanup automatico oltre PENDING_ORDER_TTL_SEC.
_pending_orders = {}
_pending_orders_lock = threading.Lock()
PENDING_ORDER_TTL_SEC = 60 * 60  # 1 ora

# Capture lock: serializza il flusso check-idempotency + capture + store per
# evitare race condition con due richieste capture parallele sullo stesso order.
# Hold time massimo: una chiamata HTTP a PayPal (~secondi), accettabile vista
# la frequenza ridotta dei capture.
_capture_lock = threading.Lock()

# Rate limit voucher_validate
# IP -> list[timestamps] (sliding window). Limiti: 5/min, 30/ora.
# Email -> (fail_count, lockout_until) dopo N fallimenti consecutivi.
# Global -> deque ts di TUTTI i tentativi (safety net contro distributed scan).
_voucher_attempts_ip = {}
_voucher_attempts_email = {}
_voucher_attempts_global: list = []
_voucher_rl_lock = threading.Lock()
VOUCHER_RL_PER_MIN = 5
VOUCHER_RL_PER_HOUR = 30
VOUCHER_EMAIL_FAIL_LIMIT = 10    # fallimenti consecutivi prima del lockout
VOUCHER_EMAIL_LOCKOUT_SEC = 900  # 15 minuti
# Global burst cap: ~100/min totali su tutto il processo bloccano un attacker
# con rotating IP e generated emails. Soglie override-abili via env.
VOUCHER_GLOBAL_PER_MIN = int(os.environ.get("ABM_VOUCHER_GLOBAL_PER_MIN", "100"))
VOUCHER_GLOBAL_PER_HOUR = int(os.environ.get("ABM_VOUCHER_GLOBAL_PER_HOUR", "1000"))

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
    global _voucher_attempts_global
    now = time.time()
    with _voucher_rl_lock:
        # Global burst safety net (taglia attacker con rotating IP+email)
        _voucher_attempts_global = [t for t in _voucher_attempts_global if now - t < 3600]
        gmin = [t for t in _voucher_attempts_global if now - t < 60]
        if len(gmin) >= VOUCHER_GLOBAL_PER_MIN:
            retry = 60 - int(now - gmin[0])
            return False, max(1, retry), "rate_limit_global_minute"
        if len(_voucher_attempts_global) >= VOUCHER_GLOBAL_PER_HOUR:
            retry = 3600 - int(now - _voucher_attempts_global[0])
            return False, max(1, retry), "rate_limit_global_hour"
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
        # Record hit for IP + global — caller can trigger email-fail separately
        hits.append(now)
        _voucher_attempts_ip[ip] = hits
        _voucher_attempts_global.append(now)
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
            _atomic_write_json(_PAYMENTS_FILE, _payments, indent=2)
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
            _atomic_write_json(_VOUCHERS_FILE, _vouchers, indent=2)
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


def has_refund_for_job(job_id: str, payment_token: str = "") -> bool:
    """True se esiste gia' una traccia PERSISTENTE di refund per il job:
    - un voucher di rimborso emesso con origin_job_id == job_id (path PayPal,
      filtrato anche su origin_order_id se ``payment_token`` e' noto), o
    - riaccrediti su voucher (uses con amount_eur negativo e stesso job_id)
      in numero >= degli addebiti per lo stesso job (un re-pagamento legittimo
      dello stesso job dopo un refund resta quindi rimborsabile).

    Guard idempotente money-critical: il flag in-memory job["refund_done"] si
    perde al restart (incidente 2026-06: recovery ri-esegue job gia' rimborsati
    e un secondo cancel/error duplicherebbe il rimborso).
    """
    if not job_id:
        return False
    tok = (payment_token or "").strip()
    with _vouchers_lock:
        # Path PayPal: voucher di rimborso gia' emesso per questo job/ordine.
        for v in _vouchers.values():
            if v.get("kind") != "refund" or v.get("origin_job_id") != job_id:
                continue
            if tok and v.get("origin_order_id") and v.get("origin_order_id") != tok:
                continue
            return True
        # Path voucher: confronta addebiti vs riaccrediti per il job.
        charged = refunded = 0
        for code, v in _vouchers.items():
            if tok and code != tok:
                continue
            uses = v.get("uses")
            if not isinstance(uses, list):
                continue
            for u in uses:
                if u.get("job_id") != job_id:
                    continue
                try:
                    amt = float(u.get("amount_eur", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if amt > 0:
                    charged += 1
                elif amt < 0:
                    refunded += 1
        return refunded > 0 and refunded >= charged


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
        _atomic_write_json(_PAID_OPT_DONE_FILE, list(_paid_opt_done))
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
    resp = r.json()
    order_id = resp.get("id")
    if order_id:
        _register_pending_order(order_id, amount_eur, purpose=(custom_id or ""))
    return resp


def _register_pending_order(order_id, amount_requested_eur, purpose=""):
    """Registra un ordine PayPal appena creato per amount reconciliation alla
    cattura. Cleanup automatico delle voci stantie (oltre PENDING_ORDER_TTL_SEC).
    """
    now = time.time()
    cutoff = now - PENDING_ORDER_TTL_SEC
    with _pending_orders_lock:
        for oid in list(_pending_orders.keys()):
            if _pending_orders[oid].get("created_at", 0) < cutoff:
                del _pending_orders[oid]
        _pending_orders[order_id] = {
            "amount_requested_eur": round(float(amount_requested_eur), 2),
            "created_at": now,
            "purpose": purpose,
        }


def _get_pending_amount(order_id):
    """Ritorna amount richiesto al create, oppure None se non tracciato (es.
    server restart fra create e capture, oppure TTL scaduto).
    """
    with _pending_orders_lock:
        rec = _pending_orders.get(order_id)
        return float(rec["amount_requested_eur"]) if rec else None


def _consume_pending_order(order_id):
    """Rimuove l'ordine dal tracker pending (chiamato dopo cattura riuscita)."""
    with _pending_orders_lock:
        _pending_orders.pop(order_id, None)


# ---------------------------------------------------------------------------
# F3: Payment token consumption (voucher or captured PayPal order)
# ---------------------------------------------------------------------------

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


def email_for_token(token: str) -> str:
    """Best-effort: email associata a un payment token (voucher o PayPal order).

    Restituisce stringa vuota se il token non e' noto o non ha email. Funziona
    anche DOPO il consumo del token (sia il voucher sia l'ordine PayPal restano
    nei rispettivi store, marcati come usati/scalati). Usata per registrare il
    job pagato in modalita' batch (notifica + protezione heartbeat).
    """
    if not token:
        return ""
    v = _vouchers.get(token)
    if v:
        return (v.get("email") or "").strip().lower()
    with _payments_lock:
        pay = _payments.get(token)
        if pay:
            return (pay.get("email") or "").strip().lower()
    return ""


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


class CaptureAmountMismatchError(ValueError):
    """Capture amount non corrisponde a quanto creato (price tampering)."""


class DuplicateJobCaptureError(ValueError):
    """Il job ha gia' un capture PayPal incassato E consumato: catturare un
    secondo ordine sarebbe un doppio addebito. Sollevata PRIMA di chiamare
    l'API di capture, cosi' l'ordine approvato-ma-non-catturato si auto-annulla
    in PayPal (nessun secondo addebito). Vedi incidente doppio pagamento
    K1Rpn-x0fmaylsjKYGdftg (2026-07)."""


def capture_and_store_order(order_id: str, job_id: str = "",
                            amount_tolerance: float = 0.01):
    """Cattura un ordine PayPal in modo atomico con amount reconciliation.

    Acquisisce ``_capture_lock`` per tutto il flusso (idempotency check ->
    capture API -> validazione amount -> store) per evitare race condition
    su capture concorrenti dello stesso ``order_id``.

    Ritorna dict con: amount_eur, email, capture_id, captured_at, already_captured.

    Raise:
      - ``ValueError`` su input invalido o capture rifiutata da PayPal
      - ``CaptureAmountMismatchError`` se l'amount catturato differisce da quello
        registrato al create oltre la tolleranza (price tampering defense).
    """
    if not order_id:
        raise ValueError("missing order_id")

    with _capture_lock:
        # Idempotency: se gia' capturato, ritorna lo stato salvato
        with _payments_lock:
            pay = _payments.get(order_id)
        if pay:
            return {
                "order_id": order_id,
                "amount_eur": pay.get("amount_eur", 0),
                "email": pay.get("email", ""),
                "capture_id": pay.get("capture_id", ""),
                "captured_at": pay.get("captured_at", 0),
                "already_captured": True,
            }

        # Idempotency a livello JOB (anti doppio-pagamento). Se il job ha gia'
        # un capture incassato con order_id DIVERSO, questo e' un secondo ordine
        # nato da un ri-click del bottone PayPal prima della conferma: NON lo
        # catturiamo. L'ordine approvato-ma-non-catturato si auto-annulla in
        # PayPal (nessun secondo addebito).
        #   - capture esistente NON consumato -> riusa quel token (il flusso
        #     prosegue col pagamento gia' incassato).
        #   - capture esistente gia' consumato -> job pagato/in corso ->
        #     DuplicateJobCaptureError (il frontend mostra "gia' pagato").
        # Serializzato da _capture_lock: due capture concorrenti sullo stesso
        # job (order_id diversi) non possono superare entrambi il guard.
        if job_id:
            with _payments_lock:
                existing = None
                for oid, p in _payments.items():
                    if (isinstance(p, dict) and oid != order_id
                            and (p.get("job_id", "") or "") == job_id
                            and p.get("captured_at")):
                        existing = (oid, p)
                        if not p.get("used"):
                            break  # preferisci un capture ancora consumabile
            if existing is not None:
                eoid, ep = existing
                if ep.get("used"):
                    raise DuplicateJobCaptureError(
                        f"job {job_id} already has a consumed capture ({eoid}); "
                        f"refusing duplicate capture of order {order_id}")
                print(f"[paypal] duplicate capture for job {job_id}: reusing "
                      f"already-captured order {eoid}, skipping capture of {order_id}")
                return {
                    "order_id": eoid,
                    "amount_eur": ep.get("amount_eur", 0),
                    "email": ep.get("email", ""),
                    "capture_id": ep.get("capture_id", ""),
                    "captured_at": ep.get("captured_at", 0),
                    "already_captured": True,
                    "duplicate_skipped_order_id": order_id,
                }

        # Capture via PayPal API
        captured = _paypal_capture_order(order_id)

        purchase_units = captured.get("purchase_units", [])
        if not purchase_units:
            raise ValueError("invalid capture response: no purchase_units")
        pu = purchase_units[0]
        captures = pu.get("payments", {}).get("captures", [])
        if not captures or captures[0].get("status") not in ("COMPLETED", "PENDING"):
            raise ValueError("payment not completed")
        cap = captures[0]
        try:
            amount_eur = float(cap.get("amount", {}).get("value", "0"))
        except (TypeError, ValueError):
            raise ValueError("invalid captured amount")

        # Amount reconciliation: confronto con quanto registrato al create.
        # Se pending non disponibile (server restart fra create e capture),
        # log warning e accetta l'amount catturato (graceful degradation).
        expected = _get_pending_amount(order_id)
        if expected is not None:
            if abs(amount_eur - expected) > amount_tolerance:
                raise CaptureAmountMismatchError(
                    f"capture amount {amount_eur:.2f} != requested {expected:.2f} "
                    f"(order {order_id})"
                )
        else:
            print(f"[paypal] WARN capture without pending record: order={order_id} "
                  f"amount={amount_eur:.2f} (server restart or expired TTL)")

        payer = captured.get("payer", {})
        email = (payer.get("email_address") or "").lower().strip()

        with _payments_lock:
            # Re-check sotto _payments_lock (defense-in-depth: il _capture_lock
            # gia' serializza, ma garantiamo coerenza completa con altri reader)
            if order_id in _payments:
                pay = _payments[order_id]
                return {
                    "amount_eur": pay.get("amount_eur", 0),
                    "email": pay.get("email", ""),
                    "capture_id": pay.get("capture_id", ""),
                    "captured_at": pay.get("captured_at", 0),
                    "already_captured": True,
                }
            now = time.time()
            _payments[order_id] = {
                "order_id": order_id,
                "amount_eur": amount_eur,
                "amount_requested_eur": expected if expected is not None else amount_eur,
                "email": email,
                "job_id": job_id,
                "captured_at": now,
                "used": False,
                "used_at": None,
                "capture_id": cap.get("id", ""),
            }
            try:
                _save_payments()
            except Exception as e:
                print(f"[paypal] save_payments failed (post-capture): {e}")

        _consume_pending_order(order_id)

        return {
            "order_id": order_id,
            "amount_eur": amount_eur,
            "email": email,
            "capture_id": cap.get("id", ""),
            "captured_at": _payments[order_id]["captured_at"],
            "already_captured": False,
        }


# ---------------------------------------------------------------------------
# Capture PayPal incassati ma mai consumati (used=False) — detection & refund
# ---------------------------------------------------------------------------
# Difetto storico: un ordine PayPal viene catturato (PAYMENT_CAPTURED, used=False)
# ma la chiamata che lo consuma (/api/translate, /api/optimize, /api/generate)
# non parte mai — tipicamente per un redirect mobile interrotto. Il job resta in
# `analyzed`, viene poi smaltito dalla cleanup "stale analyzed" e il capture
# rimane orfano in _payments.json: cliente addebitato, nessun servizio, nessun
# rimborso. Le funzioni sotto rilevano e rimborsano questi capture.

def iter_unused_captures(min_age_sec=0, now=None):
    """Elenca i capture PayPal incassati ma NON consumati (`used` falsy).

    Un record è incluso se ha `captured_at` valorizzato, `used` falsy e (se
    `min_age_sec` > 0) un'età >= min_age_sec. Salta i record già marcati per
    rimborso manuale che non vogliamo ri-segnalare? No: vengono inclusi finché
    `used` è falsy, così l'admin continua a vederli finché non agisce.

    Ritorna lista di dict: order_id, amount_eur, email, job_id, captured_at,
    age_sec, capture_id, needs_manual_refund.
    """
    if now is None:
        now = time.time()
    out = []
    with _payments_lock:
        items = list(_payments.items())
    for oid, pay in items:
        if not isinstance(pay, dict):
            continue
        if pay.get("used"):
            continue
        cap_at = pay.get("captured_at")
        if not cap_at:
            continue
        age = now - float(cap_at)
        if min_age_sec and age < min_age_sec:
            continue
        out.append({
            "order_id": oid,
            "amount_eur": float(pay.get("amount_eur", 0) or 0),
            "email": (pay.get("email") or "").strip(),
            "job_id": pay.get("job_id", "") or "",
            "captured_at": float(cap_at),
            "age_sec": age,
            "capture_id": pay.get("capture_id", "") or "",
            "needs_manual_refund": bool(pay.get("needs_manual_refund")),
        })
    out.sort(key=lambda r: r["captured_at"])
    return out


def refund_unused_capture(order_id, reason="", force=False):
    """Rimborsa un singolo capture PayPal incassato ma non consumato.

    Comportamento (money-critical, idempotente):
      - Se l'ordine non esiste o è già `used` → no-op (ritorna None).
      - Se `AUTO_REFUND_UNUSED_CAPTURES` (o `force=True`) ed esiste l'email del
        pagante → emette un voucher di rimborso (kind="refund", bonus standard),
        marca l'ordine `used=True` con causale, salva. Idempotente: un secondo
        giro trova `used=True` e non fa nulla.
      - Se manca l'email (impossibile emettere voucher) → marca
        `needs_manual_refund=True` SENZA consumare l'ordine, così resta visibile
        ai report finché l'admin non emette il rimborso PayPal manuale.
      - Se auto-refund disattivo e non `force` → marca `needs_manual_refund=True`
        e lascia all'admin.

    Ritorna dict {order_id, amount_eur, email, job_id, voucher_code, manual} o None.
    """
    with _payments_lock:
        pay = _payments.get(order_id)
        if not pay or not isinstance(pay, dict):
            return None
        if pay.get("used"):
            return None
        amount = float(pay.get("amount_eur", 0) or 0)
        email = (pay.get("email") or "").strip().lower()
        job_id = pay.get("job_id", "") or ""

    do_voucher = (AUTO_REFUND_UNUSED_CAPTURES or force) and bool(email) and amount > 0
    voucher_code = None

    if do_voucher:
        # _create_voucher prende il proprio lock (_vouchers_lock): chiamata fuori
        # da _payments_lock per evitare lock-ordering inconsistente.
        voucher_code, _ = _create_voucher(
            email, amount, origin_order_id=order_id, origin_job_id=job_id,
            kind="refund",
            note=f"auto-refund capture non consumato ({reason})"[:500],
            created_by="auto_refund",
        )

    with _payments_lock:
        pay = _payments.get(order_id)
        if not pay:
            return None
        if pay.get("used"):
            # Race: consumato/rimborsato nel frattempo. Se avevamo appena emesso
            # un voucher è un caso patologico (consume + refund concorrenti); lo
            # logghiamo ma non ritocchiamo lo stato.
            if voucher_code:
                print(f"[payment] WARN refund_unused_capture race: order {order_id} "
                      f"diventato used dopo emissione voucher {voucher_code}")
            return None
        now = time.time()
        if voucher_code:
            pay["used"] = True
            pay["used_at"] = now
            pay["used_for"] = "auto_refund_unused"
            pay["refund_reason"] = (reason or "")[:200]
            pay["refund_voucher"] = voucher_code
            pay.pop("needs_manual_refund", None)
            manual = False
        else:
            # Nessun voucher emesso (no email / auto-refund off): segnala manuale.
            pay["needs_manual_refund"] = True
            pay["refund_reason"] = (reason or "")[:200]
            manual = True
        try:
            _save_payments()
        except Exception as e:
            print(f"[payment] save_payments failed (refund_unused_capture): {e}")

    return {
        "order_id": order_id,
        "amount_eur": amount,
        "email": email,
        "job_id": job_id,
        "voucher_code": voucher_code,
        "manual": manual,
    }


def refund_unused_captures_for_job(job_id, reason=""):
    """Rimborsa tutti i capture non consumati legati a `job_id`.

    Usato dalla cleanup del job: quando un job pagato viene smaltito senza che il
    servizio sia partito, ogni capture orfano viene rimborsato (o segnalato per
    rimborso manuale). Ritorna la lista dei risultati (dict di
    `refund_unused_capture`, esclusi i no-op).
    """
    if not job_id:
        return []
    with _payments_lock:
        order_ids = [
            oid for oid, pay in _payments.items()
            if isinstance(pay, dict) and not pay.get("used")
            and (pay.get("job_id", "") or "") == job_id
            and pay.get("captured_at")
        ]
    results = []
    for oid in order_ids:
        try:
            res = refund_unused_capture(oid, reason=reason)
            if res:
                results.append(res)
        except Exception as e:
            print(f"[payment] refund_unused_captures_for_job error order={oid}: {e}")
    return results


def settle_capture_consumed(order_id, job_id="", reason=""):
    """Marca `used=True` un capture PayPal incassato ma non consumato, SENZA
    rimborso: il servizio è stato erogato (o sta per esserlo), quindi il denaro
    è dovuto.

    Usato per correggere il falso positivo del rilevatore di capture orfani su
    job realmente consegnati (traduzione/ottimizzazione andata a buon fine ma
    il mark-consume non è mai avvenuto — es. divergenza di stima frontend/backend).
    Idempotente: un ordine già `used` è no-op. Ritorna dict
    {order_id, amount_eur, email} o None.
    """
    if not order_id:
        return None
    with _payments_lock:
        pay = _payments.get(order_id)
        if not isinstance(pay, dict):
            return None
        if pay.get("used"):
            return None
        if not pay.get("captured_at"):
            return None
        pay["used"] = True
        pay["used_at"] = time.time()
        pay["used_for"] = "delivered_settle"
        if job_id:
            pay["used_for_job"] = job_id
        pay["settle_reason"] = (reason or "")[:200]
        pay.pop("needs_manual_refund", None)
        res = {
            "order_id": order_id,
            "amount_eur": float(pay.get("amount_eur", 0) or 0),
            "email": (pay.get("email") or "").strip().lower(),
        }
        try:
            _save_payments()
        except Exception as e:
            print(f"[payment] save_payments failed (settle_capture_consumed): {e}")
    return res


def settle_delivered_captures_for_job(job_id, reason=""):
    """Riconcilia i capture non consumati di un job il cui servizio risulta
    EROGATO. Contraltare di `refund_unused_captures_for_job` (lì il job è stato
    smaltito senza consegna → rimborso).

    Distingue due sotto-casi, perché un job consegnato può avere piu' di un
    capture (doppio pagamento da ri-click PayPal, incidente K1Rpn 2026-07):

      - Il job ha GIA' un capture consumato (`used=True`): il servizio è coperto
        da quello. Ogni ULTERIORE capture non consumato è un DOPPIO ADDEBITO
        reale → `refund_unused_capture(force=True)` (voucher o manual refund),
        NON incasso.
      - Nessun capture consumato ma servizio erogato: vero falso positivo (il
        mark-consume non è mai avvenuto) → `settle_capture_consumed` (denaro
        dovuto, nessun rimborso).

    Ritorna la lista dei risultati (esclusi no-op). Gli esiti di rimborso
    duplicato portano `refunded_duplicate=True`.
    """
    if not job_id:
        return []
    with _payments_lock:
        job_orders = [
            (oid, pay) for oid, pay in _payments.items()
            if isinstance(pay, dict)
            and (pay.get("job_id", "") or "") == job_id
            and pay.get("captured_at")
        ]
    has_consumed = any(pay.get("used") for _, pay in job_orders)
    unused = [oid for oid, pay in job_orders if not pay.get("used")]
    out = []
    for oid in unused:
        try:
            if has_consumed:
                # Un pagamento del job è gia' stato consumato per erogare il
                # servizio: questo capture è un duplicato reale → rimborso.
                r = refund_unused_capture(
                    oid, reason=(f"{reason} [duplicate-of-delivered]").strip(),
                    force=True)
                if r:
                    r["refunded_duplicate"] = True
                    out.append(r)
            else:
                r = settle_capture_consumed(oid, job_id=job_id, reason=reason)
                if r:
                    out.append(r)
        except Exception as e:
            print(f"[payment] settle_delivered_captures_for_job error order={oid}: {e}")
    return out
