"""La sezione privacy sulle voci campionate (spec §11): presente in IT ed EN,
numerazione delle sezioni coerente, data aggiornata, riga di riassunto SEO
in tutte le lingue."""
import re

import privacy_content
import seo_content


def _html(lang):
    return privacy_content.render_privacy_page(lang)


def test_sezione_voci_campionate_it_en():
    it = _html("it")
    en = _html("en")
    assert "Voci campionate" in it and "voci campionate" in it.lower()
    assert "Sampled voices" in en and "sampled voice" in en.lower()
    for h in (it, en):
        assert "voice_code" not in h
    for kw in ("15", "email", "codice"):
        assert kw in it
    for kw in ("15", "email", "code"):
        assert kw in en


def test_numerazione_sezioni_coerente():
    for lang in ("it", "en"):
        nums = [int(n) for n in re.findall(r"<h2[^>]*>\s*(\d+)\.", _html(lang))]
        assert nums == list(range(1, len(nums) + 1)), nums
        assert len(nums) == 11


def test_data_aggiornata():
    assert privacy_content._LAST_UPDATED["it"].endswith("2026")
    assert "settembre" in privacy_content._LAST_UPDATED["it"]
    assert "September" in privacy_content._LAST_UPDATED["en"]


def test_riassunto_seo_in_tutte_le_lingue():
    for lang in ("it", "en", "fr", "es", "de", "zh", "hi"):
        blob = seo_content._CONTENT[lang]["privacy"]
        testo = str(blob).lower()
        assert any(
            k in testo for k in ("voce", "voice", "voix", "voz", "stimme", "声音", "आवाज़")
        ), lang
