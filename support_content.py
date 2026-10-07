"""support_content.py — Pagina di assistenza (/support).

Pagina statica multilingua (IT/EN) con FAQ sull'app Audiobook Maker & Player.
Nessun dato dinamico: testo approvato dal titolare. Pattern self-contained
coerente con privacy_content.py (stesso tema, breadcrumb + footer + langswitch).
"""

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
    return f"""<!DOCTYPE html><html lang="{t['lang']}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="index,follow">
<title>{t['title']}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700&amp;family=DM+Serif+Display&amp;display=swap" rel="stylesheet">
<style>
:root{{--bg:#f5f3ef;--srf:#fff;--brd:#d5d0c8;--tx:#2c2a26;--txd:#6b6760;--txm:#9e9890;--ac:#c47a2a;--ach:#d4903e;--r:12px}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'DM Sans','PingFang SC','Microsoft YaHei','Noto Sans SC',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--tx);line-height:1.7;padding:20px;max-width:720px;margin:0 auto}}
h1{{font-family:'DM Serif Display',Georgia,serif;font-size:2rem;color:var(--ac);margin:18px 0 4px;line-height:1.25}}
h2{{font-family:'DM Serif Display',Georgia,serif;font-size:1.4rem;margin:32px 0 12px;color:var(--tx)}}
p,li{{margin-bottom:10px;color:var(--txd)}}
ul{{padding-left:22px;margin-bottom:10px}}
strong{{color:var(--tx)}}
a{{color:var(--ac);text-decoration:none}}
a:hover{{color:var(--ach);text-decoration:underline}}
.breadcrumb{{font-size:.85rem;color:var(--txm);margin-bottom:16px}}
.langswitch{{font-size:.85rem;margin-bottom:18px}}
.intro,.contact{{background:var(--srf);border:1px solid var(--brd);border-left:4px solid var(--ac);border-radius:var(--r);padding:14px 18px;margin:18px 0}}
.intro p,.contact p{{margin-bottom:0}}
footer{{margin-top:48px;padding-top:24px;border-top:1px solid var(--brd);font-size:.85rem;color:var(--txm)}}
</style></head><body>
<nav class="breadcrumb"><a href="{home}">Audiobook Maker</a> &rsaquo; {t['crumb']}</nav>
<div class="langswitch"><a href="{t['switch_href']}">{t['switch_label']}</a></div>
<article>
<h1>{t['title']}</h1>
<div class="intro"><p>{t['intro']}</p></div>
{faq_html}
<h2>{t['contact_h']}</h2>
<div class="contact"><p>{t['contact']}</p></div>
</article>
<footer><p>{t['footer']}</p></footer>
</body></html>"""
