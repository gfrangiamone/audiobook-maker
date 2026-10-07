"""Blocco C2: i contenuti editoriali vivono in content/, i moduli tengono solo
il codice. Il gate di estrazione (2026-10-07) ha confrontato byte per byte
76 pagine (home, guide in 7 lingue, content SEO, FAQ, privacy, support,
sitemap) prima e dopo: identiche."""
from pathlib import Path

import content_store as cs


def test_content_tree_is_complete():
    assert cs.CONTENT_DIR.is_dir()
    meta = cs.content_json("guides", "meta.json")
    assert set(meta) == {"free-ebooks", "epub-to-audiobook", "m4b-format",
                         "text-to-speech-audiobook", "gemini-tts", "podcast"}
    for gid in meta:
        for lang in ("en", "it", "fr", "es", "de", "zh"):
            assert cs.content_exists("guides", gid, f"{lang}.html"), (gid, lang)
            assert len(cs.content_text("guides", gid, f"{lang}.html")) > 500, (gid, lang)
    assert set(cs.content_json("seo", "content.json")) == {"it", "en", "fr", "es", "de", "zh", "hi"}
    tables = cs.content_json("seo", "tables.json")
    assert set(tables) == {"voice_table", "table_headers", "howto_steps", "ld_features"}
    for lang in ("it", "en"):
        assert cs.content_exists("privacy", f"{lang}.json") and cs.content_exists("privacy", f"{lang}.html")
    assert set(cs.content_json("support", "texts.json")) == {"it", "en"}
    vc = "voice-cloning-audiobook"
    for f in ("meta.json", "sample_langs.json", "texts.json"):
        assert set(cs.content_json("guides", vc, f)) == {"en", "it", "fr", "es", "de", "zh", "hi"}


def test_modules_load_the_files_and_keep_their_api():
    import guide_content as gc, seo_content as sc, privacy_content as pc, support_content as spc, guide_voice_clone as gvc
    assert gc._GUIDE_META["gemini-tts"]["it"]["title"]
    assert "voice-cloning-audiobook" in gc._GUIDE_META and "voice-cloning-audiobook" in gc._GUIDE_BODY_EN
    assert gc._GUIDE_BODY_EN["podcast"].startswith("<") or "<" in gc._GUIDE_BODY_EN["podcast"][:200]
    assert gc._GUIDE_BODY_HI == {"voice-cloning-audiobook": gvc.body("hi")}
    assert sc._CONTENT["en"]["heading"] and len(sc._VOICE_TABLE) == 8
    for _lc, labels, count in sc._VOICE_TABLE:      # la forma (codice, etichette, conteggio) resta
        assert isinstance(labels, dict) and isinstance(count, (int, str))
    assert pc._TXT["it"]["body"].lstrip().startswith("<") and pc._TXT["en"]["title"]
    assert spc._TXT["en"]["faq"]
    assert gvc.META["it"]["h1"] and gvc._T["en"]["intro"]
    assert "<li>" in gvc.body("fr")


def test_json_is_cached_but_returned_as_a_copy():
    a = cs.content_json("seo", "tables.json")
    b = cs.content_json("seo", "tables.json")
    assert a == b and a is not b
    a["voice_table"].append("x")
    assert cs.content_json("seo", "tables.json") == b


def test_content_modules_hold_no_big_literals():
    root = Path(cs.__file__).parent
    for name, cap in (("guide_content.py", 20_000), ("seo_content.py", 30_000), ("privacy_content.py", 6_000),
                      ("support_content.py", 5_000), ("guide_voice_clone.py", 6_000)):
        assert (root / name).stat().st_size < cap, name


def test_content_store_is_a_leaf():
    import ast
    src = Path(cs.__file__).read_text(encoding="utf-8")
    mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert mods <= {"copy", "json", "pathlib"}
