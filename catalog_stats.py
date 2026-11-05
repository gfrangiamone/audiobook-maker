"""catalog_stats — statistiche del catalogo audiolibri gratuiti per l'admin.

Spec catalogo §10.1. Nessun archivio proprio: gli eventi sono le righe
dell'activity log scritte dalle route del catalogo (`FREE_CATALOG_DL`:
scaricamento M4B dalla pagina; `FREE_CATALOG_APP`: import nell'app via
`/s/fc-…/dl`), i dati dei libri vengono dal catalogo pubblico, le visite dal
contatore `web_visit_from_catalog` di `metrics_store`, i pagamenti attribuiti
dagli audit dei servizi premium (`acquisition_source = "catalog"`).
"""
from datetime import datetime, timedelta

import activity_log
import free_catalog
import gemini_cost_audit
import metrics_store
import optimization_cost_audit

OP_DL = "FREE_CATALOG_DL"
OP_APP = "FREE_CATALOG_APP"
# Periodo di default e tetto: piu' di un anno di righe e' un'altra analisi.
DEFAULT_DAYS = 30
MAX_DAYS = 400


def _day(raw):
    try:
        return datetime.strptime(str(raw or "").strip(), "%Y-%m-%d")
    except ValueError:
        return None


def period(date_from=None, date_to=None, today=None):
    """(inizio, fine esclusa) del periodo: date `YYYY-MM-DD` incluse; senza
    date gli ultimi `DEFAULT_DAYS` giorni; mai oltre `MAX_DAYS`."""
    today = (today or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (_day(date_to) or today) + timedelta(days=1)
    start = _day(date_from) or end - timedelta(days=DEFAULT_DAYS)
    if start >= end:
        start = end - timedelta(days=1)
    start = max(start, end - timedelta(days=MAX_DAYS))
    return start, end


def _platform(row):
    if row.op == OP_DL:
        return "download"
    p = (row.platform or "").lower()
    return p if p in ("android", "ios") else "app_other"


def _empty():
    return {"download": 0, "android": 0, "ios": 0, "app_other": 0, "total": 0}


def stats(date_from=None, date_to=None, *, lang=None, model=None, today=None):
    """Statistiche del periodo, con filtro opzionale per lingua del libro e
    modello TTS (`voice_model` del catalogo, es. "Gemini 3.8")."""
    start, end = period(date_from, date_to, today)
    books = {b["book_id"]: (l, b) for l, b in (free_catalog.all_books() or [])}

    def _keep(book_id):
        l, b = books.get(book_id, (book_id[:2], None))
        if lang and l != lang:
            return False
        return not model or (b is not None and b.get("voice_model") == model)

    per_book, per_lang, per_day = {}, {}, {}
    visitors, totals = set(), _empty()
    for row in activity_log.iter_rows(start, end, ops={OP_DL, OP_APP}):
        book_id = row.filename
        if not book_id or not _keep(book_id):
            continue
        kind = _platform(row)
        for bucket in (per_book.setdefault(book_id, _empty()),
                       per_lang.setdefault(books.get(book_id, (book_id[:2],))[0], _empty()),
                       per_day.setdefault(row.ts[:10], _empty()), totals):
            bucket[kind] += 1
            bucket["total"] += 1
        if row.ip:
            visitors.add(row.ip)

    rows = []
    for book_id, (l, b) in books.items():
        if not _keep(book_id) or (b["status"] != "published" and book_id not in per_book):
            continue
        rows.append({"book_id": book_id, "lang": l, "title": b["title"],
                     "author": b["author"]["name"], "model": b.get("voice_model") or "",
                     "published_at": b.get("published_at") or "",
                     **per_book.get(book_id, _empty())})
    # Libri nel log ma usciti dal catalogo (ritirati): restano contati.
    rows += [{"book_id": k, "lang": k[:2], "title": "", "author": "", "model": "",
              "published_at": "", **v} for k, v in per_book.items() if k not in books]
    rows.sort(key=lambda r: (-r["total"], r["title"]))
    days = [{"day": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
             **per_day.get((start + timedelta(days=i)).strftime("%Y-%m-%d"), _empty())}
            for i in range((end - start).days)]
    return {
        "from": start.strftime("%Y-%m-%d"), "to": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "totals": {**totals, "visitors": len(visitors),
                   "books_with_events": sum(1 for r in rows if r["total"])},
        "books": rows,
        "langs": [{"lang": k, **v} for k, v in sorted(per_lang.items(), key=lambda x: -x[1]["total"])],
        "days": days,
        "return": _ritorno(start, end),
    }


def _ritorno(start, end):
    """Visite dal catalogo e pagamenti dei visitatori arrivati dal catalogo."""
    giorni = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end - start).days)]
    visite = sum((metrics_store.read_range(giorni).get("web_visit_from_catalog") or {}).values())
    d_from, d_to = giorni[0], giorni[-1]
    pagamenti, euro = 0, 0.0
    for store in (gemini_cost_audit, optimization_cost_audit):
        for rec in store.iter_records(date_from=d_from, date_to=d_to):
            if rec.get("acquisition_source") != "catalog":
                continue
            pagamenti += 1
            euro += float(rec.get("user_price_eur_charged", 0) or 0)
    return {"visits": visite, "payments": pagamenti, "payments_eur": round(euro, 2)}
