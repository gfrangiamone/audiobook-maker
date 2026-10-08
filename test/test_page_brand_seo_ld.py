"""C3b: hreflang/og:locale da page_brand, JSON-LD da seo_ld (un posto solo)."""
import ast
import json
import pathlib

import i18n
import page_brand as pb
import seo_ld


def test_maps_follow_site_langs():
    assert pb.SITE_LANGS == i18n.LANGS
    assert tuple(pb.HREFLANG) == pb.SITE_LANGS and tuple(pb.OG_LOCALE) == pb.SITE_LANGS
    assert pb.html_lang("zh") == "zh-Hans" and pb.html_lang("it") == "it" and pb.html_lang("xx") == "en"
    assert seo_ld.IN_LANGUAGES == ["it", "en", "fr", "es", "de", "zh-Hans", "hi"]


def test_hreflang_links_html_and_sitemap():
    html = pb.hreflang_links(lambda lc: f"/faq/{lc}/", "/faq/en/", sep="|")
    parts = html.split("|")
    assert len(parts) == len(pb.SITE_LANGS) + 1
    assert parts[0] == '<link rel="alternate" hreflang="it" href="/faq/it/">'
    assert parts[5] == '<link rel="alternate" hreflang="zh-Hans" href="/faq/zh/">'
    assert parts[-1] == '<link rel="alternate" hreflang="x-default" href="/faq/en/">'
    xml = pb.hreflang_links(lambda lc: f"https://x/{lc}/", "https://x/", xhtml=True)
    lines = xml.split("\n")
    assert lines[0] == '      <xhtml:link rel="alternate" hreflang="it" href="https://x/it/"/>'
    assert lines[-1].endswith('hreflang="x-default" href="https://x/"/>')


def test_og_locale_tags():
    cur, alt = pb.og_locale_tags("fr", sep="|")
    assert cur == "fr_FR"
    assert "fr_FR" not in alt and alt.count("og:locale:alternate") == len(pb.SITE_LANGS) - 1
    assert pb.og_locale_tags("xx")[0] == "en_US"


def test_ld_json_escapes_script_close():
    s = seo_ld.ld_json({"t": "a</script><b>"})
    assert "</" not in s and json.loads(s)["t"] == "a</script><b>"
    assert "ü" in seo_ld.ld_json({"t": "ü"})


def test_faq_howto_breadcrumb_key_order():
    faq = seo_ld.faq_ld([("q", "a")], in_lang="it", date_modified="2026-01-01")
    assert list(faq) == ["@context", "@type", "inLanguage", "mainEntity", "dateModified"]
    assert faq["mainEntity"][0] == {"@type": "Question", "name": "q",
                                    "acceptedAnswer": {"@type": "Answer", "text": "a"}}
    assert list(seo_ld.faq_ld([])) == ["@context", "@type", "mainEntity"]
    how = seo_ld.howto_ld("n", "d", [("s1", "t1"), {"@type": "HowToStep", "position": 2}],
                          in_lang="en", before_steps={"totalTime": "PT1M"})
    assert list(how) == ["@context", "@type", "name", "description", "inLanguage", "totalTime", "step"]
    assert how["step"] == [{"@type": "HowToStep", "name": "s1", "text": "t1"},
                           {"@type": "HowToStep", "position": 2}]
    bc = seo_ld.breadcrumb_ld([("A", "/"), ("B", "/b/")])
    assert bc["itemListElement"][1] == {"@type": "ListItem", "position": 2, "name": "B", "item": "/b/"}
    assert seo_ld.publisher("https://x", logo_size=192)["logo"]["width"] == 192
    assert "logo" not in seo_ld.publisher("https://x")
    assert seo_ld.author_block() == seo_ld.AUTHOR and seo_ld.author_block() is not seo_ld.AUTHOR


def test_leaves_import_only_stdlib_and_leaves():
    for mod, allowed in ((pb, {"i18n"}), (seo_ld, {"json", "page_brand"})):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
                for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
        assert mods <= allowed, (mod.__name__, mods)


def test_pages_use_shared_hreflang_and_ld():
    import audiobook_app as app
    app.app.config["TESTING"] = True
    c = app.app.test_client()
    faq = c.get("/faq/zh/").data.decode("utf-8")
    assert '<html lang="zh-Hans"' in faq
    assert faq.count('rel="alternate" hreflang=') == len(pb.SITE_LANGS) + 1
    assert '"@type": "FAQPage"' in faq
    sitemap = c.get("/sitemap.xml").data.decode("utf-8")
    n_urls = sitemap.count("<url>")
    assert sitemap.count("<xhtml:link") == n_urls * (len(pb.SITE_LANGS) + 1)
    home = c.get("/en/").data.decode("utf-8")
    assert '"inLanguage": ["it", "en", "fr", "es", "de", "zh-Hans", "hi"]' in home
    guide = c.get("/guide/podcast/zh/").data.decode("utf-8")
    assert '"inLanguage": "zh-Hans"' in guide and '<meta property="og:locale" content="zh_CN">' in guide
    assert guide.count('og:locale:alternate') == len(pb.SITE_LANGS) - 1
    import seo_content
    assert seo_content.lang_content("xx") is seo_content.lang_content("en")
