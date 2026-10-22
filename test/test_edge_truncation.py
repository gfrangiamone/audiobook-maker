"""Rilevamento dell'MP3 edge-tts troncato dalla sola dimensione del file.

22/10/2026: un chunk fatto di "Nooooo..." (219 caratteri) dava ~2 s di audio,
sotto il minimo di 219/40 s: tre tentativi scartati come troncati e silenzio
consegnato, ripetuto a ogni ripasso. La voce legge una lettera ripetuta come
una sola, allungata: le ripetizioni non contano nel minimo atteso.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_engine

BPS = edge_engine._EDGE_MP3_BYTES_PER_SEC
FRASE = "Margaret pressed her face to the window and watched the shops go by. "


def _mp3(tmp_path, seconds):
    p = tmp_path / "c.mp3"
    p.write_bytes(b"\0" * int(seconds * BPS))
    return str(p)


def test_lettera_ripetuta_non_e_troncamento(tmp_path):
    testo = "N" + "o" * 214 + "!!!!"
    assert len(testo) == 219
    assert not edge_engine._edge_output_looks_truncated(_mp3(tmp_path, 2.1), testo)


def test_ripetizione_in_mezzo_al_testo(tmp_path):
    testo = FRASE + "N" + "O" * 100 + "o" * 100 + "."
    assert not edge_engine._edge_output_looks_truncated(_mp3(tmp_path, 4.0), testo)


def test_testo_normale_troppo_corto_resta_troncato(tmp_path):
    testo = (FRASE * 4)[:219]
    assert edge_engine._edge_output_looks_truncated(_mp3(tmp_path, 2.1), testo)


def test_troncamento_vero_con_una_ripetizione_nel_testo(tmp_path):
    testo = FRASE * 25 + "Nooooooooooooooooooo! " + FRASE * 3
    assert edge_engine._edge_output_looks_truncated(_mp3(tmp_path, 10.0), testo)


def test_audio_completo_non_e_troncato(tmp_path):
    testo = FRASE * 29
    assert not edge_engine._edge_output_looks_truncated(_mp3(tmp_path, 95.0), testo)


def test_ellissi_e_spazi_ripetuti_non_alzano_il_minimo(tmp_path):
    testo = "Wait" + "." * 60 + " " * 60 + "what?"
    assert not edge_engine._edge_output_looks_truncated(_mp3(tmp_path, 1.0), testo)
