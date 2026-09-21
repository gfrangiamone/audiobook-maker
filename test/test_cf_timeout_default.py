"""Default del timeout HTTP verso Cloudflare, e sua relazione con la sonda.

Il 21/09/2026 il breaker di flash31 e' scattato su un backend che stava
rispondendo: il log dell'AI Gateway mostrava risposte RIUSCITE fino a 44.6s
contro un timeout di 45s. La prova che non fosse un guasto e' la sonda di
rientro, che sintetizza poche parole senza nessun utente collegato ed e'
fallita "dopo 45.1s": una latenza indipendente dalla lunghezza del testo e'
coda a monte, non un backend rotto.

La politica di questo backend (ruling 21/09/2026) e' che il costo viene prima
dell'attesa: Cloudflare e' l'opzione economica, Vertex azzera il margine, e
quindi il timeout va tarato perche' non tagli mai una risposta sana. Questi
test fissano il default e l'invariante che lega sonda e traffico vero, non il
numero in se': chi lo alza ancora non deve rompere nulla, chi lo ABBASSA
sotto la coda osservata sta ripetendo l'episodio.
"""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ABM_CF_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("ABM_CF_PROBE_TIMEOUT_MS", raising=False)


def test_the_default_leaves_room_above_the_slowest_healthy_response():
    # 44.6s e' la risposta sana piu' lenta osservata il 21/09/2026.
    assert gemini_tts._cf_timeout_ms() >= 45000 + 5000
    assert gemini_tts._cf_timeout_ms() == 65000


def test_the_environment_still_wins(monkeypatch):
    monkeypatch.setenv("ABM_CF_TIMEOUT_MS", "30000")
    assert gemini_tts._cf_timeout_ms() == 30000


def test_a_malformed_value_falls_back_to_the_same_default(monkeypatch):
    # Il ripiego dell'except deve valere quanto il default della lettura: due
    # numeri diversi qui vorrebbero dire che una virgola nell'unit systemd
    # cambia in silenzio il comportamento del failover.
    monkeypatch.setenv("ABM_CF_TIMEOUT_MS", "sessantacinque")
    assert gemini_tts._cf_timeout_ms() == 65000


def test_the_probe_is_never_stricter_than_production():
    # Regressione del 19/09/2026: una sonda piu' corta della produzione non
    # misura il backend, misura se stessa.
    assert gemini_tts._cf_probe_timeout_ms() >= gemini_tts._cf_timeout_ms()


def test_the_probe_floor_follows_a_raised_production_timeout(monkeypatch):
    monkeypatch.setenv("ABM_CF_TIMEOUT_MS", "90000")
    monkeypatch.setenv("ABM_CF_PROBE_TIMEOUT_MS", "15000")
    assert gemini_tts._cf_probe_timeout_ms() == 90000
