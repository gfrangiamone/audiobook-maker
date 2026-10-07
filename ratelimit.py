"""ratelimit — finestre scorrevoli, lockout e throttle condivisi.

Modulo foglia (solo stdlib). Prima lo stesso algoritmo (lista di timestamp
`time.time()`, finestre a 60 e 3600 s, `retry = finestra - int(now - primo)`)
era scritto a mano in `audiobook_app._ip_rl_check`, `payment._voucher_rl_check`
(due volte: IP e globale), nei throttle delle email admin e nei contatori di
download. Qui ci sono solo le funzioni pure sullo stato del chiamante: la
disciplina di lock resta a chi possiede il dizionario, come prima, e lo
stato resta ispezionabile dai test (`audiobook_app._ip_rl_buckets`).
"""
import time


def window_check(hits, limits, now=None, *, record=True):
    """Finestra scorrevole su una lista di timestamp.

    `limits`: sequenza di (finestra_sec, max_colpi), in ordine di finestra
    crescente. Ritorna `(ok, retry_after_sec, indice_limite, hits_potati)`:
    con `ok=False` `indice_limite` e' il limite che ha bloccato e
    `retry_after_sec >= 1`; con `ok=True` l'indice e' -1 e, se `record`, il
    colpo corrente e' gia' stato aggiunto alla lista ritornata.
    """
    now = time.time() if now is None else now
    longest = max((w for w, _ in limits), default=0)
    hits = [t for t in hits if now - t < longest]
    for i, (win, cap) in enumerate(limits):
        in_win = [t for t in hits if now - t < win]
        if len(in_win) >= cap:
            retry = win - int(now - in_win[0])
            return False, max(1, retry), i, hits
    if record:
        hits.append(now)
    return True, 0, -1, hits


def sliding_check(store, key, limits, now=None, *, record=True):
    """`window_check` su `store[key]` (dict chiave -> lista di timestamp),
    aggiornando lo store. Ritorna (ok, retry_after_sec, indice_limite)."""
    ok, retry, idx, hits = window_check(store.get(key, []), limits, now, record=record)
    store[key] = hits
    return ok, retry, idx


def window_record(store, key, now=None):
    """Registra un colpo senza controllare (per chi controlla prima piu'
    finestre e registra solo se tutte passano)."""
    now = time.time() if now is None else now
    store.setdefault(key, []).append(now)


def lockout_remaining(store, key, now=None):
    """Secondi di lockout residui per `key` (0 se libero).
    `store[key] = {"fail_count": n, "lockout_until": ts}`."""
    now = time.time() if now is None else now
    info = store.get(key)
    if info and info.get("lockout_until", 0) > now:
        return int(info["lockout_until"] - now)
    return 0


def lockout_record(store, key, success, *, max_fails, lock_sec, now=None):
    """Aggiorna il contatore di fallimenti di `key`: un successo lo azzera;
    al `max_fails`-esimo fallimento scatta un lockout di `lock_sec` e il
    contatore riparte da zero. Ritorna True se il lockout e' appena scattato."""
    now = time.time() if now is None else now
    if success:
        store.pop(key, None)
        return False
    info = store.get(key) or {"fail_count": 0, "lockout_until": 0}
    info["fail_count"] = info.get("fail_count", 0) + 1
    tripped = False
    if info["fail_count"] >= max_fails:
        info["lockout_until"] = now + lock_sec
        info["fail_count"] = 0
        tripped = True
    store[key] = info
    return tripped


def throttle_ok(last_sent, key, min_interval, now=None):
    """True (e registra l'invio) se sono passati almeno `min_interval`
    secondi dall'ultimo invio per `key`; altrimenti False senza registrare.
    `last_sent`: dict chiave -> timestamp dell'ultimo invio."""
    now = time.time() if now is None else now
    if (now - last_sent.get(key, 0.0)) < min_interval:
        return False
    last_sent[key] = now
    return True


def cooldown_counter(store, key, *, cooldown_sec, max_count, now=None):
    """Contatore con cooldown fra un uso e l'altro e tetto totale (download).
    Ritorna `("cooldown", secondi)`, `("exhausted", None)` se il tetto era
    gia' raggiunto (lo stato resta: chi chiama decide se cancellare),
    `("last", 0)` se questo e' l'ultimo uso permesso, `("ok", residui)`.
    `store[key] = {"count": n, "last_download": ts}`."""
    now = time.time() if now is None else now
    rec = store.get(key)
    if rec:
        elapsed = now - rec["last_download"]
        if elapsed < cooldown_sec:
            return "cooldown", int(cooldown_sec - elapsed)
    current = rec["count"] if rec else 0
    if current >= max_count:
        return "exhausted", None
    new_count = current + 1
    if rec:
        rec["count"] = new_count
        rec["last_download"] = now
    else:
        store[key] = {"count": new_count, "last_download": now}
    if new_count >= max_count:
        return "last", 0
    return "ok", max_count - new_count
