# account_page.py
"""Pagine server-side dell'account (modulo foglia): conferma magic link,
errori, account cancellato e, dal Task 6, lo storico. Solo stdlib: i testi
arrivano gia' scelti per lingua (dict `t`), l'escaping e' fatto qui.
"""
import html

import page_brand

_CSS = page_brand.BASE_CSS + (
    "body{max-width:760px}"
    "h1{font-size:1.5em;margin:0 0 .3em}"
    "button.small{padding:.3em .8em;font-size:.85em;white-space:nowrap}"
    ".signed{display:flex;align-items:center;justify-content:space-between;gap:1em;flex-wrap:wrap}"
    ".signed p{margin:0}"
    ".cnt{display:inline-block;min-width:1.4em;text-align:center;font-size:.85em;border-radius:1em;"
    "padding:0 .4em;background:var(--ac);color:#fff;margin-left:.3em}"
    "button.primary .cnt{background:#fff;color:var(--ac)}"
    ".tabs{display:flex;gap:.3em;border-bottom:1px solid var(--brd);margin:1.4em 0 0}"
    ".tabs button{border:1px solid transparent;border-bottom:none;border-radius:8px 8px 0 0;"
    "background:transparent;color:var(--txd);margin-bottom:-1px;font-weight:500}"
    ".tabs button:hover{background:var(--srf2);border-color:transparent}"
    ".tabs button[aria-selected=true]{background:var(--srf);border-color:var(--brd);color:var(--tx);font-weight:600}"
    ".panel{padding-top:.4em}"
    "table{width:100%;border-collapse:collapse;margin-top:1em;font-size:.95em}"
    "th,td{text-align:left;padding:.5em .4em;border-top:1px solid var(--brd);vertical-align:top}"
    "th{color:var(--txd);font-weight:600;border-top:none}"
    ".bk b{display:block;font-weight:600}"
    ".bk .meta{display:block;font-size:.8em;color:var(--txm);word-break:break-all}"
    ".plan .meta{display:block;font-size:.8em;color:var(--txm);margin-top:.2em}"
    ".badge{font-size:.8em;border-radius:1em;padding:.1em .6em;background:var(--srf2);color:var(--txd);white-space:nowrap}"
    ".badge.premium{background:var(--acs,var(--srf2));color:var(--ac)}"
    ".badge.done{background:var(--oks);color:var(--ok)}.badge.error,.badge.cancelled{background:var(--errs);color:var(--err)}"
    ".badge.running{background:var(--infos);color:var(--info)}.badge.expired{background:var(--srf2);color:var(--txm)}"
    ".prog{display:block;height:4px;border-radius:2px;background:var(--srf2);margin-top:.4em;overflow:hidden;max-width:8em}"
    ".prog i{display:block;height:100%;width:0;background:var(--ac);transition:width .6s}"
    ".dl a{margin-right:.6em;white-space:nowrap;color:var(--ac)}"
    "td.act{text-align:right;width:1%}"
    "button.del{padding:.25em;line-height:0;background:transparent;border:1px solid transparent;"
    "color:var(--txm);border-radius:6px}button.del:hover{color:var(--err);border-color:var(--brd)}"
    "button.del svg{width:16px;height:16px}"
    ".voices{list-style:none;padding:0}.voices li{display:flex;align-items:center;gap:.8em;flex-wrap:wrap;"
    "border-top:1px solid var(--brd);padding:.8em 0}.voices li b{flex:1 1 10em}"
    "dialog{border:1px solid var(--brd);border-radius:12px;padding:1.2em 1.4em;max-width:min(92vw,680px);"
    "background:var(--srf);color:var(--tx)}dialog::backdrop{background:rgba(0,0,0,.45)}"
    "dialog h2{margin:0 0 .4em;font-size:1.2em}dialog p{margin:.3em 0}"
    "dialog table{margin-top:.6em}code{font-size:.85em;background:var(--srf2);padding:.1em .3em;border-radius:4px}"
    "@media(max-width:600px){table,thead,tbody,tr,td,th{display:block}thead{display:none}"
    "td{border-top:none;padding:.15em 0}tr{border-top:1px solid var(--brd);padding:.6em 0}}"
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


def page_html(t, lang, title, body_html, h1=True, tools_html=""):
    """Scheletro HTML completo. `body_html` e' gia' escapato dal chiamante.
    Con `h1=False` il titolo resta solo nel <title>: il corpo lo mette dove
    vuole. `tools_html` va a destra del marchio, allineato al logo."""
    brand = _e(t.get("brand", "Audiobook Maker"))
    heading = f"<h1>{_e(title)}</h1>" if h1 else ""
    return (
        f"<!doctype html><html lang=\"{_e(lang)}\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<meta name=\"robots\" content=\"noindex,nofollow\">"
        f"<title>{brand} - {_e(title)}</title>{page_brand.THEME_SCRIPT}<style>{_CSS}</style></head>"
        f"<body>{page_brand.brand_bar(page_brand.LOGO_SVG, brand, tools_html=tools_html)}"
        f"{heading}{body_html}</body></html>"
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


# Chiave modello -> chiave i18n dell'etichetta mostrata. Le chiavi grezze
# ('flash25', 'voxcpm', ...) non si mostrano mai: sono identificatori interni.
# Le etichette sono le stesse del selettore voci della SPA (`_modelLabel`):
# chi rilegge lo storico deve ritrovare il nome che ha scelto.
_MODEL_LABEL_KEYS = {
    "flash25": "model_flash25",
    "flash31": "model_flash31",
    "simba-3.2": "model_simba",
    "voxcpm": "model_voxcpm",
}


def _plan_cell(t, r, kind):
    """Contenuto della colonna Piano: badge Gratis/PREMIUM (con il modello
    sotto, quando lo conosciamo) per gli audiolibri, etichetta del tipo per
    ottimizzazione e traduzione, che di voci non ne usano.

    Storico piu' vecchio delle colonne engine/model (righe adottate da
    `_payments.json`): il piano non e' ricostruibile, ma un job pagato era per
    forza PREMIUM — quello si puo' dire; il resto resta un trattino."""
    if kind != "generate":
        return _e(t.get("kind_" + kind, kind))
    engine = (r.get("engine") or "").strip()
    if not engine and float(r.get("paid_eur") or 0) > 0:
        engine = "premium"
    if engine == "standard":
        return f"<span class=\"badge\">{_e(t['plan_free'])}</span>"
    if engine != "premium":
        return "<span class=\"meta\">&mdash;</span>"
    out = f"<span class=\"badge premium\">{_e(t['plan_premium'])}</span>"
    key = _MODEL_LABEL_KEYS.get((r.get("model") or "").strip())
    if key and t.get(key):
        out += f"<span class=\"meta\">{_e(t[key])}</span>"
    return out


def _expiry_label(t, expires_at, now):
    left = int(expires_at - now)
    if left <= 0:
        return t["dl_expired"]
    if left < 3600:
        return t["dl_expires_soon"].replace("{minutes}", str(max(1, left // 60)))
    return t["dl_expires_in"].replace("{hours}", str(left // 3600))


def _devices_dialog(t, sessions, current_sid):
    rows = ""
    for sd in sessions or []:
        sid = str(sd.get("id") or "")
        name = _e(sd.get("device_name") or t["dev_unnamed"])
        if current_sid and sid == current_sid:
            name += f" <span class=\"me\">{_e(t['dev_this'])}</span>"
        rows += (f"<tr><td><code>{_e(sid[:8])}</code></td><td>{name}</td>"
                 f"<td>{_e(_fmt_date(sd.get('created_at')))}</td>"
                 f"<td>{_e(_fmt_date(sd.get('last_seen_at')))}</td>"
                 f"<td><button type=\"button\" class=\"danger small\" data-sid=\"{_e(sid)}\">"
                 f"{_e(t['dev_logout'])}</button></td></tr>")
    return (
        f"<dialog id=\"acctDevicesDlg\"><h2>{_e(t['devices_title'])}</h2>"
        f"<p class=\"meta\">{_e(t['devices_intro'])}</p>"
        f"<table><thead><tr><th>{_e(t['dev_col_id'])}</th><th>{_e(t['dev_col_name'])}</th>"
        f"<th>{_e(t['dev_col_login'])}</th><th>{_e(t['dev_col_last'])}</th><th></th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"<div class=\"actions\"><button type=\"button\" id=\"acctLogoutAll\">{_e(t['logout_all'])}</button>"
        f"<button type=\"button\" data-close>{_e(t['close_btn'])}</button></div></dialog>"
    )


def _logout_dialog(t):
    """Conferma dell'«Esci»: e' l'azione che cambia qualcosa (tornare
    all'app no: la sessione resta). «Annulla» ha il fuoco iniziale, cosi'
    Invio non disconnette per sbaglio."""
    return (
        f"<dialog id=\"acctLogoutDlg\"><h2>{_e(t['logout_popup_title'])}</h2>"
        f"<p>{_e(t['logout_popup_p'])}</p>"
        f"<div class=\"actions\"><button type=\"button\" class=\"danger\" id=\"acctLogoutConfirm\">"
        f"{_e(t['logout'])}</button>"
        f"<button type=\"button\" class=\"primary\" data-close autofocus>{_e(t['cancel_btn'])}</button></div></dialog>"
    )


_TRASH_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/></svg>')


def _job_delete_dialog(t):
    """Conferma dell'eliminazione di un job che ha ancora link vivi: il file
    non sparisce, resta scaricabile dall'email. Senza link si elimina subito."""
    return (
        f"<dialog id=\"acctJobDelDlg\"><h2>{_e(t['job_delete_title'])}</h2>"
        f"<p>{_e(t['job_delete_p'])}</p>"
        f"<div class=\"actions\"><button type=\"button\" class=\"danger\" id=\"acctJobDelConfirm\">"
        f"{_e(t['job_delete'])}</button>"
        f"<button type=\"button\" class=\"primary\" data-close autofocus>{_e(t['cancel_btn'])}</button></div></dialog>"
    )


def _delete_dialog(t):
    return (
        f"<dialog id=\"acctDeleteDlg\"><h2>{_e(t['delete_popup_title'])}</h2>"
        f"<p>{_e(t['delete_popup_p'])}</p><p>{_e(t['delete_popup_email'])}</p>"
        f"<div class=\"actions\"><button type=\"button\" class=\"danger\" id=\"acctDeleteConfirm\">"
        f"{_e(t['confirm_delete_btn'])}</button>"
        f"<button type=\"button\" data-close>{_e(t['cancel_btn'])}</button></div></dialog>"
    )


_HISTORY_JS = (
    "<script>(function(){"
    "function post(u,b){return fetch(u,{method:'POST',credentials:'same-origin',"
    "headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});}"
    "function openDlg(d){if(!d)return;if(d.showModal){d.showModal();}else{d.setAttribute('open','');}}"
    "function closeDlg(d){if(!d)return;if(d.close){d.close();}else{d.removeAttribute('open');}}"
    "var tabs=document.querySelectorAll('.tabs [data-tab]');"
    "function showTab(k){tabs.forEach(function(b){var on=b.getAttribute('data-tab')===k;"
    "b.setAttribute('aria-selected',on?'true':'false');"
    "var p=document.getElementById('tab-'+b.getAttribute('data-tab'));if(p)p.hidden=!on;});"
    "try{history.replaceState(null,'',k==='books'?location.pathname:'?tab='+k);}catch(e){}}"
    "tabs.forEach(function(b){b.addEventListener('click',function(){showTab(b.getAttribute('data-tab'));});});"
    "document.querySelectorAll('[data-close]').forEach(function(b){"
    "b.addEventListener('click',function(){closeDlg(b.closest('dialog'));});});"
    "var dv=document.getElementById('acctDevices'),dd=document.getElementById('acctDevicesDlg');"
    "if(dv)dv.onclick=function(){openDlg(dd);};"
    "document.querySelectorAll('[data-sid]').forEach(function(b){b.addEventListener('click',function(){"
    "b.disabled=true;post('/api/auth/logout_device',{id:b.getAttribute('data-sid')})"
    ".then(function(r){return r.json();}).then(function(d){"
    "if(d&&d.current){location.href='/';}else{location.reload();}})"
    ".catch(function(){b.disabled=false;});});});"
    "['acctClose','acctCloseX'].forEach(function(id){var b=document.getElementById(id);"
    "if(b)b.onclick=function(){location.href='/';};});"
    "var la=document.getElementById('acctLogoutAll');"
    "if(la)la.onclick=function(){la.disabled=true;post('/api/auth/logout_all').then(function(){location.href='/';});};"
    "var lo=document.getElementById('acctLogout'),ld=document.getElementById('acctLogoutDlg'),"
    "lc=document.getElementById('acctLogoutConfirm');"
    "if(lo)lo.onclick=function(){openDlg(ld);};"
    "if(lc)lc.onclick=function(){lc.disabled=true;post('/api/auth/logout').then(function(){location.href='/';});};"
    "var del=document.getElementById('acctDelete'),ddl=document.getElementById('acctDeleteDlg'),"
    "dc=document.getElementById('acctDeleteConfirm');"
    "if(del)del.onclick=function(){openDlg(ddl);};"
    "if(dc)dc.onclick=function(){dc.disabled=true;post('/api/account/delete_request').then(function(){"
    "closeDlg(ddl);del.disabled=true;document.getElementById('acctDeleteSent').hidden=false;});};"
    "var jd=document.getElementById('acctJobDelDlg'),jc=document.getElementById('acctJobDelConfirm'),jb=null;"
    "function delJob(b){b.disabled=true;post('/api/account/jobs/delete',{job_id:b.getAttribute('data-del')})"
    ".then(function(r){if(r.ok||r.status===404){var tr=b.closest('tr');if(tr)tr.remove();}else{b.disabled=false;}})"
    ".catch(function(){b.disabled=false;});}"
    "document.querySelectorAll('[data-del]').forEach(function(b){b.addEventListener('click',function(){"
    "if(b.getAttribute('data-dl')==='1'){jb=b;openDlg(jd);}else{delJob(b);}});});"
    "if(jc)jc.onclick=function(){closeDlg(jd);if(jb)delJob(jb);jb=null;};"
    "var live=document.querySelectorAll('[data-job]');"
    "var ids=[];live.forEach(function(el){ids.push(el.getAttribute('data-job'));});"
    "var ENDED={done:1,partial:1,error:1,cancelled:1,interrupted:1};"
    "function reloadOnce(id){var k='acct_rl_'+id;try{if(sessionStorage.getItem(k))return;"
    "sessionStorage.setItem(k,'1');}catch(e){}location.reload();}"
    "function tick(){if(!ids.length)return;"
    "fetch('/api/account/progress?ids='+encodeURIComponent(ids.join(',')),{credentials:'same-origin'})"
    ".then(function(r){return r.ok?r.json():null;}).then(function(d){if(!d||!d.jobs)return;"
    "var keep=[];ids.forEach(function(id){var j=d.jobs[id];if(!j)return;"
    "if(ENDED[j.status]){reloadOnce(id);return;}keep.push(id);"
    "var el=document.querySelector('[data-job=\"'+id+'\"]');if(!el)return;"
    "var p=el.querySelector('.pct'),bar=el.querySelector('.prog i');"
    "if(p)p.textContent=j.pct>0?' \u00b7 '+j.pct+'%':'';if(bar)bar.style.width=(j.pct||0)+'%';});"
    "ids=keep;if(ids.length)setTimeout(tick,3000);}).catch(function(){setTimeout(tick,10000);});}"
    "if(ids.length)tick();"
    "})();</script>"
)


def render_history(t, *, lang, account, rows, page, per_page, total, voices_count, voices=None,
                   now=None, sessions=None, current_sid="", tab="books", link_lang="",
                   new_voice_url=""):
    """Area personale: intestazione con il bottone «I tuoi dispositivi», tab
    audiolibri / voci campionate, azioni in fondo e i due popup (dispositivi,
    conferma cancellazione). `sessions` come da `accounts.list_sessions`,
    `current_sid` e' l'id della sessione che sta guardando la pagina.
    `new_voice_url` e' il link che riapre l'app sul campionamento: vuoto
    quando la funzione non e' attiva, cosi' il bottone non compare."""
    import time as _time
    now = now if now is not None else _time.time()
    voices = voices or []
    tab = "voices" if tab == "voices" else "books"
    n_sess = len(sessions or [])
    parts = [
        f"<h1>{_e(t['history_title'])}</h1>",
        f"<div class=\"signed\"><p class=\"meta\">{_e(t['history_signed_in_as'])} <strong>{_e(account['email'])}</strong></p>"
        f"<button type=\"button\" class=\"small\" id=\"acctDevices\">{_e(t['devices_btn'])}"
        f"<span class=\"cnt\">{n_sess}</span></button></div>",
        "<nav class=\"tabs\" role=\"tablist\">"
        f"<button type=\"button\" role=\"tab\" data-tab=\"books\" aria-selected=\"{'true' if tab == 'books' else 'false'}\">"
        f"{_e(t['tab_books'])}</button>"
        f"<button type=\"button\" role=\"tab\" data-tab=\"voices\" aria-selected=\"{'true' if tab == 'voices' else 'false'}\">"
        f"{_e(t['tab_voices'])}{f' ({voices_count})' if voices_count else ''}</button></nav>",
        f"<section class=\"panel\" id=\"tab-books\"{'' if tab == 'books' else ' hidden'}>",
    ]
    if not rows:
        parts.append(f"<p>{_e(t['history_empty'])}</p>")
    else:
        parts.append("<table><thead><tr>"
                     f"<th>{_e(t['history_col_date'])}</th><th>{_e(t['history_col_book'])}</th>"
                     f"<th>{_e(t['history_col_plan'])}</th><th>{_e(t['history_col_status'])}</th>"
                     f"<th>{_e(t['history_col_downloads'])}</th><th></th></tr></thead><tbody>")
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
            job_id = r.get("job_id") or ""
            # Il titolo e' cio' che l'utente riconosce; il job_id resta sotto,
            # piccolo, perche' e' quello che si cita nelle richieste di
            # assistenza. Storico adottato dai pagamenti (adopt_history): il
            # titolo non c'e', e il job_id prende il suo posto.
            title = r.get("book_title") or job_id
            book = f"<b>{_e(title)}</b>"
            fmt = (r.get("output_format") or "").upper()
            if fmt == "ZIP_RSS":
                fmt = "ZIP+RSS"
            voice = r.get("voice") or ""
            bits = []
            if r.get("book_title"):
                bits.append(_e(job_id))
            if paid > 0:
                bits.append(f"&euro; {paid:.2f}")
            bits += [_e(b) for b in (fmt, voice) if b]
            if bits:
                book += f"<span class=\"meta\">{' &middot; '.join(bits)}</span>"
            st_cell = f"<span class=\"badge {_e(status)}\">{_e(t.get('status_' + status, status))}"
            if status == "running":
                # Il JS della pagina interroga /api/account/progress e riempie
                # .pct e la barra; se il job non e' piu' in memoria resta cosi'.
                st_cell = (f"<td data-job=\"{_e(r.get('job_id') or '')}\">{st_cell}<span class=\"pct\"></span></span>"
                           f"<span class=\"prog\"><i></i></span></td>")
            else:
                st_cell = f"<td>{st_cell}</span></td>"
            # Eliminazione dall'elenco: non per i job che stanno lavorando.
            # data-dl=1 (link ancora vivi) chiede conferma prima.
            act = ""
            if status != "running":
                act = (f"<button type=\"button\" class=\"del\" data-del=\"{_e(job_id)}\" "
                       f"data-dl=\"{'1' if dls else '0'}\" title=\"{_e(t['job_delete'])}\" "
                       f"aria-label=\"{_e(t['job_delete'])}\">{_TRASH_SVG}</button>")
            parts.append(
                f"<tr><td>{_e(_fmt_date(r.get('created_at')))}</td><td class=\"bk\">{book}</td>"
                f"<td class=\"plan\">{_plan_cell(t, r, kind)}</td>{st_cell}"
                f"<td class=\"dl\">{cell}</td><td class=\"act\">{act}</td></tr>")
        parts.append("</tbody></table>")
        pages = max(1, (int(total) + per_page - 1) // per_page)
        if pages > 1:
            # lingua chiesta esplicitamente (?lang=): la paginazione la conserva
            qs = f"&amp;lang={_e(link_lang)}" if link_lang else ""
            nav = []
            if page > 1:
                nav.append(f"<a class=\"btn\" href=\"/account?p={page - 1}{qs}\">{_e(t['page_prev'])}</a>")
            nav.append(f"<span class=\"meta\">{page} / {pages}</span>")
            if page < pages:
                nav.append(f"<a class=\"btn\" href=\"/account?p={page + 1}{qs}\">{_e(t['page_next'])}</a>")
            parts.append("<p class=\"actions\">" + " ".join(nav) + "</p>")
    parts.append("</section>")
    parts.append(f"<section class=\"panel\" id=\"tab-voices\"{'' if tab == 'voices' else ' hidden'}>")
    # Il vincolo del modello si dice prima della lista: una voce campionata
    # non compare fra le voci degli altri modelli, e chi la cerca li' la crede
    # sparita.
    parts.append(f"<p class=\"meta\">{_e(t['voices_premium_note'])}</p>")
    if not voices:
        parts.append(f"<p>{_e(t['voices_empty'])}</p>")
    else:
        parts.append("<ul class=\"voices\">")
        for v in voices:
            state = "ready" if v.get("state") == "ready" else "pending"
            parts.append(f"<li><b>{_e(v['name'])}</b><span class=\"badge {'done' if state == 'ready' else 'running'}\">"
                         f"{_e(t['vstate_' + state])}</span>"
                         f"<a class=\"btn\" href=\"{_e(v['url'])}\">{_e(t['voice_manage'])}</a></li>")
        parts.append("</ul>")
    if new_voice_url:
        # Il campionamento vive nell'app (microfono, pagamento, prove): da qui
        # si offre l'avvio, non una seconda procedura.
        parts.append(f"<p class=\"actions\"><a class=\"btn\" href=\"{_e(new_voice_url)}\">"
                     f"{_e(t['voice_new'])}</a>"
                     f"<span class=\"meta\">{_e(t['voice_new_hint'])}</span></p>")
    parts.append("</section>")
    parts.append(
        "<div class=\"actions\">"
        f"<button type=\"button\" id=\"acctLogout\">{_e(t['logout'])}</button>"
        f"<button type=\"button\" class=\"danger\" id=\"acctDelete\">{_e(t['delete_account'])}</button>"
        f"<button type=\"button\" class=\"primary end\" id=\"acctClose\" autofocus>{_e(t['close_btn_app'])}</button>"
        "</div>"
        f"<p class=\"meta\" id=\"acctDeleteSent\" hidden>{_e(t['delete_sent'])}</p>"
        + _logout_dialog(t) + _devices_dialog(t, sessions, current_sid) + _delete_dialog(t)
        + _job_delete_dialog(t) + _HISTORY_JS
    )
    # «X» a destra del marchio: torna all'app (la sessione resta).
    chiudi = (f"<button type=\"button\" class=\"icon-x\" id=\"acctCloseX\" title=\"{_e(t['close_btn_app'])}\" "
              f"aria-label=\"{_e(t['close_btn_app'])}\">{page_brand.CLOSE_SVG}</button>")
    return page_html(t, lang, t["history_title"], "".join(parts), h1=False, tools_html=chiudi)
