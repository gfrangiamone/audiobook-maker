"""Configurazione, disponibilita' e listino del motore VoxCPM.

Nessuna rete: il ponte verso RunPod si prova col doppio in
test_voxcpm_tts_runpod.py.
"""
import os

import pytest

import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")


@pytest.fixture
def configurato(monkeypatch):
    """Motore pienamente configurato: endpoint, chiave, catalogo, tariffa."""
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "abc123endpoint")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "rp-chiave-finta")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    voxcpm_catalog.invalidate_cache()
    yield
    voxcpm_catalog.invalidate_cache()


def test_disponibile_quando_tutto_c_e(configurato):
    assert voxcpm_tts.is_available() is True


def test_senza_endpoint_non_disponibile(configurato, monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_ENDPOINT_ID")
    assert voxcpm_tts.is_available() is False


def test_senza_chiave_non_disponibile(configurato, monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_API_KEY")
    assert voxcpm_tts.is_available() is False


def test_senza_tariffa_non_disponibile(configurato, monkeypatch):
    # §15.3: il listino si fissa prima del deploy. Meglio il motore nascosto
    # che libri generati a un prezzo che nessuno ha deciso.
    monkeypatch.delenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR")
    assert voxcpm_tts.is_available() is False


def test_tariffa_zero_non_disponibile(configurato, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "0")
    assert voxcpm_tts.is_available() is False


def test_catalogo_vuoto_non_disponibile(configurato, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", os.path.join(FIXTURE, "nonesiste"))
    voxcpm_catalog.invalidate_cache()
    assert voxcpm_tts.is_available() is False


def test_concorrenza_default_e_override(configurato, monkeypatch):
    assert voxcpm_tts.concurrency() == 32
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "8")
    assert voxcpm_tts.concurrency() == 8
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "0")
    assert voxcpm_tts.concurrency() == 1      # floor
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "cavallo")
    assert voxcpm_tts.concurrency() == 32     # valore illeggibile -> default


def test_listino_e_tariffa_diretta(configurato):
    # 250.000 caratteri a 4,00 EUR/Mchar = 1,00 EUR.
    p = voxcpm_tts.compute_user_price_eur(250_000)
    assert p["chars"] == 250_000
    assert p["list_price_eur"] == 1.00
    assert p["user_price_eur"] == 1.00
    assert p["is_free"] is False


def test_sotto_soglia_e_gratis(configurato):
    # 25.000 caratteri = 0,10 EUR, sotto ABM_VOXCPM_FREE_THRESHOLD_EUR (0,50).
    p = voxcpm_tts.compute_user_price_eur(25_000)
    assert p["list_price_eur"] == 0.10
    assert p["user_price_eur"] == 0.0
    assert p["is_free"] is True


def test_caratteri_assurdi_non_sollevano(configurato):
    assert voxcpm_tts.compute_user_price_eur(0)["list_price_eur"] == 0.0
    assert voxcpm_tts.compute_user_price_eur(-5)["chars"] == 0
    assert voxcpm_tts.compute_user_price_eur(None)["chars"] == 0


def test_costo_gpu_misurato_e_separato_dal_listino(configurato):
    # §8.3: base di costo misurata su RTX 4090, serve all'audit, non al prezzo.
    assert voxcpm_tts.cost_usd_per_mchar() == 0.91
    p = voxcpm_tts.compute_user_price_eur(1_000_000)
    assert p["list_price_eur"] == 4.00      # dalla tariffa, non dal costo
    assert p["cost_usd"] == 0.91


def test_cinese_pesa_i_caratteri_per_la_durata(configurato, monkeypatch):
    # Un ideogramma dura ~3,3 lettere: senza fattore un'ora di audio cinese
    # costava all'utente un terzo di un'ora latina, alla GPU lo stesso.
    monkeypatch.delenv("ABM_VOXCPM_LANG_FACTOR_ZH", raising=False)
    it = voxcpm_tts.compute_user_price_eur(1_000_000, "it")
    zh = voxcpm_tts.compute_user_price_eur(1_000_000, "zh")
    assert it["lang_factor"] == 1.0 and it["list_price_eur"] == 4.00
    assert zh["lang_factor"] == 3.3
    assert zh["chars"] == 1_000_000
    assert zh["list_price_eur"] == 13.20
    assert zh["cost_usd"] == pytest.approx(0.91 * 3.3)
    # Prezzo per ora di audio allineato: it a 14,8 car/s, zh a 4,43.
    ora_it = it["list_price_eur"] / 1_000_000 * 14.8 * 3600
    ora_zh = zh["list_price_eur"] / 1_000_000 * 4.43 * 3600
    assert ora_zh == pytest.approx(ora_it, rel=0.05)


def test_fattore_lingua_da_env(configurato, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_LANG_FACTOR_ZH", "2,5")
    assert voxcpm_tts.lang_price_factor("zh-CN") == 2.5
    monkeypatch.setenv("ABM_VOXCPM_LANG_FACTOR_JA", "2.7")
    assert voxcpm_tts.compute_user_price_eur(1_000_000, "ja")["list_price_eur"] == 10.80
    # illeggibile o non positivo -> default della lingua
    monkeypatch.setenv("ABM_VOXCPM_LANG_FACTOR_ZH", "0")
    assert voxcpm_tts.lang_price_factor("zh") == 3.3
    assert voxcpm_tts.lang_price_factor(None) == 1.0


def test_stima_libro_cinese_applica_il_fattore(configurato, monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_LANG_FACTOR_ZH", raising=False)

    class Cap:
        def __init__(self, text):
            self.text = text
    s = voxcpm_tts.estimate_book_cost([Cap("字" * 250_000)], language="zh")
    assert s["chars_total"] == 250_000
    assert s["lang_factor"] == 3.3
    assert s["list_price_eur"] == 3.30


def test_stima_libro_somma_i_capitoli(configurato):
    class Cap:
        def __init__(self, text):
            self.text = text
    capitoli = [Cap("a" * 100_000), Cap("b" * 150_000)]
    s = voxcpm_tts.estimate_book_cost(capitoli, language="it")
    assert s["chars_total"] == 250_000
    assert s["chars_per_chapter"] == [100_000, 150_000]
    assert s["list_price_eur"] == 1.00
    assert s["language"] == "it"
    assert s["model_key"] == "v2"


def test_stima_conta_i_titoli_che_il_piano_legge(configurato):
    """Il titolo anteposto dal piano si paga: il worker lo legge davvero."""
    import tts_split

    class Cap:
        def __init__(self, index, title, text, synthetic=False):
            self.index = index
            self.title = title
            self.text = text
            self.synthetic_title = synthetic
    corpo = "Era una notte buia e tempestosa. " * 20
    capitoli = [
        Cap(0, "Il ritorno", corpo),                     # letto: +13
        Cap(1, "Section 2", corpo, synthetic=True),      # sintetico: 0
        Cap(2, "La partenza", "La partenza. " + corpo),  # gia' nel testo: 0
        Cap(3, "Perché?", corpo),                        # niente punto: +9
    ]
    s = voxcpm_tts.estimate_book_cost(capitoli, language="it")
    assert s["chars_per_chapter"] == [
        len(corpo) + len("Il ritorno.\n\n"),
        len(corpo),
        len("La partenza. " + corpo),
        len(corpo) + len("Perché?\n\n"),
    ]

    # Stessa regola del piano: i caratteri stimati sono quelli che il
    # piano manda al motore (a meno degli spazi che la spezzatura toglie).
    class Info:
        chapters = capitoli
    piano = tts_split._plan_chunks(Info(), max_chars=10_000)
    letti = {}
    for b in piano:
        letti[b["chapter_index"]] = letti.get(b["chapter_index"], 0) + b["chars"]
    for i, n in enumerate(s["chars_per_chapter"]):
        assert abs(letti[i] - n) <= 3


def test_jobs_in_flight_ha_un_floor(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "0")
    assert voxcpm_tts.jobs_in_flight() == 1
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "4")
    assert voxcpm_tts.jobs_in_flight() == 4
    monkeypatch.delenv("ABM_VOXCPM_JOBS", raising=False)
    assert voxcpm_tts.jobs_in_flight() == 2


def test_apply_rate_non_fa_niente_a_velocita_normale(tmp_path):
    p = tmp_path / "x.pcm"
    p.write_bytes(b"\x00\x01" * 100)
    for neutro in ("+0%", "0%", "", None):
        assert voxcpm_tts.apply_rate(str(p), neutro, 48000) is False
    assert p.stat().st_size == 200


def test_speed_effettiva_moltiplica_il_passo_della_voce():
    # +10% su una voce a 0,88 da' 0,968: l'utente chiede il 10% in piu' di
    # quello che ascolta nella clip, non di una velocita' che non ha sentito.
    assert voxcpm_tts.speed_effettiva(0.88, "+10%") == 0.968
    assert voxcpm_tts.speed_effettiva(0.93, "+0%") == 0.93
    assert voxcpm_tts.speed_effettiva(0.93, "") == 0.93
    assert voxcpm_tts.speed_effettiva(0.93, None) == 0.93
    assert voxcpm_tts.speed_effettiva(0.93, "-30%") == 0.651
    assert voxcpm_tts.speed_effettiva(0.6, "-30%") == 0.5      # stretto in basso
    assert voxcpm_tts.speed_effettiva(1.8, "+30%") == 2.0      # stretto in alto
    assert voxcpm_tts.speed_effettiva(0.93, "storto") == 0.93  # cursore illeggibile


def test_passo_di_voce_dal_catalogo(monkeypatch):
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", fixture)
    voxcpm_catalog.invalidate_cache()
    assert voxcpm_tts.passo_di_voce("voxcpm:v2:it-IT/Stefano") == 0.88
    # Una voce clonata (`mine`) sconosciuta prende la base delle campionate
    # (1,0, passo nativo); una di catalogo sparita il default del catalogo.
    assert voxcpm_tts.passo_di_voce("voxcpm:mine:abc123") == 1.0
    assert voxcpm_tts.passo_di_voce("voxcpm:v2:it-IT/Nessuno") == 0.93


def test_apply_rate_accelera_il_pcm(tmp_path):
    # ffmpeg vero su un PCM di silenzio: +30% deve accorciare il file.
    p = tmp_path / "x.pcm"
    p.write_bytes(b"\x00\x00" * 48000)          # 1 s a 48 kHz, 16 bit mono
    assert voxcpm_tts.apply_rate(str(p), "+30%", 48000) is True
    assert 60000 < p.stat().st_size < 84000     # ~1/1,3 di 96000 byte


def test_apply_rate_ffmpeg_fallito_non_perde_l_audio(tmp_path, monkeypatch):
    # ffmpeg mancante o che fallisce non deve buttare via il PCM gia' pagato
    # al worker: resta quello originale, si legge a velocita' normale.
    import subprocess
    originale = b"\x01\x02" * 48000
    p = tmp_path / "x.pcm"
    p.write_bytes(originale)

    def fallisce(cmd, check=True):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fallisce)
    assert voxcpm_tts.apply_rate(str(p), "+30%", 48000) is False
    assert p.read_bytes() == originale


def test_apply_rate_ffmpeg_fallito_pulisce_il_file_temporaneo(tmp_path, monkeypatch):
    import subprocess
    p = tmp_path / "x.pcm"
    p.write_bytes(b"\x01\x02" * 48000)

    def fallisce(cmd, check=True):
        raise FileNotFoundError("ffmpeg non trovato")

    monkeypatch.setattr(subprocess, "run", fallisce)
    assert voxcpm_tts.apply_rate(str(p), "+30%", 48000) is False
    assert not (tmp_path / "x.pcm.rate").exists()


def test_apply_rate_ffmpeg_fallito_non_logga_il_path(tmp_path, monkeypatch, caplog):
    import logging
    import subprocess

    p = tmp_path / "x.pcm"
    p.write_bytes(b"\x01\x02" * 48000)

    def fallisce(cmd, check=True):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fallisce)
    with caplog.at_level(logging.WARNING, logger="voxcpm_tts"):
        voxcpm_tts.apply_rate(str(p), "+30%", 48000)
    testo = "\n".join(r.getMessage() for r in caplog.records)
    assert str(p) not in testo
    assert str(tmp_path) not in testo


class _HealthResp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


class _HealthSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.urls = resp, exc, []

    def get(self, url, headers=None, timeout=None):
        self.urls.append((url, timeout))
        if self.exc:
            raise self.exc
        return self.resp


def test_worker_health_legge_i_contatori(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep1")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "k")
    ses = _HealthSession(_HealthResp(200, {"jobs": {"inQueue": 0},
                                           "workers": {"running": 1, "idle": 2}}))
    assert voxcpm_tts.worker_health(session=ses) == {"running": 1, "idle": 2}
    assert ses.urls[0][0].endswith("/ep1/health")
    assert ses.urls[0][1] <= 10


def test_worker_health_none_senza_configurazione(monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_ENDPOINT_ID", raising=False)
    monkeypatch.delenv("ABM_VOXCPM_API_KEY", raising=False)
    ses = _HealthSession(_HealthResp(200, {"workers": {"running": 1}}))
    assert voxcpm_tts.worker_health(session=ses) is None
    assert ses.urls == []


def test_worker_health_none_su_errore(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep1")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "k")
    assert voxcpm_tts.worker_health(session=_HealthSession(_HealthResp(503, {}))) is None
    assert voxcpm_tts.worker_health(session=_HealthSession(exc=OSError("rete"))) is None
    assert voxcpm_tts.worker_health(session=_HealthSession(_HealthResp(200, {"x": 1}))) is None
