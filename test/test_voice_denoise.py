"""Pulizia ZipEnhancer del campione sul server (voice_denoise, denoise_sample)."""
import base64
import os
import shutil
import subprocess

import numpy as np
import pytest

import community_store
import storage_backend
import voice_clone as vc
import voice_clone_audio as vca
import voice_clone_demo as vcd
import voice_denoise
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOICE_CLONE_DENOISE", "1")
    monkeypatch.delenv("ABM_VOXCPM_DENOISE_MINE", raising=False)
    voxcpm_catalog.invalidate_cache()
    voxcpm_tts.invalidate_clone_cache()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(vcd, "pcm_to_wav48", lambda p, w: shutil.move(p, w))
    yield
    voxcpm_catalog.invalidate_cache()
    voxcpm_tts.invalidate_clone_cache()


class PuliziaFinta:
    """Doppio di voice_denoise.clean: scrive «PULITO:» + i byte d'ingresso."""

    def __init__(self, errore=None):
        self.errore = errore
        self.ingressi = []

    def __call__(self, src, dst):
        data = open(src, "rb").read()
        self.ingressi.append(data)
        if self.errore:
            raise self.errore
        with open(dst, "wb") as f:
            f.write(b"PULITO:" + data)
        return 12.3


def _voce(tmp_path, wav=b"RIFF-grezzo", cid="cid-x"):
    s = tmp_path / "s.wav"
    s.write_bytes(wav)
    o = tmp_path / "o.webm"
    o.write_bytes(b"webm")
    return vc.create_draft(cid, lang="it", locale="it-IT", gender="f",
                           prompt_text="Ogni mattina apro la finestra",
                           sample_wav=str(s), original_path=str(o), original_ext="webm",
                           metrics={}, ui_lang="it")


def _file(rec, nome):
    return open(os.path.join(vc.voice_dir(rec["token"]), nome), "rb").read()


def test_denoise_sample_pulisce_e_tiene_il_grezzo(tmp_path, monkeypatch):
    p = PuliziaFinta()
    monkeypatch.setattr(voice_denoise, "clean", p)
    rec = _voce(tmp_path)
    assert vc.denoise_sample(rec["id"]) == "done"
    assert _file(rec, "sample.wav") == b"PULITO:RIFF-grezzo"
    assert _file(rec, vc.RAW_SAMPLE) == b"RIFF-grezzo"
    nuovo = vc.get(rec["id"])
    assert nuovo["denoised_at"] and nuovo["denoise_s"] == 12.3
    assert not [f for f in os.listdir(vc.voice_dir(rec["token"])) if "tmp" in f]
    # una volta per voce
    assert vc.denoise_sample(rec["id"]) == "skipped"
    assert len(p.ingressi) == 1


def test_denoise_sample_riparte_dal_grezzo(tmp_path, monkeypatch):
    # Rifare la pulizia (record riportato indietro a mano) non pulisce due volte.
    p = PuliziaFinta()
    monkeypatch.setattr(voice_denoise, "clean", p)
    rec = _voce(tmp_path)
    vc.denoise_sample(rec["id"])
    vc.store().update(rec["id"], {"denoised_at": None})
    vc.denoise_sample(rec["id"])
    assert p.ingressi == [b"RIFF-grezzo", b"RIFF-grezzo"]
    assert _file(rec, "sample.wav") == b"PULITO:RIFF-grezzo"


def test_denoise_sample_spenta_dall_ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOICE_CLONE_DENOISE", "0")
    p = PuliziaFinta()
    monkeypatch.setattr(voice_denoise, "clean", p)
    rec = _voce(tmp_path)
    assert vc.denoise_sample(rec["id"]) == "skipped"
    assert p.ingressi == [] and _file(rec, "sample.wav") == b"RIFF-grezzo"


def test_denoise_sample_fallita_lascia_il_campione(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_denoise, "clean",
                        PuliziaFinta(voice_denoise.DenoiseFailed("exit 1")))
    rec = _voce(tmp_path)
    with pytest.raises(voice_denoise.DenoiseFailed):
        vc.denoise_sample(rec["id"])
    assert _file(rec, "sample.wav") == b"RIFF-grezzo"
    assert not vc.get(rec["id"]).get("denoised_at")


def test_denoise_sample_carica_su_r2(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_denoise, "clean", PuliziaFinta())
    rec = _voce(tmp_path)
    caricati = []
    monkeypatch.setattr(vc, "upload_to_r2", lambda r, nome: caricati.append(nome))
    vc.denoise_sample(rec["id"])
    assert sorted(caricati) == ["sample.wav", vc.RAW_SAMPLE]
    assert vc.RAW_SAMPLE in vc._files_to_replicate(vc.get(rec["id"]))


def test_clone_block_non_chiede_la_pulizia_per_un_campione_pulito(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_denoise, "clean", PuliziaFinta())
    rec = _voce(tmp_path)
    vid = vc.voice_id_of(rec)
    prima = voxcpm_tts.clone_block(vid)
    assert prima["denoise"] is True
    assert base64.b64decode(prima["prompt_wav_b64"]) == b"RIFF-grezzo"
    vc.denoise_sample(rec["id"])
    # la cache non tiene il campione di prima: il file e' cambiato
    os.utime(os.path.join(vc.voice_dir(rec["token"]), "sample.wav"), ns=(1, 1))
    dopo = voxcpm_tts.clone_block(vid)
    assert "denoise" not in dopo
    assert base64.b64decode(dopo["prompt_wav_b64"]) == b"PULITO:RIFF-grezzo"


def test_generate_demos_pulisce_prima_delle_demo(tmp_path, monkeypatch):
    p = PuliziaFinta()
    monkeypatch.setattr(voice_denoise, "clean", p)
    rec = _voce(tmp_path)
    blocchi = []

    def worker(chunks, voice_id, dest, **kw):
        blocchi.append(voxcpm_tts.clone_block(voice_id))
        open(dest, "wb").write(b"\x01\x02")
        return {}
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", worker)
    assert vcd.generate_demos(rec["id"], sleep=lambda s: None)[0] == "ok"
    assert len(p.ingressi) == 1 and blocchi
    assert all("denoise" not in b for b in blocchi)


def test_generate_demos_va_avanti_se_la_pulizia_fallisce(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_denoise, "clean",
                        PuliziaFinta(voice_denoise.DenoiseFailed("oltre 900s")))
    rec = _voce(tmp_path)
    blocchi = []

    def worker(chunks, voice_id, dest, **kw):
        blocchi.append(voxcpm_tts.clone_block(voice_id))
        open(dest, "wb").write(b"\x01\x02")
        return {}
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", worker)
    assert vcd.generate_demos(rec["id"], sleep=lambda s: None)[0] == "ok"
    # ripiego: la pulizia la fa il worker, come prima
    assert blocchi and all(b["denoise"] is True for b in blocchi)


def test_clean_porta_il_volume_a_quello_di_abm(tmp_path, monkeypatch):
    # Il figlio e' finto: scrive un tono a 24 kHz troppo forte. Il padre deve
    # portarlo a TARGET_LUFS senza superare PEAK_DBFS.
    def figlio(cmd, **kw):
        t = np.arange(vca.SAMPLE_RATE) / vca.SAMPLE_RATE
        vca.write_wav(cmd[-1], 0.9 * np.sin(2 * np.pi * 220 * t), vca.SAMPLE_RATE)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", figlio)
    monkeypatch.setattr(vca, "loudness_lufs", lambda p: -3.0)
    dst = str(tmp_path / "out.wav")
    assert voice_denoise.clean(str(tmp_path / "in.wav"), dst) >= 0
    y, sr = vca.read_wav(dst)
    assert sr == vca.SAMPLE_RATE
    atteso = 0.9 * 10 ** ((vca.TARGET_LUFS + 3.0) / 20)
    assert abs(float(np.max(np.abs(y))) - atteso) < 1e-3


def test_clean_figlio_fallito_solleva(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, "", "Traceback\nModuleNotFoundError: No module named 'modelscope'"))
    with pytest.raises(voice_denoise.DenoiseFailed, match="modelscope"):
        voice_denoise.clean(str(tmp_path / "in.wav"), str(tmp_path / "out.wav"))


def test_denoise_backfill_pulisce_le_voci_gia_registrate(tmp_path, monkeypatch):
    p = PuliziaFinta()
    monkeypatch.setattr(voice_denoise, "clean", p)
    pronta, in_demo, gia = (_voce(tmp_path, cid=c) for c in ("cid-a", "cid-b", "cid-c"))
    vc.store().update(pronta["id"], {"state": "ready"})
    vc.store().update(in_demo["id"], {"state": "demos_generating"})
    vc.store().update(gia["id"], {"state": "ready", "denoised_at": 1})
    assert vcd.denoise_backfill() == 1
    assert vc.get(pronta["id"])["denoised_at"]
    assert not vc.get(in_demo["id"]).get("denoised_at")
    assert vcd.denoise_backfill() == 0
