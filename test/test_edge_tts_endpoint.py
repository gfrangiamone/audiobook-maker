"""Endpoint websocket di edge-tts (incidente 2026-10-10: 403 su speech.platform.bing.com).

edge_engine sposta edge-tts su api.msedgeservices.com all'import, con
`ABM_EDGE_TTS_ENDPOINT=legacy` per tornare indietro, e allunga la pausa sui 429
con cui il nuovo endpoint limita i burst.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_tts.communicate as communicate

import edge_engine


def test_all_import_edge_tts_usa_il_nuovo_endpoint():
    assert communicate.WSS_URL == edge_engine._EDGE_WSS_MSEDGE
    assert communicate.WSS_URL.startswith("wss://api.msedgeservices.com/")
    assert "Ocp-Apim-Subscription-Key=" in communicate.WSS_URL


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


def test_pausa_piu_lunga_sul_429():
    assert edge_engine._edge_retry_wait(0, _Handshake(429)) == 3.0
    assert edge_engine._edge_retry_wait(1, _Handshake(429)) == 6.0
    assert edge_engine._edge_retry_wait(0, _Handshake(403)) == 1.0
    assert edge_engine._edge_retry_wait(1, RuntimeError("x")) == 2.0
