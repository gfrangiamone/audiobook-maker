"""Giudizio semantico sulle sezioni del libro (System One).

`is_content_chapter` separa il contenuto dall'apparato con liste di frasi in
sei lingue e sei soglie tarate a mano; il TTS legge in oltre cinquanta lingue.
Qui si copre il secondo parere: quando rimette nel libro una sezione scartata,
quando ne toglie una, e soprattutto quando NON tocca niente — le guardie
contano piu' del giudizio, perche' un libro mutilato non si recupera.

Nessuna rete: la risposta del servizio e' finta.
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import epub_to_tts as E
import section_judge as sjg
import semantic_judge as sj


# Senza `typesafe-sdk` le classi delle domande sono None e il giudizio non
# parte: restano attivi i test del fail-open, che coprono proprio quel caso.
requires_sdk = pytest.mark.skipif(
    sj.Noul is None, reason="typesafe-sdk non installato")

BOOKS = os.path.join(os.path.dirname(__file__), "books")


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------

def response(probs):
    """Risposta System One finta: una Noul per sezione."""
    return SimpleNamespace(
        nouls={sjg._key(sid): SimpleNamespace(noul=p)
               for sid, p in probs.items()},
        choices={}, scores={})


def section(sid, chars=1200, title="Capitolo", text=None, position="middle"):
    return {"id": sid, "title": title, "chars": chars, "position": position,
            "text": text if text is not None else "Prosa. " * (chars // 7)}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_TYPESAFE_API_KEY", "k-test")
    monkeypatch.setenv("ABM_SECTION_JUDGE_MODE", "on")
    monkeypatch.delenv("ABM_TYPESAFE_ENABLE", raising=False)
    for v in ("ABM_SECTION_MIN_RECOVER", "ABM_SECTION_MAX_DROP",
              "ABM_SECTION_MAX_DROP_RATIO", "ABM_SECTION_MIN_CHARS",
              "ABM_SECTION_MAX_QUESTIONS", "ABM_SECTION_MAX_KEPT_CHARS"):
        monkeypatch.delenv(v, raising=False)
    sj.reset()
    yield tmp_path
    sj.reset()


def _book(name):
    path = os.path.join(BOOKS, name)
    if not os.path.exists(path):
        pytest.skip(f"file di test assente: {name}")
    return path


# --------------------------------------------------------------------------
# modo e disponibilita'
# --------------------------------------------------------------------------

def test_default_mode_is_observe(monkeypatch):
    monkeypatch.delenv("ABM_SECTION_JUDGE_MODE", raising=False)
    assert sjg.mode() == "observe"
    assert sjg.applies() is False


def test_unknown_mode_does_not_switch_on(monkeypatch):
    """Un refuso nell'unit systemd non deve accendere gli scarti."""
    monkeypatch.setenv("ABM_SECTION_JUDGE_MODE", "ON!")
    assert sjg.mode() == "observe"
    assert sjg.applies() is False


def test_off_asks_nothing(env, monkeypatch):
    monkeypatch.setenv("ABM_SECTION_JUDGE_MODE", "off")
    with patch.object(sj, "ask",
                      side_effect=AssertionError("non deve chiamare")):
        assert sjg.review({}, [section("drop_0")], []) == {}


def test_no_key_no_judgement(env, monkeypatch):
    monkeypatch.delenv("ABM_TYPESAFE_API_KEY", raising=False)
    sj.reset()
    assert sjg.enabled() is False
    assert sjg.review({}, [section("drop_0")], []) == {}


# --------------------------------------------------------------------------
# selezione dei candidati
# --------------------------------------------------------------------------

def test_tiny_sections_are_not_asked(env):
    """Pagine-immagine e frontespizi vuoti non valgono una domanda."""
    picked = sjg._pick([section("drop_0", chars=40, text="x" * 40)], [], 24)
    assert picked == []


def test_biggest_drops_come_first(env):
    drops = [section(f"drop_{i}", chars=c)
             for i, c in enumerate((300, 9000, 1500))]
    picked = sjg._pick(drops, [], 2)
    assert [s["id"] for s in picked] == ["drop_1", "drop_2"]


def test_only_the_edges_of_the_book_are_reviewed(env):
    """L'apparato sta in testa o in coda: i capitoli centrali non si chiedono."""
    kept = [section(f"kept_{i}") for i in range(20)]
    picked = sjg._pick([], kept, 24)
    ids = [s["id"] for s in picked]
    assert ids == ["kept_0", "kept_1", "kept_2",
                   "kept_15", "kept_16", "kept_17", "kept_18", "kept_19"]


def test_long_kept_chapters_are_not_questioned(env):
    """Misurato sui libri di prova: senza cap si chiedeva se una parte da
    221.000 caratteri fosse contenuto. L'apparato sfuggito alle liste e' corto
    — «Newsletter», «Afterword» — e un capitolo lungo ha comunque il budget a
    difenderlo."""
    kept = [section("kept_0", chars=221_000), section("kept_1", chars=215)]
    picked = sjg._pick([], kept, 24)
    assert [s["id"] for s in picked] == ["kept_1"]


def test_the_kept_size_cap_comes_from_env(env, monkeypatch):
    monkeypatch.setenv("ABM_SECTION_MAX_KEPT_CHARS", "500")
    kept = [section("kept_0", chars=900), section("kept_1", chars=400)]
    assert [s["id"] for s in sjg._pick([], kept, 24)] == ["kept_1"]


def test_the_cap_spares_the_discarded_sections(env):
    """Il tetto vale per i capitoli tenuti: uno scarto grosso resta il caso
    piu' importante da intercettare, qualunque sia la sua taglia."""
    picked = sjg._pick([section("drop_0", chars=90_000)], [], 24)
    assert [s["id"] for s in picked] == ["drop_0"]


def test_drops_have_priority_over_the_question_budget(env):
    """Gli scarti sono gia' fuori dal libro: il budget e' loro per primo."""
    drops = [section(f"drop_{i}") for i in range(3)]
    kept = [section(f"kept_{i}") for i in range(5)]
    picked = sjg._pick(drops, kept, 3)
    assert [s["id"] for s in picked] == ["drop_0", "drop_1", "drop_2"]


@requires_sdk
def test_one_question_per_section_in_one_request(env):
    drops = [section("drop_0"), section("drop_1")]
    seen = {}

    def _ask(state, questions, timeout=None):
        seen["state"] = state
        seen["questions"] = questions
        return response({"drop_0": 0.9, "drop_1": 0.1})

    with patch.object(sj, "ask", side_effect=_ask):
        out = sjg.review({"language": "pl"}, drops, [])
    assert set(seen["questions"]) == {sjg._key("drop_0"), sjg._key("drop_1")}
    assert out == {"drop_0": 0.9, "drop_1": 0.1}
    assert seen["state"]["book"]["language"] == "pl"


@requires_sdk
def test_excerpt_not_whole_text(env):
    """Venti sezioni intere sarebbero un libro spedito a ogni analisi."""
    long_text = "Parola " * 5000
    seen = {}

    def _ask(state, questions, timeout=None):
        seen["state"] = state
        return response({"drop_0": 0.9})

    with patch.object(sj, "ask", side_effect=_ask):
        sjg.review({}, [section("drop_0", chars=35000, text=long_text)], [])
    sent = seen["state"]["sections"][0]
    assert len(sent["excerpt"]) <= sjg._EXCERPT_CHARS + 1
    assert sent["chars"] == 35000


@requires_sdk
def test_line_statistics_travel_with_the_excerpt(env):
    """Righe corte e numeri sono il profilo di un indice in ogni lingua."""
    toc = "\n".join(f"Rozdział {i}    {i * 7}" for i in range(1, 31))
    seen = {}

    def _ask(state, questions, timeout=None):
        seen["state"] = state
        return response({"drop_0": 0.05})

    with patch.object(sj, "ask", side_effect=_ask):
        sjg.review({}, [section("drop_0", chars=len(toc), text=toc)], [])
    sent = seen["state"]["sections"][0]
    assert sent["lines"] == 30
    assert sent["digit_pct"] == 100


# --------------------------------------------------------------------------
# soglie asimmetriche
# --------------------------------------------------------------------------

def test_recover_above_threshold(env):
    drops = [section("drop_0"), section("drop_1")]
    verdicts = {"drop_0": 0.90, "drop_1": 0.30}
    recover, drop = sjg.decide(verdicts, drops, [section("kept_0")])
    assert recover == ["drop_0"]
    assert drop == []


def test_middle_band_touches_nothing(env):
    """Fra scarto e recupero non si muove niente: nel dubbio vince il parser."""
    drops = [section("drop_0")]
    kept = [section("kept_0"), section("kept_1")]
    recover, drop = sjg.decide({"drop_0": 0.40, "kept_0": 0.45}, drops, kept)
    assert recover == [] and drop == []


def test_drop_needs_a_much_stronger_verdict_than_recovery(env):
    """0.30 non basta a togliere, 0.60 basta a rimettere: i due errori non
    pesano uguale."""
    kept = [section("kept_0"), section("kept_1")]
    _rec, drop = sjg.decide({"kept_0": 0.30}, [], kept)
    assert drop == []
    rec, _drop = sjg.decide({"drop_0": 0.60}, [section("drop_0")], kept)
    assert rec == ["drop_0"]


def test_thresholds_come_from_env(env, monkeypatch):
    monkeypatch.setenv("ABM_SECTION_MIN_RECOVER", "0.30")
    recover, _drop = sjg.decide({"drop_0": 0.35}, [section("drop_0")],
                                [section("kept_0")])
    assert recover == ["drop_0"]


# --------------------------------------------------------------------------
# guardie
# --------------------------------------------------------------------------

def test_drop_budget_caps_the_damage(env):
    """Se il giudizio sbaglia in blocco, sbaglia su poco: gli scarti si
    fermano al 25% dei caratteri del libro."""
    kept = [section(f"kept_{i}", chars=1000) for i in range(10)]
    verdicts = {f"kept_{i}": 0.01 for i in range(10)}
    _rec, drop = sjg.decide(verdicts, [], kept)
    assert len(drop) == 2          # 2 sezioni su 10 = 2000 char su 10000


def test_least_likely_sections_are_dropped_first(env):
    kept = [section("kept_0", chars=1000), section("kept_1", chars=1000),
            section("kept_2", chars=1000), section("kept_3", chars=1000)]
    verdicts = {"kept_0": 0.10, "kept_1": 0.02, "kept_2": 0.11}
    _rec, drop = sjg.decide(verdicts, [], kept)
    assert drop == ["kept_1"]


def test_never_leaves_the_book_empty(env, monkeypatch):
    monkeypatch.setenv("ABM_SECTION_MAX_DROP_RATIO", "1.0")
    kept = [section("kept_0", chars=800)]
    _rec, drop = sjg.decide({"kept_0": 0.01}, [], kept)
    assert drop == []


def test_a_kept_section_is_never_recovered_twice(env):
    """Una sezione gia' nel libro non puo' comparire fra i recuperi."""
    kept = [section("kept_0"), section("kept_1")]
    recover, _drop = sjg.decide({"kept_0": 0.99}, [], kept)
    assert recover == []


# --------------------------------------------------------------------------
# modo observe
# --------------------------------------------------------------------------

@requires_sdk
def test_observe_writes_audit_and_changes_nothing(env, monkeypatch):
    monkeypatch.setenv("ABM_SECTION_JUDGE_MODE", "observe")
    drops = [section("drop_0", title="Nachwort")]
    kept = [section("kept_0"), section("kept_1")]
    with patch.object(sj, "ask", return_value=response({"drop_0": 0.95})):
        recover, drop = sjg.review_and_decide({"language": "de"}, drops, kept)
    assert recover == [] and drop == []
    rows = [json.loads(l) for l in _audit_lines(env)]
    assert rows and rows[0]["mode"] == "observe"
    # Il verdetto viene registrato comunque: e' il dato su cui si tarano le
    # soglie prima di passare a `on`.
    assert rows[0]["recover"] == ["drop_0"]
    assert rows[0]["sections"][0]["title"] == "Nachwort"


@requires_sdk
def test_on_applies_and_audits(env):
    drops = [section("drop_0")]
    kept = [section("kept_0"), section("kept_1")]
    with patch.object(sj, "ask", return_value=response({"drop_0": 0.95})):
        recover, drop = sjg.review_and_decide({}, drops, kept)
    assert recover == ["drop_0"] and drop == []
    assert _audit_lines(env)


def _audit_lines(data_dir):
    for name in os.listdir(data_dir):
        if name.startswith("section_judge_audit_"):
            with open(os.path.join(data_dir, name), encoding="utf-8") as f:
                return [l for l in f if l.strip()]
    return []


def test_audit_survives_a_missing_data_dir(env, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", os.path.join(str(env), "non-esiste"))
    sjg.write_audit({}, {"drop_0": 0.5}, [section("drop_0")], [], [], [])


# --------------------------------------------------------------------------
# fail-open
# --------------------------------------------------------------------------

@requires_sdk
def test_silent_service_leaves_the_parser_alone(env):
    with patch.object(sj, "ask", return_value=None):
        assert sjg.review_and_decide({}, [section("drop_0")], []) == ([], [])


@requires_sdk
def test_partial_answer_judges_only_what_came_back(env):
    drops = [section("drop_0"), section("drop_1")]
    with patch.object(sj, "ask", return_value=response({"drop_0": 0.9})):
        out = sjg.review({}, drops, [])
    assert out == {"drop_0": 0.9}


def test_empty_verdicts_decide_nothing(env):
    assert sjg.decide({}, [section("drop_0")], [section("kept_0")]) == ([], [])


# --------------------------------------------------------------------------
# innesto nel parser
# --------------------------------------------------------------------------

def test_parser_untouched_without_judgement(env, monkeypatch):
    """Il libro parsato con il giudizio muto e' identico a quello di prima."""
    monkeypatch.setenv("ABM_SECTION_JUDGE_MODE", "off")
    info = E.parse_epub(_book("La giungla Upton Sinclair.epub"))
    assert info.chapters
    assert all(ch.index == i for i, ch in enumerate(info.chapters, start=1))


@requires_sdk
def test_dropped_section_returns_to_its_place(env):
    """Una sezione recuperata torna dov'era nello spine, non in fondo."""
    info = SimpleNamespace(title="T", author="A", language="it",
                           chapters=[E.Chapter(index=1, title="Uno", text="a" * 900),
                                     E.Chapter(index=2, title="Due", text="b" * 900)])
    dropped = [{"title": "Prologo", "text": "p" * 900, "after": 0,
                "source_file": "p.xhtml", "synthetic_title": False}]
    with patch.object(sj, "ask", return_value=response({"drop_0": 0.95})):
        E._apply_section_judgement(info, dropped)
    assert [c.title for c in info.chapters] == ["Prologo", "Uno", "Due"]
    assert [c.index for c in info.chapters] == [1, 2, 3]


@requires_sdk
def test_several_recoveries_keep_their_order(env):
    info = SimpleNamespace(title="T", author="A", language="it",
                           chapters=[E.Chapter(index=1, title="Uno", text="a" * 900),
                                     E.Chapter(index=2, title="Due", text="b" * 900)])
    dropped = [{"title": "Coda", "text": "c" * 900, "after": 2},
               {"title": "Prologo", "text": "p" * 900, "after": 0}]
    with patch.object(sj, "ask",
                      return_value=response({"drop_0": 0.9, "drop_1": 0.9})):
        E._apply_section_judgement(info, dropped)
    assert [c.title for c in info.chapters] == ["Prologo", "Uno", "Due", "Coda"]


@requires_sdk
def test_apparatus_chapter_is_removed_and_renumbered(env):
    info = SimpleNamespace(
        title="T", author="A", language="tr",
        chapters=[E.Chapter(index=1, title="Bir", text="a" * 4000),
                  E.Chapter(index=2, title="İki", text="b" * 4000),
                  E.Chapter(index=3, title="Kaynakça", text="c" * 900)])
    with patch.object(sj, "ask", return_value=response({"kept_2": 0.02})):
        E._apply_section_judgement(info, [])
    assert [c.title for c in info.chapters] == ["Bir", "İki"]
    assert [c.index for c in info.chapters] == [1, 2]


def test_parser_survives_a_broken_judgement(env, monkeypatch):
    """Un'eccezione qualunque non deve costare il libro all'utente."""
    info = SimpleNamespace(title="T", author="A", language="it",
                           chapters=[E.Chapter(index=1, title="Uno", text="a" * 900)])
    monkeypatch.setattr(sjg, "review_and_decide",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    E._apply_section_judgement(info, [])
    assert [c.title for c in info.chapters] == ["Uno"]
