"""Attributi HTML dentro i testi della SPA e delle pagine: mai delimitati da
virgolette tipografiche. Nel testo francese dell'«À propos» `href=’https://…’`
faceva del link GitHub un percorso relativo (`/fr/’https://github.com/…’`, 404
in Search Console, 12/11/2026)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TYPO_ATTR = re.compile(r"\b[a-z-]+=[‘’“”]")


def test_nessun_attributo_con_virgolette_tipografiche():
    files = [*(ROOT / "templates").rglob("*.js"), *(ROOT / "templates").rglob("*.html"),
             *(ROOT / "i18n").glob("*.json"), *(ROOT / "content").rglob("*.html"),
             *(ROOT / "content").rglob("*.json")]
    assert files
    bad = [f"{p.relative_to(ROOT)}:{n}" for p in files
           for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
           if _TYPO_ATTR.search(line)]
    assert not bad, bad
