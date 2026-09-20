# account_page.py
"""Pagine server-side dell'account (modulo foglia): conferma magic link,
errori, account cancellato e, dal Task 6, lo storico. Solo stdlib: i testi
arrivano gia' scelti per lingua (dict `t`), l'escaping e' fatto qui.
"""
import html

_CSS = (
    ":root{--acc:#c29a6c;--acc-d:#a67d50;--bd:#dcd6cd;--mut:#666}"
    "body{font-family:system-ui,sans-serif;max-width:760px;margin:3em auto;padding:0 1em;"
    "color:#222;background:#fff;line-height:1.5}"
    "button,a.btn{font:inherit;padding:.5em 1.1em;border:1px solid var(--bd);border-radius:8px;"
    "background:#f6f3ee;color:#222;cursor:pointer;text-decoration:none;display:inline-block}"
    "button:hover,a.btn:hover{background:#ece7df}"
    "button.primary{background:var(--acc);border-color:var(--acc);color:#fff}"
    "button.primary:hover{background:var(--acc-d);border-color:var(--acc-d)}"
    "button.danger{background:#fff;color:#b3261e;border-color:#e8bdb9}"
    "button.danger:hover{background:#fdecea}"
    ".meta{color:var(--mut);font-size:.9em}.actions{display:flex;gap:.6em;flex-wrap:wrap;margin-top:1.5em}"
    "table{width:100%;border-collapse:collapse;margin-top:1em;font-size:.95em}"
    "th,td{text-align:left;padding:.5em .4em;border-top:1px solid var(--bd);vertical-align:top}"
    "th{color:var(--mut);font-weight:600;border-top:none}"
    ".badge{font-size:.8em;border-radius:1em;padding:.1em .6em;background:#eee;color:#444;white-space:nowrap}"
    ".badge.done{background:#e6f4ea;color:#1e6b34}.badge.error{background:#fdecea;color:#b3261e}"
    ".badge.running{background:#eef3ff;color:#2c4a8a}.badge.expired{background:#f3f0ea;color:#8a7a62}"
    ".dl a{margin-right:.6em;white-space:nowrap}"
    ".brand{display:flex;align-items:center;gap:.6em;margin-bottom:1.8em;color:inherit;text-decoration:none}"
    ".brand span{font-size:1.1em;font-weight:600}"
    "@media(max-width:600px){table,thead,tbody,tr,td,th{display:block}thead{display:none}"
    "td{border-top:none;padding:.15em 0}tr{border-top:1px solid var(--bd);padding:.6em 0}}"
)


def _e(s):
    return html.escape(str(s if s is not None else ""))


def mask_email(email):
    """`a@b.it` -> `a***@b.it`. Input vuoto o senza `@` -> stringa vuota."""
    email = str(email or "")
    if "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    if not local:
        return ""
    return f"{local[0]}***@{domain}"


def page_html(t, lang, title, body_html):
    """Scheletro HTML completo. `body_html` e' gia' escapato dal chiamante."""
    brand = _e(t.get("brand", "Audiobook Maker"))
    return (
        f"<!doctype html><html lang=\"{_e(lang)}\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<meta name=\"robots\" content=\"noindex,nofollow\">"
        f"<title>{brand} - {_e(title)}</title><style>{_CSS}</style></head>"
        f"<body><a class=\"brand\" href=\"/\"><span>{brand}</span></a>"
        f"<h1>{_e(title)}</h1>{body_html}</body></html>"
    )


def render_confirm(t, *, lang, purpose, action_url, masked_email="", csrf=""):
    """Pagina GET /auth/<token>: un form POST, cosi' il GET non consuma mai.

    `csrf` e' il gemello del cookie posato dalla stessa risposta GET
    (double-submit): il POST che consuma il link vale solo se arriva dal
    browser che la pagina l'ha davvero aperta."""
    key = "confirm_delete" if purpose == "delete" else "confirm_login"
    cls = "danger" if purpose == "delete" else "primary"
    who = f"<p class=\"who\"><strong>{_e(masked_email)}</strong></p>" if masked_email else ""
    hidden = f"<input type=\"hidden\" name=\"csrf\" value=\"{_e(csrf)}\">" if csrf else ""
    body = (
        f"<p>{_e(t[key + '_p'])}</p>"
        f"{who}"
        f"<form method=\"post\" action=\"{_e(action_url)}\" class=\"actions\">"
        f"{hidden}"
        f"<button type=\"submit\" class=\"{cls}\">{_e(t[key + '_btn'])}</button></form>"
    )
    return page_html(t, lang, t[key + "_title"], body)


def render_error(t, *, lang, status_key):
    key = status_key if status_key in ("expired", "locked", "none", "wrong") else "none"
    body = (f"<p>{_e(t['err_' + key + '_p'])}</p>"
            f"<p class=\"actions\"><a class=\"btn\" href=\"/\">{_e(t['home'])}</a></p>")
    return page_html(t, lang, t["err_" + key + "_title"], body)


def render_deleted(t, *, lang):
    body = (f"<p>{_e(t['deleted_p'])}</p>"
            f"<p class=\"actions\"><a class=\"btn\" href=\"/\">{_e(t['home'])}</a></p>")
    return page_html(t, lang, t["deleted_title"], body)


def _fmt_date(epoch):
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return ""


def _expiry_label(t, expires_at, now):
    left = int(expires_at - now)
    if left <= 0:
        return t["dl_expired"]
    if left < 3600:
        return t["dl_expires_soon"].replace("{minutes}", str(max(1, left // 60)))
    return t["dl_expires_in"].replace("{hours}", str(left // 3600))


def render_history(t, *, lang, account, rows, page, per_page, total, voices_count, voices=None, now=None):
    import time as _time
    now = now if now is not None else _time.time()
    parts = [f"<p class=\"meta\">{_e(t['history_signed_in_as'])} <strong>{_e(account['email'])}</strong>"]
    if voices_count:
        parts.append(" &middot; " + _e(t["voices_linked"].replace("{n}", str(voices_count))))
        if voices:
            links = ", ".join(f"<a href=\"{_e(v['url'])}\">{_e(v['name'])}</a>" for v in voices)
            parts.append(" " + links)
    parts.append("</p>")
    if not rows:
        parts.append(f"<p>{_e(t['history_empty'])}</p>")
    else:
        parts.append("<table><thead><tr>"
                     f"<th>{_e(t['history_col_date'])}</th><th>{_e(t['history_col_book'])}</th>"
                     f"<th>{_e(t['history_col_kind'])}</th><th>{_e(t['history_col_status'])}</th>"
                     f"<th>{_e(t['history_col_downloads'])}</th></tr></thead><tbody>")
        for r in rows:
            status = r.get("status") or "running"
            kind = r.get("kind") or "generate"
            dls = r.get("downloads") or []
            if dls:
                cell = "".join(
                    f"<a href=\"{_e(d['url'])}\">{_e(t.get('dl_' + d['kind'], d['kind']))}</a>" for d in dls)
                cell += f" <span class=\"badge\">{_e(_expiry_label(t, min(d['expires_at'] for d in dls), now))}</span>"
            elif status == "done":
                cell = f"<span class=\"badge expired\">{_e(t['dl_expired'])}</span>"
            else:
                cell = ""
            paid = float(r.get("paid_eur") or 0)
            book = _e(r.get("book_title") or r.get("job_id") or "")
            if paid > 0:
                book += f" <span class=\"meta\">&euro; {paid:.2f}</span>"
            fmt = (r.get("output_format") or "").upper()
            if fmt == "ZIP_RSS":
                fmt = "ZIP+RSS"
            voice = r.get("voice") or ""
            bits = [_e(b) for b in (fmt, voice) if b]
            if bits:
                book += f" <span class=\"meta\">{' &middot; '.join(bits)}</span>"
            parts.append(
                f"<tr><td>{_e(_fmt_date(r.get('created_at')))}</td><td>{book}</td>"
                f"<td>{_e(t.get('kind_' + kind, kind))}</td>"
                f"<td><span class=\"badge {_e(status)}\">{_e(t.get('status_' + status, status))}</span></td>"
                f"<td class=\"dl\">{cell}</td></tr>")
        parts.append("</tbody></table>")
        pages = max(1, (int(total) + per_page - 1) // per_page)
        if pages > 1:
            nav = []
            if page > 1:
                nav.append(f"<a class=\"btn\" href=\"/account?p={page - 1}\">{_e(t['page_prev'])}</a>")
            nav.append(f"<span class=\"meta\">{page} / {pages}</span>")
            if page < pages:
                nav.append(f"<a class=\"btn\" href=\"/account?p={page + 1}\">{_e(t['page_next'])}</a>")
            parts.append("<p class=\"actions\">" + " ".join(nav) + "</p>")
    parts.append(
        "<div class=\"actions\">"
        f"<button type=\"button\" id=\"acctLogout\">{_e(t['logout'])}</button>"
        f"<button type=\"button\" id=\"acctLogoutAll\">{_e(t['logout_all'])}</button>"
        f"<button type=\"button\" class=\"danger\" id=\"acctDelete\">{_e(t['delete_account'])}</button>"
        "</div>"
        f"<p class=\"meta\" id=\"acctDeleteHint\">{_e(t['delete_account_p'])}</p>"
        f"<p class=\"meta\" id=\"acctDeleteSent\" hidden>{_e(t['delete_sent'])}</p>"
        "<script>"
        "(function(){"
        "function post(u){return fetch(u,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'});}"
        "document.getElementById('acctLogout').onclick=function(){post('/api/auth/logout').then(function(){location.href='/';});};"
        "document.getElementById('acctLogoutAll').onclick=function(){post('/api/auth/logout_all').then(function(){location.href='/';});};"
        "document.getElementById('acctDelete').onclick=function(){"
        "var b=this;b.disabled=true;post('/api/account/delete_request').then(function(){"
        "document.getElementById('acctDeleteSent').hidden=false;});};"
        "})();"
        "</script>"
    )
    return page_html(t, lang, t["history_title"], "".join(parts))
