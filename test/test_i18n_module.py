"""i18n (blocco C3a): lingue, loader, lookup e rilevamento in un posto solo."""
import i18n


def test_norm_lang():
    assert i18n.norm_lang("it-IT") == "it" and i18n.norm_lang(" EN ") == "en"
    assert i18n.norm_lang(None) == "" and i18n.norm_lang("", "it") == "it"
    assert i18n.norm_lang("zh-Hans") == "zh" and i18n.norm_lang("-") == ""


def test_load_is_cached_and_tolerant(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(i18n, "I18N_DIR", tmp_path)
    monkeypatch.setattr(i18n, "_cache", {})
    (tmp_path / "ok.json").write_text('{"en": {"a": "A"}}', encoding="utf-8")
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    assert i18n.load("ok") == {"en": {"a": "A"}}
    assert i18n.load("ok") is i18n.load("ok")
    assert i18n.load("bad") == {} and i18n.load("missing") == {}
    assert "bad.json" in capsys.readouterr().err


def test_pick_merge_and_whole_value():
    table = {"en": {"a": "A-en", "b": "B-en"}, "fr": {"a": "A-fr"}}
    assert i18n.pick(table, "fr-FR") == {"a": "A-fr", "b": "B-en"}
    assert i18n.pick(table, "zz") == {"a": "A-en", "b": "B-en"}
    assert i18n.pick(table, "en", base={"c": "C"}) == {"c": "C", "a": "A-en", "b": "B-en"}
    assert i18n.pick(table, "fr", base={"a": "A-base"})["a"] == "A-fr"
    t = {"en": ("T", "B"), "it": ("Ti", "Bi")}
    assert i18n.pick(t, "it", merge=False) == ("Ti", "Bi")
    assert i18n.pick(t, "de", merge=False) == ("T", "B")
    assert i18n.pick(t, None, merge=False) == ("T", "B")


def test_browser_lang_first_and_ranked():
    assert i18n.browser_lang("it-IT,it;q=0.9,en;q=0.8") == "it"
    assert i18n.browser_lang("") == "" and i18n.browser_lang(None, default="en") == "en"
    assert i18n.browser_lang("xx;q=0.5,fr;q=0.9,en;q=0.7", supported=i18n.LANGS, ranked=True) == "fr"
    assert i18n.browser_lang("xx,yy", supported=i18n.LANGS, ranked=True, default="en") == "en"
    assert i18n.browser_lang("en-US;q=0.8,de;q=0.9", supported={"en", "de"}, ranked=True) == "de"


def test_choose_lang():
    sup = {"en": {}, "it": {}}
    assert i18n.choose_lang(["", "IT", "en"], sup) == "it"
    assert i18n.choose_lang(["fr", None], sup) == "en"
    assert i18n.choose_lang([], sup, default="it") == "it"


def test_app_detectors_delegate(monkeypatch):
    import audiobook_app as app
    with app.app.test_request_context("/", headers={"Accept-Language": "fr-CA,fr;q=0.9,en;q=0.5"}):
        assert app._get_browser_lang() == "fr"
        assert app._detect_lang_from_request() == "fr"
    with app.app.test_request_context("/", headers={"Accept-Language": "xx;q=0.9,de;q=0.8"}):
        assert app._detect_lang_from_request() == "de"
    with app.app.test_request_context("/"):
        assert app._get_browser_lang() == "" and app._detect_lang_from_request() == "en"


def test_i18n_is_a_leaf():
    import ast, pathlib
    src = pathlib.Path(i18n.__file__).read_text(encoding="utf-8")
    mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert mods <= {"json", "re", "sys", "pathlib"}
