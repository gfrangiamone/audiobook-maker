"""Riuso dei chunk gia' sintetizzati al recovery. Vincoli da difendere:
- si riusa solo con impronta identica (mai fra voci/piani diversi);
- l'ultimo chunk scritto non si riusa mai (poteva essere troncato dal crash);
- Speechify e' escluso (il sample rate reale arriva dalla pre-sintesi);
- a testo cambiato e voce uguale si riusa per contenuto (`align_to_plan`), e
  nessun file del piano vecchio resta a un indice del piano nuovo."""
import os

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


def test_chapter_done_in_another_output_dir_is_copied(tmp_path):
    # Lo ZIP si fa dalla output_N corrente: un capitolo codificato in quella
    # di un'altra gen_epoch (rilancio, poi recovery a epoch 1: C-IucY4 il
    # 07/11/2026) si copia li', e l'originale resta per i token della sua epoch.
    fp = _fp(**EDGE)
    chunk_reuse.write_manifest(tmp_path, fp)
    _out2, p = _chapter_mp3(tmp_path, epoch=2, data=b"ID3" + b"\x01" * 200)
    chunk_reuse.mark_chapter_done(tmp_path, 2, p)
    out1 = tmp_path / "output_1"
    out1.mkdir()
    copia = out1 / p.name
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out1) == {2: str(copia)}
    assert copia.read_bytes() == p.read_bytes() and p.exists()
    # Il segno passa alla cartella corrente: il restart dopo la trova li'.
    p.unlink()
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out1) == {2: str(copia)}


def test_chapter_in_another_output_dir_changed_is_not_copied(tmp_path):
    fp = _fp(**EDGE)
    chunk_reuse.write_manifest(tmp_path, fp)
    _out2, p = _chapter_mp3(tmp_path, epoch=2, data=b"ID3" + b"\x01" * 200)
    chunk_reuse.mark_chapter_done(tmp_path, 2, p)
    p.write_bytes(b"ID3")  # riscritto dopo il segno
    out1 = tmp_path / "output_1"
    out1.mkdir()
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out1) == {}
    assert not list(out1.iterdir())


def test_chapter_record_outside_output_dirs_is_ignored(tmp_path):
    fp = _fp(**EDGE)
    chunk_reuse.write_manifest(tmp_path, fp)
    (tmp_path / "voices").mkdir()
    p = tmp_path / "voices" / "002_Cap 2.mp3"
    p.write_bytes(b"ID3" + b"\x01" * 200)
    chunk_reuse.mark_chapter_done(tmp_path, 2, p)
    out1 = tmp_path / "output_1"
    out1.mkdir()
    assert chunk_reuse.reusable_chapters(tmp_path, fp, out1) == {}
    assert not list(out1.iterdir())


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


# --- Riuso per contenuto al cambio del testo (align_to_plan) -----------------
# 06/11/2026: il deploy delle 15:12 ha cambiato il testo preparato di pochi
# caratteri e 18 job sono ripartiti da zero (uno a 551 chunk su 1262).

def _plan(*texts):
    return [{"text": t, "chars": len(t)} for t in texts]


def _fp_edge(plan, **kw):
    return _fp(plan=plan, engine="edge", voice="en-US-AndrewNeural", **kw)


def _write_texts(d, plan, ext="mp3"):
    """File di chunk il cui contenuto e' il testo: si vede dove e' finito."""
    for i, b in enumerate(plan):
        (d / f"chunk_{i:06d}.{ext}").write_bytes(b["text"].encode())


def _contents(d, ext="mp3"):
    return {int(p.name[6:12]): p.read_bytes().decode()
            for p in d.glob(f"chunk_*.{ext}")}


def test_manifest_without_chunk_sha_still_matches(tmp_path):
    # I manifest scritti prima del riuso per contenuto non hanno chunk_sha:
    # stesso piano = stesso run, riuso e falliti intatti.
    _write_chunks(tmp_path, 5)
    fp = _fp()
    old = {k: v for k, v in fp.items() if k != "chunk_sha"}
    chunk_reuse.write_manifest(tmp_path, old)
    chunk_reuse.mark_failed(tmp_path, 1)
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "pcm") == {0, 2, 3}
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.read_failed(tmp_path) == {1}
    assert chunk_reuse.read_manifest(tmp_path) == fp


def test_realign_moves_chunks_by_text(tmp_path):
    old = _plan("a0", "a1", "a2", "b0", "b1")
    _write_texts(tmp_path, old)
    chunk_reuse.write_manifest(tmp_path, _fp_edge(old))
    chunk_reuse.mark_failed(tmp_path, 2)  # silenzio di ripiego: non e' audio
    # a1 riscritto, un chunk nuovo inserito prima di b0 (indici spostati).
    new = _plan("a0", "A1", "a2", "nuovo", "b0", "b1")
    fp = _fp_edge(new)
    moved, dropped = chunk_reuse.align_to_plan(tmp_path, fp, "mp3")
    # Sorgenti: a0 e b0. a2 e' fallito, b1 e' l'ultimo scritto, a1 e' sparito.
    assert (moved, dropped) == (2, 3)
    assert _contents(tmp_path) == {0: "a0", 4: "b0"}
    assert chunk_reuse.read_manifest(tmp_path) == fp
    assert chunk_reuse.read_failed(tmp_path) == {1, 2, 3, 5}
    # L'indice massimo presente resta escluso come sempre.
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "mp3") == {0}
    chunk_reuse.write_manifest(tmp_path, fp)  # il motore lo riscrive: falliti intatti
    assert chunk_reuse.read_failed(tmp_path) == {1, 2, 3, 5}


def test_realign_copies_repeated_text(tmp_path):
    old = _plan("* * *", "a", "b", "c")
    _write_texts(tmp_path, old)
    chunk_reuse.write_manifest(tmp_path, _fp_edge(old))
    (tmp_path / "chunk_000000.mp3.realign").write_bytes(b"residuo")
    new = _plan("* * *", "a", "* * *", "b", "* * *", "c")
    # "c" era l'ultimo scritto: non e' una sorgente e si cancella, come il
    # temporaneo rimasto da chissa' dove.
    assert chunk_reuse.align_to_plan(tmp_path, _fp_edge(new), "mp3") == (5, 2)
    assert _contents(tmp_path) == {0: "* * *", 1: "a", 2: "* * *", 3: "b", 4: "* * *"}
    assert not list(tmp_path.glob("*.realign"))


def test_same_plan_leaves_files_alone(tmp_path):
    plan = _plan("a", "b", "c")
    _write_texts(tmp_path, plan)
    fp = _fp_edge(plan)
    chunk_reuse.write_manifest(tmp_path, fp)
    assert chunk_reuse.align_to_plan(tmp_path, fp, "mp3") == (0, 0)
    assert _contents(tmp_path) == {0: "a", 1: "b", 2: "c"}


def test_voice_change_wipes_old_chunks(tmp_path):
    # Senza cancellazione, col manifest nuovo un secondo restart prenderebbe
    # i file della voce vecchia per audio della nuova.
    plan = _plan("a", "b", "c")
    _write_texts(tmp_path, plan)
    chunk_reuse.write_manifest(tmp_path, _fp_edge(plan))
    other = _fp(plan=plan, engine="edge", voice="en-US-AvaNeural")
    assert chunk_reuse.align_to_plan(tmp_path, other, "mp3") == (0, 3)
    assert _contents(tmp_path) == {}


def test_missing_manifest_wipes_chunks(tmp_path):
    plan = _plan("a", "b")
    _write_texts(tmp_path, plan)
    assert chunk_reuse.align_to_plan(tmp_path, _fp_edge(plan), "mp3") == (0, 2)
    assert _contents(tmp_path) == {}


def test_voxcpm_text_change_wipes_instead_of_realigning(tmp_path):
    (tmp_path / "chunk_000000.pcm").write_bytes(b"\x00" * 200)
    (tmp_path / "chunk_000001.pcm").write_bytes(b"")
    chunk_reuse.write_manifest(tmp_path, _fp_voxcpm())
    changed = [dict(b) for b in VOXCPM_PLAN]
    changed[5]["text"] = "z"
    assert chunk_reuse.align_to_plan(tmp_path, _fp_voxcpm(plan=changed), "pcm") == (0, 2)


def test_interrupted_realign_wipes_everything(tmp_path):
    plan = _plan("a", "b", "c")
    _write_texts(tmp_path, plan)
    (tmp_path / "chunk_000007.mp3.realign").write_bytes(b"x")
    chunk_reuse.write_json_safe(chunk_reuse.manifest_path(tmp_path),
                                {chunk_reuse._REALIGN_MARK: True})
    fp = _fp_edge(plan)
    assert chunk_reuse.align_to_plan(tmp_path, fp, "mp3") == (0, 4)
    assert not list(tmp_path.glob("chunk_*"))
    assert chunk_reuse.reusable_indices(tmp_path, fp, 3, "mp3") == set()


def test_realign_error_midway_wipes_everything(tmp_path, monkeypatch):
    old = _plan("a", "b", "c", "d")
    _write_texts(tmp_path, old)
    chunk_reuse.write_manifest(tmp_path, _fp_edge(old))
    real_rename = os.rename
    n = []

    def rename_then_fail(src, dst):
        n.append(src)
        if len(n) == 3:
            raise OSError("disco pieno")
        return real_rename(src, dst)
    monkeypatch.setattr(chunk_reuse.os, "rename", rename_then_fail)
    fp = _fp_edge(_plan("x", "a", "b", "c"))
    assert chunk_reuse.align_to_plan(tmp_path, fp, "mp3")[0] == 0
    assert not list(tmp_path.glob("chunk_*"))
    assert chunk_reuse.reusable_indices(tmp_path, fp, 4, "mp3") == set()


def _age(path, seconds):
    t = os.path.getmtime(path) - seconds
    os.utime(path, (t, t))


def test_legacy_manifest_drops_stale_chunks_of_previous_plan(tmp_path):
    # Stato dei job colpiti il 06/11 alle 15:12: piano cambiato col codice di
    # allora, manifest nuovo senza chunk_sha, run ripartito da 0 e chunk del
    # piano vecchio ancora agli indici successivi.
    plan = _plan("a", "b", "c", "d", "e", "f")
    fp = _fp_edge(plan)
    _write_texts(tmp_path, _plan("A", "B", "vecchio", "vecchio", "vecchio", "vecchio"))
    for p in tmp_path.glob("chunk_*"):
        _age(p, 600)
    chunk_reuse.write_manifest(tmp_path, {k: v for k, v in fp.items() if k != "chunk_sha"})
    _age(chunk_reuse.manifest_path(tmp_path), 300)
    _write_texts(tmp_path, plan[:2])  # il run corrente ha riscritto 0 e 1
    assert chunk_reuse.align_to_plan(tmp_path, fp, "mp3") == (0, 4)
    assert _contents(tmp_path) == {0: "a", 1: "b"}
    assert chunk_reuse.reusable_indices(tmp_path, fp, 6, "mp3") == {0}


def test_legacy_manifest_keeps_chunks_reused_before_the_current_run(tmp_path):
    # Restart a piano invariato: i chunk riusati sono piu' vecchi del manifest
    # ma stanno tutti prima del primo scritto dal run corrente.
    plan = _plan("a", "b", "c", "d", "e")
    fp = _fp_edge(plan)
    _write_texts(tmp_path, plan[:3])
    for p in tmp_path.glob("chunk_*"):
        _age(p, 600)
    chunk_reuse.write_manifest(tmp_path, {k: v for k, v in fp.items() if k != "chunk_sha"})
    _age(chunk_reuse.manifest_path(tmp_path), 300)
    (tmp_path / "chunk_000003.mp3").write_bytes(b"d")
    (tmp_path / "chunk_000004.mp3").write_bytes(b"e")
    assert chunk_reuse.align_to_plan(tmp_path, fp, "mp3") == (0, 0)
    assert chunk_reuse.reusable_indices(tmp_path, fp, 5, "mp3") == {0, 1, 2, 3}


def test_chunk_sha_matches_plan_text():
    fp = _fp_edge(_plan("uno", "due"))
    assert fp["chunk_sha"] == [chunk_reuse.chunk_sha("uno"), chunk_reuse.chunk_sha("due")]
    assert len(fp["chunk_sha"][0]) == 16 and fp["chunk_sha"][0] != fp["chunk_sha"][1]
