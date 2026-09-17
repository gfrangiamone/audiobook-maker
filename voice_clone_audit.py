"""Audit admin delle voci campionate: una riga per voce con incassi, costi e
margini, piu' i dati che servono a leggerla (dispositivi, attivazione,
scadenza, libri generati).

Funzioni pure sui record di `voice_clone`: niente store, niente rete. Il
cambio USD->EUR e la fee PayPal arrivano da fuori, cosi' restano quelli
delle altre tab di /admin/audit-premium.

- Ricavo: `payment.amount_eur`; zero se la voce e' stata rimborsata (come
  gli `*_refunded` delle altre tab) o era gratis.
- Costo: la GPU delle demo (`demo_cost.usd`). I libri generati con la voce
  li paga il loro job e stanno nella tab Audit TTS.
- Periodo: la data di pagamento; le bozze, che non ne hanno, la creazione.
"""
from datetime import datetime, timezone

# Filtri di stato: "paid" (il default) sono le voci con un pagamento, anche
# gratuito; "drafts" i campioni mai confermati, visibili solo a richiesta.
STATE_GROUPS = {
    "demos": ("paid", "demos_generating", "demos_ready", "demo_failed"),
}
STATE_FILTERS = ("paid", "drafts", "all", "ready", "demos", "refunded", "expired", "deleted")


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def reference_ts(rec):
    pay = rec.get("payment") or {}
    return pay.get("paid_at") or rec.get("paid_at") or rec.get("created_at")


def _day(ts):
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def row(rec, *, usd_eur=1.0, fee_fn=None):
    """La riga della tabella per un record voce. Mai token/segreti: solo
    l'id `vc_...` e i dati descrittivi."""
    pay = rec.get("payment") or {}
    method = (pay.get("type") or "") if pay else ""
    charged = round(_f(pay.get("amount_eur")), 4)
    refund = rec.get("refund") or {}
    refunded = rec.get("state") == "refunded" or bool(refund)
    revenue = 0.0 if refunded else charged
    cost = rec.get("demo_cost") or {}
    cost_usd = _f(cost.get("usd"))
    cost_eur = round(cost_usd * _f(usd_eur), 4)
    fee = 0.0
    if fee_fn and revenue > 0:
        try:
            fee = round(_f(fee_fn(revenue, method)), 4)
        except Exception:       # noqa: BLE001 - una fee illeggibile non rompe la pagina
            fee = 0.0
    devices = rec.get("devices") or []
    demo = rec.get("demo") or {}
    note = rec.get("reject_note")
    note = note if isinstance(note, dict) else {}
    return {
        "id": rec.get("id"),
        "name": rec.get("name") or "",
        "state": rec.get("state") or "",
        "delete_reason": rec.get("delete_reason") or "",
        "refund_reason": refund.get("reason") or "",
        "lang": rec.get("lang") or "",
        "locale": rec.get("locale") or "",
        "gender": rec.get("gender") or "",
        "owner_email": rec.get("owner_email") or "",
        "demo_extra_id": demo.get("extra_id") or "",
        "demo_fail_count": int(demo.get("fail_count") or 0),
        "created_at": rec.get("created_at"),
        "paid_at": pay.get("paid_at") or rec.get("paid_at"),
        "ready_at": rec.get("ready_at"),
        "expires_at": rec.get("expires_at"),
        "last_used_at": rec.get("last_used_at"),
        "ended_at": rec.get("refunded_at") or rec.get("expired_at") or rec.get("deleted_at"),
        "ref_ts": reference_ts(rec),
        "payment_method": method,
        "charged_eur": charged,
        "refund_eur": round(_f(refund.get("amount_eur")), 4) if refunded else 0.0,
        "revenue_eur": round(revenue, 4),
        "gpu_cost_usd": round(cost_usd, 6),
        "gpu_cost_eur": cost_eur,
        "gpu_seconds": round(_f(cost.get("gpu_seconds")), 2),
        "gpu_jobs": int(cost.get("jobs") or 0),
        "margin_eur": round(revenue - cost_eur, 4),
        "paypal_fee_eur": fee,
        "net_margin_eur": round(revenue - cost_eur - fee, 4),
        "devices": len(devices),
        "device_names": [d.get("name") or "" for d in devices],
        "books": len(rec.get("books") or []),
        # motivo del rifiuto: la traduzione italiana arriva in background
        "reject_note_original": note.get("text") or "",
        "reject_note_it": note.get("it") or "",
        "reject_note_lang": note.get("lang") or "",
    }


def _state_ok(rec, state):
    has_pay = bool(rec.get("payment"))
    if state == "all":
        return True
    if state == "drafts":
        return not has_pay
    if not has_pay:
        return False
    if state == "paid":
        return True
    return rec.get("state") in STATE_GROUPS.get(state, (state,))


def select(recs, *, state=None, language=None, date_from=None, date_to=None):
    state = state if state in STATE_FILTERS else "paid"
    out = []
    for rec in recs or []:
        if not isinstance(rec, dict) or not _state_ok(rec, state):
            continue
        if language and rec.get("lang") != language:
            continue
        day = _day(reference_ts(rec))
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        out.append(rec)
    out.sort(key=lambda r: _f(reference_ts(r)), reverse=True)
    return out


def aggregate(rows):
    rev = sum(r["revenue_eur"] for r in rows)
    cost = sum(r["gpu_cost_eur"] for r in rows)
    fee = sum(r["paypal_fee_eur"] for r in rows)
    net = rev - cost - fee
    return {
        "count": len(rows),
        "charged_eur": round(sum(r["charged_eur"] for r in rows), 4),
        "refund_eur": round(sum(r["refund_eur"] for r in rows), 4),
        "revenue_eur": round(rev, 4),
        "gpu_cost_eur": round(cost, 4),
        "margin_eur": round(rev - cost, 4),
        "paypal_fees_eur": round(fee, 4),
        "net_margin_eur": round(net, 4),
        "margin_pct_avg": round(net / cost * 100, 2) if cost > 0 else 0.0,
        "books": sum(r["books"] for r in rows),
        "devices": sum(r["devices"] for r in rows),
    }


def report(recs, *, state=None, language=None, date_from=None, date_to=None,
           usd_eur=1.0, fee_fn=None, limit=200, offset=0):
    chosen = select(recs, state=state, language=language,
                    date_from=date_from, date_to=date_to)
    rows = [row(r, usd_eur=usd_eur, fee_fn=fee_fn) for r in chosen]
    languages = sorted({str(r.get("lang")) for r in recs or []
                        if isinstance(r, dict) and r.get("lang")})
    return {
        "records": rows[offset:offset + limit],
        "count": len(rows),
        "aggregates": aggregate(rows),
        "languages": languages,
    }
