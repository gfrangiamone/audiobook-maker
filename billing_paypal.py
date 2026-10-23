# billing_paypal.py
"""Adattatore PayPal Subscriptions per `subscriptions` (l'unico punto che
conosce PayPal per gli abbonamenti).

Interfaccia usata dal dominio: `available`, `create_checkout`, `fetch`,
`list_payments`, `cancel`, `refund_payment`, `verify_webhook`, `parse_webhook`.
Token OAuth e base URL vengono da `payment` (un solo client PayPal, REGOLE
§5.4); ogni id esterno passa da `payment.is_order_id` prima di finire in un
URL. Le chiamate idempotenti si ritentano con `retry_util` solo su 429/5xx e
cadute di rete.

CLI: `python -m billing_paypal setup` crea product e plan mensili (prezzi da
`subscriptions.price_eur`) e stampa le righe d'ambiente da copiare; con i plan
gia' configurati ne verifica prezzo e valuta.
"""
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import payment
import retry_util
from env_utils import env_str


PROVIDER = "paypal"
PLAN_ENV = {"sub_5": "ABM_PAYPAL_PLAN_SUB5", "sub_10": "ABM_PAYPAL_PLAN_SUB10"}
PLAN_LABEL = {"sub_5": "5 GB", "sub_10": "10 GB"}
REMOTE_STATUSES = ("APPROVAL_PENDING", "APPROVED", "ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED")
_CERT_HOSTS = ("api.paypal.com", "api.sandbox.paypal.com", "api-m.paypal.com",
               "api-m.sandbox.paypal.com")
_SIG_HEADERS = ("PAYPAL-TRANSMISSION-ID", "PAYPAL-TRANSMISSION-TIME", "PAYPAL-TRANSMISSION-SIG",
                "PAYPAL-AUTH-ALGO", "PAYPAL-CERT-URL")
_LOCALES = {"it": "it-IT", "en": "en-US", "fr": "fr-FR", "es": "es-ES", "de": "de-DE",
            "zh": "zh-CN", "hi": "en-IN"}
_ATTEMPTS = 3
_sleep = time.sleep          # i test la sostituiscono


class ProviderError(Exception):
    """Errore di una chiamata al fornitore. `transient` dice se ritentare."""

    def __init__(self, message, *, status=None, issue="", debug_id="", transient=False):
        super().__init__(message)
        self.status = status
        self.issue = issue or ""
        self.debug_id = debug_id or ""
        self.transient = bool(transient)


@dataclass(frozen=True)
class Remote:
    """Stato remoto di un abbonamento (epoch interi o None)."""
    external_id: str
    status: str
    plan: str
    custom_id: str
    next_billing_at: int | None
    last_payment_at: int | None
    last_payment_eur: float | None
    failed_payments: int


@dataclass(frozen=True)
class Payment:
    """Un pagamento dell'abbonamento: `state` completed|refunded|reversed|other."""
    payment_id: str
    amount_eur: float
    paid_at: int
    state: str
    currency: str


@dataclass(frozen=True)
class Event:
    """Webhook normalizzato: `type` refresh (rileggere lo stato remoto) |
    renewed (pagamento riuscito) | payment_reversed (rimborso o storno)."""
    event_id: str
    type: str
    external_id: str
    payment: Payment | None
    raw_type: str


# ------------------------------------------------------------------ HTTP

def _send(method, url, *, headers, json=None, params=None, timeout=15):
    """Unico punto di rete del modulo (i test lo sostituiscono)."""
    return requests.request(method, url, headers=headers, json=json, params=params,
                            timeout=timeout)


def _check_id(value):
    if not payment.is_order_id(value):
        raise ValueError(f"invalid PayPal id: {str(value)[:20]!r}")
    return value


def _request(method, path, *, body=None, params=None, request_id=None, timeout=15,
             ok=(200, 201, 204), retry=True):
    """Chiamata autenticata a PayPal; ritorna il JSON (dict vuoto per 204).
    ProviderError su errore; 429/5xx e cadute di rete si ritentano se `retry`."""
    def once(_attempt):
        token = payment._paypal_get_access_token()
        if not token:
            raise ProviderError("PayPal not configured")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "Accept": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            r = _send(method, payment.PAYPAL_API_BASE + path, headers=headers, json=body,
                      params=params, timeout=timeout)
        except requests.RequestException as e:
            raise ProviderError(f"{method} {path}: {type(e).__name__}", transient=True) from e
        if r.status_code in ok:
            if r.status_code == 204:
                return {}
            try:
                data = r.json()
            except ValueError:
                data = None
            return data if isinstance(data, dict) else {}
        issue, name, description, debug_id = payment._paypal_error_details(r)
        raise ProviderError(f"{method} {path}: HTTP {r.status_code} {issue or name} {description}"[:300],
                            status=r.status_code, issue=issue or name, debug_id=debug_id,
                            transient=retry_util.is_transient_http(r.status_code))

    return retry_util.retry_call(once, attempts=_ATTEMPTS if retry else 1,
                                 is_retryable=lambda e: getattr(e, "transient", False),
                                 sleep=_sleep)


def _epoch(value):
    """Epoch intero da un istante ISO 8601 di PayPal, None se assente o illeggibile."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _money(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ piani

def plan_id(plan):
    """Id del plan PayPal configurato per il piano interno (stringa vuota se manca)."""
    name = PLAN_ENV.get(plan)
    return env_str(name).strip() if name else ""


def plan_for_remote_id(remote_plan_id):
    """Piano interno di un plan PayPal ('' se non e' uno dei nostri)."""
    if not remote_plan_id:
        return ""
    for plan in PLAN_ENV:
        if plan_id(plan) == remote_plan_id:
            return plan
    return ""


def available():
    """True se credenziali, plan e webhook sono configurati."""
    return bool(payment._paypal_available() and all(plan_id(p) for p in PLAN_ENV)
                and env_str("ABM_PAYPAL_WEBHOOK_ID").strip())


# ------------------------------------------------------------------ interfaccia

def create_checkout(*, sub_id, plan, email, lang, return_url, cancel_url):
    """Crea l'abbonamento in attesa di approvazione; ritorna (id esterno, URL di
    approvazione). `sub_id` (id interno) e' anche `custom_id` e chiave di
    idempotenza della richiesta."""
    pid = plan_id(plan)
    if not pid:
        raise ProviderError(f"no PayPal plan configured for {plan}")
    body = {
        "plan_id": pid,
        "custom_id": sub_id,
        "application_context": {
            "brand_name": "Audiobook Maker",
            "locale": _LOCALES.get(lang or "", "en-US"),
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "payment_method": {"payer_selected": "PAYPAL",
                               "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"},
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    if email:
        body["subscriber"] = {"email_address": email}
    data = _request("POST", "/v1/billing/subscriptions", body=body, request_id=sub_id,
                    timeout=20, ok=(200, 201))
    ext = str(data.get("id") or "")
    approve = next((link.get("href") for link in data.get("links") or []
                    if isinstance(link, dict) and link.get("rel") == "approve"), "")
    if not payment.is_order_id(ext) or not approve:
        raise ProviderError("PayPal subscription without id or approve link")
    return ext, approve


def fetch(external_id):
    """Stato remoto dell'abbonamento."""
    data = _request("GET", f"/v1/billing/subscriptions/{_check_id(external_id)}", ok=(200,))
    info = data.get("billing_info") or {}
    last = info.get("last_payment") or {}
    status = str(data.get("status") or "")
    try:
        failed = int(info.get("failed_payments_count") or 0)
    except (TypeError, ValueError):
        failed = 0
    return Remote(external_id=external_id,
                  status=status if status in REMOTE_STATUSES else "",
                  plan=plan_for_remote_id(data.get("plan_id")),
                  custom_id=str(data.get("custom_id") or ""),
                  next_billing_at=_epoch(info.get("next_billing_time")),
                  last_payment_at=_epoch(last.get("time")),
                  last_payment_eur=_money((last.get("amount") or {}).get("value")),
                  failed_payments=failed)


_TX_STATES = {"COMPLETED": "completed", "REFUNDED": "refunded", "PARTIALLY_REFUNDED": "refunded"}


def list_payments(external_id, since, until):
    """Pagamenti dell'abbonamento fra `since` e `until` (epoch)."""
    data = _request("GET", f"/v1/billing/subscriptions/{_check_id(external_id)}/transactions",
                    params={"start_time": _iso(since), "end_time": _iso(until)}, ok=(200,))
    out = []
    for tx in data.get("transactions") or []:
        if not isinstance(tx, dict) or not payment.is_order_id(tx.get("id")):
            continue
        gross = (tx.get("amount_with_breakdown") or {}).get("gross_amount") or {}
        amount, at = _money(gross.get("value")), _epoch(tx.get("time"))
        if amount is None or at is None:
            continue
        out.append(Payment(payment_id=tx["id"], amount_eur=amount, paid_at=at,
                           state=_TX_STATES.get(str(tx.get("status") or ""), "other"),
                           currency=str(gross.get("currency_code") or "")))
    return out


def cancel(external_id, reason):
    """Disdice l'abbonamento (nessun addebito futuro). True anche se era gia'
    disdetto o scaduto."""
    try:
        _request("POST", f"/v1/billing/subscriptions/{_check_id(external_id)}/cancel",
                 body={"reason": (reason or "cancelled")[:128]}, ok=(200, 204))
    except ProviderError as e:
        if e.status == 422 and e.issue == "SUBSCRIPTION_STATUS_INVALID":
            return True
        raise
    return True


def refund_payment(payment_id, amount_eur):
    """Rimborsa per intero un pagamento dell'abbonamento."""
    _request("POST", f"/v1/payments/sale/{_check_id(payment_id)}/refund",
             body={"amount": {"total": f"{float(amount_eur):.2f}", "currency": "EUR"}},
             request_id=f"refund-{payment_id}", timeout=20, ok=(200, 201))
    return True


def verify_webhook(headers, event):
    """True se il webhook e' firmato da PayPal per il nostro `ABM_PAYPAL_WEBHOOK_ID`.
    Header mancanti o certificato fuori dai domini PayPal: False senza chiamate."""
    h = {str(k).upper(): str(v) for k, v in (headers or {}).items()}
    webhook_id = env_str("ABM_PAYPAL_WEBHOOK_ID").strip()
    if not webhook_id or not isinstance(event, dict) or any(not h.get(k) for k in _SIG_HEADERS):
        return False
    cert = urlparse(h["PAYPAL-CERT-URL"])
    if cert.scheme != "https" or (cert.hostname or "") not in _CERT_HOSTS:
        return False
    body = {"auth_algo": h["PAYPAL-AUTH-ALGO"], "cert_url": h["PAYPAL-CERT-URL"],
            "transmission_id": h["PAYPAL-TRANSMISSION-ID"],
            "transmission_sig": h["PAYPAL-TRANSMISSION-SIG"],
            "transmission_time": h["PAYPAL-TRANSMISSION-TIME"],
            "webhook_id": webhook_id, "webhook_event": event}
    try:
        data = _request("POST", "/v1/notifications/verify-webhook-signature", body=body, ok=(200,))
    except ProviderError as e:
        print(f"[billing_paypal] verifica webhook fallita: {e}", flush=True)
        return False
    return data.get("verification_status") == "SUCCESS"


def _sale_payment(res, state):
    """Pagamento dalla risorsa di un webhook di vendita: per un rimborso la
    risorsa e' il refund e la vendita e' `sale_id`; altrimenti e' la vendita."""
    amount = res.get("amount") or {}
    sale = res.get("sale_id") if state == "refunded" else None
    return Payment(payment_id=str(sale or res.get("id") or ""),
                   amount_eur=_money(amount.get("total")) or 0.0,
                   paid_at=_epoch(res.get("create_time")) or 0,
                   state=state, currency=str(amount.get("currency") or ""))


def parse_webhook(event):
    """Evento normalizzato (Event) o None per i tipi che non ci riguardano."""
    if not isinstance(event, dict):
        return None
    raw, eid = str(event.get("event_type") or ""), str(event.get("id") or "")
    res = event.get("resource") if isinstance(event.get("resource"), dict) else {}
    if not eid:
        return None
    if raw == "PAYMENT.SALE.COMPLETED":
        ext = str(res.get("billing_agreement_id") or "")
        if not ext:
            return None
        return Event(eid, "renewed", ext, _sale_payment(res, "completed"), raw)
    if raw in ("PAYMENT.SALE.REFUNDED", "PAYMENT.SALE.REVERSED"):
        pay = _sale_payment(res, "refunded" if raw.endswith("REFUNDED") else "reversed")
        if not pay.payment_id:
            return None
        return Event(eid, "payment_reversed", str(res.get("billing_agreement_id") or ""), pay, raw)
    if raw.startswith("BILLING.SUBSCRIPTION."):
        ext = str(res.get("id") or "")
        return Event(eid, "refresh", ext, None, raw) if ext else None
    return None


# ------------------------------------------------------------------ setup (CLI)

def _plan_body(product_id, plan, price):
    return {
        "product_id": product_id,
        "name": f"Audiobook Maker cloud library {PLAN_LABEL[plan]} (monthly)",
        "status": "ACTIVE",
        "billing_cycles": [{
            "frequency": {"interval_unit": "MONTH", "interval_count": 1},
            "tenure_type": "REGULAR", "sequence": 1, "total_cycles": 0,
            "pricing_scheme": {"fixed_price": {"value": f"{price:.2f}", "currency_code": "EUR"}},
        }],
        "payment_preferences": {"auto_bill_outstanding": True,
                                "setup_fee_failure_action": "CANCEL",
                                "payment_failure_threshold": 1},
    }


def setup_plans(prices, out=print):
    """Crea product e plan mancanti (stampa le righe d'ambiente) e verifica
    prezzo e valuta di quelli gia' configurati. `prices`: {piano: EUR}.
    Ritorna il numero di problemi."""
    problems, product_id = 0, ""
    for plan in PLAN_ENV:
        price, existing = round(float(prices[plan]), 2), plan_id(plan)
        if existing:
            data = _request("GET", f"/v1/billing/plans/{_check_id(existing)}", ok=(200,))
            cycles = data.get("billing_cycles") or [{}]
            fixed = ((cycles[0].get("pricing_scheme") or {}).get("fixed_price") or {})
            got = (_money(fixed.get("value")), fixed.get("currency_code"))
            if got != (price, "EUR") or data.get("status") != "ACTIVE":
                problems += 1
                out(f"# {plan}: plan {existing} ha {got} stato {data.get('status')}, "
                    f"atteso ({price}, 'EUR') ACTIVE")
            else:
                out(f"# {plan}: plan {existing} ok")
            continue
        if not product_id:
            product = _request("POST", "/v1/catalogs/products", ok=(200, 201),
                               body={"name": "Audiobook Maker cloud library", "type": "SERVICE",
                                     "category": "SOFTWARE"},
                               request_id=f"abm-product-{int(time.time())}")
            product_id = str(product.get("id") or "")
            out(f"# product {product_id}")
        created = _request("POST", "/v1/billing/plans", body=_plan_body(product_id, plan, price),
                           ok=(200, 201), request_id=f"abm-plan-{plan}-{int(time.time())}")
        out(f"{PLAN_ENV[plan]}={created.get('id')}")
    return problems


def main(argv):
    if argv[1:2] != ["setup"]:
        print("uso: python -m billing_paypal setup", file=sys.stderr)
        return 2
    if not payment._paypal_available():
        print("ABM_PAYPAL_CLIENT_ID/ABM_PAYPAL_SECRET/ABM_PAYPAL_MODE mancanti", file=sys.stderr)
        return 2
    import subscriptions        # solo da CLI: i prezzi sono del dominio
    print(f"# PayPal {payment.PAYPAL_MODE} ({payment.PAYPAL_API_BASE})")
    return 1 if setup_plans({p: subscriptions.price_eur(p) for p in PLAN_ENV}) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
