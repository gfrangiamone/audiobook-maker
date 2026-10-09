"""E1(d): un solo punto che sceglie il writer di audit per motore premium."""
import inspect

import generation_engine as ge


def test_premium_engine_and_table():
    assert ge._premium_engine(True, False, False) == "gemini"
    assert ge._premium_engine(False, True, False) == "speechify"
    assert ge._premium_engine(False, False, True) == "voxcpm"
    assert ge._premium_engine(False, False, False) == ""
    assert set(ge._PREMIUM_AUDIT) == {"gemini", "speechify", "voxcpm"}
    for name in ge._PREMIUM_AUDIT.values():
        assert callable(getattr(ge, name))


def test_write_premium_audit_resolves_patched_writer_and_swallows(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ge, "_write_voxcpm_audit", lambda *a: calls.append(a))
    monkeypatch.setattr(ge, "_audit_language", lambda job, info: "it")
    ge._write_premium_audit("J", {"j": 1}, "voxcpm:v2:it-IT/Stefano", None, "completed", "voxcpm")
    assert calls == [("J", {"j": 1}, "voxcpm:v2:it-IT/Stefano", "it", "completed")]
    ge._write_premium_audit("J", {}, "v", None, "completed", "")            # Edge: no-op
    assert len(calls) == 1

    def boom(*a):
        raise RuntimeError("disk")

    monkeypatch.setattr(ge, "_write_speechify_audit", boom)
    ge._write_premium_audit("J", {}, "v", None, "failed_refunded", "speechify")
    assert "speechify audit failed (non-fatal): disk" in capsys.readouterr().out


def test_exit_paths_use_the_dispatcher():
    src = inspect.getsource(ge.run_generation)
    for writer in ("_write_gemini_audit(", "_write_speechify_audit(", "_write_voxcpm_audit("):
        assert writer not in src, writer
    assert src.count("_write_premium_audit(") + src.count("_premium_fail(") >= 6
    assert "_write_premium_audit(" in inspect.getsource(ge._premium_fail)
    for fn in (ge._premium_job_failed, ge._gemini_quality_refund):
        s = inspect.getsource(fn)
        assert "_premium_fail(" in s and "_write_voxcpm_audit(" not in s and "_write_gemini_audit(" not in s
