"""E1(b): il loop chunk di run_generation senza copie, chunk_reuse.chunk_path."""
import ast
import inspect
import pathlib
from pathlib import Path

import chunk_reuse
import generation_engine as ge


def test_chunk_path_is_the_only_place_that_names_chunk_files(tmp_path):
    assert chunk_reuse.chunk_path(tmp_path, 7, "pcm") == tmp_path / "chunk_000007.pcm"
    assert chunk_reuse.chunk_path(str(tmp_path), 123456, "mp3") == Path(str(tmp_path)) / "chunk_123456.mp3"
    for mod in (ge, chunk_reuse):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert src.count('f"chunk_{') == (1 if mod is chunk_reuse else 0), mod.__name__


def test_run_generation_uses_the_shared_loop_helpers():
    src = inspect.getsource(ge.run_generation)
    assert src.count("Progress: chunk") == 1 and src.count("EARLY-ABORT:") == 1
    assert src.count("_get_audio_duration_ms(mp3_path)") == 1
    tree = ast.parse(src)
    names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    for helper in ("_log_progress", "_count_failure_and_maybe_abort", "_flush_chapter", "_synthesize_chunk", "_carry_tick"):
        assert names.count(helper) == 1, helper
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") in
             ("_log_progress", "_count_failure_and_maybe_abort", "_flush_chapter")]
    by_name = {}
    for c in calls:
        by_name[c.func.id] = by_name.get(c.func.id, 0) + 1
    assert by_name == {"_log_progress": 2, "_count_failure_and_maybe_abort": 2, "_flush_chapter": 2}
