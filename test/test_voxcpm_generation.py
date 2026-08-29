"""VoxCPM dentro la catena di generazione: scelta motore, raggruppamento in
capitoli, pre-sintesi.

`synthesize_chapter` e' sostituita da un doppio: qui si prova come il libro
viene diviso in job e dove finisce l'audio, non come si parla con RunPod.
"""
import os

import pytest

import generation_engine
import voxcpm_tts

VOCE = "voxcpm:v2:it-IT/Stefano"


def blocco(testo, capitolo):
    return {"text": testo, "chapter_index": capitolo}


PIANO = [blocco("a", 0), blocco("b", 0), blocco("c", 1),
         blocco("d", 2), blocco("e", 2), blocco("f", 2)]


def test_il_motore_si_riconosce_dal_prefisso():
    assert generation_engine._engine_for_voice(VOCE) == "voxcpm"
    assert generation_engine._engine_for_voice("voxcpm:mine:abc") == "voxcpm"
    # Gli altri tre non si spostano.
    assert generation_engine._engine_for_voice("gemini:flash25:Zephyr") == "gemini"
    assert generation_engine._engine_for_voice("speechify:simba-3.2:harper_32") == "speechify"
    assert generation_engine._engine_for_voice("it-IT-IsabellaNeural") == "edge"
    assert generation_engine._engine_for_voice("") == "edge"


def test_nome_amichevole_senza_locale_ne_prefisso():
    assert generation_engine._friendly_voice_name(VOCE) == "Stefano"
    assert generation_engine._friendly_voice_name("voxcpm:v2:en-GB/Rufus") == "Rufus"


def test_i_chunk_si_raggruppano_per_capitolo():
    gruppi = generation_engine._voxcpm_chapter_groups(PIANO, set())
    assert gruppi == [(0, [0, 1]), (1, [2]), (2, [3, 4, 5])]


def test_un_capitolo_tutto_riusabile_si_salta():
    gruppi = generation_engine._voxcpm_chapter_groups(PIANO, {0, 1})
    assert gruppi == [(1, [2]), (2, [3, 4, 5])]


def test_un_capitolo_riusabile_a_meta_si_rifa_intero():
    # Rigenerare un solo chunk costerebbe comunque il job intero, e il PCM
    # parziale non si potrebbe ricucire: non c'e' mezza misura.
    gruppi = generation_engine._voxcpm_chapter_groups(PIANO, {3, 4})
    assert gruppi == [(0, [0, 1]), (1, [2]), (2, [3, 4, 5])]


class FintaSintesi:
    """Al posto di voxcpm_tts.synthesize_chapter: scrive byte finti."""

    def __init__(self, errore=None):
        self.chiamate = []
        self.errore = errore

    def __call__(self, chunks, voice_id, dest_path, **kw):
        self.chiamate.append({"chunks": list(chunks), "voice": voice_id,
                              "dest": dest_path, "key": kw.get("key", "")})
        if self.errore:
            raise self.errore
        with open(dest_path, "wb") as f:
            f.write(b"\x11\x22" * len(chunks))
        return {"sample_rate": 48000, "chars": sum(len(c) for c in chunks),
                "audio_seconds": 1.0 * len(chunks), "tts_seconds": 0.5,
                "jobs": 1, "redone": 0, "bounced": 0, "failed_chunks": 0,
                "bytes": 2 * len(chunks)}


@pytest.fixture
def sintesi_finta(monkeypatch):
    f = FintaSintesi()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setattr(voxcpm_tts, "apply_rate", lambda *a, **k: False)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")   # deterministico nei test
    return f


def test_un_job_per_capitolo_con_i_testi_del_capitolo(tmp_path, sintesi_finta):
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1", set())
    assert [c["chunks"] for c in sintesi_finta.chiamate] == [
        ["a", "b"], ["c"], ["d", "e", "f"]]


def test_l_audio_finisce_sul_primo_chunk_del_capitolo(tmp_path, sintesi_finta):
    # Il worker torna un PCM per capitolo e i confini fra i chunk non tornano
    # indietro: si scrive tutto sul primo pezzo, e gli altri restano vuoti.
    # `pcm_concat` li concatena in ordine e un pezzo vuoto non aggiunge nulla.
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1", set())
    assert os.path.getsize(tmp_path / "chunk_000000.pcm") == 4
    assert os.path.getsize(tmp_path / "chunk_000001.pcm") == 0
    assert os.path.getsize(tmp_path / "chunk_000003.pcm") == 6
    assert os.path.getsize(tmp_path / "chunk_000004.pcm") == 0
    assert os.path.getsize(tmp_path / "chunk_000005.pcm") == 0


def test_ogni_chunk_ha_un_risultato(tmp_path, sintesi_finta):
    pre = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                             "job-1", set())
    assert sorted(pre) == [0, 1, 2, 3, 4, 5]
    assert pre[0]["sample_rate"] == 48000
    # I chunk di coda non hanno audio proprio: non devono contarsi due volte.
    assert pre[1]["chars"] == 0
    assert pre[1]["audio_seconds"] == 0.0


def test_i_capitoli_riusabili_non_entrano_nella_pre_sintesi(tmp_path, sintesi_finta):
    pre = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                             "job-1", {0, 1})
    assert [c["chunks"] for c in sintesi_finta.chiamate] == [["c"], ["d", "e", "f"]]
    assert 0 not in pre and 1 not in pre


def test_la_chiave_r2_distingue_job_e_capitolo(tmp_path, sintesi_finta):
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-7", set())
    chiavi = [c["key"] for c in sintesi_finta.chiamate]
    assert chiavi == ["voxcpm/job-7/ch000000.pcm",
                      "voxcpm/job-7/ch000001.pcm",
                      "voxcpm/job-7/ch000002.pcm"]
    assert len(set(chiavi)) == 3


def test_un_capitolo_perso_ferma_il_libro(tmp_path, monkeypatch):
    # §9.4: esauriti i ritentativi, e' un fallimento del job con rimborso, non
    # un capitolo muto consegnato all'utente.
    f = FintaSintesi(errore=voxcpm_tts.VoxcpmJobError("chunk a silenzio"))
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                           "job-1", set())


def test_annullamento_ferma_le_accensioni(tmp_path, sintesi_finta):
    with pytest.raises(Exception):
        generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                           "job-1", set(),
                                           cancelled=lambda: True)
    assert sintesi_finta.chiamate == []


def test_la_velocita_si_applica_al_pcm_del_capitolo(tmp_path, monkeypatch):
    f = FintaSintesi()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")
    applicate = []
    monkeypatch.setattr(voxcpm_tts, "apply_rate",
                        lambda p, r, sr: applicate.append((os.path.basename(p), r, sr)))
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+15%", tmp_path, "job-1", set())
    # Una volta per capitolo, non una per chunk: l'audio sta tutto li'.
    assert applicate == [("chunk_000000.pcm", "+15%", 48000),
                         ("chunk_000002.pcm", "+15%", 48000),
                         ("chunk_000003.pcm", "+15%", 48000)]
