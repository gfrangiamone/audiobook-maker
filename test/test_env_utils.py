"""env_utils: semantica unica di lettura delle ABM_* (blocco B1)."""
import env_utils as eu


def test_str_strip_default_and_fallback(monkeypatch):
    monkeypatch.delenv("ABM_T_A", raising=False)
    monkeypatch.setenv("ABM_T_B", "  bb ")
    assert eu.env_str("ABM_T_A", "d") == "d"
    assert eu.env_str("ABM_T_A", "d", fallback="ABM_T_B") == "bb"
    monkeypatch.setenv("ABM_T_A", "   ")
    assert eu.env_str("ABM_T_A", "d") == "d"


def test_float_comma_underscore_invalid_and_clamp(monkeypatch, capsys):
    monkeypatch.setenv("ABM_T_F", "0,5")
    assert eu.env_float("ABM_T_F", 1.0) == 0.5
    monkeypatch.setenv("ABM_T_F", "1_000.25")
    assert eu.env_float("ABM_T_F", 1.0) == 1000.25
    monkeypatch.setenv("ABM_T_F", "abc")
    eu._warned.discard("ABM_T_F")
    assert eu.env_float("ABM_T_F", 2.5) == 2.5
    assert "ABM_T_F" in capsys.readouterr().err
    monkeypatch.setenv("ABM_T_F", "")
    assert eu.env_float("ABM_T_F", 3) == 3.0 and isinstance(eu.env_float("ABM_T_F", 3), float)
    monkeypatch.setenv("ABM_T_F", "-5")
    assert eu.env_float("ABM_T_F", 1.0, floor=0.0) == 0.0
    assert eu.env_float("ABM_T_F", 1.0, ceil=-10.0) == -10.0
    monkeypatch.delenv("ABM_T_F")
    assert eu.env_float("ABM_T_F", -1.0, floor=0.0) == 0.0


def test_int_accepts_float_strings_and_clamps(monkeypatch):
    monkeypatch.setenv("ABM_T_I", "3.0")
    assert eu.env_int("ABM_T_I", 1) == 3
    monkeypatch.setenv("ABM_T_I", "3,9")
    assert eu.env_int("ABM_T_I", 1) == 3
    monkeypatch.setenv("ABM_T_I", "x")
    assert eu.env_int("ABM_T_I", 7) == 7
    monkeypatch.setenv("ABM_T_I", "-3")
    assert eu.env_int("ABM_T_I", 1, floor=0) == 0
    monkeypatch.delenv("ABM_T_I")
    assert eu.env_int("ABM_T_I", "12") == 12


def test_bool_sets_and_default(monkeypatch):
    for v, exp in (("1", True), ("true", True), ("YES", True), (" on ", True),
                   ("0", False), ("false", False), ("No", False), ("off", False)):
        monkeypatch.setenv("ABM_T_B", v)
        assert eu.env_bool("ABM_T_B", not exp) is exp
    monkeypatch.setenv("ABM_T_B", "maybe")
    assert eu.env_bool("ABM_T_B", True) is True
    monkeypatch.setenv("ABM_T_B", "")
    assert eu.env_bool("ABM_T_B", True) is True
    monkeypatch.delenv("ABM_T_B")
    assert eu.env_bool("ABM_T_B") is False


def test_warning_once_per_name(monkeypatch, capsys):
    monkeypatch.setenv("ABM_T_W", "zz")
    eu._warned.discard("ABM_T_W")
    eu.env_int("ABM_T_W", 1); eu.env_int("ABM_T_W", 1)
    assert capsys.readouterr().err.count("ABM_T_W") == 1


def test_env_utils_is_a_leaf():
    import ast, pathlib
    src = pathlib.Path(eu.__file__).read_text(encoding="utf-8")
    mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert mods <= {"os", "sys"}
