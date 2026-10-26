"""Riuso dei chunk gia' sintetizzati al recovery. Vincoli da difendere:
- si riusa solo con impronta identica (mai fra voci/piani diversi);
- l'ultimo chunk scritto non si riusa mai (poteva essere troncato dal crash);
- Speechify e' escluso (il sample rate reale arriva dalla pre-sintesi)."""
import chunk_reuse


PLAN = [{"text": f"blocco numero {i}", "chars": 16} for i in range(6)]


def _fp(**kw):
    base = dict(voice="gemini:flash31:Enceladus", rate="+0%", engine="gemini",
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


# --- VoxCPM: riuso per capitolo, non per chunk (un job = un capitolo) -----

VOXCPM_PLAN = [
    {"text": "a", "chapter_index": 0},
    {"text": "b", "chapter_index": 0},
    {"text": "c", "chapter_index": 1},
    {"text": "d", "chapter_index": 2},
    {"text": "e", "chapter_index": 2},
    {"text": "f", "chapter_index": 2},
]


def _fp_voxcpm(**kw):
    base = dict(voice="voxcpm:v2:it-IT/Stefano", rate="+0%", engine="voxcpm",
                plan=VOXCPM_PLAN, style_instruction="", accent="",
                strip_round=True, strip_square=True)
    base.update(kw)
    return chunk_reuse.fingerprint(**base)


def test_voxcpm_capitolo_completo_e_riusabile(tmp_path):
    # Capitolo 0 (chunk 0,1) e capitolo 2 (chunk 3,4,5) scritti per intero:
    # testa piena, coda vuota per costruzione (non un crash).
    (tmp_path / "chunk_000000.pcm").write_bytes(b"\x00" * 200)
    (tmp_path / "chunk_000001.pcm").write_bytes(b"")
    (tmp_path / "chunk_000003.pcm").write_bytes(b"\x00" * 300)
    (tmp_path / "chunk_000004.pcm").write_bytes(b"")
    (tmp_path / "chunk_000005.pcm").write_bytes(b"")
    fp = _fp_voxcpm()
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.reusable_indices(
        tmp_path, fp, len(VOXCPM_PLAN), "pcm", plan=VOXCPM_PLAN
    ) == {0, 1, 3, 4, 5}


def test_voxcpm_capitolo_con_una_coda_mancante_si_rifa_intero(tmp_path):
    # Capitolo 2: testa presente ma manca un chunk di coda -> l'intero
    # capitolo torna da sintetizzare, non solo il chunk mancante (il PCM del
    # worker non si ricuce a pezzi).
    (tmp_path / "chunk_000000.pcm").write_bytes(b"\x00" * 200)
    (tmp_path / "chunk_000001.pcm").write_bytes(b"")
    (tmp_path / "chunk_000003.pcm").write_bytes(b"\x00" * 300)
    (tmp_path / "chunk_000004.pcm").write_bytes(b"")
    # chunk_000005.pcm mancante
    fp = _fp_voxcpm()
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.reusable_indices(
        tmp_path, fp, len(VOXCPM_PLAN), "pcm", plan=VOXCPM_PLAN
    ) == {0, 1}


def test_voxcpm_testa_vuota_non_si_riusa(tmp_path):
    # La testa e' li' ma vuota: il capitolo non e' completo, anche se la
    # coda (vuota per costruzione) sarebbe presente.
    (tmp_path / "chunk_000000.pcm").write_bytes(b"")
    (tmp_path / "chunk_000001.pcm").write_bytes(b"")
    fp = _fp_voxcpm()
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.reusable_indices(
        tmp_path, fp, len(VOXCPM_PLAN), "pcm", plan=VOXCPM_PLAN) == set()


def test_voxcpm_senza_plan_non_riusa_niente(tmp_path):
    # Senza il piano non si sa quali chunk appartengono a quale capitolo.
    (tmp_path / "chunk_000000.pcm").write_bytes(b"\x00" * 200)
    (tmp_path / "chunk_000001.pcm").write_bytes(b"")
    fp = _fp_voxcpm()
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.reusable_indices(
        tmp_path, fp, len(VOXCPM_PLAN), "pcm") == set()


def test_failed_chunks_not_reused(tmp_path):
    # Il file di un chunk fallito e' il silenzio di ripiego: non vuoto ma da
    # non riusare (incidente 12/10/2026, capitoli muti dopo i restart).
    _write_chunks(tmp_path, 5, ext="mp3")
    fp = _fp(voice="en-US-AndrewMultilingualNeural", engine="edge")
    chunk_reuse.write_manifest(tmp_path, fp)
    chunk_reuse.mark_failed(tmp_path, 1)
    chunk_reuse.mark_failed(tmp_path, 2)
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "mp3") == {0, 3}
    chunk_reuse.clear_failed(tmp_path, 2)
    assert chunk_reuse.read_failed(tmp_path) == {1}
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "mp3") == {0, 2, 3}


def test_failed_list_survives_same_fingerprint_reset_on_change(tmp_path):
    fp = _fp()
    chunk_reuse.write_manifest(tmp_path, fp)
    chunk_reuse.mark_failed(tmp_path, 3)
    chunk_reuse.write_manifest(tmp_path, fp)  # restart, stesso piano
    assert chunk_reuse.read_failed(tmp_path) == {3}
    chunk_reuse.write_manifest(tmp_path, _fp(rate="+10%"))  # piano diverso
    assert chunk_reuse.read_failed(tmp_path) == set()


def test_read_failed_ignores_garbage(tmp_path):
    (tmp_path / chunk_reuse.FAILED_NAME).write_text('{"x": 1}', encoding="utf-8")
    assert chunk_reuse.read_failed(tmp_path) == set()


# --- Capitoli gia' codificati (ramo multi-file) ---------------------------
# Dopo l'encode del capitolo le sue parti si cancellano: al restart il riuso
# per chunk non le vede piu' e solo il segno del capitolo evita di rifarlo
# (26/10/2026: job zip ripartiti dal capitolo 1 dopo il deploy).

EDGE = dict(voice="en-US-AndrewNeural", engine="edge")


def _chapter_mp3(work, epoch=1, name="002_Cap 2.mp3", data=b"ID3" + b"" * 200):
    out = work / f"output_{epoch}"
    out.mkdir(exist_ok=True)
    p = out / name
    p.write_bytes(data)
    return out, p


def test_chapter_done_is_reused_with_same_fingerprint(tmp_path):
    fp = _fp(**EDGE)
    chunk_reuse.write_manifest(tmp_path, fp)
    out, p = _chapter_mp3(tmp_path)
    chunk_reuse.mark_chapter_done(tmp_path, 2, p)
    chunk_reuse.write_manifest(tmp_path, fp)  # restart, stesso piano
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out) == {2: str(p)}


def test_chapter_done_not_reused_if_file_changed_or_missing(tmp_path):
    fp = _fp(**EDGE)
    chunk_reuse.write_manifest(tmp_path, fp)
    out, p = _chapter_mp3(tmp_path)
    chunk_reuse.mark_chapter_done(tmp_path, 2, p)
    p.write_bytes(b"ID3" + b"" * 200)  # riscritto da un encode poi interrotto
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out) == {}
    p.unlink()
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out) == {}


def test_chapter_done_only_in_the_same_output_dir(tmp_path):
    # Lo ZIP si fa dalla output_N corrente: un MP3 identico in un'altra
    # cartella (altra gen_epoch) non vale.
    fp = _fp(**EDGE)
    chunk_reuse.write_manifest(tmp_path, fp)
    _out1, p = _chapter_mp3(tmp_path, epoch=1)
    chunk_reuse.mark_chapter_done(tmp_path, 2, p)
    out2, _p2 = _chapter_mp3(tmp_path, epoch=2)
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out2) == {}


def test_chapters_done_reset_on_fingerprint_change(tmp_path):
    fp = _fp(**EDGE)
    chunk_reuse.write_manifest(tmp_path, fp)
    out, p = _chapter_mp3(tmp_path)
    chunk_reuse.mark_chapter_done(tmp_path, 2, p)
    other = _fp(rate="+10%", **EDGE)
    chunk_reuse.write_manifest(tmp_path, other)
    assert chunk_reuse.reusable_chapters(tmp_path, other, out) == {}
    chunk_reuse.write_manifest(tmp_path, fp)  # il segno non risorge
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out) == {}


def test_speechify_never_reuses_chapters(tmp_path):
    fp = _fp(engine="speechify", voice="speechify:scott")
    chunk_reuse.write_manifest(tmp_path, fp)
    out, p = _chapter_mp3(tmp_path)
    chunk_reuse.mark_chapter_done(tmp_path, 2, p)
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out) == {}


def test_reusable_chapters_ignores_garbage(tmp_path):
    fp = _fp(**EDGE)
    chunk_reuse.write_manifest(tmp_path, fp)
    out, _p = _chapter_mp3(tmp_path)
    (tmp_path / chunk_reuse.CHAPTERS_NAME).write_text(
        '{"x": 1, "2": {"dir": "output_1", "file": "../002_Cap 2.mp3", "sha256": ""}}',
        encoding="utf-8")
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out) == {}
