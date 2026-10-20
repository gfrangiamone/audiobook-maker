# archive_tolerance.py
"""Tolleranza sull'eccedenza dell'archivio degli abbonati.

Quando l'archivio di un account supera la sua quota (regalo scaduto, consenso
ritirato, libri oltre il piano) non si toglie niente subito: `sweep` manda
un'email con l'elenco dei libri piu' vecchi che andrebbero tolti e apre una
tolleranza di ABM_ARCHIVE_TOLERANCE_DAYS giorni (`accounts.archive_over_since`),
con un promemoria ABM_ARCHIVE_TOLERANCE_REMIND_DAYS giorni prima della fine.
Se a scadenza l'archivio e' ancora oltre la quota si tolgono i libri piu' vecchi,
non uno di piu' di quelli che servono a rientrare. Senza email partita la
tolleranza non si apre e non si cancella niente; rientrando nella quota la
tolleranza si chiude da sola.

L'elenco dell'avviso vale per l'eccedenza annunciata, usato - quota
(`accounts.archive_notice_excess`). I libri nuovi entrano sempre dopo quelli che
ci sono e quelli che ci sono si possono togliere in qualsiasi momento: con
un'eccedenza non oltre quella annunciata il piano dal piu' vecchio e' quindi un
sottoinsieme dei libri elencati. Se a tolleranza aperta l'eccedenza supera quella
annunciata (quota scesa per regalo scaduto o consenso ritirato, archivio cresciuto)
l'elenco non copre piu' quello che si cancellerebbe: parte un nuovo avviso con
elenco e scadenza ricalcolati e la finestra riparte da quell'istante. Finche'
quell'avviso non e' partito non si cancella niente, nemmeno oltre la vecchia
scadenza. Se l'eccedenza cala (quota risalita, libri tolti dall'utente) non parte
niente e l'eccedenza annunciata non cambia: ritirare e riattivare il consenso non
allunga la finestra oltre quella dell'ultimo avviso. Eccedenza annunciata NULL
(stato migrato): niente da confrontare.

Un giro manda al piu' MAX_NOTICES_PER_SWEEP email (anche i tentativi falliti):
gli account oltre il tetto aspettano il giro dopo, senza cambiare stato.

Un job tolto perde la protezione (i file tornano alla retention ordinaria), un
libro caricato dall'app si cancella da R2 e poi dal DB: al primo errore si
ferma, la tolleranza resta aperta e il giro dopo riprova.

Modulo di servizio: dipende da `accounts`, `user_archive`, `email_service` e dalla
stdlib. Lo chiama il loop di cleanup (vedi cleanup._cleanup_loop).
"""
import time

import accounts
import email_service
import user_archive

SWEEP_INTERVAL_SEC = 3600
MAX_NOTICES_PER_SWEEP = 20      # email (avvisi, riavvii, promemoria) per giro; si legge a ogni giro
_sweep_state = {"at": 0.0}
_DAY = 86400


def _day(ts):
    """Data UTC `YYYY-MM-DD` di un epoch, come la mostrano le email."""
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _plan(entries, excess):
    """Le voci piu' vecchie (`entries` e' gia' in ordine) che bastano a liberare
    `excess` byte, e nessuna di piu'."""
    out, freed = [], 0
    for entry in entries:
        if freed >= excess:
            break
        out.append(entry)
        freed += entry["bytes"]
    return out


def _mail_args(plan, deadline, quota, used):
    return {"books": [(e["title"], accounts.format_bytes(e["bytes"])) for e in plan],
            "deadline": _day(deadline), "quota": accounts.format_bytes(quota),
            "used": accounts.format_bytes(used),
            "manage_url": email_service.BASE_URL + "/account"}


def _warn(acct, what, out):
    out["errors"] += 1
    print(f"WARNING archive_tolerance: {what} per l'account {acct['id']}", flush=True)


def _take_slot(budget, out):
    """Un posto fra le email di questo giro; a tetto raggiunto False e il rinvio si conta."""
    if budget["left"] <= 0:
        out["deferred"] += 1
        return False
    budget["left"] -= 1
    return True


def _start(acct, plan, quota, used, now, out, budget, restart=False):
    """Apre la tolleranza (o la riapre, `restart`: l'eccedenza e' cresciuta oltre
    quella annunciata) solo se l'avviso e' partito: senza email non si cancella.
    Salva l'eccedenza annunciata (usato - quota)."""
    if not _take_slot(budget, out):
        return
    deadline = now + accounts.archive_tolerance_days() * _DAY
    if not email_service.send_archive_over(acct["email"], acct["lang"], off=(quota == 0),
                                           **_mail_args(plan, deadline, quota, used)):
        _warn(acct, "nuovo avviso per eccedenza cresciuta non inviato: non si toglie niente fino a "
                    "quando non parte, si riprova al giro dopo" if restart
              else "avviso di inizio tolleranza non inviato, la tolleranza non parte", out)
        return
    accounts.set_archive_tolerance(acct["id"], now, 1, notice_excess=used - quota)
    out["started"] += 1


def _remind(acct, plan, quota, used, now, deadline, out, budget):
    """Promemoria una volta sola, negli ultimi ABM_ARCHIVE_TOLERANCE_REMIND_DAYS giorni."""
    if acct["archive_notice_stage"] != 1:
        return
    if now < deadline - accounts.archive_tolerance_remind_days() * _DAY:
        return
    if not _take_slot(budget, out):
        return
    if not email_service.send_archive_remind(acct["email"], acct["lang"],
                                             **_mail_args(plan, deadline, quota, used)):
        _warn(acct, "promemoria non inviato, si riprova al giro dopo", out)
        return
    accounts.set_archive_tolerance(acct["id"], acct["archive_over_since"], 2,
                                   notice_excess=acct.get("archive_notice_excess"))
    out["reminded"] += 1


def _evict_entry(account_id, entry, now):
    """Toglie una voce dall'archivio; False se non e' stato possibile (R2 giu')."""
    if entry["kind"] == "job":
        return (user_archive.purge_job_links(account_id, entry["id"])
                and accounts.evict_archived_job(entry["id"], now))
    item = user_archive.get_item(account_id, entry["id"])
    return item is None or user_archive.purge_item(item)


def _evict(acct, plan, quota, now, out):
    for entry in plan:
        if not _evict_entry(acct["id"], entry, now):
            _warn(acct, f"{entry['kind']} {entry['id']} non tolto, si riprova al giro dopo", out)
            return
        out["evicted"] += 1
    if accounts.archive_usage(acct["id"])[0] <= quota:
        accounts.set_archive_tolerance(acct["id"], None, 0)


def _check_account(acct, now, out, budget):
    acct = accounts.get(acct["id"])         # stato di adesso: le email dei giri prima hanno richiesto tempo
    if acct is None or acct.get("deleted_at") is not None:
        return
    quota = accounts.archive_quota_for(acct, now)
    used = accounts.archive_usage(acct["id"])[0]
    since = acct.get("archive_over_since")
    if used <= quota:
        if since is not None:
            accounts.set_archive_tolerance(acct["id"], None, 0)
            out["cleared"] += 1
        return
    plan = _plan(accounts.archive_entries(acct["id"]), used - quota)
    if not plan:                            # oltre la quota solo per upload ancora aperti: niente da togliere
        return
    if since is None:
        _start(acct, plan, quota, used, now, out, budget)
        return
    announced = acct.get("archive_notice_excess")
    if announced is not None and used - quota > int(announced):     # NULL (stato migrato): niente da confrontare
        _start(acct, plan, quota, used, now, out, budget, restart=True)
        return                              # mai cancellare con un elenco annunciato piu' corto
    deadline = int(since) + accounts.archive_tolerance_days() * _DAY
    if now < deadline:
        _remind(acct, plan, quota, used, now, deadline, out, budget)
        return
    _evict(acct, plan, quota, now, out)


def sweep(now=None, force=False):
    """Un giro della tolleranza (dal loop di cleanup, al piu' ogni
    SWEEP_INTERVAL_SEC; `force` salta l'attesa): riporta a `free` i regali
    scaduti e poi, per ogni account con archivio, avvisa, ricorda o toglie.
    Un errore su un account non ferma gli altri; oltre MAX_NOTICES_PER_SWEEP email
    gli account che ne servono aspettano il giro dopo (`deferred`).
    Ritorna {"gifts_expired", "started", "reminded", "evicted", "cleared", "errors", "deferred"}
    (`started` conta anche i riavvii per eccedenza cresciuta)."""
    t = int(time.time() if now is None else now)
    out = dict.fromkeys(("gifts_expired", "started", "reminded", "evicted", "cleared", "errors",
                         "deferred"), 0)
    if not force and t - _sweep_state["at"] < SWEEP_INTERVAL_SEC:
        return out
    _sweep_state["at"] = t
    if not accounts.enabled():
        return out
    out["gifts_expired"] = accounts.expire_gifts(t)
    budget = {"left": MAX_NOTICES_PER_SWEEP}
    for acct in accounts.archive_accounts_to_check():
        try:
            _check_account(acct, t, out, budget)
        except Exception as e:  # noqa: BLE001
            out["errors"] += 1
            print(f"[archive_tolerance] account {acct['id']}: {type(e).__name__}: {e}", flush=True)
    if out["deferred"]:
        print(f"[archive_tolerance] tetto di {MAX_NOTICES_PER_SWEEP} email per giro: "
              f"{out['deferred']} account rinviati al giro dopo", flush=True)
    if any(out.values()):
        print(f"[archive_tolerance] sweep: {out}", flush=True)
    return out
