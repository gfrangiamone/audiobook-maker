"""M6 (analisi post-piano 2026-10): i test non si rompono a vicenda.

Tre regole sui file di test (AST, quindi i commenti non contano):
- nessun `from audiobook_app import ...`: un from-import a collection time
  resta legato agli oggetti pre-reload (404 "job not found" solo nella suite
  completa);
- nessun `importlib.reload(audiobook_app)` / `reload(generation_engine)` fuori
  dalla fixture `fresh_app` di conftest, che ricarica in ordine fisso e
  ripristina i default a fine test;
- nessuna riassegnazione `<modulo>.jobs = {...}`: scollega l'engine dal dict
  della app per il resto della sessione (era test_combined_estimate_threshold).

Piu' il comportamento di `fresh_app`: env applicate al reload, default
ripristinati nel test successivo.
"""
import ast
import os
from pathlib import Path

import audiobook_app
import email_service
import generation_engine

TEST_DIR = Path(__file__).resolve().parent
BANNED_RELOAD = {"audiobook_app", "generation_engine"}


def _test_files():
    return sorted(p for p in TEST_DIR.glob("test_*.py"))


def _violations(path):
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "audiobook_app":
            out.append(f"{path.name}:{n.lineno} from audiobook_app import")
        elif isinstance(n, ast.Call):
            f = n.func
            is_reload = (isinstance(f, ast.Attribute) and f.attr == "reload") or \
                        (isinstance(f, ast.Name) and f.id == "reload")
            if is_reload and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id in BANNED_RELOAD:
                out.append(f"{path.name}:{n.lineno} reload({n.args[0].id})")
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute) and t.attr == "jobs":
                    out.append(f"{path.name}:{n.lineno} {ast.unparse(t)} = ...")
    return out


def test_nessun_from_import_reload_o_riassegnazione_di_jobs_nei_test():
    bad = [v for p in _test_files() for v in _violations(p)]
    assert not bad, "usare fresh_app / monkeypatch.setitem(audiobook_app.jobs, ...):\n  " + "\n  ".join(bad)


def test_conftest_e_l_unico_posto_che_ricarica_l_app():
    src = (TEST_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "def fresh_app(" in src and "def _reload_chain(" in src
    assert src.count("importlib.reload(audiobook_app)") == 1
    assert src.count("importlib.reload(generation_engine)") == 1


_BEFORE = {}


def test_fresh_app_applica_le_env_e_rilega_l_engine(fresh_app):
    _BEFORE["cap"] = audiobook_app.MAX_VOXCPM_TEXT_CHARS
    _BEFORE["jobs"] = audiobook_app.jobs
    app = fresh_app(env={"ABM_MAX_VOXCPM_TEXT_CHARS": "4321"})
    assert app is audiobook_app                      # stesso oggetto modulo
    assert audiobook_app.MAX_VOXCPM_TEXT_CHARS == 4321
    # Dopo il reload l'engine vede il dict jobs della app ricaricata.
    assert generation_engine._jobs is audiobook_app.jobs


def test_il_test_successivo_trova_i_default():
    assert audiobook_app.MAX_VOXCPM_TEXT_CHARS == _BEFORE["cap"]
    assert generation_engine._jobs is audiobook_app.jobs


def test_env_none_toglie_la_variabile(fresh_app, monkeypatch):
    monkeypatch.setenv("ABM_MAX_VOXCPM_TEXT_CHARS", "999")
    fresh_app(env={"ABM_MAX_VOXCPM_TEXT_CHARS": None})
    assert audiobook_app.MAX_VOXCPM_TEXT_CHARS == _BEFORE["cap"]


# Le ABM_SMTP_* del profilo di sviluppo sono quelle vere: i test non devono
# poter spedire, nemmeno dopo un reload che rilegge l'ambiente.
_SMTP_ENV = ("ABM_SMTP_HOST", "ABM_SMTP_USER", "ABM_SMTP_PASS", "ABM_SMTP_FROM",
             "ABM_SMTP_PORT", "ABM_ADMIN_EMAIL")


def test_nessun_smtp_vero_nei_test():
    assert [k for k in _SMTP_ENV if k in os.environ] == []
    assert not email_service._smtp_available()


def test_reload_di_email_service_resta_senza_smtp(fresh_app):
    fresh_app(leaves=("email_service",))
    assert not email_service._smtp_available()


def test_dopo_il_ripristino_di_fresh_app_resta_senza_smtp():
    assert not email_service._smtp_available()
