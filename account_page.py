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


def render_confirm(t, *, lang, purpose, action_url, masked_email=""):
    """Pagina GET /auth/<token>: un form POST, cosi' il GET non consuma mai."""
    key = "confirm_delete" if purpose == "delete" else "confirm_login"
    cls = "danger" if purpose == "delete" else "primary"
    who = f"<p class=\"who\"><strong>{_e(masked_email)}</strong></p>" if masked_email else ""
    body = (
        f"<p>{_e(t[key + '_p'])}</p>"
        f"{who}"
        f"<form method=\"post\" action=\"{_e(action_url)}\" class=\"actions\">"
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
