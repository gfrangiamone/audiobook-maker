"""VoxCPM dentro la catena di generazione: scelta motore, raggruppamento in
capitoli, pre-sintesi.

`synthesize_chapter` e' sostituita da un doppio: qui si prova come il libro
viene diviso in job e dove finisce l'audio, non come si parla con RunPod.
"""
import os
import threading
import time

import pytest

import chunk_reuse
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


def test_nome_amichevole_voce_clonata_senza_slash():
    # 'voxcpm:mine:<token>' non ha '/': il token non e' un nome da mostrare
    # nell'email di consegna, va sostituito con un'etichetta amichevole.
    assert generation_engine._friendly_voice_name("voxcpm:mine:ab12cd34") == "La tua voce"
    # Schema voxcpm ignoto (ne' v2 ne' mine): ultimo segmento ':' come ripiego,
    # ma mai il token/id grezzo per intero senza alcun tentativo di pulizia.
    assert generation_engine._friendly_voice_name("voxcpm:altro") == "altro"


def test_pcm_sample_rate_per_motore():
    assert generation_engine._pcm_sample_rate({}, False, True) == 48000    # voxcpm
    assert generation_engine._pcm_sample_rate({}, False, False) == 24000   # gemini/edge/google
    assert generation_engine._pcm_sample_rate({}, True, False) == 48000    # speechify, default
    assert generation_engine._pcm_sample_rate(
        {"speechify_sample_rate": 44100}, True, False) == 44100


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
                "bytes": 2 * len(chunks),
                "runpod": [{"exec_s": 30.0, "queue_s": 1.0, "worker": "w1",
                            "gpu": "NVIDIA RTX PRO 6000 MIG 1g.24gb"}]}


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


def test_fallimento_in_corsa_con_l_annullamento_esce_come_annullamento(tmp_path, monkeypatch):
    # Il controllo in testa a _uno non basta da solo: se l'annullamento arriva
    # DOPO che la sintesi e' partita, e l'ultimo tentativo del worker fallisce
    # proprio allora, non e' un capitolo perso a ritentativi esauriti (§9.4) ma
    # una cancellazione in corsa col retry -> va sul binario del rimborso.
    stato = {"annullato": False}

    def cancellato():
        return stato["annullato"]

    def sintesi_che_fallisce_dopo_l_annullamento(chunks, voice_id, dest_path, **kw):
        stato["annullato"] = True
        raise voxcpm_tts.VoxcpmJobError("chunk a silenzio")

    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter",
                        sintesi_che_fallisce_dopo_l_annullamento)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")
    with pytest.raises(generation_engine._CancelledError):
        generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                           "job-1", set(), cancelled=cancellato)


def test_un_capitolo_perso_senza_annullamento_resta_un_fallimento(tmp_path, monkeypatch):
    # Controllo di non regressione sul percorso "normale" di errore §9.4: se
    # non c'e' alcun annullamento in corso, l'eccezione originale deve restare
    # VoxcpmJobError, non diventare una cancellazione.
    f = FintaSintesi(errore=voxcpm_tts.VoxcpmJobError("chunk a silenzio"))
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                           "job-1", set(), cancelled=lambda: False)


def test_la_velocita_applicata_aggiorna_byte_e_durata(tmp_path, monkeypatch):
    # Dopo che apply_rate riscrive il PCM sul posto, le statistiche del
    # capitolo (bytes/audio_seconds) devono riflettere il file FINALE, non
    # quello uscito dal worker, altrimenti gli "attuali" del Task 11 non
    # corrispondono all'audio davvero consegnato.
    f = FintaSintesi()
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", f)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")

    def rate_finto(path, r, sr):
        with open(path, "wb") as fh:
            fh.write(b"\x00\x00" * 24000)  # 0.5 s a 48 kHz, 16 bit mono
        return True

    monkeypatch.setattr(voxcpm_tts, "apply_rate", rate_finto)
    pre = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+15%", tmp_path,
                                             "job-1", set())
    assert pre[0]["bytes"] == 48000
    assert pre[0]["audio_seconds"] == 0.5


def test_velocita_non_applicata_non_tocca_le_statistiche(tmp_path, sintesi_finta):
    # apply_rate finto ritorna False (rate neutro/nessun cambiamento): le
    # statistiche restano quelle originali del worker.
    pre = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                             "job-1", set())
    assert pre[0]["bytes"] == 2 * 2       # FintaSintesi: 2 byte per chunk, 2 chunk nel cap.0
    assert pre[0]["audio_seconds"] == 2.0


def test_concorrenza_capitoli_limitata_da_abm_voxcpm_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "2")
    monkeypatch.setattr(voxcpm_tts, "apply_rate", lambda *a, **k: False)
    piano5 = [blocco(f"testo{c}", c) for c in range(5)]  # 5 capitoli, 1 chunk ciascuno
    lock = threading.Lock()
    stato = {"correnti": 0, "picco": 0}

    def sintesi_lenta(chunks, voice_id, dest_path, **kw):
        with lock:
            stato["correnti"] += 1
            stato["picco"] = max(stato["picco"], stato["correnti"])
        time.sleep(0.05)
        with lock:
            stato["correnti"] -= 1
        with open(dest_path, "wb") as fh:
            fh.write(b"\x11\x22")
        return {"sample_rate": 48000, "chars": 1, "audio_seconds": 1.0,
                "tts_seconds": 0.5, "jobs": 1, "redone": 0, "bounced": 0,
                "failed_chunks": 0, "bytes": 2}

    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", sintesi_lenta)
    generation_engine._voxcpm_pre_pass(piano5, VOCE, "+0%", tmp_path, "job-1", set())
    assert stato["picco"] == 2


def test_capitolo_perso_a_meta_libro_lascia_le_statistiche_dei_capitoli_gia_fatti(
        tmp_path, monkeypatch):
    # Review Task 11, Important 1: se il libro si ferma a meta' per un
    # capitolo perso a ritentativi esauriti, le statistiche dei capitoli GIA'
    # completati non devono sparire - job["voxcpm_actual"] e' cio' che
    # l'audit del rimborso (§9.4) legge per sapere quanto e' stato davvero
    # prodotto prima dello stop, non solo quanto e' stato pagato.
    chiamate = []

    def sintesi(chunks, voice_id, dest_path, **kw):
        chiamate.append(list(chunks))
        if len(chiamate) == 3:
            raise voxcpm_tts.VoxcpmJobError("chunk a silenzio")
        with open(dest_path, "wb") as f:
            f.write(b"\x11\x22" * len(chunks))
        return {"sample_rate": 48000, "chars": sum(len(c) for c in chunks),
                "audio_seconds": 1.0 * len(chunks), "tts_seconds": 0.5,
                "jobs": 1, "redone": 0, "bounced": 0, "failed_chunks": 0,
                "bytes": 2 * len(chunks)}

    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", sintesi)
    monkeypatch.setattr(voxcpm_tts, "apply_rate", lambda *a, **k: False)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")   # sequenziale: ordine deterministico
    job = {}
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                           "job-1", set(), job=job)
    # Capitolo 0 ("a"+"b" = 2 char, 1 job) e capitolo 1 ("c" = 1 char, 1 job)
    # sono gia' passati prima che il capitolo 2 sollevasse l'errore: 3 char e
    # 2 job totali devono restare, non azzerarsi.
    assert job["voxcpm_actual"]["chars"] == 3
    assert job["voxcpm_actual"]["jobs"] == 2
    assert job["voxcpm_actual"]["tts_seconds"] == 1.0


def test_capitolo_0_perso_non_perde_le_statistiche_dei_capitoli_dopo_in_concorrenza(
        tmp_path, monkeypatch):
    # Review finale, Important F1: con `_ex.map`, il capitolo fallito e' il
    # PRIMO in ordine di sottomissione (capitolo 0) e il generatore solleva
    # subito al primo next() -> il corpo del for non gira nemmeno una volta,
    # e i capitoli 1-3 (gia' completati o in corso su altri worker, perche'
    # ABM_VOXCPM_JOBS=4 li sottomette tutti insieme) spariscono dall'audit
    # anche se il worker li ha davvero fatturati. Con `as_completed` ogni
    # esito si accumula appena arriva, indipendentemente dall'ordine.
    piano4 = [blocco("cap0", 0), blocco("cap1", 1),
             blocco("cap2", 2), blocco("cap3", 3)]

    def sintesi(chunks, voice_id, dest_path, **kw):
        if "ch000000.pcm" in kw.get("key", ""):
            raise voxcpm_tts.VoxcpmJobError("chunk a silenzio")
        with open(dest_path, "wb") as f:
            f.write(b"\x11\x22" * len(chunks))
        return {"sample_rate": 48000, "chars": sum(len(c) for c in chunks),
                "audio_seconds": 1.0 * len(chunks), "tts_seconds": 0.5,
                "jobs": 1, "redone": 0, "bounced": 0, "failed_chunks": 0,
                "bytes": 2 * len(chunks)}

    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", sintesi)
    monkeypatch.setattr(voxcpm_tts, "apply_rate", lambda *a, **k: False)
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "4")   # sottomessi tutti insieme
    job = {}
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        generation_engine._voxcpm_pre_pass(piano4, VOCE, "+0%", tmp_path,
                                           "job-1", set(), job=job)
    # Capitoli 1, 2 e 3 (4 caratteri ciascuno, "cap1"/"cap2"/"cap3") sono
    # riusciti: le loro misure GPU devono restare nell'audit anche se il
    # capitolo 0 -- primo in ordine di sottomissione -- e' quello fallito.
    assert job["voxcpm_actual"]["chars"] == 12
    assert job["voxcpm_actual"]["jobs"] == 3
    assert job["voxcpm_actual"]["tts_seconds"] == 1.5


def test_le_righe_di_fattura_arrivano_all_audit(tmp_path, sintesi_finta):
    # Il costo del libro e' la somma dei job che RunPod ha fatturato, non dei
    # caratteri consegnati: le righe devono sopravvivere alla pre-sintesi,
    # capitolo per capitolo, come le altre misure.
    job = {}
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1",
                                       set(), job=job)
    righe = job["voxcpm_actual"]["runpod"]
    assert len(righe) == 3          # tre capitoli, un job per capitolo
    assert {r["worker"] for r in righe} == {"w1"}
    assert voxcpm_tts.gpu_cost_usd(righe)["exec_seconds"] == 90.0


def test_un_actual_gia_aperto_senza_righe_non_esplode(tmp_path, sintesi_finta):
    # Un job iniziato prima di questa versione ha un `voxcpm_actual` senza la
    # chiave: l'aggregazione la deve creare, non pretenderla.
    job = {"voxcpm_actual": {"chars": 0, "audio_seconds": 0.0,
                             "tts_seconds": 0.0, "jobs": 0, "redone": 0,
                             "bounced": 0, "failed_chunks": 0}}
    generation_engine._voxcpm_pre_pass([blocco("a", 0)], VOCE, "+0%", tmp_path,
                                       "job-1", set(), job=job)
    assert len(job["voxcpm_actual"]["runpod"]) == 1


class JobSpia(dict):
    """Un job che ricorda ogni scrittura sulla barra.

    Le future partono tutte alla sottomissione, quindi spiare
    `synthesize_chapter` non dice nulla su quando la barra si muove: e' il
    thread che consuma `as_completed` a scriverla, un capitolo alla volta.
    """

    def __init__(self):
        super().__init__(progress_current=2)
        self.storia = []

    def __setitem__(self, chiave, valore):
        if chiave == "progress_current":
            self.storia.append(valore)
        super().__setitem__(chiave, valore)


def test_la_barra_avanza_a_ogni_capitolo_consegnato(tmp_path, sintesi_finta):
    # Il difetto: la barra restava a 2/(N+2) per tutto il tempo della sintesi
    # — cioe' per tutto il tempo del job — e si muoveva solo all'assemblaggio.
    job = JobSpia()
    generation_engine._voxcpm_pre_pass(
        PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    # Tre capitoli da 2, 1 e 3 chunk: la barra sale a ogni consegna, non tutta
    # insieme alla fine. Con ABM_VOXCPM_JOBS=1 l'ordine e' quello del piano.
    assert job.storia == [2 + 9 * 2, 2 + 9 * 3, 2 + 9 * 6]
    assert job["progress_message"] == "Sintesi vocale: 3 di 3 capitoli"


def test_un_libro_di_un_capitolo_non_dice_capitoli(tmp_path, sintesi_finta):
    job = {"progress_current": 2}
    generation_engine._voxcpm_pre_pass(
        [blocco("a", 0)], VOCE, "+0%", tmp_path, "job-1", set(), job=job,
        peso_barra=generation_engine._VOXCPM_PESO_BARRA)
    assert job["progress_message"] == "Sintesi vocale: 1 di 1 capitolo"


def test_senza_peso_la_barra_resta_ferma(tmp_path, sintesi_finta):
    # Il default non tocca la barra: i chiamanti che non la governano (e i
    # test che passano `job` solo per le statistiche) non devono vederla
    # muoversi da sola.
    job = {"progress_current": 2, "progress_message": "invariato"}
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1",
                                       set(), job=job)
    assert job["progress_current"] == 2
    assert job["progress_message"] == "invariato"


def test_la_sintesi_vale_il_grosso_della_barra():
    # Fondo scala e offset dell'assemblaggio devono combaciare: a sintesi
    # finita la barra sta al 90%, e il 10% che resta e' l'assemblaggio.
    peso = generation_engine._VOXCPM_PESO_BARRA
    for chunk in (1, 6, 137):
        fondo = chunk * (peso + 1) + 2
        fine_sintesi = 2 + peso * chunk
        assert fine_sintesi < fondo
        assert round(fine_sintesi / fondo * 100) >= 88


def test_job_none_non_rompe_la_pre_sintesi(tmp_path, sintesi_finta):
    # Compatibilita': tutte le chiamate dirette esistenti non passano `job=`,
    # e devono continuare a funzionare esattamente come prima.
    pre = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                             "job-1", set())
    assert sorted(pre) == [0, 1, 2, 3, 4, 5]


def test_indice_presente_nella_pre_sintesi_torna_il_suo_esito():
    pre = {0: {"chars": 2, "bytes": 4}}
    assert generation_engine._voxcpm_chunk_result(0, pre, set(), "job-1") == pre[0]


def test_indice_assente_ma_nel_piano_di_riuso_e_un_riuso_legittimo():
    # Il caso normale: il capitolo era gia' su disco da un tentativo
    # precedente e non e' mai entrato nella pre-sintesi apposta.
    assert generation_engine._voxcpm_chunk_result(
        3, {}, {3, 4}, "job-1") == {"reused": True}


def test_indice_assente_e_fuori_dal_piano_di_riuso_solleva(capsys):
    # Review finale, Minor F4: un indice mancante nella pre-pass che NON e'
    # nemmeno un riuso legittimo non deve degradare in silenzio a un audio
    # "riusato" muto (il file-parte resterebbe vuoto o di un tentativo
    # vecchio, consegnato come se fosse valido).
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        generation_engine._voxcpm_chunk_result(5, {0: {}}, {0, 1}, "job-9")
    assert "5" in str(e.value)
    assert "job-9" in str(e.value)
    out = capsys.readouterr().out
    assert "5" in out and "job-9" in out


def test_riuso_capitolo_completo_non_richiama_il_worker_ne_lo_fattura(tmp_path, sintesi_finta):
    # Capitolo 0 (chunk 0,1) gia' completo su disco: chunk_reuse deve
    # segnalarlo riusabile, e la pre-sintesi deve saltarlo del tutto (non
    # comparire in `pre` -> non ri-fatturato, e il suo primo chunk prendera'
    # la via {"reused": True} dentro _synthesize_chunk perche' l'indice e'
    # in _reusable_chunks).
    (tmp_path / "chunk_000000.pcm").write_bytes(b"\x11\x22" * 2)
    (tmp_path / "chunk_000001.pcm").write_bytes(b"")
    fp = chunk_reuse.fingerprint(voice=VOCE, rate="+0%", engine="voxcpm", plan=PIANO)
    chunk_reuse.write_manifest(tmp_path, fp)
    reusable = chunk_reuse.reusable_indices(tmp_path, fp, len(PIANO), "pcm",
                                            plan=PIANO)
    assert reusable == {0, 1}   # il capitolo 0 e' riusabile per intero

    pre = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path,
                                             "job-1", reusable)
    # Solo i capitoli 1 e 2 vengono sintetizzati: il worker non viene mai
    # chiamato per il capitolo 0, quindi non viene mai fatturato.
    assert [c["chunks"] for c in sintesi_finta.chiamate] == [["c"], ["d", "e", "f"]]
    assert 0 not in pre and 1 not in pre
