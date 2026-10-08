"""
Guida SEO/GEO «Audiolibri con la tua voce»: /guide/voice-cloning-audiobook/.

Contenuti in 7 lingue, registrati in guide_content.py. Passi e FAQ stanno qui
come dati strutturati: da una sola fonte nascono sia l'HTML visibile sia il
JSON-LD HowTo/FAQPage, così testo e schema non possono divergere.

Le etichette fra «» sono quelle reali dell'interfaccia (i18n_data.js): se
cambiano là vanno aggiornate anche qui. Nessun provider nominato.
"""

from __future__ import annotations

from content_store import content_json
from i18n import pick as _i18n_pick
import seo_ld as _seo_ld
import html as _html
import re as _re

GUIDE_ID = "voice-cloning-audiobook"
PUBLISHED = "2026-09-17"
SECTION = "Voice Cloning"

META = content_json("guides", GUIDE_ID, "meta.json")

# Lingue in cui si può campionare la voce (voice_clone_prompts.languages()).
_SAMPLE_LANGS = content_json("guides", GUIDE_ID, "sample_langs.json")

_T = content_json("guides", GUIDE_ID, "texts.json")

LANGS = tuple(_T.keys())


def _li(items):
    return "\n".join(f"  <li>{x}</li>" for x in items)


def body(lang: str) -> str:
    """HTML del corpo della guida; lingue sconosciute ricadono sull'inglese."""
    t = _i18n_pick(_T, lang, merge=False)
    steps = "\n".join(
        f'  <li id="step-{i}"><strong>{name}</strong> &mdash; {text}</li>'
        for i, (name, text) in enumerate(t["steps"], 1))
    faq = "\n".join(
        f"<details><summary>{q}</summary>\n<p>{a}</p>\n</details>" for q, a in t["faq"])
    return (
        f"\n{t['intro']}\n\n"
        f'<h2 id="what-you-need">{t["need_h2"]}</h2>\n<ul>\n{_li(t["need"])}\n</ul>\n\n'
        f'<h2 id="steps">{t["steps_h2"]}</h2>\n<ol>\n{steps}\n</ol>\n\n'
        f'<h2 id="tips">{t["tips_h2"]}</h2>\n<ul>\n{_li(t["tips"])}\n</ul>\n\n'
        f'<h2 id="other-devices">{t["devices_h2"]}</h2>\n{t["devices"]}\n\n'
        f'<h2 id="privacy">{t["privacy_h2"]}</h2>\n<ul>\n{_li(t["privacy"])}\n</ul>\n\n'
        f'<h2 id="faq">{t["faq_h2"]}</h2>\n{faq}\n'
    )


_TAG_RE = _re.compile(r"<[^>]+>")


def _plain(s: str) -> str:
    return " ".join(_html.unescape(_TAG_RE.sub("", s)).split())


def extra_ld(lang: str, canonical: str, meta: dict) -> list:
    """JSON-LD HowTo + FAQPage, generati dagli stessi dati del testo visibile."""
    t = _i18n_pick(_T, lang, merge=False)
    in_lang = _seo_ld.in_language(lang if lang in _T else "en")
    howto = _seo_ld.howto_ld(
        meta.get("h1", meta.get("title", "")), meta.get("desc", ""),
        [{"@type": "HowToStep", "position": i, "name": _plain(name), "text": _plain(text),
          **({"url": f"{canonical}#step-{i}"} if canonical else {})}
         for i, (name, text) in enumerate(t["steps"], 1)],
        in_lang=in_lang,
        before_steps={"totalTime": "PT15M",
                      "supply": [{"@type": "HowToSupply", "name": "EPUB, PDF, TXT"}],
                      "tool": [{"@type": "HowToTool", "name": "Microphone"}]})
    faq = _seo_ld.faq_ld([(_plain(q), _plain(a)) for q, a in t["faq"]], in_lang=in_lang)
    return [_seo_ld.ld_json(howto), _seo_ld.ld_json(faq)]
