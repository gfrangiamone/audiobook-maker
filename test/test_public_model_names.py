"""Nomi dei modelli nei testi per l'utente (13/11/2026): il modello delle voci
inventate si chiama «Audiobook Maker (Fast)», quello lento «Audiobook Maker
(batch)»; il nome del motore (VoxCPM) non compare in nessuna etichetta."""
import json
import re
from pathlib import Path

import email_service
import pocket_catalog
import voxcpm_catalog

ROOT = Path(__file__).resolve().parents[1]
ENGINE = re.compile(r"voxcpm", re.I)


def _json_strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _json_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _json_strings(v)
    elif isinstance(node, str):
        yield node


def test_model_labels():
    assert voxcpm_catalog.MODEL_LABEL == "Audiobook Maker (Fast)"
    assert pocket_catalog.MODEL_LABEL == "Audiobook Maker (batch)"
    assert not [v for v in email_service._VOUCHER_SERVICE_LABELS.values() if ENGINE.search(v)]


def test_spa_strings_never_name_the_engine():
    # Chiavi, classi CSS e commenti possono dire voxcpm: i testi no.
    src = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    values = re.findall(r':"((?:[^"\\]|\\.)*)"', src)
    assert values
    bad = [v[:80] for v in values if re.search(r"VoxCPM|VOXCPM", v)]
    assert not bad
    for lang in ("it", "en", "fr", "es", "de", "zh", "hi"):
        assert f'Object.assign(L.{lang},{{lbl_model_voxcpm:"Audiobook Maker (Fast)"' in src, lang


def test_server_texts_never_name_the_engine():
    for rel in ("i18n/account_pages.json", "i18n/account_emails.json", "content/seo/content.json"):
        data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        bad = [s[:80] for s in _json_strings(data) if ENGINE.search(s)]
        assert not bad, rel
    for rel in ["templates/pages/llms.txt"] + [
            str(p.relative_to(ROOT)) for p in (ROOT / "content/guides").rglob("*.html")]:
        assert not ENGINE.search((ROOT / rel).read_text(encoding="utf-8")), rel
    dl = (ROOT / "templates/pages/dl_page.html").read_text(encoding="utf-8")
    assert not re.search(r"VoxCPM|VOXCPM", dl)
