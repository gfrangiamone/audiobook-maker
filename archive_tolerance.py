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

Si toglie solo quello che l'ultima email ha elencato (`accounts.archive_notice_ids`: avviso,
riavvio o promemoria): se a tolleranza aperta il piano ricalcolato contiene un libro che
quell'email non elencava (quota scesa, archivio cresciuto, libro elencato tolto dall'utente,
upload chiuso) parte un nuovo avviso con elenco e scadenza ricalcolati e la finestra riparte da
quell'istante, senza togliere niente finche' non e' partito. Solo con le chiavi annunciate NULL
(stato migrato) non c'e' niente da confrontare; se sono illeggibili valgono l'insieme vuoto
(nessun libro elencato): nuovo avviso, mai lo sfratto di un libro che l'email non elencava.

Un giro manda al piu' MAX_NOTICES_PER_SWEEP email (anche i tentativi falliti):
gli account oltre il tetto aspettano il giro dopo, senza cambiare stato. Il giro dopo
riparte dall'account successivo all'ultimo che ha preso un posto (cursore in memoria,
`_sweep_state["cursor"]`): con la posta che rifiuta per i primi account in ordine di id i
loro tentativi falliti non occupano tutti i posti a ogni giro lasciando gli altri senza
avviso. Dopo un riavvio il cursore riparte dall'inizio.

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
_sweep_state = {"at": 0.0, "cursor": None}
_DAY = 86400


def _rotate(accts, cursor):
    """`accts` (in ordine di id) ripartendo dal primo con id oltre `cursor`; senza cursore
    l'ordine resta com'e'."""
    if cursor is None:
        return accts
    return [a for a in accts if a["id"] > cursor] + [a for a in accts if a["id"] <= cursor]


def _keys(plan):
    """Chiavi `job:<id>`/`item:<id>` delle voci di un piano (come le salva `accounts`)."""
    return {f"{e['kind']}:{e['id']}" for e in plan}


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
            "deadline": accounts.utc_day(deadline), "quota": accounts.format_bytes(quota),
            "used": accounts.format_bytes(used),
            "manage_url": email_service.BASE_URL + "/account"}


def _warn(acct, what, out, level="WARNING"):
    out["errors"] += 1
    print(f"{level} archive_tolerance: {what} per l'account {acct['id']}", flush=True)


def _take_slot(budget, out):
    """Un posto fra le email di questo giro; a tetto raggiunto False e il rinvio si conta."""
    if budget["left"] <= 0:
        out["deferred"] += 1
        return False
    budget["left"] -= 1
    return True


def _start(acct, plan, quota, used, now, out, budget, restart=False):
    """Apre la tolleranza (o la riapre, `restart`: il piano esce dall'ultimo elenco inviato)
    solo se l'avviso e' partito: senza email non si cancella. Salva le chiavi del piano."""
    if not _take_slot(budget, out):
        return
    deadline = now + accounts.archive_tolerance_days() * _DAY
    if not email_service.send_archive_over(acct["email"], acct["lang"], off=(quota == 0),
                                           **_mail_args(plan, deadline, quota, used)):
        _warn(acct, "nuovo avviso per un elenco diverso non inviato: non si toglie niente fino a "
                    "quando non parte, si riprova al giro dopo" if restart
              else "avviso di inizio tolleranza non inviato, la tolleranza non parte", out)
        return
    accounts.set_archive_tolerance(acct["id"], now, 1, notice_ids=_keys(plan))
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
    accounts.set_archive_tolerance(acct["id"], acct["archive_over_since"], 2, notice_ids=_keys(plan))
    out["reminded"] += 1


def _evict_entry(account_id, entry, now):
    """Toglie una voce dall'archivio; False se non e' stato possibile (R2 giu')."""
    if entry["kind"] == "job":
        return (user_archive.purge_job_links(account_id, entry["id"])
                and accounts.evict_archived_job(entry["id"], now))
    item = user_archive.get_item(account_id, entry["id"])
    return item is None or user_archive.purge_item(item)


def _evict(acct, plan, quota, now, out, announced):
    """Toglie il piano a scadenza. Difesa in profondita': `_check_account` riavvia prima se il piano
    esce dall'ultimo elenco, quindi qui non succede; se succede non si toglie niente."""
    stray = [] if announced is None else sorted(_keys(plan) - announced)
    if stray:
        _warn(acct, f"piano di sfratto fuori dall'ultimo elenco inviato ({', '.join(stray)}): "
                    "niente tolto", out, level="ERROR")
        return
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
    announced = accounts.archive_notice_keys(acct)      # None (stato migrato): niente da confrontare; JSON rotto: set()
    if announced is not None and not _keys(plan) <= announced:
        _start(acct, plan, quota, used, now, out, budget, restart=True)
        return                              # mai cancellare (ne' aspettare la scadenza) con un elenco diverso
    deadline = int(since) + accounts.archive_tolerance_days() * _DAY
    if now < deadline:
        _remind(acct, plan, quota, used, now, deadline, out, budget)
        return
    _evict(acct, plan, quota, now, out, announced)


def sweep(now=None, force=False):
    """Un giro della tolleranza (dal loop di cleanup, al piu' ogni
    SWEEP_INTERVAL_SEC; `force` salta l'attesa): riporta a `free` i regali
    scaduti e poi, per ogni account con archivio, avvisa, ricorda o toglie.
    Un errore su un account non ferma gli altri; oltre MAX_NOTICES_PER_SWEEP email
    gli account che ne servono aspettano il giro dopo (`deferred`), che riparte
    dall'account dopo l'ultimo che ha preso un posto (`_rotate`). Le cancellazioni
    a scadenza non prendono posto.
    Ritorna {"gifts_expired", "started", "reminded", "evicted", "cleared", "errors", "deferred"}
    (`started` conta anche i riavvii per un elenco diverso)."""
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
    for acct in _rotate(accounts.archive_accounts_to_check(), _sweep_state["cursor"]):
        slots = budget["left"]
        try:
            _check_account(acct, t, out, budget)
        except Exception as e:  # noqa: BLE001
            out["errors"] += 1
            print(f"[archive_tolerance] account {acct['id']}: {type(e).__name__}: {e}", flush=True)
        if budget["left"] < slots:          # ha preso un posto (anche se l'invio e' fallito)
            _sweep_state["cursor"] = acct["id"]
    if out["deferred"]:
        print(f"[archive_tolerance] tetto di {MAX_NOTICES_PER_SWEEP} email per giro: "
              f"{out['deferred']} account rinviati al giro dopo", flush=True)
    if any(out.values()):
        print(f"[archive_tolerance] sweep: {out}", flush=True)
    return out
