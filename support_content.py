"""support_content.py — Pagina di assistenza (/support).

Pagina statica multilingua (IT/EN) con FAQ sull'app Audiobook Maker & Player.
Nessun dato dinamico: testo approvato dal titolare. Pattern self-contained
coerente con privacy_content.py (stesso tema, breadcrumb + footer + langswitch).
"""

import page_brand
from content_store import content_json
_TXT = content_json("support", "texts.json")


def render_support_page(lang="it", base_url=""):
    """Ritorna l'HTML completo della pagina /support nella lingua richiesta.

    Stile coerente con /privacy (font DM Sans/DM Serif Display, variabili
    tema, breadcrumb + footer). Lingue: it (default), en.
    """
    t = _TXT.get(lang, _TXT["it"])
    home = base_url or "/"
    faq_html = "\n".join(
        f'<h2>{q}</h2>\n<p>{a}</p>' for q, a in t["faq"]
    )
    css = "h1{margin:18px 0 4px}\nul{padding-left:22px;margin-bottom:10px}\nli{margin-bottom:10px}\n"
    body = f"""<div class="langswitch"><a href="{t['switch_href']}">{t['switch_label']}</a></div>
<article>
<h1>{t['title']}</h1>
<div class="box"><p>{t['intro']}</p></div>
{faq_html}
<h2>{t['contact_h']}</h2>
<div class="box"><p>{t['contact']}</p></div>
</article>"""
    return page_brand.public_page(lang=t["lang"], title=t["title"], home=home, crumb=t["crumb"],
                                  body=body, footer=f"<p>{t['footer']}</p>", css=css)
