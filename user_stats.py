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
    line = line.rstrip("\r\n")
    if line.endswith(" #"):
        # `platform` vuoto: la riga finisce con " # " e chi ha gia' fatto
        # strip() si e' mangiato l'ultimo separatore. Senza questo ripristino
        # l'ancoraggio a destra slitta di un campo (lang diventa "en #" e, se
        # il titolo contiene " # ", l'operazione diventa un pezzo di titolo).
        line += " "
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

    Ritorna OrderedDict job_id -> {events:set, voice, lang, client_id,
    client_ip, platform, day}. Come `_parse_log_sessions` in audiobook_app.py:
    per voice/lang/client_id/ip vince l'ultimo valore non vuoto.
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
            sid, dt_str, _filename, operation, client_id, client_ip, voice, lang, platform = fields
            if not sid:
                continue  # righe di sistema (voucher, admin) senza job
            if operation.startswith("VOUCHER_ATTEMPT"):
                continue

            s = sessions.get(sid)
            if s is None:
                s = sessions[sid] = {
                    "events": set(), "voice": "", "lang": "", "client_id": "",
                    "client_ip": "", "platform": "", "day": dt_str[:10],
                }
            s["events"].add(operation)
            if client_id:
                s["client_id"] = client_id
            if client_ip:
                s["client_ip"] = client_ip
            if voice:
                s["voice"] = voice
            if lang:
                s["lang"] = lang
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


def _lang_key(lang):
    """Codice lingua normalizzato ("it-IT" -> "it"); "?" se il log non lo dice.

    Il campo non e' sempre una lingua: alcune righe (es. il rifiuto di una
    seconda capture sullo stesso job) ci scrivono un messaggio libero. Si
    accetta quindi solo un tag plausibile, corto e senza spazi.
    """
    v = (lang or "").strip().lower().replace("_", "-")
    if not v or len(v) > 12 or v.split() != [v]:
        return "?"
    v = v.split("-")[0]
    return v if v.isalpha() and 2 <= len(v) <= 3 else "?"


def ripartizione(amounts, key_name="chiave"):
    """Ripartizione di una grandezza per chiave (qui: la lingua del libro).

    Le chiavi sono poche e non anonime, quindi la curva utile non e' il Gini
    ma la classifica: quota di ciascuna, quota cumulata, e quante chiavi
    servono per coprire il 50/70/90% del totale. `hhi` (Herfindahl, 0-10000)
    riassume quanto il mix e' concentrato su poche lingue.
    """
    total = sum(amounts.values())
    total = round(total, 2) if isinstance(total, float) else total
    out = {
        "totale": total,
        "chiavi": len(amounts),
        "righe": [],
        "quantili": {f"{int(q * 100)}%": 0 for q in QUANTILI},
        "hhi": 0,
    }
    if not total or total <= 0:
        return out

    cum = 0.0
    hhi = 0.0
    quant = {q: None for q in QUANTILI}
    for k, v in sorted(amounts.items(), key=lambda kv: (-kv[1], kv[0])):
        cum += v
        share = v / total * 100
        hhi += share * share
        out["righe"].append({
            key_name: k,
            "valore": round(v, 2) if isinstance(v, float) else v,
            "pct": round(share, 1),
            "pct_cumulata": round(cum / total * 100, 1),
        })
        for q in QUANTILI:
            if quant[q] is None and cum >= q * total:
                quant[q] = len(out["righe"])
    for q in QUANTILI:
        out["quantili"][f"{int(q * 100)}%"] = quant[q] or len(out["righe"])
    out["hhi"] = int(round(hhi))
    return out


def language_stats(sessions, payments, ym=""):
    """Ripartizione per lingua del libro: libri completati e incassi.

    I libri sono contati in due classifiche separate secondo la voce usata
    (`libri` = voci premium Gemini/Speechify, `libri_free` = voci standard):
    la domanda e' su quali lingue si concentra il prodotto, e le due coorti
    hanno mix diversi. Il criterio qui e' la sola voce, non il pagamento:
    un libro a voce standard con ottimizzazione AI pagata resta un libro free.

    Gli incassi invece sono presi tutti insieme, perche' il fatturato include
    anche l'ottimizzazione AI su voce standard, e non si suddividono per
    coorte: sarebbe la stessa domanda della concentrazione di spesa.
    """
    libri = Counter()
    libri_free = Counter()
    eur = Counter()
    pagamenti = Counter()
    meta = {"senza_lingua": 0, "senza_lingua_eur": 0.0,
            "libri_senza_lingua": 0, "libri_free_senza_lingua": 0}

    for s in sessions.values():
        if COMPLETE_OP not in s["events"]:
            continue
        premium = is_premium_voice(s.get("voice", ""))
        k = _lang_key(s.get("lang", ""))
        if k == "?":
            meta["libri_senza_lingua" if premium
                 else "libri_free_senza_lingua"] += 1
        if premium:
            libri[k] += 1
        else:
            libri_free[k] += 1

    for rec in payments or []:
        if ym and _payment_month(rec) != ym:
            continue
        try:
            amt = round(float(rec.get("amount_eur", 0) or 0), 2)
        except (TypeError, ValueError):
            continue
        if amt <= 0 or rec.get("pending_unfunded"):
            continue
        s = sessions.get(rec.get("job_id", "")) if rec.get("job_id") else None
        k = _lang_key(s.get("lang", "")) if s else "?"
        if k == "?":
            meta["senza_lingua"] += 1
            meta["senza_lingua_eur"] = round(meta["senza_lingua_eur"] + amt, 2)
        eur[k] = round(eur[k] + amt, 2)
        pagamenti[k] += 1

    incassi = ripartizione(eur, key_name="lingua")
    for row in incassi["righe"]:
        row["pagamenti"] = pagamenti[row["lingua"]]
    return {
        "libri": ripartizione(libri, key_name="lingua"),
        "libri_free": ripartizione(libri_free, key_name="lingua"),
        "incassi": incassi,
        "meta": meta,
    }


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

    # Mix linguistico: dove si concentrano i libri (per coorte) e il fatturato.
    res["lingue"] = language_stats(sessions, payments, ym=_ym_from_name(path))

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
        "lingue": {"libri": ripartizione({}, key_name="lingua"),
                   "libri_free": ripartizione({}, key_name="lingua"),
                   "incassi": ripartizione({}, key_name="lingua"),
                   "meta": {"senza_lingua": 0, "senza_lingua_eur": 0.0,
                            "libri_senza_lingua": 0,
                            "libri_free_senza_lingua": 0}},
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


# ---------------------------------------------------------------------------
# Power user (digest admin): client con molti avvii a voce STANDARD nelle 24h
# ---------------------------------------------------------------------------

def grey_source(filename):
    """Indizio (solo indizio) di provenienza del file dal nome: le shadow
    library lasciano il proprio marchio nel nome del file scaricato. Nessun
    blocco: pura osservabilita' nel digest admin."""
    f = (filename or "").lower()
    if "z-lib" in f or "1lib" in f or "zlibrary" in f or "z-library" in f:
        return "zlib"
    if "anna" in f and "archive" in f:
        return "anna"
    if "libgen" in f:
        return "libgen"
    return ""


def power_users(paths, since, min_jobs=5, quota_table=None, top=10, month_ym=None):
    """Client con >= `min_jobs` avvii a voce STANDARD (GENERATE + REUSE) dal
    datetime `since` in poi, ordinati per avvii decrescenti (max `top`).

    `paths`: file activity_YYYY-MM.log da leggere (mese corrente, piu' il
    precedente a cavallo del mese). `quota_table`: output di
    `free_tts_quota.month_table()` per caratteri e job oltre quota del mese.
    `month_ym`: mese (YYYY-MM) dei contatori mensili; default = mese di `since`.
    Identita' = client_id, fallback `ip:<ip>` (come `user_key`). Nessun dato
    personale oltre a cio' che il log gia' contiene.
    """
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")
    month_ym = month_ym or since.strftime("%Y-%m")
    users = {}
    for path in paths:
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                fl = split_line(line.strip())
                if not fl:
                    continue
                sid, ts, fn, op, cid, ip, voice, lang, plat = fl
                key = cid or (f"ip:{ip}" if ip else "")
                if not key:
                    continue
                u = users.get(key)
                if u is None:
                    u = users[key] = {
                        "jobs_24h": 0, "reuse_24h": 0, "premium_24h": 0,
                        "gate_24h": 0, "block_24h": 0, "books_month": 0,
                        "starts_month": 0, "ips": set(), "platforms": Counter(),
                        "sources": Counter(), "langs": Counter(),
                    }
                recent = ts >= since_str
                in_month = ts.startswith(month_ym)
                premium = is_premium_voice(voice)
                if op == "GENERATE":
                    if premium:
                        if recent:
                            u["premium_24h"] += 1
                    else:
                        if in_month:
                            u["starts_month"] += 1
                        if recent:
                            u["jobs_24h"] += 1
                        if lang:
                            u["langs"][_lang_key(lang)] += 1
                elif op == "REUSE":
                    if in_month:
                        u["starts_month"] += 1
                    if recent:
                        u["jobs_24h"] += 1
                        u["reuse_24h"] += 1
                elif op == "COMPLETE":
                    if in_month and not premium:
                        u["books_month"] += 1
                elif op == "QUOTA_GATE":
                    if recent:
                        u["gate_24h"] += 1
                elif op == "QUOTA_BLOCK":
                    if recent:
                        u["block_24h"] += 1
                elif op == "ANALYZE":
                    src = grey_source(fn)
                    if src and in_month:
                        u["sources"][src] += 1
                if recent and ip:
                    u["ips"].add(ip)
                if plat:
                    u["platforms"][plat] += 1
    qt = quota_table or {}
    rows = []
    for key, u in users.items():
        if u["jobs_24h"] < max(1, int(min_jobs or 1)):
            continue
        q = qt.get(key) if isinstance(qt.get(key), dict) else {}
        rows.append({
            "client_id": key,
            "jobs_24h": u["jobs_24h"],
            "reuse_24h": u["reuse_24h"],
            "premium_24h": u["premium_24h"],
            "gate_24h": u["gate_24h"],
            "block_24h": u["block_24h"],
            "books_month": u["books_month"],
            "starts_month": u["starts_month"],
            "chars_month": int(q.get("chars", 0) or 0),
            "gated_month": int(q.get("gated", 0) or 0),
            "ips_24h": len(u["ips"]),
            "platform": (u["platforms"].most_common(1) or [("", 0)])[0][0],
            "langs": [l for l, _n in u["langs"].most_common(3) if l],
            "sources": dict(u["sources"]),
        })
    rows.sort(key=lambda r: (-r["jobs_24h"], -r["books_month"], r["client_id"]))
    return rows[:max(1, int(top or 1))]
