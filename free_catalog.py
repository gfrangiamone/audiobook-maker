"""free_catalog — catalogo degli audiolibri gratuiti (`/free-audiobooks/`).

Spec: docs/superpowers/specs/2026-11-04-catalogo-audiolibri-gratuiti-design.md.
Il catalogo pubblico e' un JSON per lingua scritto dal repo privato
`abm-free-catalog` (`catalog/<lang>.json`, con `schema_version`): qui lo si
legge da `ABM_FREE_CATALOG_SOURCE` (percorso o URL con `{lang}`), lo si
valida, lo si tiene in cache e si costruiscono le pagine sulla shell
pubblica. Senza la env il catalogo e' spento e le route rispondono 404.

Il catalogo non porta mai il nome di un fornitore: la voce e' un'etichetta
(`voice_label`), l'id voce serve solo all'invito verso l'app.

Non importa `audiobook_app`: il QR arriva come funzione dal chiamante.
"""
import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request

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


def _valid_file(f):
    """File pubblicato: URL, durata positiva, capitoli con inizio crescente."""
    if not isinstance(f, dict):
        return None
    url = _text(f.get("url"))
    duration = _num(f.get("duration_s"))
    if not url.startswith(("https://", "http://", "/")) or not duration or duration <= 0:
        return None
    chapters = []
    for ch in f.get("chapters") or []:
        start = _num(ch.get("start_s")) if isinstance(ch, dict) else None
        if start is None or start < 0 or start >= duration:
            continue
        chapters.append({"title": _text(ch.get("title")), "start_s": float(start)})
    chapters.sort(key=lambda c: c["start_s"])
    return {"url": url, "duration_s": float(duration), "bytes": int(_num(f.get("bytes")) or 0),
            "chapters": chapters}


def _valid_book(b):
    """Libro normalizzato, o None se manca un campo indispensabile."""
    if not isinstance(b, dict):
        return None
    book_id, slug, title = _text(b.get("book_id")), _text(b.get("slug")), _text(b.get("title"))
    author = b.get("author") if isinstance(b.get("author"), dict) else {}
    status = _text(b.get("status")) or "published"
    if not (_BOOK_ID_RE.match(book_id) and _SLUG_RE.match(slug) and title
            and _text(author.get("name")) and status in STATUSES):
        return None
    out = {"book_id": book_id, "slug": slug, "title": title, "status": status,
           "author": {"name": _text(author.get("name")), "born": _num(author.get("born")),
                      "died": _num(author.get("died"))},
           "first_published": _num(b.get("first_published")),
           "description": _text(b.get("description")),
           "voice_label": _text(b.get("voice_label")),
           "voice_id": _text(b.get("voice_id")),
           "source": b.get("source") if isinstance(b.get("source"), dict) else {},
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


def book(lang, slug):
    """Libro pubblicato di `lang` con quello slug, o None."""
    for b in books(lang) or []:
        if b["slug"] == slug and b["status"] == "published":
            return b
    return None


def share_token(b):
    return SHARE_PREFIX + b["book_id"]


def book_for_share_token(token):
    """Libro pubblicato del token `fc-<book_id>`, o None."""
    if not isinstance(token, str) or not token.startswith(SHARE_PREFIX):
        return None
    book_id = token[len(SHARE_PREFIX):]
    lang = book_id[:2]
    for b in books(lang) or []:
        if b["book_id"] == book_id and b["status"] == "published":
            return b
    return None


def file_name(b):
    """Nome del file scaricato: "<Titolo> - <Autore>.m4b" con la regola unica
    dei nomi file degli output audio (`fileio.safe_filename`)."""
    return safe_filename(f"{b['title']} - {b['author']['name']}", replacement=" ") + ".m4b"


def download_path(lang, b):
    return f"{PATH}/dl/{lang}/{b['slug']}.m4b"


# --- presentazione -----------------------------------------------------------

def _t(lang):
    return i18n.pick(i18n.load("free_catalog"), lang)


def _esc(value):
    return html.escape(str(value or ""), quote=True)


def _duration(seconds, t):
    minutes = max(1, int(round(seconds / 60.0)))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return t["duration_h"].format(h=hours, m=minutes)
    return t["duration_m"].format(m=minutes)


def _size(n_bytes, t):
    return t["size_mb"].format(mb=max(1, int(round(n_bytes / 1_000_000)))) if n_bytes else ""


def _years(author):
    born, died = author.get("born"), author.get("died")
    if born and died:
        return f"{int(born)}–{int(died)}"
    return f"† {int(died)}" if died else ""


def _clock(seconds):
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _paragraphs(text):
    return "\n".join(f"<p>{_esc(p.strip())}</p>" for p in text.split("\n\n") if p.strip())


def _initials(title):
    words = [w for w in re.split(r"[\s,.;:'’\-]+", title) if w[:1].isalpha()]
    return "".join(w[0].upper() for w in words[:2]) or title[:1].upper()


def _card(lang, b, t):
    published = b["status"] == "published"
    title = _esc(b["title"])
    if published:
        title = f'<a href="{PATH}/{lang}/{_esc(b["slug"])}/">{title}</a>'
        meta = _duration(b["file"]["duration_s"], t)
        badge = t["badge_published"]
    else:
        meta, badge = "", t["badge_coming"]
    years = _years(b["author"])
    search = f"{b['title']} {b['author']['name']}".lower()
    return page_brand.render_page("free_catalog_card.html", {
        "__STATUS__": _esc(b["status"]), "__SEARCH__": _esc(search),
        "__INITIALS__": _esc(_initials(b["title"])), "__TITLE__": title,
        "__AUTHOR__": _esc(b["author"]["name"]) + (f" <span>({_esc(years)})</span>" if years else ""),
        "__META__": _esc(meta), "__BADGE__": _esc(badge),
    })


def _footer(t):
    return f'<p>{_esc(t["footer"])} <a href="/">{_esc(t["footer_link"])}</a></p>'


def hub_html(lang, base_url):
    """Indice del catalogo di `lang`, o None se spento o lingua ignota."""
    items = books(lang)
    if items is None:
        return None
    t = _t(lang)
    canonical = f"{base_url}{PATH}/{lang}/"
    published = sum(1 for b in items if b["status"] == "published")
    body = page_brand.render_page("free_catalog_hub.html", {
        "__H1__": _esc(t["hub_h1"]), "__INTRO__": _esc(t["hub_intro"]),
        "__COUNT__": _esc(t["hub_count"].format(n=published, total=len(items))),
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
        og_image=og_image_url(base_url), lang=lang if lang in i18n.LANGS else None,
        ld=[seo_ld.ld_json(seo_ld.breadcrumb_ld([
            ("Audiobook Maker", f"{base_url}/"), (t["crumb"], canonical)]))])
    return page_brand.public_page(
        lang=lang, title=_esc(t["hub_title"]), crumb=_esc(t["crumb"]), body=body,
        footer=_footer(t), head=head, css=page_brand.page_template("free_catalog.css"))


def _chapters_html(f):
    return "\n".join(
        f'<li><button type="button" data-t="{int(c["start_s"])}">'
        f'<span>{_esc(c["title"]) or "&nbsp;"}</span><time>{_clock(c["start_s"])}</time></button></li>'
        for c in f["chapters"])


def _related_html(lang, b, t):
    others = [o for o in books(lang) or []
              if o["status"] == "published" and o["slug"] != b["slug"]
              and o["author"]["name"] == b["author"]["name"]]
    if not others:
        return ""
    links = "".join(f'<li><a href="{PATH}/{lang}/{_esc(o["slug"])}/">{_esc(o["title"])}</a></li>'
                    for o in others[:6])
    return f'<section class="fc-related"><h2>{_esc(t["related"])}</h2><ul>{links}</ul></section>'


def _source_html(b, t):
    src = b["source"]
    site, url, lic = _text(src.get("site")), _text(src.get("url")), _text(src.get("license"))
    if not site:
        return ""
    name = f'<a href="{_esc(url)}" rel="nofollow noopener">{_esc(site)}</a>' if url.startswith("https://") else _esc(site)
    return _esc(t["source"]).replace("{site}", name).replace("{license}", _esc(lic or "—"))


def book_html(lang, slug, base_url, qr_data_uri):
    """Pagina di un libro pubblicato, o None. `qr_data_uri(text)` -> data URI
    PNG del QR (stringa vuota se non disponibile)."""
    b = book(lang, slug)
    if b is None:
        return None
    t = _t(lang)
    f = b["file"]
    canonical = f"{base_url}{PATH}/{lang}/{b['slug']}/"
    hub = f"{PATH}/{lang}/"
    token = share_token(b)
    app_link = f"{base_url}/s/{token}"
    host = urllib.parse.urlsplit(base_url).netloc or "audiobook-maker.com"
    qr = qr_data_uri(app_link) or ""
    meta = [_duration(f["duration_s"], t), t["chapters_n"].format(n=len(f["chapters"]))]
    if f["bytes"]:
        meta.append(_size(f["bytes"], t))
    years = _years(b["author"])
    # L'invito porta il libro, non l'id voce: l'id contiene il nome del motore,
    # che nella pagina non deve comparire. La SPA risolve `fc` nella voce.
    cta = "/?" + urllib.parse.urlencode(
        {"fc": b["book_id"], "utm_source": "catalog", "utm_campaign": f"{lang}-{b['slug']}"})
    body = page_brand.render_page("free_catalog_book.html", {
        "__INITIALS__": _esc(_initials(b["title"])), "__TITLE__": _esc(b["title"]),
        "__AUTHOR__": _esc(b["author"]["name"]), "__YEARS__": _esc(years),
        "__META__": _esc(" · ".join(meta)),
        "__VOICE__": _esc(t["voice"].format(voice=b["voice_label"] or t["voice_default"])),
        "__DESCRIPTION__": _paragraphs(b["description"]),
        "__AUDIO_LABEL__": _esc(t["listen"]), "__AUDIO_SRC__": _esc(f["url"]),
        "__CHAPTERS_LABEL__": _esc(t["chapters"]), "__CHAPTERS__": _chapters_html(f),
        "__DL_HREF__": _esc(download_path(lang, b)), "__DL_LABEL__": _esc(t["download"]),
        "__DL_HINT__": _esc(t["download_hint"].format(size=_size(f["bytes"], t) or "M4B")),
        "__APP_TITLE__": _esc(t["app_title"]),
        "__APP_QR_IMG__": (f'<img src="{_esc(qr)}" alt="{_esc(t["app_qr_alt"])}" width="168" height="168">'
                           if qr else ""),
        "__APP_QR_HINT__": _esc(t["app_qr_hint"]),
        "__APP_OPEN_HREF__": _esc(f"abm://{host}/s/{token}"), "__APP_OPEN__": _esc(t["app_open"]),
        "__APP_GET__": _esc(t["app_get"]), "__APP_WIFI__": _esc(t["app_wifi"]),
        "__SOURCE__": _source_html(b, t), "__SYNTHETIC__": _esc(t["synthetic"]),
        "__CTA_TITLE__": _esc(t["cta_voice_title"]), "__CTA_TEXT__": _esc(t["cta_voice_text"]),
        "__CTA_HREF__": _esc(cta), "__CTA_BTN__": _esc(t["cta_voice_button"]),
        "__RELATED__": _related_html(lang, b, t),
        "__BACK_HREF__": hub, "__BACK__": _esc(t["back"]),
    })
    desc = t["book_desc"].format(title=b["title"], author=b["author"]["name"])
    ld = [seo_ld.audiobook_ld(
              name=b["title"], author=b["author"]["name"], in_lang=seo_ld.in_language(lang)
              if lang in i18n.LANGS else lang, url=canonical,
              content_url=base_url + download_path(lang, b), duration_s=f["duration_s"],
              description=b["description"][:300], date_published=b["published_at"] or None,
              base=base_url or seo_ld.SITE_URL),
          seo_ld.breadcrumb_ld([("Audiobook Maker", f"{base_url}/"),
                                (t["crumb"], f"{base_url}{hub}"), (b["title"], canonical)])]
    head = page_brand.seo_head(
        desc=_esc(desc), canonical=canonical, og_type="book", og_title=_esc(b["title"]),
        og_desc=_esc(desc), og_url=canonical, og_image=og_image_url(base_url),
        lang=lang if lang in i18n.LANGS else None, ld=[seo_ld.ld_json(x) for x in ld])
    title = _esc(t["book_title"].format(title=b["title"], author=b["author"]["name"]))
    crumb = f'<a href="{hub}">{_esc(t["crumb"])}</a> &rsaquo; {_esc(b["title"])}'
    return page_brand.public_page(
        lang=lang, title=title, crumb=crumb, body=body, footer=_footer(t), head=head,
        css=page_brand.page_template("free_catalog.css"))
