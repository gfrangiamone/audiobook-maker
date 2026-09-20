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

# Stessa tavolozza e stessi controlli della pagina di gestione voce
# (`_vc_page` in audiobook_app): chi passa da una pagina all'altra deve
# ritrovare lo stesso aspetto.
BASE_CSS = (
    ":root{--acc:#c29a6c;--acc-d:#a67d50;--bd:#dcd6cd;--mut:#666}"
    "body{font-family:system-ui,sans-serif;margin:3em auto;padding:0 1em;"
    "color:#222;background:#fff;line-height:1.5}"
    "[hidden]{display:none!important}"
    "button,a.btn{font:inherit;padding:.5em 1.1em;border:1px solid var(--bd);border-radius:8px;"
    "background:#f6f3ee;color:#222;cursor:pointer;text-decoration:none;display:inline-block}"
    "button:hover,a.btn:hover{background:#ece7df}"
    "button.primary{background:var(--acc);border-color:var(--acc);color:#fff}"
    "button.primary:hover{background:var(--acc-d);border-color:var(--acc-d)}"
    "button.danger{background:#fff;color:#b3261e;border-color:#e8bdb9}"
    "button.danger:hover{background:#fdecea}"
    "button:disabled{opacity:.55;cursor:default}"
    ".card{border:1px solid var(--bd);border-radius:12px;padding:1em 1.2em;margin:1.2em 0 2em;"
    "background:#fbf9f6}.card h2{margin:0 0 .3em;font-size:1.2em}"
    ".card p{margin:.2em 0 1em;color:var(--mut)}"
    ".meta{color:var(--mut);font-size:.9em}"
    ".actions{display:flex;gap:.6em;flex-wrap:wrap;margin-top:1.5em}"
    ".me{font-size:.8em;background:#eef3ff;border-radius:1em;padding:.1em .6em;margin-left:.4em;white-space:nowrap}"
    ".brand{display:flex;align-items:center;gap:.6em;margin-bottom:1.8em;color:inherit;text-decoration:none}"
    ".brand svg{width:42px;height:42px;flex:none}"
    ".brand span{font-size:1.1em;font-weight:600}"
)
