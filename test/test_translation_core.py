import pytest
import translation_core as tc


def test_usage_tracker_estimates_when_no_usage_obj():
    u = tc.UsageTracker()
    u.track("sys", "user content", "output text")
    r = u.report()
    assert r["calls"] == 1
    assert r["estimated"] is True
    assert r["prompt_tokens"] == int((len("sys") + len("user content")) / tc.EST_CHARS_PER_TOKEN)
    assert r["completion_tokens"] == int(len("output text") / tc.EST_CHARS_PER_TOKEN)


def test_usage_tracker_uses_real_usage_when_complete():
    class U:
        prompt_tokens = 100
        completion_tokens = 50
    u = tc.UsageTracker()
    u.track("s", "u", "o", usage_obj=U())
    r = u.report()
    assert r["estimated"] is False
    assert r["prompt_tokens"] == 100
    assert r["completion_tokens"] == 50


def test_usage_tracker_isolated_instances():
    a, b = tc.UsageTracker(), tc.UsageTracker()
    a.track("s", "u", "o")
    assert b.report()["calls"] == 0


def test_split_chunks_respects_paragraphs():
    text = "para uno.\n\npara due.\n\npara tre."
    chunks = tc.split_text_into_chunks(text, 22)
    assert all(len(c) <= 22 for c in chunks)
    assert "".join(chunks).replace("\n\n", "") == text.replace("\n\n", "")


def test_split_chunks_splits_giant_paragraph_on_sentences():
    text = "Frase uno. " * 50  # un solo paragrafo > max
    chunks = tc.split_text_into_chunks(text.strip(), 100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_strip_fences():
    assert tc._strip_fences("```text\nciao\n```") == "ciao"
    assert tc._strip_fences("ciao") == "ciao"


def test_build_system_prompt_mentions_langs():
    p = tc.build_system_prompt("it", "en", optimize=False)
    assert "'it'" in p and "'en'" in p
    assert "TTS OPTIMIZATION RULES" not in p


def test_build_system_prompt_optimize_appends_tts_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "PROMPT_DIR", tmp_path)
    (tmp_path / "prompt_tts_en.md").write_text("RULE-X", encoding="utf-8")
    p = tc.build_system_prompt("it", "en", optimize=True)
    assert "TTS OPTIMIZATION RULES" in p and "RULE-X" in p
