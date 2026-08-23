"""La conversione M4B non ha piu' un tetto a tempo fisso.

Incidente 23/08/2026: un audiolibro di ~98 ore (MP3 sorgente 2,1 GB) veniva
ucciso dal timeout di 3600 s quando l'encode aveva gia' scritto il 90% del
file, e il retry ripeteva identica la stessa corsa condannata. Ora l'encode
passa da _run_ffmpeg_encode, che sorveglia la crescita dell'output invece del
cronometro: finche' ffmpeg scrive ha tutto il tempo che gli serve.
"""
import os

import pytest

import audio_utils


@pytest.fixture
def scena(tmp_path, monkeypatch):
    """MP3 sorgente + cover su disco, ffprobe finto, ffmpeg sostituibile."""
    mp3 = tmp_path / "libro.mp3"
    mp3.write_bytes(b"ID3" + b"\0" * 512)
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff" + b"\0" * 128)
    m4b = tmp_path / "libro.m4b"

    monkeypatch.setattr(audio_utils, "_get_audio_bitrate", lambda p: 48)
    # 98 ore: la durata che il vecchio timeout fisso non poteva contemplare.
    monkeypatch.setattr(audio_utils, "_get_audio_duration_ms", lambda p: 98 * 3600 * 1000)
    monkeypatch.setattr(audio_utils, "_validate_m4b_file", lambda p: True)
    return {"mp3": str(mp3), "cover": str(cover), "m4b": str(m4b)}


def _fake_encode(calls, esito, scrivi_parziale=False):
    """Sostituto di _run_ffmpeg_encode che registra le chiamate."""
    def run(cmd, output_path, tag, **kwargs):
        calls.append({"cmd": cmd, "expected_sec": kwargs.get("expected_sec")})
        if scrivi_parziale:
            with open(output_path, "wb") as f:
                f.write(b"\0" * 4096)          # ffmpeg ucciso a meta' opera
        elif esito[0]:
            with open(output_path, "wb") as f:
                f.write(b"\0" * 8192)
        return esito
    return run


def test_encode_riuscito_produce_m4b(scena, monkeypatch):
    calls = []
    monkeypatch.setattr(audio_utils, "_run_ffmpeg_encode",
                        _fake_encode(calls, (True, "", "")))

    ok = audio_utils._convert_mp3_to_m4b(scena["mp3"], scena["m4b"],
                                         title="Libro", cover_path=scena["cover"])

    assert ok is True
    assert os.path.exists(scena["m4b"])
    assert len(calls) == 1, "una conversione riuscita non va ritentata"


def test_durata_del_libro_arriva_al_watchdog(scena, monkeypatch):
    """expected_sec dimensiona il tetto assoluto sull'opera, non su una costante."""
    calls = []
    monkeypatch.setattr(audio_utils, "_run_ffmpeg_encode",
                        _fake_encode(calls, (True, "", "")))

    audio_utils._convert_mp3_to_m4b(scena["mp3"], scena["m4b"], title="Libro")

    assert calls[0]["expected_sec"] == pytest.approx(98 * 3600)


def test_errore_di_ffmpeg_ritenta_senza_cover(scena, monkeypatch):
    """Un rc!=0 puo' dipendere dalla cover: il fallback ha senso."""
    calls = []
    monkeypatch.setattr(audio_utils, "_run_ffmpeg_encode",
                        _fake_encode(calls, (False, "bad cover", "rc=1")))

    ok = audio_utils._convert_mp3_to_m4b(scena["mp3"], scena["m4b"],
                                         title="Libro", cover_path=scena["cover"])

    assert ok is False
    assert len(calls) == 2, "il fallback senza cover non e' stato tentato"
    assert "-c:v" in calls[0]["cmd"] and "-c:v" not in calls[1]["cmd"]


def test_stallo_non_ritenta_senza_cover(scena, monkeypatch):
    """Uno stallo non dipende dalla cover: ripartire brucia solo altro tempo."""
    calls = []
    monkeypatch.setattr(audio_utils, "_run_ffmpeg_encode",
                        _fake_encode(calls, (False, "killed", "stall"),
                                     scrivi_parziale=True))

    ok = audio_utils._convert_mp3_to_m4b(scena["mp3"], scena["m4b"],
                                         title="Libro", cover_path=scena["cover"])

    assert ok is False
    assert len(calls) == 1, "uno stallo e' stato ritentato inutilmente"
    assert not os.path.exists(scena["m4b"]), "il file parziale non e' stato rimosso"


def test_tetto_assoluto_non_ritenta_senza_cover(scena, monkeypatch):
    calls = []
    monkeypatch.setattr(audio_utils, "_run_ffmpeg_encode",
                        _fake_encode(calls, (False, "", "hard_timeout"),
                                     scrivi_parziale=True))

    assert audio_utils._convert_mp3_to_m4b(scena["mp3"], scena["m4b"],
                                           title="Libro",
                                           cover_path=scena["cover"]) is False
    assert len(calls) == 1
    assert not os.path.exists(scena["m4b"])


def test_nessun_timeout_fisso_nel_sorgente():
    """Il tetto a tempo fisso non deve rientrare dalla finestra."""
    import inspect
    src = inspect.getsource(audio_utils._convert_mp3_to_m4b)
    assert "M4B_TIMEOUT" not in src
    assert "timeout=" not in src, "l'encode M4B non deve avere un tetto wall-clock"
