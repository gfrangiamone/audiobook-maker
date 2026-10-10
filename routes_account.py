"""routes_account — accesso con magic link e pagina account (E3, seam account,
2026-10-10).

Blueprint `account`: `/api/auth/{request,verify,logout,logout_all,
logout_device,me}`, `/auth/<token>` (magic link con anti-CSRF), `/account`
(pagina), `/api/account/jobs` (elenco con download e stato riconciliato),
`/api/account/jobs/delete`, `/api/account/delete_request`,
`/api/account/delete_confirm`; con i cookie di sessione e CSRF, l'invio
dei codici, la cancellazione dell'account, le righe dei job e le voci
dell'utente. Spostato pari pari da `audiobook_app`; lo stato vive in
`accounts`, le pagine in `account_page`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app), gli helper in FUNCS e i valori
`jobs`, `BASE_URL`; per riferimento il lock dei job, i testi delle pagine
account e i nomi dei cookie e dell'header del client. Non importa
`audiobook_app`.
"""
import hmac
import secrets
import time

from flask import Blueprint, Response, abort, g, jsonify, redirect, request

import account_page
import accounts
import email_service
import i18n as _i18n
import pending_jobs
import routes_mobile
import routes_voice_clone
import token_store as _tkstore
import voice_clone
from client_identity import EMAIL_RE as _ACCT_EMAIL_RE

bp = Blueprint("account", __name__)

_cfg = {}
_jobs_lock = None
_ACCT_PAGES_I18N = None
_ACCOUNT_SESSION_COOKIE = None
_LANG_COOKIE = None
_MOBILE_CID_HEADER = None

FUNCS = ['client_ip', '_smtp_available', '_hash_ip', '_get_browser_lang', '_ip_rl_check', '_apply_no_cache', '_effective_retention_for_token_info', '_get_client_id', '_log_activity']
VALUES = ('jobs', 'base_url')


def configure(*, _jobs_lock, _ACCT_PAGES_I18N, _ACCOUNT_SESSION_COOKIE, _LANG_COOKIE, _MOBILE_CID_HEADER, **fns):
    """`fns`: una funzione per ogni nome in FUNCS e VALUES (la app passa
    lambda che risolvono i suoi globali a ogni chiamata)."""
    missing = [n for n in FUNCS + list(VALUES) if n not in fns]
    assert not missing, f"routes_account.configure: mancano {missing}"
    _cfg.update(fns)
    globals()["_jobs_lock"] = _jobs_lock
    globals()["_ACCT_PAGES_I18N"] = _ACCT_PAGES_I18N
    globals()["_ACCOUNT_SESSION_COOKIE"] = _ACCOUNT_SESSION_COOKIE
    globals()["_LANG_COOKIE"] = _LANG_COOKIE
    globals()["_MOBILE_CID_HEADER"] = _MOBILE_CID_HEADER


# Valori della app usati dal codice spostato: risolti a ogni chiamata.
def _jobs():
    return _cfg["jobs"]()

def _base_url():
    return _cfg["base_url"]()


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def client_ip(*a, **k):
    return _cfg["client_ip"](*a, **k)

def _smtp_available(*a, **k):
    return _cfg["_smtp_available"](*a, **k)

def _hash_ip(*a, **k):
    return _cfg["_hash_ip"](*a, **k)

def _get_browser_lang(*a, **k):
    return _cfg["_get_browser_lang"](*a, **k)

def _ip_rl_check(*a, **k):
    return _cfg["_ip_rl_check"](*a, **k)

def _apply_no_cache(*a, **k):
    return _cfg["_apply_no_cache"](*a, **k)

def _effective_retention_for_token_info(*a, **k):
    return _cfg["_effective_retention_for_token_info"](*a, **k)

def _get_client_id(*a, **k):
    return _cfg["_get_client_id"](*a, **k)

def _log_activity(*a, **k):
    return _cfg["_log_activity"](*a, **k)


def _acct_err(code, msg, status, **extra):
    return jsonify({"error": msg, "error_code": code, **extra}), status


def _acct_gate():
    """None se la feature e' usabile, altrimenti la risposta 404 da ritornare."""
    if not accounts.enabled() or not _smtp_available():
        return _acct_err("account_disabled", "Accounts are not available", 404)
    return None


def _acct_session_token():
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(_ACCOUNT_SESSION_COOKIE, "")


def _current_account():
    """Account della richiesta corrente o None. Cache in flask.g."""
    if hasattr(g, "_acct"):
        return g._acct
    acct = None
    try:
        if accounts.enabled():
            acct = accounts.resolve_session(_acct_session_token())
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _current_account: {e}", flush=True)
    g._acct = acct
    return acct


def _acct_cookie_secure():
    if (_base_url() or "").startswith("https"):
        return True
    return (request.headers.get("X-Forwarded-Proto") or "").lower() == "https"


def _acct_set_cookie(resp, token):
    resp.set_cookie(_ACCOUNT_SESSION_COOKIE, token, max_age=accounts.SESSION_DAYS * 86400,
                    httponly=True, samesite="Lax", secure=_acct_cookie_secure(), path="/")


def _acct_clear_cookie(resp):
    resp.set_cookie(_ACCOUNT_SESSION_COOKIE, "", max_age=0, expires=0, httponly=True,
                    samesite="Lax", secure=_acct_cookie_secure(), path="/")


# --- anti login-CSRF sul magic link ------------------------------------
# Il POST di /auth/<token> apre una sessione: senza guardia un sito terzo puo'
# auto-inviare un form verso /auth/<token_dell_attaccante> e il browser della
# vittima riceve Set-Cookie: abm_session (SameSite=Lax impedisce di INVIARE
# cookie cross-site, non di IMPOSTARLI). La vittima si ritrova loggata
# nell'account dell'attaccante e i suoi job successivi vengono notificati a
# quell'indirizzo. La guardia e' un double-submit cookie legato al BROWSER che
# ha aperto il link: un nonce derivato dal token non servirebbe, perche' il
# token e' dell'attaccante e il nonce sarebbe leggibile dal suo stesso GET.
_ACCT_CSRF_COOKIE = "abm_auth_csrf"


def _acct_set_csrf_cookie(resp, value):
    resp.set_cookie(_ACCT_CSRF_COOKIE, value, max_age=accounts.CODE_TTL_MIN * 60,
                    httponly=True, samesite="Strict", secure=_acct_cookie_secure(),
                    path="/auth")


def _acct_clear_csrf_cookie(resp):
    resp.set_cookie(_ACCT_CSRF_COOKIE, "", max_age=0, expires=0, httponly=True,
                    samesite="Strict", secure=_acct_cookie_secure(), path="/auth")


def _acct_origin_ok():
    """False se la richiesta arriva dichiaratamente da un'altra origine.

    Header assenti = consentito: su una navigazione diretta (click sul link
    dell'email) alcuni browser non mandano ne' Origin ne' Referer.
    Ammesse due origini: quella dichiarata in BASE_URL (se valorizzata) e
    quella della richiesta stessa (`host_url`), perche' l'host arriva dal
    browser e non e' scrivibile da una pagina terza — e' lo stesso criterio
    del guard globale `_csrf_protect`. Serve a non chiudere fuori un
    deployment raggiungibile anche su un hostname diverso da ABM_BASE_URL."""
    origin = (request.headers.get("Origin") or "").strip()
    if origin.lower() == "null":
        return False
    src = origin or (request.headers.get("Referer") or "").strip()
    if not src:
        return True
    from urllib.parse import urlsplit
    a = urlsplit(src)
    allowed = {(urlsplit(request.host_url).scheme, urlsplit(request.host_url).netloc)}
    base = (_base_url() or "").strip()
    if base:
        b = urlsplit(base)
        allowed.add((b.scheme, b.netloc))
    return (a.scheme, a.netloc) in allowed


def _acct_csrf_ok():
    """Double-submit: il campo nascosto del form deve combaciare con il cookie
    posato dal GET sullo stesso browser."""
    sent = (request.form.get("csrf") or "").strip()
    cookie = (request.cookies.get(_ACCT_CSRF_COOKIE) or "").strip()
    if not sent or not cookie:
        return False
    return hmac.compare_digest(sent, cookie)


def _acct_log(op, email, extra=""):
    """Business log senza email in chiaro: sid = acct-<hash8>."""
    try:
        sid = "acct-" + accounts.email_hash(email)[:8]
        _log_activity(sid, extra, op, client_id=_get_client_id(), client_ip=client_ip())
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _acct_log: {e}", flush=True)


def _acct_page_lang(*preferred):
    """Lingua delle pagine account: scelta nell'app (`?lang=`, poi cookie
    `abm_lang`), poi quelle passate dal chiamante (lingua dell'account o
    del codice), poi Accept-Language, poi inglese. I valori non tradotti
    sono saltati, non degradano a inglese."""
    return _i18n.choose_lang([request.args.get("lang"), request.cookies.get(_LANG_COOKIE),
                              *preferred, _get_browser_lang()], _ACCT_PAGES_I18N)


def _acct_txt(lang):
    return _i18n.pick(_ACCT_PAGES_I18N, lang)


def _acct_html(html_doc, status=200):
    resp = _apply_no_cache(Response(html_doc, status=status, mimetype="text/html"))
    resp.headers["Vary"] = "Accept-Language, Cookie"
    return resp


def _acct_send_code(email, purpose, lang):
    """Genera e spedisce il codice. Sempre silenzioso: risposta neutra a monte."""
    try:
        out = accounts.request_code(email, purpose, lang, ip_hash=_hash_ip(client_ip()),
                                    ua=request.headers.get("User-Agent", ""))
        if out is None:
            return
        token, code = out
        if accounts.is_review_login(email, purpose):
            # Account demo dei revisori store: codice fisso, niente email.
            _acct_log("ACCOUNT_REVIEW_CODE", email)
            return
        link = f"{_base_url()}/auth/{token}" + ("?p=delete" if purpose == "delete" else "")
        email_service.send_account_code(
            email, lang, code=code, link_url=link,
            purpose=purpose, minutes=accounts.CODE_TTL_MIN)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _acct_send_code: {type(e).__name__}: {e}", flush=True)


def _acct_do_delete(acct, lang):
    """Cancellazione confermata: DB, log, email di cortesia (best-effort)."""
    accounts.delete_account(acct["id"])
    _acct_log("ACCOUNT_DELETE", acct["email"])
    try:
        email_service.send_account_deleted(acct["email"], acct.get("lang") or lang)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING send_account_deleted: {e}", flush=True)


def _acct_device_name(raw=None):
    """Nome del dispositivo mostrato in «I tuoi dispositivi»: quello dichiarato
    dal client (app) o quello dedotto dallo User-Agent («Chrome · Windows»);
    se non si riconosce nulla resta lo User-Agent grezzo, troncato."""
    raw = str(raw or "").strip()[:80]
    if raw:
        return raw
    ua = request.headers.get("User-Agent") or ""
    return voice_clone.device_name_from_ua(ua) or ua[:80]


def _acct_login_response(acct, payload=None, device_name=None):
    """Apre la sessione, logga, imposta il cookie. `session_token` solo per
    l'app (header X-ABM-Cid), che non usa i cookie."""
    device_name = _acct_device_name(device_name)
    token = accounts.open_session(acct["id"],
                                  device_name=device_name,
                                  ip_hash=_hash_ip(client_ip()))
    _acct_log("ACCOUNT_LOGIN", acct["email"])
    body = {"ok": True, "email": acct["email"], "lang": acct.get("lang") or "en",
            "plan": acct.get("plan") or "free"}
    if payload is not None:
        body.update(payload)
    if (request.headers.get(_MOBILE_CID_HEADER) or "").strip():
        body["session_token"] = token
    resp = jsonify(body)
    _acct_set_cookie(resp, token)
    return resp


@bp.route("/api/auth/request", methods=["POST"])
def api_auth_request():
    gate = _acct_gate()
    if gate:
        return gate
    ip = client_ip()
    allowed, retry = _ip_rl_check("auth_request", ip, 5, 30)
    if not allowed:
        return _acct_err("rate_limited", "Too many requests", 429, retry_after=retry)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not _ACCT_EMAIL_RE.match(email):
        return _acct_err("invalid_email", "Invalid email address", 400)
    lang = (data.get("lang") or _get_browser_lang() or "en")[:8]
    _acct_send_code(email, "login", lang)
    return jsonify({"ok": True})


@bp.route("/api/auth/verify", methods=["POST"])
def api_auth_verify():
    gate = _acct_gate()
    if gate:
        return gate
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    device_name = (data.get("device_name") or "").strip()[:80]
    if token:
        status, acct = accounts.verify(token=token, purpose="login")
    elif email and code:
        status, acct = accounts.verify(email=email, code=code, purpose="login")
    else:
        return _acct_err("bad_request", "token or email+code required", 400)
    if status != "ok":
        return _acct_err(status, "Verification failed", 401)
    return _acct_login_response(acct, device_name=device_name or None)


@bp.route("/auth/<token>", methods=["GET", "POST"])
def auth_magic_link(token):
    lang = _acct_page_lang()
    t = _acct_txt(lang)
    if not accounts.enabled() or not _smtp_available():
        return _acct_html(account_page.render_error(t, lang=lang, status_key="none"), 404)
    purpose = "delete" if request.args.get("p") == "delete" else "login"
    if request.method == "GET":
        # Mai consumare al GET: i client di posta pre-aprono i link. Una
        # lettura innocua basta pero' a distinguere un link mai esistito
        # (410) da uno ancora valido in attesa di conferma (200). La lingua
        # segue quella scelta al momento della richiesta (auth_codes.lang,
        # la stessa con cui e' partita l'email), non quella del browser.
        status, info = accounts.peek(token, purpose)
        code_lang = info.get("lang") if info else None
        if code_lang in _ACCT_PAGES_I18N:
            lang = _acct_page_lang(code_lang)
            t = _acct_txt(lang)
        if status != "ok":
            return _acct_html(account_page.render_error(t, lang=lang, status_key=status), 410)
        csrf = secrets.token_urlsafe(16)
        resp = _acct_html(account_page.render_confirm(
            t, lang=lang, purpose=purpose, action_url=request.full_path.rstrip("?"),
            masked_email=account_page.mask_email(info["email"]), csrf=csrf))
        _acct_set_csrf_cookie(resp, csrf)
        return resp
    # Il token NON viene consumato se la conferma non proviene dal browser che
    # ha aperto il link: pagina d'errore generica (nessun indizio all'esterno
    # su validita' o stato del token) e nessun effetto collaterale.
    if not _acct_origin_ok() or not _acct_csrf_ok():
        return _acct_html(account_page.render_error(t, lang=lang, status_key="none"), 403)
    status, acct = accounts.verify(token=token, purpose=purpose)
    if acct and acct.get("lang") in _ACCT_PAGES_I18N:
        lang = _acct_page_lang(acct["lang"])
        t = _acct_txt(lang)
    if status != "ok":
        return _acct_html(account_page.render_error(t, lang=lang, status_key=status), 410)
    if purpose == "delete":
        _acct_do_delete(acct, lang)
        resp = _acct_html(account_page.render_deleted(t, lang=lang))
        _acct_clear_cookie(resp)
        _acct_clear_csrf_cookie(resp)
        return resp
    session_token = accounts.open_session(
        acct["id"], device_name=_acct_device_name(), ip_hash=_hash_ip(client_ip()))
    _acct_log("ACCOUNT_LOGIN", acct["email"])
    resp = redirect("/account", code=302)
    _acct_set_cookie(resp, session_token)
    _acct_clear_csrf_cookie(resp)
    return resp


@bp.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    gate = _acct_gate()
    if gate:
        return gate
    token = _acct_session_token()
    acct = _current_account()
    if token:
        try:
            accounts.revoke_session(token)
        except Exception as e:  # noqa: BLE001
            print(f"WARNING logout: {e}", flush=True)
    if acct:
        _acct_log("ACCOUNT_LOGOUT", acct["email"])
    resp = jsonify({"ok": True})
    _acct_clear_cookie(resp)
    return resp


@bp.route("/api/auth/logout_all", methods=["POST"])
def api_auth_logout_all():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    n = accounts.revoke_all(acct["id"])
    _acct_log("ACCOUNT_LOGOUT_ALL", acct["email"], str(n))
    resp = jsonify({"ok": True, "revoked": n})
    _acct_clear_cookie(resp)
    return resp


@bp.route("/api/auth/logout_device", methods=["POST"])
def api_auth_logout_device():
    """Chiude una sola sessione dell'account (popup «I tuoi dispositivi»).
    L'id e' l'hash della sessione, non il token: mostrarlo non apre nulla.
    Se e' la sessione corrente il cookie viene tolto e il client torna alla
    home (`current: true`)."""
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    data = request.get_json(silent=True) or {}
    sid = str(data.get("id") or "").strip()
    if not sid:
        return _acct_err("bad_request", "id required", 400)
    ok = accounts.revoke_session_id(acct["id"], sid)
    _acct_log("ACCOUNT_LOGOUT_DEVICE", acct["email"], "ok" if ok else "none")
    if sid == (acct.get("session_id") or ""):
        resp = jsonify({"ok": True, "revoked": ok, "current": True})
        _acct_clear_cookie(resp)
        return resp
    return jsonify({"ok": True, "revoked": ok, "current": False})


@bp.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    if not accounts.enabled() or not _smtp_available():
        return jsonify({"logged_in": False, "enabled": False})
    acct = _current_account()
    if not acct:
        return jsonify({"logged_in": False, "enabled": True})
    return jsonify({
        "logged_in": True, "enabled": True, "email": acct["email"],
        "lang": acct.get("lang") or "en", "plan": acct.get("plan") or "free",
        "sessions_count": accounts.sessions_count(acct["id"]),
    })


_ACCT_PER_PAGE = 50


def _download_tokens_index():
    """Indice `job_id -> [(token, info)]` costruito UNA volta per richiesta da
    uno snapshot di _tkstore.download_tokens preso sotto _tkstore.tokens_lock.

    Due motivi, non uno: (a) _tkstore.download_tokens e' mutato dai thread di
    generazione (creazione token a fine job) e dal cleanup, quindi scorrerlo
    senza snapshot e' una `RuntimeError: dictionary changed size during
    iteration` in attesa del momento giusto — lo stesso schema che uccise il
    cleanup._cleanup_loop; (b) lo storico chiama _account_downloads_for per ogni riga
    mostrata, e una scansione lineare per riga costa O(righe x token)."""
    with _tkstore.tokens_lock:
        items = list(_tkstore.download_tokens.items())
    idx = {}
    for tok, ti in items:
        if not isinstance(ti, dict):
            continue
        jid = ti.get("job_id")
        if jid:
            idx.setdefault(jid, []).append((tok, ti))
    return idx


def _account_downloads_for(row, now=None, index=None):
    """Link ancora vivi per una riga dello storico. Il token arriva dalla
    riga (`download_token`) o, per i job adottati dai pagamenti, dalla
    ricerca per job_id nell'indice (`index`, vedi _download_tokens_index;
    se None viene costruito qui). `expires_at` usa la retention
    effettiva del token (protezione no-download compresa)."""
    now = now if now is not None else time.time()
    job_id = row.get("job_id") or ""
    token = row.get("download_token") or ""
    info = _tkstore.download_tokens.get(token) if token else None
    if info is None:
        if index is None:
            index = _download_tokens_index()
        candidates = index.get(job_id) or []
        if candidates:
            token, info = max(candidates, key=lambda kv: float(kv[1].get("created_at") or 0))
    if not isinstance(info, dict) or not token:
        return []
    try:
        expires_at = float(info.get("created_at") or 0) + float(_effective_retention_for_token_info(info))
    except Exception:  # noqa: BLE001
        return []
    if expires_at <= now:
        return []
    base = (_base_url() or "").rstrip("/")
    exp = int(expires_at)
    out = [{"kind": "page", "url": f"{base}/dl/{token}", "expires_at": exp}]
    dl_type = info.get("download_type") or "audio"
    # File assenti su entrambi i tier -> nessun pulsante per quel formato
    # (ma la pagina /dl/<token> resta comunque linkata: puo' mostrare altri
    # formati ancora presenti dello stesso token).
    if dl_type == "optimized_abm":
        if routes_mobile._file_available(info.get("optimized_abm_path") or ""):
            out.append({"kind": "abm", "url": f"{base}/dl/{token}/abm", "expires_at": exp})
    elif dl_type == "translated":
        if routes_mobile._file_available(info.get("translated_path") or ""):
            out.append({"kind": "translated", "url": f"{base}/dl/{token}/translated", "expires_at": exp})
    elif info.get("output_m4b"):
        if routes_mobile._file_available(info.get("output_m4b") or ""):
            out.append({"kind": "m4b", "url": f"{base}/dl/{token}/m4b", "expires_at": exp})
    return out


# Una riga "running" il cui job non esiste piu' (ne' in memoria ne' come
# descrittore di recovery) oltre questa finestra e' persa: la si chiude.
_ACCT_STALE_RUNNING_SEC = 30 * 60
_ACCT_SETTLE_MAP = {"done": "done", "partial": "done", "error": "error",
                    "cancelled": "cancelled", "canceled": "cancelled"}


def _account_settled_status(job_id, row_updated_at, now):
    """Esito da scrivere su una riga di storico ancora "running", o None se il
    job e' (o puo' ancora essere) vivo. Rete di sicurezza per i path che
    escono dalla generazione senza passare da `_set_job_status` su un
    terminale (crash del thread, cancel riportato ad "analyzed", cleanup,
    riavvio senza recovery): senza, il job resterebbe "in corso" per sempre
    nell'area personale web e nell'app."""
    with _jobs_lock:
        job = _jobs().get(job_id)
        st = job.get("status") if isinstance(job, dict) else None
        interrupted = bool(isinstance(job, dict) and job.get("server_interrupted"))
        cancelled = bool(isinstance(job, dict) and job.get("cancelled"))
    if job is not None:
        if st in _ACCT_SETTLE_MAP:
            return "error" if interrupted else _ACCT_SETTLE_MAP[st]
        # Cancel riportato ad "analyzed": il job non sta piu' generando.
        if st == "analyzed" and (cancelled or interrupted):
            return "error" if interrupted else "cancelled"
        return None
    if now - float(row_updated_at or 0) < _ACCT_STALE_RUNNING_SEC:
        return None
    try:
        if pending_jobs.is_active(job_id):
            return None
    except Exception:  # noqa: BLE001  store illeggibile: nel dubbio non chiudere
        return None
    return "error"


def _account_reconcile_running(rows, now):
    for r in rows:
        if r.get("status") != "running":
            continue
        try:
            st = _account_settled_status(r["job_id"], r.get("updated_at"), now)
            if st and accounts.settle_running(r["job_id"], st):
                print(f"[{r['job_id']}] storico account: running -> {st} (riconciliato)",
                      flush=True)
                r["status"] = st
        except Exception as e:  # noqa: BLE001
            print(f"WARNING [{r.get('job_id')}] riconciliazione storico: {e}", flush=True)


def _account_rows_for(acct, page):
    rows, total = accounts.list_jobs(acct["id"], page=page, per_page=_ACCT_PER_PAGE)
    _account_reconcile_running(rows, time.time())
    now = time.time()
    index = _download_tokens_index()
    out = []
    for r in rows:
        d = dict(r)
        d["downloads"] = _account_downloads_for(d, now, index)
        out.append(d)
    return out, total


def _account_voices_for(acct):
    """Voci campionate collegate, non terminali, con link alla gestione
    attuale (/vc/<manage_token>/devices). Best-effort: [] su qualunque errore."""
    try:
        out = []
        for vid in voice_clone.ids_for_email(acct["email"]):
            rec = voice_clone.store().get(vid)
            if rec is None or rec.get("state") in voice_clone._TERMINAL or not rec.get("manage_token"):
                continue
            out.append({"name": rec.get("name") or vid, "url": routes_voice_clone._vc_urls(rec)["manage_url"],
                        "state": rec.get("state") or ""})
        return out
    except Exception:  # noqa: BLE001
        return []


@bp.route("/account", methods=["GET"])
def account_page_view():
    if not accounts.enabled() or not _smtp_available():
        abort(404)
    acct = _current_account()
    if not acct:
        return redirect("/?login=1", code=302)
    try:
        page = max(1, int(request.args.get("p") or 1))
    except ValueError:
        page = 1
    rows, total = _account_rows_for(acct, page)
    voices = _account_voices_for(acct)
    try:
        sessions = accounts.list_sessions(acct["id"])
    except Exception as e:  # noqa: BLE001
        print(f"WARNING list_sessions: {e}", flush=True)
        sessions = []
    for sd in sessions:
        # Sessioni aperte prima di questa versione hanno lo User-Agent grezzo.
        sd["device_name"] = voice_clone.device_name_from_ua(sd.get("device_name")) or sd.get("device_name") or ""
    tab = "voices" if request.args.get("tab") == "voices" else "books"
    lang = _acct_page_lang(acct.get("lang"))
    t = _acct_txt(lang)
    # Un ?lang= esplicito viaggia anche sui link di paginazione; il cookie
    # posato dalla SPA non ne ha bisogno.
    link_lang = lang if (request.args.get("lang") or "").strip().lower() == lang else ""
    # Il campionamento si offre solo se la funzione e' viva: con la feature
    # spenta o il motore premium assente il bottone porterebbe a un wizard
    # che non si apre.
    new_voice_url = "/?vc=new" if routes_voice_clone._vc_gate() is None else ""
    return _acct_html(account_page.render_history(
        t, lang=lang, account=acct, rows=rows, page=page, per_page=_ACCT_PER_PAGE,
        total=total, voices_count=len(voices), voices=voices,
        sessions=sessions, current_sid=acct.get("session_id") or "", tab=tab,
        link_lang=link_lang, new_voice_url=new_voice_url))


@bp.route("/api/account/jobs", methods=["GET"])
def api_account_jobs():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    try:
        page = max(1, int(request.args.get("p") or 1))
    except ValueError:
        page = 1
    rows, total = _account_rows_for(acct, page)
    # Ottimizzazione con audiolibro: per l'app e' un audiolibro ("generate",
    # importabile in libreria); `optimized` conserva il resto dell'informazione.
    jobs = [{
        "job_id": r["job_id"], "created_at": r.get("created_at"),
        "kind": "generate" if account_page.is_optimize_with_audio(r) else r.get("kind"),
        "optimized": r.get("kind") == "optimize",
        "book_title": r.get("book_title") or "", "output_format": r.get("output_format") or "",
        "status": r.get("status"), "paid_eur": float(r.get("paid_eur") or 0),
        "engine": r.get("engine") or "", "model": r.get("model") or "",
        "downloads": r["downloads"],
    } for r in rows]
    return jsonify({"jobs": jobs, "total": total, "page": page, "per_page": _ACCT_PER_PAGE})


@bp.route("/api/account/jobs/delete", methods=["POST"])
def api_account_job_delete():
    """Elimina un job dall'area personale (web e app). Nasconde solo la riga
    di storico: file hot/cold e token restano, cosi' il link dell'email di
    notifica continua a funzionare fino alla scadenza."""
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id") or "").strip()
    if not job_id:
        return _acct_err("bad_request", "job_id required", 400)
    res = accounts.hide_job(acct["id"], job_id)
    if res == "not_found":
        return _acct_err("not_found", "Job not found", 404)
    if res == "running":
        return _acct_err("job_running", "Job still in progress", 409)
    _acct_log("ACCOUNT_JOB_DELETE", acct["email"], job_id)
    return jsonify({"ok": True})


@bp.route("/api/account/delete_request", methods=["POST"])
def api_account_delete_request():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    ip = client_ip()
    allowed, retry = _ip_rl_check("auth_request", ip, 5, 30)
    if not allowed:
        return _acct_err("rate_limited", "Too many requests", 429, retry_after=retry)
    # L'email e' quella dell'account: il body viene ignorato (nessuna cancellazione per conto terzi).
    _acct_send_code(acct["email"], "delete", acct.get("lang") or "en")
    return jsonify({"ok": True})


@bp.route("/api/account/delete_confirm", methods=["POST"])
def api_account_delete_confirm():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    code = (data.get("code") or "").strip()
    if token:
        status, target = accounts.verify(token=token, purpose="delete")
    elif code:
        status, target = accounts.verify(email=acct["email"], code=code, purpose="delete")
    else:
        return _acct_err("bad_request", "token or code required", 400)
    if status != "ok" or not target or target["id"] != acct["id"]:
        return _acct_err(status if status != "ok" else "wrong", "Verification failed", 401)
    _acct_do_delete(acct, acct.get("lang") or "en")
    resp = jsonify({"ok": True})
    _acct_clear_cookie(resp)
    return resp
