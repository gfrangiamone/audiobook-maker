"""privacy_content.py — Informativa privacy (pagina /privacy).

Pagina statica multilingua (IT/EN) richiesta dal Play Store e dal GDPR.
Nessun dato dinamico: testo approvato dal titolare. Pattern self-contained
come le altre pagine HTML servite dall'app.
"""

import page_brand
from content_store import content_json, content_text
_LAST_UPDATED = content_json("privacy", "last_updated.json")

_TXT = {lang: dict(content_json("privacy", f"{lang}.json"),
                   body=content_text("privacy", f"{lang}.html"))
        for lang in ("it", "en")}


def render_privacy_page(lang="it", base_url=""):
    """Ritorna l'HTML completo della pagina /privacy nella lingua richiesta.

    Stile coerente con le guide del sito (font DM Sans/DM Serif Display,
    variabili tema, breadcrumb + footer). Lingue: it (default), en.
    """
    t = _TXT.get(lang, _TXT["it"])
    updated = _LAST_UPDATED.get(t["lang"], _LAST_UPDATED["it"])
    home = base_url or "/"
    css = ("h1{margin:18px 0 4px}\nul{padding-left:22px;margin-bottom:10px}\nli{margin-bottom:10px}\n"
           ".cookiebtn{display:inline-block;margin-top:6px;padding:10px 22px;background:var(--ac);color:#fff;"
           "border-radius:8px;text-decoration:none;font-weight:600}\n"
           ".cookiebtn:hover{background:var(--ach);color:#fff;text-decoration:none}\n")
    body = f"""<div class="langswitch"><a href="{t['switch_href']}">{t['switch_label']}</a></div>
<p class="updated">{t['updated_label']}: {updated}</p>
<article>
{t['body']}
<h2>{t['cookie_h']}</h2>
<p>{t['cookie_p']}</p>
<p>{t['cookie_p2']}</p>
<p><a class="cookiebtn" href="{home}?cookies=1">{t['cookie_btn']}</a></p>
<h2>{t['changes_h']}</h2>
<p>{t['changes_p']}</p>
</article>"""
    return page_brand.public_page(lang=t["lang"], title=t["title"], home=home, crumb=t["crumb"],
                                  body=body, footer=f"<p>{t['footer']}</p>", css=css)
