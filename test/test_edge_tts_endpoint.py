"""Endpoint websocket di edge-tts (incidente 2026-10-10: 403 su speech.platform.bing.com).

edge_engine sposta edge-tts su api.msedgeservices.com, con
`ABM_EDGE_TTS_ENDPOINT=legacy` per tornare indietro, e allunga la pausa sui 429
con cui il nuovo endpoint limita i burst.

22/10/2026: sul legacy alcune voci arrivano a velocita' di parlato (timeout a
120 s sui chunk da 2000 caratteri) o senza audio (en-US-EmmaNeural), mentre
msedgeservices le serve; msedgeservices a sua volta risponde 429 alle raffiche.
Ogni tentativo ripetuto va sull'altro endpoint.

Stesso giorno, dalle 11:44: msedgeservices rifiuta con 429 quasi ogni
connessione. Con l'alternanza il terzo tentativo tornava su msedgeservices:
429, timeout sul legacy, 429 e il chunk restava muto (66 in un'ora). Dopo un
429 l'endpoint resta in pausa per tutti i chunk e il 429 non consuma un
tentativo finche' c'e' un altro endpoint libero.
"""

import asyncio
import os
import sys

import aiohttp
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_tts
import edge_tts.communicate as communicate

import edge_engine
import edge_health

MSEDGE = edge_engine._EDGE_WSS_MSEDGE
LEGACY = edge_engine._EDGE_WSS_LEGACY


@pytest.fixture(autouse=True)
def _nessuna_pausa(monkeypatch):
    """Le pause per i 429 valgono per tutto il processo: ogni test parte senza."""
    monkeypatch.setattr(edge_engine, "_edge_paused_until", {}, raising=False)


def _url():
    """L'URL come lo costruisce edge-tts a ogni connessione (f-string)."""
    return f"{communicate.WSS_URL}"


def test_all_import_edge_tts_usa_il_nuovo_endpoint(monkeypatch):
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    assert _url() == MSEDGE
    assert _url().startswith("wss://api.msedgeservices.com/")
    assert "Ocp-Apim-Subscription-Key=" in _url()


def test_l_endpoint_si_legge_a_ogni_connessione(monkeypatch):
    monkeypatch.setenv("ABM_EDGE_TTS_ENDPOINT", "legacy")
    assert _url() == LEGACY
    monkeypatch.setenv("ABM_EDGE_TTS_ENDPOINT", "")
    assert _url() == MSEDGE


def test_legacy_torna_all_url_della_libreria():
    assert "speech.platform.bing.com" in edge_engine._edge_wss_url("legacy")
    assert edge_engine._edge_wss_url(" LEGACY ") == edge_engine._EDGE_WSS_LEGACY


def test_url_esplicito_e_default():
    assert edge_engine._edge_wss_url("wss://x.example/v1?k=1") == "wss://x.example/v1?k=1"
    assert edge_engine._edge_wss_url("") == edge_engine._EDGE_WSS_MSEDGE
    assert edge_engine._edge_wss_url(None) == edge_engine._EDGE_WSS_MSEDGE


class _Handshake(Exception):
    def __init__(self, status):
        super().__init__(f"{status}, message='Invalid response status'")
        self.status = status


def test_pausa_piu_lunga_sul_429_con_un_solo_endpoint(monkeypatch):
    monkeypatch.setenv("ABM_EDGE_TTS_ENDPOINT", "wss://x.example/v1?k=1")
    assert edge_engine._edge_retry_wait(0, _Handshake(429)) == 3.0
    assert edge_engine._edge_retry_wait(1, _Handshake(429)) == 6.0
    assert edge_engine._edge_retry_wait(0, _Handshake(403)) == 1.0
    assert edge_engine._edge_retry_wait(1, RuntimeError("x")) == 2.0


def test_429_senza_pausa_lunga_se_il_tentativo_cambia_endpoint(monkeypatch):
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    assert edge_engine._edge_retry_wait(0, _Handshake(429)) == 1.0
    assert edge_engine._edge_retry_wait(1, _Handshake(429)) == 2.0


@pytest.fixture
def fake_edge(monkeypatch):
    """Communicate finto: registra l'URL che edge-tts userebbe a ogni tentativo."""
    state = {"urls": [], "errors": []}

    class _Comm:
        def __init__(self, text, voice, rate):
            pass

        async def save(self, path):
            state["urls"].append(_url())
            if state["errors"]:
                raise state["errors"].pop(0)
            with open(path, "wb") as f:
                f.write(b"\0" * 60000)

    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", _Comm)
    monkeypatch.setattr(edge_engine, "_edge_retry_wait", lambda a, e: 0)
    edge_health.reset()
    yield state
    edge_health.reset()


def _attempts(tmp_path):
    return asyncio.run(edge_engine._edge_tts_attempts(
        "Presumimos que nosso casamento vai bem.", "pt-BR-AntonioNeural", "+0%",
        str(tmp_path / "c.mp3"), max_retries=3))


def test_il_tentativo_dopo_un_429_va_sul_legacy(fake_edge, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    fake_edge["errors"] = [_Handshake(429)]
    ok, _ = _attempts(tmp_path)
    assert ok
    assert fake_edge["urls"] == [MSEDGE, LEGACY]
    assert "[msedge]" in capsys.readouterr().out
    assert _url() == MSEDGE


def test_dal_legacy_i_tentativi_ripetuti_vanno_su_msedge(fake_edge, tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_EDGE_TTS_ENDPOINT", "legacy")
    fake_edge["errors"] = [asyncio.TimeoutError(), asyncio.TimeoutError()]
    ok, _ = _attempts(tmp_path)
    assert ok
    assert fake_edge["urls"] == [LEGACY, MSEDGE, LEGACY]
    assert _url() == LEGACY


def test_url_esplicito_resta_l_unico_endpoint(fake_edge, tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_EDGE_TTS_ENDPOINT", "wss://x.example/v1?k=1")
    fake_edge["errors"] = [_Handshake(429)]
    ok, _ = _attempts(tmp_path)
    assert ok
    assert fake_edge["urls"] == ["wss://x.example/v1?k=1"] * 2


def test_la_libreria_vera_si_connette_all_endpoint_del_tentativo(tmp_path, monkeypatch):
    """edge-tts vero fino a ws_connect: l'URL della connessione segue il tentativo."""
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", edge_tts.Communicate)
    monkeypatch.setattr(edge_engine, "_edge_retry_wait", lambda a, e: 0)
    seen = []

    class _Refused(Exception):
        pass

    def _ws_connect(self, url, **kwargs):
        seen.append(url)
        raise _Refused("rete spenta nel test")

    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", _ws_connect)
    edge_health.reset()
    try:
        ok, err = _attempts(tmp_path)
    finally:
        edge_health.reset()
    assert not ok and isinstance(err, _Refused)
    assert [u.split("&ConnectionId=")[0] for u in seen] == [MSEDGE, LEGACY, MSEDGE]


def test_dopo_un_429_msedge_resta_in_pausa_per_gli_altri_chunk(fake_edge, tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    fake_edge["errors"] = [_Handshake(429)]
    assert _attempts(tmp_path)[0]
    fake_edge["urls"].clear()
    assert _attempts(tmp_path)[0]
    assert fake_edge["urls"] == [LEGACY]


def test_finita_la_pausa_si_torna_su_msedge(fake_edge, tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    monkeypatch.setattr(edge_engine, "_EDGE_429_PAUSE_SEC", 0.0)
    fake_edge["errors"] = [_Handshake(429)]
    assert _attempts(tmp_path)[0]
    fake_edge["urls"].clear()
    assert _attempts(tmp_path)[0]
    assert fake_edge["urls"] == [MSEDGE]


def test_errore_del_legacy_dopo_un_429_non_torna_su_msedge(fake_edge, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    fake_edge["errors"] = [_Handshake(429), asyncio.TimeoutError()]
    ok, _ = _attempts(tmp_path)
    assert ok
    assert fake_edge["urls"] == [MSEDGE, LEGACY, LEGACY]
    assert "[legacy] TimeoutError" in capsys.readouterr().out


def test_il_429_non_consuma_un_tentativo(fake_edge, tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    fake_edge["errors"] = [_Handshake(429)] + [asyncio.TimeoutError()] * 2
    ok, _ = _attempts(tmp_path)
    assert ok
    assert fake_edge["urls"] == [MSEDGE, LEGACY, LEGACY, LEGACY]


def test_dal_legacy_un_429_di_msedge_rimanda_sul_legacy(fake_edge, tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_EDGE_TTS_ENDPOINT", "legacy")
    fake_edge["errors"] = [asyncio.TimeoutError(), _Handshake(429), asyncio.TimeoutError()]
    ok, _ = _attempts(tmp_path)
    assert ok
    assert fake_edge["urls"] == [LEGACY, MSEDGE, LEGACY, LEGACY]


def test_429_su_entrambi_gli_endpoint_si_ferma(fake_edge, tmp_path, monkeypatch):
    """Tutti in pausa: si torna alla rotazione e i 429 contano come tentativi."""
    monkeypatch.delenv("ABM_EDGE_TTS_ENDPOINT", raising=False)
    fake_edge["errors"] = [_Handshake(429)] * 10
    ok, err = _attempts(tmp_path)
    assert not ok and err.status == 429
    assert fake_edge["urls"] == [MSEDGE, LEGACY, MSEDGE, LEGACY]


def test_con_un_solo_endpoint_il_429_conta_come_tentativo(fake_edge, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ABM_EDGE_TTS_ENDPOINT", "wss://x.example/v1?k=1")
    fake_edge["errors"] = [_Handshake(429)] * 10
    ok, _ = _attempts(tmp_path)
    assert not ok
    assert len(fake_edge["urls"]) == 3
    assert "in pausa" not in capsys.readouterr().out


def test_la_pausa_si_annuncia_una_volta(capsys):
    edge_engine._edge_pause("msedge")
    edge_engine._edge_pause("msedge")
    assert capsys.readouterr().out.count("msedge in pausa") == 1
