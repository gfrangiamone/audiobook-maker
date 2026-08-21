"""Riuso dei chunk gia' sintetizzati al recovery. Vincoli da difendere:
- si riusa solo con impronta identica (mai fra voci/piani diversi);
- l'ultimo chunk scritto non si riusa mai (poteva essere troncato dal crash);
- Speechify e' escluso (il sample rate reale arriva dalla pre-sintesi)."""
import chunk_reuse


PLAN = [{"text": f"blocco numero {i}", "chars": 16} for i in range(6)]


def _fp(**kw):
    base = dict(voice="gemini:flash25:Enceladus", rate="+0%", engine="gemini",
                plan=PLAN, style_instruction="", accent="it-IT",
                strip_round=True, strip_square=True)
    base.update(kw)
    return chunk_reuse.fingerprint(**base)


def _write_chunks(d, n, ext="pcm", size=100):
    for i in range(n):
        (d / f"chunk_{i:06d}.{ext}").write_bytes(b"\x00" * size)


def test_reuse_requires_manifest(tmp_path):
    _write_chunks(tmp_path, 5)
    assert chunk_reuse.reusable_indices(tmp_path, _fp(), 6, "pcm") == set()


def test_reuse_skips_last_written_chunk(tmp_path):
    _write_chunks(tmp_path, 5)
    fp = _fp()
    chunk_reuse.write_manifest(tmp_path, fp)
    # scritti 0..4 -> il 4 e' l'ultimo, potenzialmente troncato
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "pcm") == {0, 1, 2, 3}


def test_no_reuse_on_voice_change(tmp_path):
    _write_chunks(tmp_path, 5)
    chunk_reuse.write_manifest(tmp_path, _fp())
    other = _fp(voice="it-IT-IsabellaNeural", engine="edge")
    assert chunk_reuse.reusable_indices(tmp_path, other, 6, "pcm") == set()


def test_no_reuse_on_plan_change(tmp_path):
    _write_chunks(tmp_path, 5)
    chunk_reuse.write_manifest(tmp_path, _fp())
    changed = list(PLAN)
    changed[2] = {"text": "testo diverso", "chars": 13}
    assert chunk_reuse.reusable_indices(tmp_path, _fp(plan=changed), 6, "pcm") == set()


def test_no_reuse_on_paren_flag_change(tmp_path):
    _write_chunks(tmp_path, 5)
    chunk_reuse.write_manifest(tmp_path, _fp())
    assert chunk_reuse.reusable_indices(
        tmp_path, _fp(strip_round=False), 6, "pcm") == set()


def test_no_reuse_on_style_or_accent_change(tmp_path):
    _write_chunks(tmp_path, 5)
    chunk_reuse.write_manifest(tmp_path, _fp())
    assert chunk_reuse.reusable_indices(
        tmp_path, _fp(style_instruction="tono cupo"), 6, "pcm") == set()
    assert chunk_reuse.reusable_indices(
        tmp_path, _fp(accent="en-US"), 6, "pcm") == set()


def test_empty_and_odd_sized_pcm_are_not_reused(tmp_path):
    _write_chunks(tmp_path, 5)
    (tmp_path / "chunk_000001.pcm").write_bytes(b"")        # vuoto
    (tmp_path / "chunk_000002.pcm").write_bytes(b"\x00" * 101)  # dispari
    fp = _fp()
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "pcm") == {0, 3}


def test_speechify_never_reuses(tmp_path):
    _write_chunks(tmp_path, 5)
    fp = _fp(engine="speechify", voice="speechify:scott")
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "pcm") == set()


def test_gap_in_sequence_keeps_earlier_chunks(tmp_path):
    """Un buco (sweep parziale) non invalida i chunk che lo precedono: la
    scrittura e' sequenziale, quindi solo l'indice massimo e' sospetto."""
    _write_chunks(tmp_path, 5)
    (tmp_path / "chunk_000003.pcm").unlink()
    fp = _fp()
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "pcm") == {0, 1, 2}


def test_mp3_engines_reuse(tmp_path):
    _write_chunks(tmp_path, 4, ext="mp3", size=101)
    fp = _fp(engine="edge", voice="it-IT-IsabellaNeural")
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "mp3") == {0, 1, 2}
