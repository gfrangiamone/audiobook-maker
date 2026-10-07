"""privacy_content.py — Informativa privacy (pagina /privacy).

Pagina statica multilingua (IT/EN) richiesta dal Play Store e dal GDPR.
Nessun dato dinamico: testo approvato dal titolare. Pattern self-contained
come le altre pagine HTML servite dall'app.
"""

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
h3{{font-family:'DM Sans',system-ui,sans-serif;font-size:1.1rem;font-weight:600;margin:20px 0 8px;color:var(--tx)}}
p,li{{margin-bottom:10px;color:var(--txd)}}
ul{{padding-left:22px;margin-bottom:10px}}
strong{{color:var(--tx)}}
a{{color:var(--ac);text-decoration:none}}
a:hover{{color:var(--ach);text-decoration:underline}}
.tablewrap{{overflow-x:auto;margin:12px 0}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}}
th,td{{border:1px solid var(--brd);padding:8px 10px;text-align:left;vertical-align:top;color:var(--txd)}}
th{{background:#efe9e0;color:var(--tx);font-weight:600}}
.breadcrumb{{font-size:.85rem;color:var(--txm);margin-bottom:16px}}
.langswitch{{font-size:.85rem;margin-bottom:18px}}
.updated{{font-size:.85rem;color:var(--txm);margin:6px 0 24px}}
footer{{margin-top:48px;padding-top:24px;border-top:1px solid var(--brd);font-size:.85rem;color:var(--txm)}}
.cookiebtn{{display:inline-block;margin-top:6px;padding:10px 22px;background:var(--ac);color:#fff;border-radius:8px;text-decoration:none;font-weight:600}}
.cookiebtn:hover{{background:var(--ach);color:#fff;text-decoration:none}}
</style></head><body>
<nav class="breadcrumb"><a href="{home}">Audiobook Maker</a> &rsaquo; {t['crumb']}</nav>
<div class="langswitch"><a href="{t['switch_href']}">{t['switch_label']}</a></div>
<p class="updated">{t['updated_label']}: {updated}</p>
<article>
{t['body']}
<h2>{t['cookie_h']}</h2>
<p>{t['cookie_p']}</p>
<p>{t['cookie_p2']}</p>
<p><a class="cookiebtn" href="{home}?cookies=1">{t['cookie_btn']}</a></p>
<h2>{t['changes_h']}</h2>
<p>{t['changes_p']}</p>
</article>
<footer><p>{t['footer']}</p></footer>
</body></html>"""
