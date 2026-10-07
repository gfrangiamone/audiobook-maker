"""
seo_content.py — Testi SEO visibili iniettati server-side nel body HTML.

Questo modulo genera un blocco <section> con:
  - Direct answer quotabile (primi 150 caratteri)
  - H2 heading con keyword primaria
  - Paragrafo descrittivo denso di keyword
  - Tabella comparativa voci/lingue (dati citabili per GEO)
  - Audience targeting ("Ideale per...")
  - Lista "Come funziona" (features)
  - FAQ con <details>/<summary> (accessibili e SEO-friendly)
  - Privacy & disclosure
  - Timestamp ultimo aggiornamento
  - FAQPage + HowTo JSON-LD schema

Tutto questo HTML è presente nel sorgente statico della pagina, visibile
ai crawler dei motori di ricerca SENZA esecuzione di JavaScript.

Il blocco si adatta al tema della pagina usando le CSS custom properties
(--tx, --txd, --srf, ecc.) già definite nel tema light/dark.
"""

from content_store import content_json
from datetime import datetime
from html import escape
import json
import re

from version import get_formatted_date

# Convert bare URLs in escaped text to clickable links
_URL_RE = re.compile(r'(https?://[^\s)<>&]+/?)(?=[)\s.,;]|$)')


def _linkify(text: str) -> str:
    """Turn plain URLs in already-escaped HTML text into <a> links."""
    return _URL_RE.sub(r"<a href='\1' target='_blank' rel='noopener'>\1</a>", text)


# ═══════════════════════════════════════════════════════════════════
# CONTENUTI SEO VISIBILI PER LINGUA
# ═══════════════════════════════════════════════════════════════════

_CONTENT = content_json("seo", "content.json")


# ─── Tabella comparativa voci/lingue (condivisa, labels per lingua) ───

_VOICE_TABLE = content_json("seo", "tables.json")["voice_table"]

_TABLE_HEADERS = content_json("seo", "tables.json")["table_headers"]


# ─── HowTo steps per lingua ───

_HOWTO_STEPS = content_json("seo", "tables.json")["howto_steps"]


# ─── Feature lists per JSON-LD SoftwareApplication ───

_LD_FEATURES = content_json("seo", "tables.json")["ld_features"]


def _build_seo_block(lang: str) -> tuple[str, str, str]:
    """Genera il contenuto HTML + JSON-LD per una singola lingua.

    Returns:
        (article_html, faq_ld_json, howto_ld_json)
    """
    c = _CONTENT.get(lang, _CONTENT["en"])

    # Key Takeaways box HTML
    kt = c.get("key_takeaways", {})
    kt_items_html = ""
    if kt:
        for item in kt.get("items", []):
            kt_items_html += f"            <li>{item}</li>\n"
        kt_box_html = f"""
        <div class="key-takeaways">
            <h3>{escape(kt.get("title", ""))}</h3>
            <ul>
{kt_items_html}            </ul>
        </div>"""
    else:
        kt_box_html = ""

    # Features <li> items
    features_li = "\n".join(
        f"            <li>{escape(f)}</li>" for f in c["features"]
    )

    # FAQ <details> items + JSON-LD data
    faqs_html = ""
    faq_ld_items = []
    for q, a in c["faqs"]:
        faqs_html += (
            f'            <details class="seo-section"><summary>{escape(q)}</summary>\n'
            f'                <p>{_linkify(escape(a))}</p>\n'
            f'            </details>\n'
        )
        faq_ld_items.append({
            "@type": "Question",
            "name": q,
            "acceptedAnswer": {"@type": "Answer", "text": a},
        })

    faq_ld_json = json.dumps(
        {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faq_ld_items},
        ensure_ascii=False,
    )

    # HowTo JSON-LD
    steps = _HOWTO_STEPS.get(lang, _HOWTO_STEPS["en"])
    howto_ld_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": escape(c["features_heading"]),
        "description": escape(c["direct_answer"]),
        "step": [
            {
                "@type": "HowToStep",
                "name": name,
                "text": text,
            }
            for name, text in steps
        ],
    }, ensure_ascii=False)

    # Voice/language table
    headers = _TABLE_HEADERS.get(lang, _TABLE_HEADERS["en"])
    table_rows = ""
    for _lc, labels, count in _VOICE_TABLE:
        label = labels.get(lang, labels["en"])
        table_rows += (
            f'            <tr><td>{escape(label)}</td>'
            f'<td>{escape(count)}</td>'
            f'<td>Microsoft Edge TTS (Neural)</td></tr>\n'
        )

    article_html = f"""
        <div class="seo-summary">
            {escape(c["direct_answer"])}
        </div>

        {kt_box_html}

        <div class="seo-section" style="border-bottom:1px solid var(--brd,#d5d0c8); padding:0.8rem 0">
            <h2 style="font-size:1.25rem; color:var(--tx,#2c2a26); font-weight:600; margin-bottom:0.5rem">{escape(c["heading"])}</h2>
            <p style="margin-left:0.5rem">{escape(c["text"])}</p>
        </div>

        <details class="seo-section">
            <summary><h3>{escape(c["audience_heading"])}</h3></summary>
            <p>{escape(c["audience"])}</p>
        </details>

        <details class="seo-section">
            <summary><h3>{escape(c["table_heading"])}</h3></summary>
            <table>
                <thead><tr><th>{escape(headers[0])}</th><th>{escape(headers[1])}</th><th>{escape(headers[2])}</th></tr></thead>
                <tbody>
{table_rows}                </tbody>
            </table>
        </details>

        <details class="seo-section">
            <summary><h3>{escape(c["features_heading"])}</h3></summary>
            <ol>
{features_li}
            </ol>
        </details>

        <details class="seo-section">
            <summary><h3>{escape(c["faq_heading"])}</h3></summary>
            <div>
{faqs_html}            </div>
        </details>

        <details class="seo-section">
            <summary><strong>{escape(c["privacy_heading"])}</strong></summary>
            <div class="seo-privacy-body">
                {escape(c["privacy"])}
            </div>
        </details>

        <details class="seo-section">
            <summary><strong>{escape(c.get("accessibility_heading", "Accessibility & Inclusion"))}</strong></summary>
            <div class="seo-privacy-body">
                {escape(c.get("accessibility", ""))}
            </div>
        </details>

        <details class="seo-section">
            <summary><h3>{escape(c.get("guides_heading", "Free Guides"))}</h3></summary>
            <div>
                {c.get("guides_html", "")}
            </div>
        </details>

        <div class="seo-updated">
            <time datetime="{datetime.now().strftime('%Y-%m')}">{escape(c["updated_label"])}: {get_formatted_date()}</time>
        </div>"""

    return article_html, faq_ld_json, howto_ld_json


_ALL_LANGS = list(_CONTENT.keys())


def build_seo_content_html(initial_lang: str) -> str:
    """Genera il blocco HTML SEO con tutte le lingue, mostrando solo quella iniziale.

    Ogni lingua è racchiusa in un <article data-seo-lang="xx"> che viene
    mostrato/nascosto via CSS inline + la funzione JS switchSeoLang().

    I JSON-LD (FAQPage + HowTo) vengono emessi solo per la lingua iniziale
    (quelli attivi per i crawler alla prima visita); il JS li aggiorna al
    cambio lingua.

    Questo blocco viene iniettato server-side nel body prima di </body>.
    I crawler lo vedono immediatamente senza eseguire JavaScript.
    """

    # CSS (emesso una sola volta)
    css = """
<style>
#seoContent { max-width:720px; margin:2.5rem auto 1rem; padding:0 1.5rem;
  font-family:'DM Sans',system-ui,sans-serif; font-size:0.92rem; line-height:1.7; color:var(--txd,#6b6760) }
#seoContent .seo-summary { background:var(--srf,#fff); border:1px solid var(--brd,#d5d0c8);
  border-radius:8px; padding:1rem 1.2rem; margin-bottom:1.2rem; font-weight:500; color:var(--tx,#2c2a26); line-height:1.6 }
/* ── Key Takeaways box ── */
#seoContent .key-takeaways { background:linear-gradient(135deg,var(--srf,#fff) 0%,#fef9f3 100%);
  border:1.5px solid var(--ac,#c47a2a); border-radius:10px; padding:1rem 1.2rem; margin-bottom:1.2rem;
  box-shadow:0 2px 12px rgba(196,122,42,.12) }
#seoContent .key-takeaways h3 { font-size:1rem; color:var(--ac,#c47a2a); margin:0 0 0.7rem 0; font-weight:700;
  display:flex; align-items:center; gap:0.4rem }
#seoContent .key-takeaways h3::before { content:'✓'; font-size:1rem; font-weight:700 }
#seoContent .key-takeaways ul { margin:0; padding:0 0 0 1.2rem; list-style:none }
#seoContent .key-takeaways li { margin-bottom:0.4rem; color:var(--tx,#2c2a26); line-height:1.5;
  padding-left:0.2rem }
#seoContent .key-takeaways li::marker { color:var(--ac,#c47a2a) }
/* ── Collapsible sections (details/summary) ── */
#seoContent .seo-section { margin-bottom:0.25rem; border-bottom:1px solid var(--brd,#d5d0c8);
  padding:0.4rem 0 }
#seoContent .seo-section > summary { cursor:pointer; list-style:none; display:flex; align-items:center; gap:0.5rem }
#seoContent .seo-section > summary::-webkit-details-marker { display:none }
#seoContent .seo-section > summary::before { content:'\\25B6'; font-size:0.6rem; color:var(--ac,#c47a2a);
  transition:transform 0.2s; flex-shrink:0 }
#seoContent .seo-section[open] > summary::before { transform:rotate(90deg) }
#seoContent .seo-section > summary:hover { color:var(--ac,#c47a2a) }
#seoContent .seo-section > summary h2,
#seoContent .seo-section > summary h3,
#seoContent .seo-section > summary strong { margin:0; display:inline }
#seoContent .seo-section h2 { font-size:1.25rem; color:var(--tx,#2c2a26); font-weight:600 }
#seoContent .seo-section h3 { font-size:1.1rem; color:var(--tx,#2c2a26); font-weight:600 }
#seoContent .seo-section > summary strong { font-size:1rem; color:var(--tx,#2c2a26) }
/* ── Inner content of collapsible sections ── */
#seoContent .seo-section p { margin:0.5rem 0 0.5rem 0.5rem }
#seoContent .seo-section ol { padding-left:1.8rem; margin:0.5rem 0 }
#seoContent .seo-section li { margin-bottom:0.3rem }
#seoContent .seo-section table { width:100%; border-collapse:collapse; margin:0.5rem 0 1rem; font-size:0.88rem }
#seoContent .seo-section th { text-align:left; padding:0.5rem 0.8rem; background:var(--srf2,#f0ede8); color:var(--tx,#2c2a26);
  font-weight:600; border-bottom:2px solid var(--brd,#d5d0c8) }
#seoContent .seo-section td { padding:0.45rem 0.8rem; border-bottom:1px solid var(--brd,#d5d0c8) }
/* ── Nested FAQ details inside a seo-section ── */
#seoContent .seo-section details { margin-bottom:0.3rem; padding:0.4rem 0; border-bottom:1px solid var(--brd,#d5d0c8) }
#seoContent .seo-section details:last-child { border-bottom:none }
#seoContent .seo-section details summary { cursor:pointer; font-weight:500; color:var(--tx,#2c2a26) }
#seoContent .seo-section details summary:hover { color:var(--ac,#c47a2a) }
#seoContent .seo-section details p { margin:0.5rem 0 0; padding-left:0.5rem }
/* ── Privacy body ── */
#seoContent .seo-privacy-body { margin:0.5rem 0 0.5rem 0.5rem; padding:0.8rem; background:var(--srf,#fff);
  border:1px solid var(--brd,#d5d0c8); border-radius:8px; font-size:0.85rem }
/* ── Updated timestamp ── */
#seoContent .seo-updated { margin-top:1rem; font-size:0.8rem; color:var(--txm,#9e9890) }
/* ── Share bar (below SEO content) ── */
#seoContent .share-icons a:hover, #seoContent .share-icons button:hover { border-color:currentColor; transform:translateY(-2px); box-shadow:0 3px 10px rgba(0,0,0,.08) }
#seoContent .share-copied.show { opacity:1!important }
</style>"""

    # Build all language blocks
    articles = []

    for lang in _ALL_LANGS:
        article_html, _, _ = _build_seo_block(lang)
        display = "block" if lang == initial_lang else "none"
        articles.append(
            f'    <article data-seo-lang="{lang}" style="display:{display}">'
            f'{article_html}'
            f'\n    </article>'
        )

    articles_html = "\n".join(articles)

    # JS function to switch SEO content language (called from setLang)
    switch_js = """
<script>
function switchSeoLang(l){
  var sec=document.getElementById('seoContent');
  if(!sec)return;
  sec.querySelectorAll('article[data-seo-lang]').forEach(function(a){
    a.style.display=a.getAttribute('data-seo-lang')===l?'block':'none';
  });
}
</script>"""

    share_bar = """
    <div class="share-row" id="shareRow" style="margin-top:2rem;padding-top:1.2rem;border-top:1px solid var(--brd,#d5d0c8);text-align:center">
        <div class="share-label" data-t="share_label" style="font-size:.82rem;color:var(--txm,#767676);margin-bottom:10px"></div>
        <div class="share-icons" style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap">
          <a id="shX" target="_blank" rel="noopener" title="X / Twitter" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#14171a;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
          <a id="shFb" target="_blank" rel="noopener" title="Facebook" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#1877F2;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg></a>
          <a id="shWa" target="_blank" rel="noopener" title="WhatsApp" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#25D366;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg></a>
          <a id="shTg" target="_blank" rel="noopener" title="Telegram" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#26A5E4;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M11.944 0A12 12 0 000 12a12 12 0 0012 12 12 12 0 0012-12A12 12 0 0012 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg></a>
          <a id="shLi" target="_blank" rel="noopener" title="LinkedIn" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#0A66C2;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg></a>
          <a id="shRd" target="_blank" rel="noopener" title="Reddit" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:#FF4500;cursor:pointer;transition:all .2s;text-decoration:none;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M12 0C5.373 0 0 5.373 0 12c0 5.084 3.163 9.426 7.627 11.174-.105-.949-.2-2.405.042-3.441.218-.937 1.407-5.965 1.407-5.965s-.359-.719-.359-1.782c0-1.668.967-2.914 2.171-2.914 1.023 0 1.518.769 1.518 1.69 0 1.029-.655 2.568-.994 3.995-.283 1.194.599 2.169 1.777 2.169 2.133 0 3.772-2.249 3.772-5.495 0-2.873-2.064-4.882-5.012-4.882-3.414 0-5.418 2.561-5.418 5.207 0 1.031.397 2.138.893 2.738a.36.36 0 01.083.345l-.333 1.36c-.053.22-.174.267-.402.161-1.499-.698-2.436-2.889-2.436-4.649 0-3.785 2.75-7.262 7.929-7.262 4.163 0 7.398 2.967 7.398 6.931 0 4.136-2.607 7.464-6.227 7.464-1.216 0-2.359-.631-2.75-1.378l-.748 2.853c-.271 1.043-1.002 2.35-1.492 3.146C9.57 23.812 10.763 24 12 24c6.627 0 12-5.373 12-12 0-6.628-5.373-12-12-12z"/></svg></a>
          <div class="share-copy-wrap" style="position:relative;display:inline-flex">
            <button id="shCopy" title="Copy link" style="width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brd,#d5d0c8);background:var(--srf2,#f0ede8);color:var(--txd,#6b6760);cursor:pointer;transition:all .2s;padding:0"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg></button>
            <span class="share-copied" id="shCopiedTip" data-t="share_copied" style="position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);background:var(--tx,#2c2a26);color:var(--bg,#f5f3ef);font-size:.72rem;padding:3px 8px;border-radius:4px;white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .2s"></span>
          </div>
        </div>
    </div>"""

    return f"""
<!-- ═══════════════════ SEO CONTENT (server-rendered, visible to crawlers) ═══════════════════ -->
{css}
{switch_js}
<section id="seoContent">
{articles_html}
{share_bar}
</section>
<!-- ═══════════════════ /SEO CONTENT ═══════════════════ -->
"""


def get_schema_ld(lang: str) -> tuple[str, str, str]:
    """Restituisce (faq_ld_json, howto_ld_json, combined_ld_json) per la lingua data.

    combined_ld_json contiene SoftwareApplication + Organization + Review in un
    array JSON-LD (graph), iniettato nel <head>.
    """
    article_html, faq_ld_raw, howto_ld_raw = _build_seo_block(lang)

    features = _LD_FEATURES.get(lang, _LD_FEATURES["en"])
    c = _CONTENT.get(lang, _CONTENT["en"])

    base_url = "https://audiobook-maker.com"

    # ISO-8601 dateModified — refreshed at startup. Tells crawlers and AI
    # assistants when the page content was last revised, which boosts
    # freshness signals in Google AI Overview / Perplexity citations.
    iso_modified = datetime.now().strftime("%Y-%m-%d")

    # SoftwareApplication
    software_app_ld = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Audiobook Maker",
        "alternateName": "Audiobook Maker Online",
        "url": f"{base_url}/{lang}/",
        "description": c["direct_answer"],
        "applicationCategory": "MultimediaApplication",
        "applicationSubCategory": "Text-to-Speech Converter",
        "operatingSystem": "Any (Web Browser)",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        "inLanguage": ["it", "en", "fr", "es", "de", "zh-Hans"],
        "featureList": features,
        "isAccessibleForFree": True,
        "screenshot": f"{base_url}/og-image.png",
        "dateModified": iso_modified,
        "author": {
            "@type": "Person",
            "name": "Giuseppe Frangiamone",
            "url": "https://github.com/gfrangiamone",
        },
        "license": "https://www.gnu.org/licenses/agpl-3.0.html",
        "sameAs": [
            "https://github.com/gfrangiamone/audiobook-maker",
            "https://alternativeto.net/software/audiobook-maker/",
        ],
    }

    # Organization
    organization_ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Audiobook Maker",
        "url": base_url,
        "logo": f"{base_url}/favicon-192.png",
        "description": c["direct_answer"],
        "foundingDate": "2024",
        "founder": {
            "@type": "Person",
            "name": "Giuseppe Frangiamone",
            "url": "https://github.com/gfrangiamone",
        },
        "sameAs": [
            "https://github.com/gfrangiamone/audiobook-maker",
            "https://alternativeto.net/software/audiobook-maker/",
        ],
    }

    # WebSite (Sitelinks Search Box). potentialAction points at the converter
    # itself — schema.org allows a `UseAction` to represent the primary
    # action a user takes on the page, which Google AI Overview uses to
    # surface "use" / "try" CTAs. We don't claim a SearchAction because the
    # site has no on-site search.
    website_ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "Audiobook Maker",
        "alternateName": "Audiobook Maker Online",
        "url": base_url,
        "description": c["direct_answer"],
        "inLanguage": ["it", "en", "fr", "es", "de", "zh-Hans"],
        "publisher": {"@type": "Organization", "name": "Audiobook Maker", "url": base_url},
        "potentialAction": {
            "@type": "UseAction",
            "name": "Convert ebook to audiobook",
            "target": f"{base_url}/{lang}/",
        },
    }

    # WebPage — single canonical block for this page. Combines:
    #   • Speakable (voice-first surfaces)
    #   • Accessibility metadata (a11y rich-results)
    #   • Breadcrumb (avoids the second top-level BreadcrumbList block)
    #   • dateModified for freshness signals
    webpage_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "url": f"{base_url}/{lang}/",
        "name": c.get("heading", "Audiobook Maker"),
        "description": c["direct_answer"],
        "inLanguage": lang if lang != "zh" else "zh-Hans",
        "isPartOf": {"@type": "WebSite", "url": base_url, "name": "Audiobook Maker"},
        "primaryImageOfPage": f"{base_url}/og-image.png",
        "datePublished": "2022-06-01",
        "dateModified": iso_modified,
        "accessibilityFeature": ["displayTransformability", "audioDescription"],
        "accessMode": ["textual", "visual", "auditory"],
        "accessModeSufficient": ["auditory"],
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Audiobook Maker", "item": base_url},
                {"@type": "ListItem", "position": 2,
                 "name": c.get("crumb", "Online Converter"),
                 "item": f"{base_url}/{lang}/"},
            ],
        },
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": ["h1", "h2", ".seo-summary"],
        },
    }

    # Inject dateModified into FAQPage + HowTo (parse the strings produced by
    # _build_seo_block, mutate, re-serialize). Cheap — these dicts are small.
    try:
        faq_obj = json.loads(faq_ld_raw)
        faq_obj["dateModified"] = iso_modified
        faq_ld = json.dumps(faq_obj, ensure_ascii=False)
    except Exception:
        faq_ld = faq_ld_raw
    try:
        howto_obj = json.loads(howto_ld_raw)
        howto_obj["dateModified"] = iso_modified
        howto_ld = json.dumps(howto_obj, ensure_ascii=False)
    except Exception:
        howto_ld = howto_ld_raw

    # Combine into a JSON-LD graph (array of objects)
    combined = [software_app_ld, organization_ld, website_ld, webpage_ld]
    combined_ld_json = json.dumps(combined, ensure_ascii=False)

    return faq_ld, howto_ld, combined_ld_json
