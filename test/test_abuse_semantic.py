"""Giudice anti-abuso con giudizi tipizzati (System One).

Copre il motore 1 di `abuse_watch.judge`: soglie di decisione in codice al
posto del "be conservative" dentro il prompt, cid presi dagli alias reali
invece che da una lista di testo libero, motivo su enum chiuso al posto della
frase dell'LLM. Nessuna rete: la risposta del servizio e' finta.

Il motore 2 (prompt + JSON a mano) resta coperto da test_abuse_judge.py.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import abuse_watch as aw
import generation_engine as ge
import semantic_judge as sj


# Senza `typesafe-sdk` installato le classi delle domande sono None e il
# motore 1 non parte: resta il ripiego, che ha i suoi test.
requires_sdk = pytest.mark.skipif(
    sj.Noul is None, reason="typesafe-sdk non installato")


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------

def response(evasion=None, scope="cids", pattern="reactive_rotation",
             cids=None, scope_conf=1.0):
    """Risposta System One finta: solo cio' che gli accessor leggono."""
    nouls = {}
    if evasion is not None:
        nouls["evasion"] = SimpleNamespace(noul=evasion)
    for alias_name, p in (cids or {}).items():
        nouls[aw._cid_key(alias_name)] = SimpleNamespace(noul=p)
    choices = {}
    if scope is not None:
        choices["scope"] = SimpleNamespace(choice=scope, confidence=scope_conf)
    if pattern is not None:
        choices["pattern"] = SimpleNamespace(choice=pattern, confidence=1.0)
    return SimpleNamespace(nouls=nouls, choices=choices, scores={})


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ABM_TYPESAFE_API_KEY", "k-test")
    monkeypatch.delenv("ABM_TYPESAFE_ENABLE", raising=False)
    monkeypatch.setattr(aw.time, "sleep", lambda *_a, **_k: None)
    sj.reset()
    yield tmp_path
    sj.reset()


def _rotating_group():
    """Gruppo con tracce di evasione: blocco quota, poi un cid nuovo con una
    email nuova. Senza queste tracce la guardia di `set_verdict` degrada ogni
    `abuse` a `inconclusive`, e i test sulle soglie non direbbero nulla."""
    g = aw.group_key("9.9.9.9", "a")
    for i in range(6):
        aw.record_event(g, "a", "generate", {"chars": 400_000, "lang": "zh",
                                             "voice": "zh-CN-XiaoxiaoNeural",
                                             "filename": f"Book {i}.epub"})
    aw.record_event(g, "a", "email", {"email": "first@example.com"})
    aw.record_event(g, "a", "quota_block", {"chars": 400_000})
    aw.record_event(g, "b", "email", {"email": "second@example.com"})
    for i in range(3):
        aw.record_event(g, "b", "quota_gate", {"chars": 400_000})
        aw.record_event(g, "b", "generate", {"chars": 400_000, "lang": "zh",
                                             "voice": "zh-CN-XiaoxiaoNeural",
                                             "filename": f"More {i}.epub"})
    return g


# --------------------------------------------------------------------------
# costruzione delle domande
# --------------------------------------------------------------------------

@requires_sdk
def test_questions_cover_group_and_every_cid(env):
    _rotating_group()
    qs = aw._semantic_questions({"cid_1": "a", "cid_2": "b"})
    assert {"evasion", "scope", "pattern"} <= set(qs)
    assert aw._cid_key("cid_1") in qs and aw._cid_key("cid_2") in qs
    assert isinstance(qs["evasion"], sj.Noul)
    assert isinstance(qs["scope"], sj.Choice)
    # Lo scope e il motivo sono insiemi chiusi: il modello non puo' rispondere
    # fuori dall'enum, che e' il punto rispetto al JSON a testo libero.
    assert set(qs["pattern"].criteria) == set(aw.PATTERNS)


@requires_sdk
def test_no_questions_without_cids(env):
    """Senza cid restano le tre domande di gruppo, nessuna per alias."""
    qs = aw._semantic_questions({})
    assert set(qs) == {"evasion", "scope", "pattern"}


# --------------------------------------------------------------------------
# soglie: il verdetto a tre stati esce dalla probabilita', non dal prompt
# --------------------------------------------------------------------------

@requires_sdk
def test_high_probability_is_abuse(env):
    g = _rotating_group()
    with patch.object(sj, "ask", return_value=response(0.93, cids={"cid_2": 0.95})):
        v = aw._semantic_verdict(g, cid="b")
    assert v["verdict"] == "abuse"
    assert v["confidence"] == pytest.approx(0.93)
    assert v["cids"] == ["b"]


@requires_sdk
def test_low_probability_is_clean(env):
    g = _rotating_group()
    with patch.object(sj, "ask", return_value=response(0.05)):
        v = aw._semantic_verdict(g)
    assert v["verdict"] == "clean"
    # La confidence di un `clean` e' la certezza del clean, non la probabilita'
    # di evasione.
    assert v["confidence"] == pytest.approx(0.95)


@requires_sdk
def test_middle_band_is_inconclusive_with_zero_confidence(env):
    """La banda di incertezza non deve poter abilitare la kill: confidence 0,
    che nessuna soglia di `kill_gate` puo' superare."""
    g = _rotating_group()
    with patch.object(sj, "ask", return_value=response(0.50, cids={"cid_2": 0.99})):
        v = aw._semantic_verdict(g, cid="b")
    assert v["verdict"] == "inconclusive"
    assert v["confidence"] == 0.0


@requires_sdk
def test_thresholds_come_from_env(env, monkeypatch):
    g = _rotating_group()
    monkeypatch.setenv("ABM_ABUSE_MIN_EVASION", "0.40")
    with patch.object(sj, "ask", return_value=response(0.45, cids={"cid_2": 0.99})):
        assert aw._semantic_verdict(g, cid="b")["verdict"] == "abuse"


# --------------------------------------------------------------------------
# scope e cid
# --------------------------------------------------------------------------

@requires_sdk
def test_only_cids_above_threshold_enter_scope(env):
    g = _rotating_group()
    with patch.object(sj, "ask",
                      return_value=response(0.95, cids={"cid_1": 0.20, "cid_2": 0.90})):
        v = aw._semantic_verdict(g, cid="b")
    assert v["cids"] == ["b"]


@requires_sdk
def test_scope_group_widens_to_known_cids(env):
    g = _rotating_group()
    with patch.object(sj, "ask", return_value=response(0.95, scope="group")):
        v = aw._semantic_verdict(g)
    assert v["scope"] == "group"
    assert set(v["cids"]) == {"a", "b"}


@requires_sdk
def test_abuse_without_named_cid_degrades(env):
    """`abuse` con scope `cids` e nessun cid sopra soglia non e' azionabile:
    stesso degrado del motore 2."""
    g = _rotating_group()
    with patch.object(sj, "ask", return_value=response(0.99, cids={"cid_1": 0.10})):
        v = aw._semantic_verdict(g)
    assert v["verdict"] == "inconclusive"


@requires_sdk
def test_cids_come_from_real_aliases_only(env):
    """Il motore 2 poteva nominare `cid_9` inesistente e il codice a valle lo
    scartava. Qui le domande esistono solo per gli alias reali, quindi una
    risposta su un alias inventato non ha dove attaccarsi."""
    g = _rotating_group()
    with patch.object(sj, "ask",
                      return_value=response(0.95, cids={"cid_9": 0.99, "cid_2": 0.95})):
        v = aw._semantic_verdict(g, cid="b")
    assert v["cids"] == ["b"]


# --------------------------------------------------------------------------
# motivo tipizzato al posto della frase libera
# --------------------------------------------------------------------------

@requires_sdk
def test_reason_is_a_pattern_from_the_enum(env):
    g = _rotating_group()
    with patch.object(sj, "ask",
                      return_value=response(0.95, pattern="disposable_cookies",
                                            cids={"cid_2": 0.95})):
        v = aw._semantic_verdict(g, cid="b")
    assert v["reason"] == "disposable_cookies"


@requires_sdk
def test_unknown_pattern_falls_back_to_none(env):
    g = _rotating_group()
    with patch.object(sj, "ask",
                      return_value=response(0.95, pattern="qualcosa_altro",
                                            cids={"cid_2": 0.95})):
        v = aw._semantic_verdict(g, cid="b")
    assert v["reason"] == "none"


# --------------------------------------------------------------------------
# le guardie deterministiche restano valide per questo motore
# --------------------------------------------------------------------------

@requires_sdk
def test_stable_identity_still_cannot_be_abuse(env):
    """Il gruppo del falso positivo del 14/09/2026: una sola email, cid
    longevi, quota incontrata ma mai evasa. Qualunque probabilita' arrivi, la
    guardia di `set_verdict` lo tiene fuori da `abuse`."""
    g = aw.group_key("7.7.7.7", "solo")
    for i in range(11):
        aw.record_event(g, "solo", "generate", {"chars": 300_000, "lang": "it",
                                                "voice": "it-IT-ElsaNeural",
                                                "filename": f"Libro {i}.epub"})
    aw.record_event(g, "solo", "email", {"email": "lettrice@example.com"})
    for _ in range(8):
        aw.record_event(g, "solo", "quota_gate", {"chars": 300_000})
    with patch.object(sj, "ask", return_value=response(0.99, cids={"cid_1": 0.99})):
        v = aw._semantic_verdict(g, cid="solo")
    assert v["verdict"] == "inconclusive"
    assert "guard" in v["reason"]


# --------------------------------------------------------------------------
# fail-open e ripiego sul motore 2
# --------------------------------------------------------------------------

@requires_sdk
def test_no_verdict_when_service_is_silent(env):
    g = _rotating_group()
    with patch.object(sj, "ask", return_value=None):
        assert aw._semantic_verdict(g) is None


@requires_sdk
def test_no_verdict_on_partial_answer(env):
    """Risposta senza la domanda principale: nessun giudizio, mai un `clean`
    preso da un silenzio."""
    g = _rotating_group()
    with patch.object(sj, "ask", return_value=response(None)):
        assert aw._semantic_verdict(g) is None


def test_unknown_group_has_no_verdict(env):
    assert aw._semantic_verdict("net:unknown") is None


def test_judge_falls_back_to_llm_engine(env, monkeypatch):
    """Motore 1 muto: `judge` prosegue col giudice LLM, non conclude."""
    g = _rotating_group()
    monkeypatch.setattr(aw, "_semantic_verdict", lambda *_a, **_k: None)
    monkeypatch.setattr(ge, "_llm_available", lambda: True)
    monkeypatch.setattr(ge, "LLM_MODEL", "deepseek-chat")
    seen = {}

    def _fake_llm(user, timeout):
        seen["called"] = True
        return ('{"verdict": "abuse", "confidence": 0.9, "scope": "cids", '
                '"cids": ["cid_2"], "reason": "rotazione"}')

    monkeypatch.setattr(aw, "_call_llm", _fake_llm)
    v = aw.judge(g, cid="b")
    assert seen.get("called") is True
    assert v["verdict"] == "abuse"


@requires_sdk
def test_judge_does_not_touch_llm_engine_when_typed_answers(env, monkeypatch):
    """Giudizio ottenuto dal motore 1: il ripiego non viene sfiorato."""
    g = _rotating_group()
    monkeypatch.setattr(aw, "_call_llm",
                        lambda *_a, **_k: pytest.fail("ripiego non atteso"))
    with patch.object(sj, "ask", return_value=response(0.95, cids={"cid_2": 0.95})):
        v = aw.judge(g, cid="b")
    assert v["verdict"] == "abuse"


def test_judge_survives_semantic_engine_error(env, monkeypatch):
    """Un'eccezione nel motore 1 non deve fermare il giudizio: si ripiega."""
    g = _rotating_group()
    monkeypatch.setattr(aw, "_semantic_verdict",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(ge, "_llm_available", lambda: False)
    assert aw.judge(g, cid="b") is None
    d = aw.dossier(g)
    assert d["judgements"][-1]["outcome"] == "unjudged"
