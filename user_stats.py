"""Analisi dell'utenza a partire dal business log mensile (modulo foglia).

Risponde alla domanda "quanti utenti hanno determinato il 50% / 70% / 90%
delle generazioni completate del mese?", separando la coorte PREMIUM da
quella FREE.

Sorgente: `activity_YYYY-MM.log` (formato
`job_id # ts # "file" # OPERATION # client_id # ip # voice # lang # platform`).

Definizione di coorte (variante B, allineata a
`generation_engine.is_premium_job`): PREMIUM = voce a pagamento **oppure**
pagamento incassato sulla sessione. Nota: i pagamenti con buono non lasciano
`PAYMENT_CAPTURED` nel log, quindi restano visibili solo se la voce e' premium.

Solo stdlib: usabile dall'app (pannello Stats di /admin/log-activity), dallo
script `scripts/analyze_user_concentration.py` e direttamente sul server.
"""
import json
import os
import re
from collections import Counter, OrderedDict
from datetime import datetime

GEMINI_VOICE_PREFIX = "gemini:"
SPEECHIFY_VOICE_PREFIX = "speechify:"

# Evento che marca una generazione TTS portata a termine.
COMPLETE_OP = "COMPLETE"
# Evento che marca l'avvio effettivo della generazione (denominatore del tasso
# di completamento).
GENERATE_OP = "GENERATE"
# Pagamenti incassati (PayPal). Un job con uno di questi eventi e' PREMIUM a
# prescindere dalla voce: copre l'ottimizzazione AI pagata su voce standard.
PAID_OPS = frozenset({"PAYMENT_CAPTURED"})

QUANTILI = (0.50, 0.70, 0.90)
# Fasce di spesa (EUR) per l'istogramma del fatturato per utente.
FASCE_SPESA = ((1.0, "< 1"), (3.0, "1-3"), (10.0, "3-10"), (30.0, "10-30"),
               (None, "> 30"))
COORTI = ("premium", "free", "totale")

# Nome canonico del business log mensile.
_YM_IN_NAME = re.compile(r"^activity_(\d{4}-\d{2})\.log$")


def is_premium_voice(voice):
    return bool(voice) and (voice.startswith(GEMINI_VOICE_PREFIX)
                            or voice.startswith(SPEECHIFY_VOICE_PREFIX))


def split_line(line):
    """Spezza una riga del log nei 9 campi, tollerando '#' nel nome file.

    Il separatore e' ' # ' ma un titolo tipo "Riftwar Saga # 2 Empire.epub"
    lo contiene: uno split secco produce campi sfasati (l'operazione diventa
    un pezzo del titolo, e la sessione sparisce dalle aggregazioni). Si
    ancorano quindi i 2 campi di testa e i 6 di coda, lasciando al nome file
    tutto il resto. Su agosto 2026: ~200 righe recuperate, 80 sessioni COMPLETE
    che il vecchio split perdeva.

    Ritorna None se la riga non ha nemmeno i campi minimi.
    """
    head = line.split(" # ", 2)
    if len(head) < 3:
        return None
    sid, ts, rest = head
    tail = rest.rsplit(" # ", 6)
    if len(tail) < 7:
        # Riga corta (log storico senza platform/lang): completa a destra.
        tail = tail + [""] * (7 - len(tail))
    filename, operation, client_id, client_ip, voice, lang, platform = tail[:7]
    return (sid.strip(), ts.strip(), filename.strip().strip('"'),
            operation.strip(), client_id.strip(), client_ip.strip(),
            voice.strip(), lang.strip(), platform.strip())


def parse_sessions(path):
    """Aggrega le righe del log per job_id.

    Ritorna OrderedDict job_id -> {events:set, voice, client_id, client_ip,
    platform, day}. Come `_parse_log_sessions` in audiobook_app.py: per
    voice/client_id/ip vince l'ultimo valore non vuoto.
    """
    sessions = OrderedDict()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            fields = split_line(line)
            if not fields:
                continue
            sid, dt_str, _filename, operation, client_id, client_ip, voice, _lang, platform = fields
            if not sid:
                continue  # righe di sistema (voucher, admin) senza job
            if operation.startswith("VOUCHER_ATTEMPT"):
                continue

            s = sessions.get(sid)
            if s is None:
                s = sessions[sid] = {
                    "events": set(), "voice": "", "client_id": "",
                    "client_ip": "", "platform": "", "day": dt_str[:10],
                }
            s["events"].add(operation)
            if client_id:
                s["client_id"] = client_id
            if client_ip:
                s["client_ip"] = client_ip
            if voice:
                s["voice"] = voice
            if platform and not s["platform"]:
                s["platform"] = platform
    return sessions


def user_key(s, ip_fallback=True):
    """Identita' dell'utente per la sessione.

    client_id (cookie abm_cid) e' la sorgente primaria. Il fallback su IP
    recupera le sessioni con cookie assente (client API, cookie bloccati) al
    prezzo di fondere utenti dietro lo stesso NAT.
    """
    cid = s.get("client_id", "")
    if cid:
        return cid
    if ip_fallback and s.get("client_ip"):
        return "ip:" + s["client_ip"]
    return ""


def cohort_of(s):
    """Coorte della sessione (variante B: voce premium OR pagamento incassato)."""
    if is_premium_voice(s.get("voice", "")):
        return "premium"
    if PAID_OPS & s.get("events", frozenset()):
        return "premium"
    return "free"


def concentration(counts):
    """counts: Counter utente -> n generazioni. Ritorna le metriche di curva."""
    total = sum(counts.values())
    n_users = len(counts)
    out = {
        "generazioni": total,
        "utenti": n_users,
        "media_per_utente": round(total / n_users, 2) if n_users else 0.0,
        "quantili": {},
        "top_share": {},
        "gini": 0.0,
        "istogramma": {},
    }
    if not total:
        return out

    ordered = sorted(counts.values(), reverse=True)

    # Quanti utenti servono per coprire il X% delle generazioni.
    cum = 0
    targets = {q: None for q in QUANTILI}
    for i, v in enumerate(ordered, start=1):
        cum += v
        for q in QUANTILI:
            if targets[q] is None and cum >= q * total:
                targets[q] = (i, cum)
    for q in QUANTILI:
        users, covered = targets[q] or (n_users, total)
        out["quantili"][f"{int(q * 100)}%"] = {
            "utenti": users,
            "pct_utenti": round(users / n_users * 100, 1),
            "generazioni_coperte": covered,
            "pct_generazioni": round(covered / total * 100, 1),
        }

    # Quota delle generazioni presa dai top-N utenti.
    for n in (1, 3, 5, 10, 20):
        if n <= n_users:
            out["top_share"][f"top{n}"] = round(sum(ordered[:n]) / total * 100, 1)

    # Gini sulla distribuzione delle generazioni per utente.
    asc = sorted(ordered)
    cumw = 0
    for i, v in enumerate(asc, start=1):
        cumw += i * v
    out["gini"] = round((2 * cumw) / (n_users * total) - (n_users + 1) / n_users, 3)

    # Istogramma: quanti utenti hanno fatto 1, 2, 3-5, 6-10, >10 generazioni.
    buckets = OrderedDict((("1", 0), ("2", 0), ("3-5", 0), ("6-10", 0), (">10", 0)))
    for v in ordered:
        if v == 1:
            buckets["1"] += 1
        elif v == 2:
            buckets["2"] += 1
        elif v <= 5:
            buckets["3-5"] += 1
        elif v <= 10:
            buckets["6-10"] += 1
        else:
            buckets[">10"] += 1
    out["istogramma"] = dict(buckets)
    return out


def concentration_value(amounts):
    """amounts: dict utente -> euro spesi. Stesse metriche di `concentration`,
    ma su una grandezza continua: niente conteggi, istogramma per fascia."""
    total = round(sum(amounts.values()), 2)
    n_users = len(amounts)
    out = {
        "totale_eur": total,
        "utenti": n_users,
        "medio_per_utente_eur": round(total / n_users, 2) if n_users else 0.0,
        "mediana_per_utente_eur": 0.0,
        "quantili": {},
        "top_share": {},
        "gini": 0.0,
        "istogramma": {},
    }
    if total <= 0:
        return out

    ordered = sorted(amounts.values(), reverse=True)
    mid = n_users // 2
    out["mediana_per_utente_eur"] = round(
        ordered[mid] if n_users % 2 else (ordered[mid - 1] + ordered[mid]) / 2, 2)

    cum = 0.0
    targets = {q: None for q in QUANTILI}
    for i, v in enumerate(ordered, start=1):
        cum += v
        for q in QUANTILI:
            if targets[q] is None and cum >= q * total:
                targets[q] = (i, cum)
    for q in QUANTILI:
        users, covered = targets[q] or (n_users, total)
        out["quantili"][f"{int(q * 100)}%"] = {
            "utenti": users,
            "pct_utenti": round(users / n_users * 100, 1),
            "spesa_coperta_eur": round(covered, 2),
            "pct_spesa": round(covered / total * 100, 1),
        }

    for n in (1, 3, 5, 10, 20):
        if n <= n_users:
            out["top_share"][f"top{n}"] = round(sum(ordered[:n]) / total * 100, 1)

    asc = sorted(ordered)
    cumw = 0.0
    for i, v in enumerate(asc, start=1):
        cumw += i * v
    out["gini"] = round((2 * cumw) / (n_users * total) - (n_users + 1) / n_users, 3)

    buckets = OrderedDict((label, 0) for _, label in FASCE_SPESA)
    for v in ordered:
        for limit, label in FASCE_SPESA:
            if limit is None or v < limit:
                buckets[label] += 1
                break
    out["istogramma"] = dict(buckets)
    return out


def load_payments(path):
    """Legge `_payments.json` (order_id -> record). File assente/illeggibile: []."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        return list(data.values())
    return list(data) if isinstance(data, list) else []


def _payment_month(rec):
    """Mese (YYYY-MM) dell'incasso, in ora locale come le righe del log."""
    ts = rec.get("captured_at") or 0
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def spend_by_user(sessions, payments, ym="", ip_fallback=True):
    """Imputa gli incassi PayPal del mese agli utenti che hanno generato.

    Il business log non riporta l'importo (le righe PAYMENT_CAPTURED hanno i
    campi client/voce vuoti): l'importo arriva da `_payments.json`, l'identita'
    dal job_id gia' presente nel log. Gli incassi `pending_unfunded` (eCheck non
    compensati) sono denaro non arrivato e restano fuori dal totale.

    Ritorna (Counter utente -> euro, meta) con nel meta i pagamenti che non si
    riescono ad attribuire a un utente.
    """
    per_user = Counter()
    meta = {"pagamenti": 0, "totale_eur": 0.0, "non_attribuiti": 0,
            "non_attribuiti_eur": 0.0, "unfunded": 0, "unfunded_eur": 0.0}
    for rec in payments or []:
        if ym and _payment_month(rec) != ym:
            continue
        try:
            amt = round(float(rec.get("amount_eur", 0) or 0), 2)
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        if rec.get("pending_unfunded"):
            meta["unfunded"] += 1
            meta["unfunded_eur"] = round(meta["unfunded_eur"] + amt, 2)
            continue
        meta["pagamenti"] += 1
        meta["totale_eur"] = round(meta["totale_eur"] + amt, 2)
        s = sessions.get(rec.get("job_id", "")) if rec.get("job_id") else None
        u = user_key(s, ip_fallback) if s else ""
        if not u:
            meta["non_attribuiti"] += 1
            meta["non_attribuiti_eur"] = round(meta["non_attribuiti_eur"] + amt, 2)
            continue
        per_user[u] = round(per_user[u] + amt, 2)
    return per_user, meta


def _ym_from_name(path):
    """Mese dal nome `activity_YYYY-MM.log`; "" se il nome non lo dice.

    Il filtro sul mese e' pericoloso al contrario (un mese sbagliato azzera
    silenziosamente gli incassi), quindi si accetta solo la forma esatta.
    """
    m = _YM_IN_NAME.match(os.path.basename(str(path)))
    return m.group(1) if m else ""


def analyze(path, ip_fallback=True, payments=None):
    """Analisi completa di un file di log. `path` deve esistere.

    `payments`: record di `_payments.json` (order_id -> dict) o loro lista;
    servono per la concentrazione in valore, che il solo log non consente.
    """
    sessions = parse_sessions(path)

    counts = {"premium": Counter(), "free": Counter(), "totale": Counter()}
    started = {"premium": 0, "free": 0, "totale": 0}
    no_user = {"complete": 0, "generate": 0}
    paying_clients = set()

    for s in sessions.values():
        ev = s["events"]
        cohort = cohort_of(s)
        u = user_key(s, ip_fallback)
        if u and (PAID_OPS & ev):
            paying_clients.add(u)
        if GENERATE_OP in ev:
            started[cohort] += 1
            started["totale"] += 1
            if not u:
                no_user["generate"] += 1
        if COMPLETE_OP in ev:
            if not u:
                no_user["complete"] += 1
                continue
            counts[cohort][u] += 1
            counts["totale"][u] += 1

    per_user_eur, spend_meta = spend_by_user(sessions, payments,
                                             ym=_ym_from_name(path),
                                             ip_fallback=ip_fallback)

    res = {
        "file": str(path),
        "sessioni_totali": len(sessions),
        "ip_fallback": ip_fallback,
        "senza_identita": no_user,
        "clienti_paganti": len(paying_clients),
        "coorti": {},
    }
    for cohort in COORTI:
        c = concentration(counts[cohort])
        c["generazioni_avviate"] = started[cohort]
        c["tasso_completamento_pct"] = (
            round(c["generazioni"] / started[cohort] * 100, 1) if started[cohort] else 0.0
        )
        res["coorti"][cohort] = c

    # Concentrazione in valore: stesse domande, unita' di misura euro.
    spesa = concentration_value(per_user_eur)
    spesa.update(spend_meta)
    res["spesa"] = spesa

    # Sovrapposizione fra le due coorti.
    p, f = set(counts["premium"]), set(counts["free"])
    res["overlap"] = {
        "solo_premium": len(p - f),
        "solo_free": len(f - p),
        "entrambi": len(p & f),
    }
    return res


def empty_result(path=""):
    """Risultato neutro per un mese senza log (nessun file)."""
    res = {
        "file": str(path),
        "sessioni_totali": 0,
        "ip_fallback": True,
        "senza_identita": {"complete": 0, "generate": 0},
        "clienti_paganti": 0,
        "coorti": {},
        "overlap": {"solo_premium": 0, "solo_free": 0, "entrambi": 0},
        "spesa": dict(concentration_value({}),
                      pagamenti=0, totale_eur=0.0, non_attribuiti=0,
                      non_attribuiti_eur=0.0, unfunded=0, unfunded_eur=0.0),
    }
    for cohort in COORTI:
        c = concentration(Counter())
        c["generazioni_avviate"] = 0
        c["tasso_completamento_pct"] = 0.0
        res["coorti"][cohort] = c
    return res
