# page_brand.py
"""Marchio condiviso dalle pagine server-side fuori dalla SPA (gestione voci
campionate, area personale): il logo SVG e la tavolozza. Modulo foglia,
solo stdlib: lo importano sia `audiobook_app` sia `account_page`, che non
puo' importare l'entry point.
"""

LOGO_SVG = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<rect width="64" height="64" rx="14" fill="#c29a6c"/>'
    '<path d="M16 44V20c0-2 1.5-3.5 3.5-3.5C23 16.5 28 17 32 19c4-2 9-2.5 12.5-2.5 2 0 3.5 1.5 3.5 3.5v24"'
    ' fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M32 19v25" stroke="white" stroke-width="2" stroke-linecap="round"/>'
    '<path d="M17 36c0-9 6.7-15 15-15s15 6 15 15" fill="none" stroke="white" stroke-width="2.8" stroke-linecap="round"/>'
    '<rect x="13" y="34" width="7" height="10" rx="3" fill="white"/>'
    '<rect x="44" y="34" width="7" height="10" rx="3" fill="white"/>'
    '<path d="M22 37.5c1.2-1 1.2-3 0-4" fill="none" stroke="#c29a6c" stroke-width="1.3" stroke-linecap="round"/>'
    '<path d="M42 37.5c-1.2-1-1.2-3 0-4" fill="none" stroke="#c29a6c" stroke-width="1.3" stroke-linecap="round"/></svg>')

# Tavolozza e controlli della SPA (static/css/style.css): chi apre queste
# pagine dall'app deve ritrovare gli stessi bottoni e lo stesso tema.
# Le variabili portano gli stessi nomi del foglio della SPA.
# «X» di chiusura/ritorno per la testata delle pagine (aria-label lo dice il chiamante).
CLOSE_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>'
)

BASE_CSS = (
    ":root{--bg:#f5f3ef;--srf:#fff;--srf2:#f0ede8;--brd:#d5d0c8;--brdh:#bfb8ae;"
    "--tx:#2c2a26;--txd:#6b6760;--txm:#767676;--ac:#c47a2a;--acs:rgba(196,122,42,.10);--ach:#d4903e;"
    "--ok:#3a9e5c;--oks:rgba(58,158,92,.10);--err:#c44040;--errs:rgba(196,64,64,.08);"
    "--info:#2c4a8a;--infos:#eef3ff;--rs:8px}"
    "[data-theme=dark]{--bg:#0e0e11;--srf:#18181d;--srf2:#222228;--brd:#333340;--brdh:#4a4a5a;"
    "--tx:#e8e8ed;--txd:#9090a0;--txm:#7a7a8a;--ac:#f0a050;--acs:rgba(240,160,80,.12);--ach:#f5b570;"
    "--ok:#50c878;--oks:rgba(80,200,120,.12);--err:#e05555;--errs:rgba(224,85,85,.12);"
    "--info:#9db4ea;--infos:rgba(120,150,230,.16)}"
    "body{font-family:'DM Sans',system-ui,sans-serif;margin:3em auto;padding:0 1em;"
    "color:var(--tx);background:var(--bg);line-height:1.5}"
    "[hidden]{display:none!important}"
    "button,a.btn{font:inherit;font-weight:600;padding:.5em 1.1em;border:1px solid var(--brd);"
    "border-radius:var(--rs);background:var(--srf);color:var(--ac);cursor:pointer;text-decoration:none;"
    "display:inline-block;transition:all .2s}"
    "button:hover,a.btn:hover{background:var(--acs);border-color:var(--ac)}"
    "button:focus-visible,a.btn:focus-visible{outline:2px solid var(--ac);outline-offset:2px}"
    "button.primary{background:var(--ac);border-color:var(--ac);color:#fff}"
    "button.primary:hover{background:var(--ach);border-color:var(--ach)}"
    "button.danger,a.btn.danger{color:var(--err)}"
    "button.danger:hover,a.btn.danger:hover{background:var(--errs);border-color:var(--err)}"
    "button:disabled{opacity:.55;cursor:default}"
    ".card{border:1px solid var(--brd);border-radius:12px;padding:1em 1.2em;margin:1.2em 0 2em;"
    "background:var(--srf)}.card h2{margin:0 0 .3em;font-size:1.2em}"
    ".card p{margin:.2em 0 1em;color:var(--txd)}"
    ".meta{color:var(--txd);font-size:.9em}"
    ".actions{display:flex;gap:.6em;flex-wrap:wrap;align-items:center;margin-top:1.5em}"
    ".actions .end{margin-left:auto}"
    ".topbar{display:flex;align-items:flex-start;justify-content:space-between;gap:1em;flex-wrap:wrap}"
    ".topbar h1{margin:0 0 .3em}"
    ".topbar .tools{display:flex;align-items:center;gap:.5em;flex-wrap:wrap;margin-top:.3em}"
    ".icon-x{padding:.35em;line-height:0;color:var(--txd)}.icon-x:hover{color:var(--tx)}"
    ".icon-x svg{width:18px;height:18px;display:block}"
    ".me{font-size:.8em;background:var(--infos);color:var(--info);border-radius:1em;padding:.1em .6em;"
    "margin-left:.4em;white-space:nowrap}"
    ".brand{display:flex;align-items:center;gap:.6em;margin-bottom:1.8em;color:inherit;text-decoration:none}"
    ".brand svg{width:42px;height:42px;flex:none}"
    ".brand span{font-size:1.1em;font-weight:600}"
)

# Va nel <head> PRIMA del foglio di stile: applica il tema scelto nella SPA
# (stessa chiave localStorage `abm_th` di applyTheme in static/js/app.js)
# senza lampo di pagina chiara. Senza scelta salvata vale il tema di sistema.
THEME_SCRIPT = (
    "<script>(function(){var t=null;try{t=localStorage.getItem('abm_th')}catch(e){}"
    "if(!t&&window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches)t='dark';"
    "if(t==='dark')document.documentElement.setAttribute('data-theme','dark');})();</script>"
)
