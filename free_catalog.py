"""free_catalog — catalogo degli audiolibri gratuiti (`/free-audiobooks/`).

Spec: docs/superpowers/specs/2026-11-04-catalogo-audiolibri-gratuiti-design.md.
Il catalogo pubblico e' un JSON per lingua scritto dal repo privato
`abm-free-catalog` (`catalog/<lang>.json`, con `schema_version`): qui lo si
legge da `ABM_FREE_CATALOG_SOURCE` (percorso o URL con `{lang}`), lo si
valida, lo si tiene in cache e si costruiscono le pagine sulla shell
pubblica e le voci della sitemap. Senza la env il catalogo e' spento e le
route rispondono 404.

Il catalogo non porta mai il nome di un fornitore: la voce e' un'etichetta
(`voice_label`), la produzione ha solo date, l'invito verso l'app porta il
libro e non l'id voce.

Non importa `audiobook_app`: il QR arriva come funzione dal chiamante.
"""
import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import i18n
import page_brand
import seo_ld
from env_utils import env_int, env_str
from fileio import load_json, safe_filename
from og_image_data import og_image_url

SCHEMA_VERSION = 1
# Lingue del catalogo (spec §2): non coincidono con quelle del sito.
LANGS = ("it", "en", "de", "pt", "nl", "es")
# Token di condivisione permanente di un libro del catalogo (spec §7.6).
SHARE_PREFIX = "fc-"
PATH = "/free-audiobooks"
STATUSES = ("published", "coming")

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_BOOK_ID_RE = re.compile(r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
# URL usabili dentro attributi HTML e `url()` CSS: niente spazi, virgolette,
# parentesi o backslash (un URL del catalogo non ne ha mai bisogno).
_URL_RE = re.compile(r"""^(https?://|/)[^\s"'()<>\\]+$""")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_lock = threading.Lock()
# lingua -> (sorgente, istante di lettura, libri validi o None)
_cache = {}


# --- lettura e validazione ---------------------------------------------------

def _source(lang):
    tpl = env_str("ABM_FREE_CATALOG_SOURCE")
    return tpl.replace("{lang}", lang) if tpl else ""


def _fetch(src):
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return load_json(src, None)


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _url(value):
    v = _text(value)
    return v if _URL_RE.match(v) else ""


def _dict(value):
    return value if isinstance(value, dict) else {}


def _valid_file(f):
    """File pubblicato: URL, durata positiva, capitoli dentro il file; i dati
    tecnici (formato, bitrate, checksum) e l'anteprima sono facoltativi.
    L'anteprima e' un file a parte (i primi minuti): sul web si ascolta solo
    quella, il libro intero va nell'app o si scarica."""
    f = _dict(f)
    url, duration = _url(f.get("url")), _num(f.get("duration_s"))
    if not url or not duration or duration <= 0:
        return None
    chapters = []
    for ch in f.get("chapters") or []:
        start = _num(ch.get("start_s")) if isinstance(ch, dict) else None
        if start is None or start < 0 or start >= duration:
            continue
        chapters.append({"title": _text(ch.get("title")), "start_s": float(start)})
    chapters.sort(key=lambda c: c["start_s"])
    sha = _text(f.get("sha256")).lower()
    preview_url, preview_s = _url(f.get("preview_url")), _num(f.get("preview_s"))
    if not preview_url or not preview_s or preview_s <= 0:
        preview_url, preview_s = "", 0
    return {"url": url, "duration_s": float(duration), "bytes": int(_num(f.get("bytes")) or 0),
            "preview_url": preview_url, "preview_s": float(preview_s),
            "chapters": chapters, "format": _text(f.get("format")) or "M4B",
            "codec": _text(f.get("codec")), "bitrate_kbps": _num(f.get("bitrate_kbps")),
            "sample_rate": _num(f.get("sample_rate")), "channels": _num(f.get("channels")),
            "sha256": sha if _SHA_RE.match(sha) else ""}


def _valid_book(b):
    """Libro normalizzato, o None se manca un campo indispensabile."""
    if not isinstance(b, dict):
        return None
    book_id, slug, title = _text(b.get("book_id")), _text(b.get("slug")), _text(b.get("title"))
    author = _dict(b.get("author"))
    status = _text(b.get("status")) or "published"
    if not (_BOOK_ID_RE.match(book_id) and _SLUG_RE.match(slug) and title
            and _text(author.get("name")) and status in STATUSES):
        return None
    translator, cover = _dict(b.get("translator")), _dict(b.get("cover"))
    rights, production = _dict(b.get("rights")), _dict(b.get("production"))
    out = {"book_id": book_id, "slug": slug, "title": title, "status": status,
           "author": {"name": _text(author.get("name")), "born": _num(author.get("born")),
                      "died": _num(author.get("died")),
                      "sex": _text(author.get("sex")) if author.get("sex") in ("f", "m") else ""},
           "translator": ({"name": _text(translator.get("name")), "died": _num(translator.get("died")),
                           "sex": _text(translator.get("sex")) if translator.get("sex") in ("f", "m") else ""}
                          if _text(translator.get("name")) else None),
           "first_published": _num(b.get("first_published")),
           "chars": _num(b.get("chars")),
           "est_duration_s": _num(b.get("est_duration_s")),
           "description": _text(b.get("description")),
           "voice_label": _text(b.get("voice_label")),
           # Modello TTS di ABM che ha letto il libro ("Gemini 3.8"), scritto
           # dalla produzione del catalogo: la scheda lo mostra accanto alla voce.
           "voice_model": _text(b.get("voice_model")),
           "cover": {"url": _url(cover.get("url")), "thumb": _url(cover.get("thumb"))},
           "source": {**{k: _text(_dict(b.get("source")).get(k)) for k in ("site", "license", "edition")},
                      # pagina di lettura e file dell'ebook di origine (EPUB)
                      **{k: _url(_dict(b.get("source")).get(k)) for k in ("url", "ebook_url")}},
           "rights": {k: rights.get(k) for k in ("eu_pd", "us_pd") if isinstance(rights.get(k), bool)},
           "production": {"generated_at": _text(production.get("generated_at"))},
           "published_at": _text(b.get("published_at"))}
    if status == "published":
        out["file"] = _valid_file(b.get("file"))
        if out["file"] is None:
            return None
    return out


def validate(doc, lang):
    """Libri validi del documento; ValueError se schema o lingua non tornano.
    Un libro malformato si scarta da solo, non fa cadere il catalogo."""
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("schema_version assente o non supportata")
    if doc.get("lang") != lang:
        raise ValueError(f"lingua del documento {doc.get('lang')!r} invece di {lang!r}")
    seen, books = set(), []
    for raw in doc.get("books") or []:
        b = _valid_book(raw)
        if b and b["slug"] not in seen:
            seen.add(b["slug"])
            books.append(b)
    return books


def invalidate_cache():
    with _lock:
        _cache.clear()


def books(lang):
    """Libri del catalogo di `lang` (pubblicati e in arrivo), o None se il
    catalogo e' spento o non ancora leggibile. Un errore di lettura tiene
    l'ultima copia valida fino al prossimo tentativo (`ABM_FREE_CATALOG_TTL_SEC`)."""
    if lang not in LANGS:
        return None
    src = _source(lang)
    if not src:
        return None
    ttl = env_int("ABM_FREE_CATALOG_TTL_SEC", 600, floor=0)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(lang)
    if hit and hit[0] == src and now - hit[1] < ttl:
        return hit[2]
    previous = hit[2] if hit and hit[0] == src else None
    try:
        loaded = validate(_fetch(src), lang)
    except Exception as e:
        print(f"[free_catalog] catalogo {lang} non letto da {src}: {e}")
        loaded = previous
    with _lock:
        _cache[lang] = (src, now, loaded)
    return loaded


def _published(lang):
    return [b for b in books(lang) or [] if b["status"] == "published"]


def book(lang, slug):
    """Libro pubblicato di `lang` con quello slug, o None."""
    return next((b for b in _published(lang) if b["slug"] == slug), None)


def share_token(b):
    return SHARE_PREFIX + b["book_id"]


def book_for_share_token(token):
    """Libro pubblicato del token `fc-<book_id>`, o None."""
    if not isinstance(token, str) or not token.startswith(SHARE_PREFIX):
        return None
    book_id = token[len(SHARE_PREFIX):]
    return next((b for b in _published(book_id[:2]) if b["book_id"] == book_id), None)


def file_name(b):
    """Nome del file scaricato: "<Titolo> - <Autore>.m4b" con la regola unica
    dei nomi file degli output audio (`fileio.safe_filename`)."""
    return safe_filename(f"{b['title']} - {b['author']['name']}", replacement=" ") + ".m4b"


def download_path(lang, b):
    return f"{PATH}/dl/{lang}/{b['slug']}.m4b"


def local_files_dir():
    """Cartella locale che fa le veci del bucket pubblico in sviluppo
    (`ABM_FREE_CATALOG_FILES_DIR`, servita su `/free-audiobooks/files/`).
    Vuota in produzione: i file stanno sul bucket e il catalogo ha URL assoluti."""
    return env_str("ABM_FREE_CATALOG_FILES_DIR")


def sitemap_entries(base_url):
    """(loc, lastmod, priority) per l'indice di ogni lingua attiva e per ogni
    libro pubblicato. I libri in arrivo non hanno pagina e restano fuori."""
    out = []
    for lang in LANGS:
        items = books(lang)
        if not items:
            continue
        pubs = [b for b in items if b["status"] == "published"]
        dates = [b["published_at"] for b in pubs if b["published_at"]]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out.append((f"{base_url}{PATH}/{lang}/", max(dates) if dates else today, "0.7"))
        out.extend((f"{base_url}{PATH}/{lang}/{b['slug']}/", b["published_at"] or today, "0.6")
                   for b in pubs)
    return out


# --- presentazione -----------------------------------------------------------

def _t(lang):
    return i18n.pick(i18n.load("free_catalog"), lang)


def _esc(value):
    return html.escape(str(value or ""), quote=True)


def _duration(seconds, t):
    minutes = max(1, int(seconds / 60.0 + 0.5))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return t["duration_h"].format(h=hours, m=minutes)
    return t["duration_m"].format(m=minutes)


def _size(n_bytes, t):
    return t["size_mb"].format(mb=max(1, int(n_bytes / 1_000_000 + 0.5))) if n_bytes else ""


def _number(n, t):
    return f"{int(n):,}".replace(",", t["thousands_sep"])


def _date(iso, t):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso or "")
    return t["date_fmt"].format(y=m.group(1), m=m.group(2), d=m.group(3)) if m else ""


def _years(person):
    """"1840–1922" solo con entrambe le date: la sola data di morte, da
    sola, si legge male (e nell'elenco non compare)."""
    born, died = person.get("born"), person.get("died")
    return f"{int(born)}–{int(died)}" if born and died else ""


def _life(person, t):
    """Anni per la scheda: intervallo, o la sola morte detta per esteso."""
    if _years(person):
        return _years(person)
    key = "died_in_f" if person.get("sex") == "f" else "died_in"
    return t[key].format(y=int(person["died"])) if person.get("died") else ""


def _paragraphs(text):
    return "\n".join(f"<p>{_esc(p.strip())}</p>" for p in text.split("\n\n") if p.strip())


def _initials(title):
    words = [w for w in re.split(r"[\s,.;:'’\-]+", title) if w[:1].isalpha()]
    return "".join(w[0].upper() for w in words[:2]) or title[:1].upper()


def _cover_img(b, *, size, cls, thumb=False, lazy=True):
    """Copertina come `<img>`; senza immagine un riquadro con le iniziali."""
    src = (b["cover"]["thumb"] if thumb else "") or b["cover"]["url"]
    if not src:
        return f'<div class="{cls} fc-noimg" aria-hidden="true">{_esc(_initials(b["title"]))}</div>'
    loading = ' loading="lazy" decoding="async"' if lazy else ' fetchpriority="high"'
    return (f'<img class="{cls}" src="{_esc(src)}" alt="" width="{size}" height="{size}"{loading}>')


def _hm(seconds):
    """Durata compatta ore:minuti ("3:30") per elenco e scaffale."""
    minutes = max(1, int(seconds / 60.0 + 0.5))
    return f"{minutes // 60}:{minutes % 60:02d}"


def _book_hm(b):
    """Durata reale del libro pubblicato, stima ("~5:20") per quello in arrivo."""
    if b["status"] == "published":
        return _hm(b["file"]["duration_s"])
    return f"~{_hm(b['est_duration_s'])}" if b["est_duration_s"] else ""


def _card(lang, b, t):
    published = b["status"] == "published"
    title = _esc(b["title"])
    if published:
        title = f'<a href="{PATH}/{lang}/{_esc(b["slug"])}/">{title}</a>'
    return page_brand.render_page("free_catalog_card.html", {
        "__STATUS__": _esc(b["status"]),
        "__SEARCH__": _esc(f"{b['title']} {b['author']['name']}".lower()),
        "__COVER__": _cover_img(b, size=72, cls="fc-thumb", thumb=True),
        "__TITLE__": title,
        "__AUTHOR__": _esc(b["author"]["name"]),
        "__DURATION__": _esc(_book_hm(b)),
        "__DURATION_LABEL__": _esc(t["duration_label"] if published else t["duration_est_label"]),
        "__BADGE__": _esc(t["badge_published"] if published else t["badge_coming"]),
    })


def _shelf(lang, items, t, title):
    """Scaffale orizzontale di libri pubblicati ('' se non ce ne sono)."""
    if not items:
        return ""
    cards = "\n".join(page_brand.render_page("free_catalog_shelf_item.html", {
        "__HREF__": f"{PATH}/{lang}/{_esc(b['slug'])}/",
        "__COVER__": _cover_img(b, size=176, cls="fc-shelf-cover"),
        "__TITLE__": _esc(b["title"]), "__AUTHOR__": _esc(b["author"]["name"]),
        "__DURATION__": _esc(_book_hm(b)), "__DURATION_LABEL__": _esc(t["duration_label"]),
    }) for b in items)
    return page_brand.render_page("free_catalog_shelf.html", {"__TITLE__": _esc(title), "__ITEMS__": cards})


def _chips(values):
    return "".join(f"<li>{_esc(v)}</li>" for v in values if v)


def _footer(t):
    return f'<p>{_esc(t["footer"])} <a href="/">{_esc(t["footer_link"])}</a></p>'


def _css():
    return page_brand.page_template("free_catalog.css")


def _lang_ok(lang):
    return lang if lang in i18n.LANGS else None


def hub_html(lang, base_url):
    """Indice del catalogo di `lang`, o None se spento o lingua ignota."""
    items = books(lang)
    if items is None:
        return None
    t = _t(lang)
    canonical = f"{base_url}{PATH}/{lang}/"
    pubs = [b for b in items if b["status"] == "published"]
    art = [b for b in pubs + [b for b in items if b["status"] != "published"] if b["cover"]["url"]][:3]
    body = page_brand.render_page("free_catalog_hub.html", {
        "__KICKER__": _esc(t["hub_kicker"]), "__H1__": _esc(t["hub_h1"]),
        "__INTRO__": _esc(t["hub_intro"]),
        "__CHIPS__": _chips([t["hub_count"].format(n=len(pubs), total=len(items)),
                             t["chip_m4b"], t["chip_free"]]),
        "__HERO_COVERS__": "".join(_cover_img(b, size=200, cls="fc-hero-cover", lazy=False) for b in art),
        "__SHELF__": _shelf(lang, pubs, t, t["shelf_available"]),
        "__STEP1_T__": _esc(t["step1_title"]), "__STEP1__": _esc(t["step1"]),
        "__STEP2_T__": _esc(t["step2_title"]), "__STEP2__": _esc(t["step2"]),
        "__STEP3_T__": _esc(t["step3_title"]), "__STEP3__": _esc(t["step3"]),
        "__ALL_TITLE__": _esc(t["all_title"]),
        "__SEARCH_LABEL__": _esc(t["search_label"]), "__SEARCH_PH__": _esc(t["search_placeholder"]),
        "__F_ALL__": _esc(t["filter_all"]), "__F_PUBLISHED__": _esc(t["filter_published"]),
        "__F_COMING__": _esc(t["filter_coming"]), "__EMPTY__": _esc(t["search_empty"]),
        "__CARDS__": "\n".join(_card(lang, b, t) for b in items),
        "__CTA_TITLE__": _esc(t["cta_title"]), "__CTA_TEXT__": _esc(t["cta_text"]),
        "__CTA_BTN__": _esc(t["cta_button"]),
    })
    head = page_brand.seo_head(
        desc=_esc(t["hub_desc"]), canonical=canonical, og_type="website",
        og_title=_esc(t["hub_title"]), og_desc=_esc(t["hub_desc"]), og_url=canonical,
        og_image=og_image_url(base_url), lang=_lang_ok(lang),
        ld=[seo_ld.ld_json(seo_ld.breadcrumb_ld([
            ("Audiobook Maker", f"{base_url}/"), (t["crumb"], canonical)]))])
    return page_brand.public_page(
        lang=lang, title=_esc(t["hub_title"]), crumb=_esc(t["crumb"]), body=body,
        footer=_footer(t), head=head, css=_css())


def _voice_text(b, t, key):
    """La voce del libro con la forma `key`; col modello TTS se il catalogo lo
    dichiara (`<key>_model`: "Sulafat (voce sintetica TTS PREMIUM Gemini 3.8)")."""
    voice = b["voice_label"] or t["voice_default"]
    if b["voice_model"]:
        return t[key + "_model"].format(voice=voice, model=b["voice_model"])
    return t[key].format(voice=voice)


def _preview_html(b, t):
    """Anteprima ascoltabile sul web ('' se il catalogo non ne ha una)."""
    f = b["file"]
    if not f["preview_url"]:
        return ""
    return page_brand.render_page("free_catalog_preview.html", {
        "__LABEL__": _esc(t["preview_title"]),
        "__VOICE__": _esc(_voice_text(b, t, "voice")),
        "__SRC__": _esc(f["preview_url"]),
        "__NOTE__": _esc(t["preview_note"].format(
            min=max(1, int(f["preview_s"] / 60 + 0.5)), duration=_duration(f["duration_s"], t))),
        "__APP_LINK__": _esc(t["preview_app_link"]),
    })


def _app_button(href, t, cls):
    """Il bottone che porta il libro nella libreria dell'app (solo telefono)."""
    return (f'<a class="fc-btn {cls}" href="{_esc(href)}"><svg viewBox="0 0 24 24" aria-hidden="true">'
            f'<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/></svg>'
            f'{_esc(t["app_library_btn"])}</a>')


def _related_html(lang, b, t):
    others = [o for o in _published(lang)
              if o["slug"] != b["slug"] and o["author"]["name"] == b["author"]["name"]]
    if not others:
        return ""
    links = "".join(f'<li><a href="{PATH}/{lang}/{_esc(o["slug"])}/">{_esc(o["title"])}</a></li>'
                    for o in others[:6])
    return f'<section class="fc-related"><h2>{_esc(t["related"])}</h2><ul>{links}</ul></section>'


def _source_link(src):
    if not src["site"]:
        return ""
    if src["url"].startswith("https://"):
        return f'<a href="{_esc(src["url"])}" rel="noopener">{_esc(src["site"])}</a>'
    return _esc(src["site"])


def _ebook_html(b, t):
    """Riquadro con l'ebook da cui e' nato l'audiolibro: lettura online e,
    se c'e', il file EPUB. '' se la fonte non ha un URL."""
    src = b["source"]
    links = []
    if src["url"].startswith("https://"):
        links.append(f'<a class="fc-btn" href="{_esc(src["url"])}" rel="noopener">{_esc(t["ebook_read"])}</a>')
    if src["ebook_url"].startswith("https://"):
        links.append(f'<a class="fc-btn" href="{_esc(src["ebook_url"])}" rel="noopener">'
                     f'{_esc(t["ebook_epub"])}</a>')
    if not links:
        return ""
    text = t["ebook_text"].format(site=src["site"] or "—", license=src["license"] or "—")
    return (f'<section class="fc-ebook"><h2>{_esc(t["ebook_title"])}</h2><p>{_esc(text)}</p>'
            f'<div class="fc-ebook-links">{"".join(links)}</div></section>')


def _yes_no(value, t):
    return t["yes"] if value else t["no"]


def _scheda_html(lang, b, t):
    """Scheda dell'audiolibro: tutti i metadati pubblici, a gruppi. Solo
    righe con un valore; nessun dato del fornitore di sintesi."""
    f, src, rights = b["file"], b["source"], b["rights"]
    tr = b["translator"]
    quality = " · ".join(v for v in (
        t["kbps"].format(n=int(f["bitrate_kbps"])) if f["bitrate_kbps"] else "",
        t["khz"].format(n=f"{f['sample_rate'] / 1000:g}") if f["sample_rate"] else "",
        (t["mono"] if f["channels"] == 1 else t["stereo"]) if f["channels"] else "") if v)
    fmt = " · ".join(v for v in (f["format"], f["codec"].upper()) if v)
    sha = f["sha256"]
    groups = [
        (t["g_work"], [
            (t["m_title"], _esc(b["title"])),
            (t["m_author"], _esc(b["author"]["name"]) + (f" ({_esc(_life(b['author'], t))})"
                                                         if _life(b["author"], t) else "")),
            (t["m_first_published"], _esc(b["first_published"] and int(b["first_published"]))),
            (t["m_language"], _esc(_dict(t["lang_names"]).get(lang, lang))),
            (t["m_translator"], _esc(tr["name"]) + (f" ({_esc(_life(tr, t))})" if _life(tr, t) else "")
             if tr else ""),
            (t["m_chars"], _esc(t["chars_n"].format(n=_number(b["chars"], t))) if b["chars"] else ""),
        ]),
        (t["g_audio"], [
            (t["m_duration"], _esc(_duration(f["duration_s"], t))),
            (t["m_chapters"], _esc(len(f["chapters"]))),
            (t["m_format"], _esc(fmt)),
            (t["m_quality"], _esc(quality)),
            (t["m_size"], _esc(_size(f["bytes"], t))),
            (t["m_voice"], _esc(_voice_text(b, t, "voice_synthetic"))),
            (t["m_generated"], _esc(_date(b["production"]["generated_at"], t))),
            (t["m_published"], _esc(_date(b["published_at"], t))),
            (t["m_id"], f"<code>{_esc(b['book_id'])}</code>"),
            (t["m_sha"], f'<code title="{_esc(sha)}">{_esc(sha[:16])}…</code>' if sha else ""),
        ]),
        (t["g_rights"], [
            (t["m_source"], _source_link(src)),
            (t["m_ebook"], f'<a href="{_esc(src["ebook_url"])}" rel="noopener">{_esc(t["ebook_epub"])}</a>'
             if src["ebook_url"].startswith("https://") else ""),
            (t["m_edition"], _esc(src["edition"])),
            (t["m_license"], _esc(src["license"])),
            (t["m_pd_eu"], _esc(_yes_no(rights["eu_pd"], t)) if "eu_pd" in rights else ""),
            (t["m_pd_us"], _esc(_yes_no(rights["us_pd"], t)) if "us_pd" in rights else ""),
        ]),
    ]
    out = []
    for name, rows in groups:
        cells = "".join(f'<div><dt>{_esc(k)}</dt><dd>{v}</dd></div>' for k, v in rows if v)
        if cells:
            out.append(f'<div class="fc-sgroup"><h3>{_esc(name)}</h3><dl>{cells}</dl></div>')
    return "\n".join(out)


def book_html(lang, slug, base_url, qr_data_uri, *, app_url=None, stores_html=""):
    """Pagina di un libro pubblicato, o None. `qr_data_uri(text)` -> data URI
    PNG del QR (stringa vuota se non disponibile); `app_url(https_url)` -> il
    deep link dell'app per il telefono della richiesta, vuoto dal computer;
    `stores_html` sono i badge degli store, gia' pronti. Sul web solo
    l'anteprima: il libro intero si ascolta nell'app (o si scarica).

    Dal telefono il QR non serve: al suo posto il bottone "Scarica nella
    libreria", che apre l'app sul libro (o, su Android, la pagina degli store
    se l'app manca), come la pagina di download di ABM."""
    b = book(lang, slug)
    if b is None:
        return None
    t = _t(lang)
    f = b["file"]
    canonical = f"{base_url}{PATH}/{lang}/{b['slug']}/"
    hub = f"{PATH}/{lang}/"
    token = share_token(b)
    share_url = f"{base_url}/s/{token}"
    app_href = app_url(share_url) if app_url else ""
    qr = "" if app_href else (qr_data_uri(share_url) or "")
    # L'invito porta il libro, non l'id voce: l'id contiene il nome del motore,
    # che nella pagina non deve comparire. La SPA risolve `fc` nella voce.
    cta = "/?" + urllib.parse.urlencode(
        {"fc": b["book_id"], "utm_source": "catalog", "utm_campaign": f"{lang}-{b['slug']}"})
    more = [o for o in _published(lang) if o["slug"] != b["slug"]][:8]
    body = page_brand.render_page("free_catalog_book.html", {
        "__BACKDROP__": (f' style="--cover:url(\'{_esc(b["cover"]["url"])}\')"'
                         if b["cover"]["url"] else ""),
        "__COVER__": _cover_img(b, size=280, cls="fc-bcover", lazy=False),
        "__KICKER__": _esc(t["book_kicker"]), "__TITLE__": _esc(b["title"]),
        "__AUTHOR__": _esc(b["author"]["name"]), "__YEARS__": _esc(_years(b["author"])),
        "__CHIPS__": _chips([_duration(f["duration_s"], t), t["chapters_n"].format(n=len(f["chapters"])),
                             _size(f["bytes"], t), b["first_published"] and str(int(b["first_published"]))]),
        "__DL_HREF__": _esc(download_path(lang, b)), "__DL_LABEL__": _esc(t["download"]),
        # Dal telefono il primo bottone e' quello dell'app, il file viene dopo.
        "__DL_CLASS__": "" if app_href else "fc-btn-primary",
        "__APP_BTN__": _app_button(app_href, t, "fc-btn-primary") if app_href else "",
        "__DL_HINT__": _esc(t["download_hint"]),
        "__SCHEDA_LINK__": _esc(t["scheda_link"]),
        "__PREVIEW__": _preview_html(b, t),
        "__APP_TITLE__": _esc(t["app_title"]), "__APP_TEXT__": _esc(t["app_text"]),
        "__APP_QR__": (f'<div class="fc-app-qr"><img src="{_esc(qr)}" alt="{_esc(t["app_qr_alt"])}" '
                       f'width="152" height="152"></div>' if qr else ""),
        "__APP_ACTION__": (_app_button(app_href, t, "fc-btn-primary") if app_href
                           else f'<p>{_esc(t["app_qr_hint"])}</p>' if qr else ""),
        "__APP_WIFI__": _esc(t["app_wifi"]), "__STORES__": stores_html,
        "__ABOUT__": _esc(t["about"]), "__DESCRIPTION__": _paragraphs(b["description"]),
        "__SYNTHETIC__": _esc(t["synthetic"]), "__EBOOK__": _ebook_html(b, t),
        "__SCHEDA_TITLE__": _esc(t["scheda_title"]), "__SCHEDA__": _scheda_html(lang, b, t),
        "__CTA_TITLE__": _esc(t["cta_voice_title"]), "__CTA_TEXT__": _esc(t["cta_voice_text"]),
        "__CTA_HREF__": _esc(cta), "__CTA_BTN__": _esc(t["cta_voice_button"]),
        "__RELATED__": _related_html(lang, b, t),
        "__MORE__": _shelf(lang, more, t, t["shelf_more"]),
        "__BACK_HREF__": hub, "__BACK__": _esc(t["back"]),
    })
    desc = t["book_desc"].format(title=b["title"], author=b["author"]["name"])
    content_url = base_url + download_path(lang, b)
    ld = [seo_ld.audiobook_ld(
              name=b["title"], author=b["author"]["name"],
              in_lang=seo_ld.in_language(lang) if _lang_ok(lang) else lang, url=canonical,
              content_url=content_url, duration_s=f["duration_s"],
              description=b["description"][:300], date_published=b["published_at"] or None,
              base=base_url or seo_ld.SITE_URL),
          seo_ld.breadcrumb_ld([("Audiobook Maker", f"{base_url}/"),
                                (t["crumb"], f"{base_url}{hub}"), (b["title"], canonical)])]
    if b["cover"]["url"]:
        ld[0]["image"] = b["cover"]["url"]
    head = page_brand.seo_head(
        desc=_esc(desc), canonical=canonical, og_type="book", og_title=_esc(b["title"]),
        og_desc=_esc(desc), og_url=canonical,
        og_image=_esc(b["cover"]["url"]) or og_image_url(base_url),
        lang=_lang_ok(lang), ld=[seo_ld.ld_json(x) for x in ld])
    title = _esc(t["book_title"].format(title=b["title"], author=b["author"]["name"]))
    crumb = f'<a href="{hub}">{_esc(t["crumb"])}</a> &rsaquo; {_esc(b["title"])}'
    return page_brand.public_page(
        lang=lang, title=title, crumb=crumb, body=body, footer=_footer(t), head=head, css=_css())
