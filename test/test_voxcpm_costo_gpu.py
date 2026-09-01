"""Il costo di un job VoxCPM, misurato sui secondi che RunPod fattura.

Il conto sui caratteri e' un ripiego: una costante misurata una volta sola, su
una scheda sola, con una forma di libro sola. Qui il costo si calcola come lo
calcola il libro mastro del worker — `executionTime` alla tariffa della scheda
su cui il job e' davvero girato, piu' l'accensione del container quando quel
job e' il primo ad aver svegliato il worker.
"""
import base64
import json
import os

import pytest

import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
VOCE = "voxcpm:v2:it-IT/Stefano"
MIG = "NVIDIA RTX PRO 6000 Blackwell MIG 1g.24gb"


@pytest.fixture(autouse=True)
def tariffa_di_default(monkeypatch):
    """Nessuna tariffa dichiarata: vale il listino, con 0,69 come ripiego.

    La variabile si toglie davvero dall'ambiente perche' la sua PRESENZA e'
    il segnale che decide chi ha l'ultima parola, non il suo valore.
    """
    monkeypatch.delenv("ABM_VOXCPM_USD_PER_HOUR", raising=False)


def riga(exec_s=60.0, queue_s=0.0, worker="w1", gpu=MIG):
    return {"exec_s": exec_s, "queue_s": queue_s, "worker": worker, "gpu": gpu}


# --------------------------------------------------------------------------
# La funzione pura: righe di job in ingresso, costo in uscita
# --------------------------------------------------------------------------

def test_un_ora_di_mig_costa_la_tariffa_di_listino():
    c = voxcpm_tts.gpu_cost_usd([riga(exec_s=3600.0)])
    assert c["cost_usd"] == pytest.approx(0.69)
    assert c["gpu"] == MIG
    assert c["usd_per_hour"] == 0.69


def test_la_scheda_decide_la_tariffa_non_una_media():
    # Un giro finito su A40 — la fascia preferita non era disponibile — non
    # deve leggersi come se fosse stato tutto sulla MIG.
    c = voxcpm_tts.gpu_cost_usd([riga(exec_s=3600.0, gpu="NVIDIA A40")])
    assert c["cost_usd"] == pytest.approx(1.22)
    assert c["usd_per_hour"] == 1.22


def test_una_scheda_sconosciuta_ripiega_sulla_tariffa_dichiarata():
    c = voxcpm_tts.gpu_cost_usd([riga(exec_s=3600.0, gpu="NVIDIA H200")])
    assert c["cost_usd"] == pytest.approx(0.69)


def test_l_accensione_si_paga_una_volta_sola_per_worker():
    # 148 s di container sulla MIG, addebitati al primo job che ha trovato
    # quel worker spento. Il secondo job lo trova gia' caldo.
    righe = [riga(exec_s=100.0, queue_s=160.0, worker="w1"),
             riga(exec_s=100.0, queue_s=160.0, worker="w1")]
    c = voxcpm_tts.gpu_cost_usd(righe)
    assert c["cold_starts"] == 1
    assert c["cold_start_seconds"] == pytest.approx(148.0)
    assert c["exec_seconds"] == pytest.approx(200.0)
    assert c["gpu_seconds"] == pytest.approx(348.0)
    assert c["cost_usd"] == pytest.approx(348.0 / 3600.0 * 0.69)


def test_due_worker_sono_due_accensioni():
    righe = [riga(exec_s=10.0, queue_s=160.0, worker="w1"),
             riga(exec_s=10.0, queue_s=160.0, worker="w2")]
    c = voxcpm_tts.gpu_cost_usd(righe)
    assert c["cold_starts"] == 2
    assert c["cold_start_seconds"] == pytest.approx(296.0)


def test_una_coda_breve_non_e_un_accensione():
    # Sotto la soglia il worker c'era gia': quei secondi sono il turno dietro
    # a un altro job, non il container che si accende.
    c = voxcpm_tts.gpu_cost_usd([riga(exec_s=100.0, queue_s=5.0)])
    assert c["cold_starts"] == 0
    # Il costo si arrotonda al micro-dollaro: sotto quella cifra non c'e'
    # fattura, e confrontare oltre misurerebbe l'arrotondamento.
    assert c["cost_usd"] == pytest.approx(100.0 / 3600.0 * 0.69, abs=1e-6)


def test_la_tariffa_dichiarata_vince_sul_listino(monkeypatch):
    # E' la voce di chi ha configurato ABM: se l'ha scritta, quella vale
    # ovunque, anche dove il listino conoscerebbe la scheda.
    monkeypatch.setenv("ABM_VOXCPM_USD_PER_HOUR", "1.50")
    c = voxcpm_tts.gpu_cost_usd([riga(exec_s=3600.0, gpu="NVIDIA A40")])
    assert c["cost_usd"] == pytest.approx(1.50)
    assert c["usd_per_hour"] == 1.50


def test_nessun_job_nessun_costo():
    c = voxcpm_tts.gpu_cost_usd([])
    assert c["cost_usd"] == 0.0
    assert c["jobs"] == 0
    assert c["gpu"] == ""


def test_una_riga_senza_scheda_eredita_quella_gia_vista():
    # Il worker dichiara la scheda in ogni risposta, ma un job caduto prima
    # di rispondere no: attribuirlo alla tariffa di ripiego, su un endpoint a
    # fasce miste, sarebbe proprio l'errore che il listino evita.
    righe = [riga(exec_s=10.0, gpu="NVIDIA A40"),
             riga(exec_s=3600.0, gpu="")]
    c = voxcpm_tts.gpu_cost_usd(righe)
    assert c["cost_usd"] == pytest.approx(3610.0 / 3600.0 * 1.22)


# --------------------------------------------------------------------------
# Il ponte: i numeri di RunPod arrivano fin qui
# --------------------------------------------------------------------------

class FintaRisposta:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FintaSessione:
    def __init__(self, post=None, get=None):
        self.copione_post = list(post or [])
        self.copione_get = list(get or [])

    def post(self, url, headers=None, json=None, timeout=None):
        return self.copione_post.pop(0)

    def get(self, url, headers=None, timeout=None):
        return self.copione_get.pop(0)


@pytest.fixture
def endpoint_configurato(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")


def test_on_billing_riceve_i_numeri_di_runpod(endpoint_configurato):
    # `executionTime` e `delayTime` stanno nella risposta di /status, non
    # nell'output del worker: finora si leggevano e si buttavano via.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "COMPLETED",
                                 "executionTime": 42_000,
                                 "delayTime": 160_000,
                                 "output": {"worker": "w-abc", "gpu": MIG}})],
    )
    viste = []
    voxcpm_tts.run_job({"input": {}}, session=ses, sleep=lambda _s: None,
                       poll=0, on_billing=viste.append)
    assert viste == [{"exec_s": 42.0, "queue_s": 160.0,
                      "worker": "w-abc", "gpu": MIG}]


def test_anche_un_job_fallito_e_stato_pagato(endpoint_configurato):
    # La GPU che si e' fermata a meta' l'abbiamo comprata lo stesso: se la
    # riga non arriva, il costo del ritentativo sparisce dal conto.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "FAILED",
                                 "executionTime": 12_000,
                                 "delayTime": 1_000,
                                 "output": {"engine_dead": True,
                                            "worker": "w-abc", "gpu": MIG}})],
        # la cancellazione di cortesia sull'uscita non riuscita
    )
    ses.copione_post.append(FintaRisposta(body={}))
    viste = []
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=lambda _s: None,
                           poll=0, on_billing=viste.append)
    assert viste[0]["exec_s"] == 12.0


def test_un_callback_che_esplode_non_porta_via_il_job(endpoint_configurato):
    # La contabilita' e' un di piu': non deve mai far fallire una sintesi
    # riuscita.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "COMPLETED",
                                 "executionTime": 1_000,
                                 "output": {"ok": True}})],
    )

    def esplode(_riga):
        raise RuntimeError("contabilita' rotta")

    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=lambda _s: None,
                             poll=0, on_billing=esplode)
    assert out == {"ok": True}


# --------------------------------------------------------------------------
# Il capitolo raccoglie le righe di tutti i suoi tentativi
# --------------------------------------------------------------------------

@pytest.fixture
def catalogo(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    monkeypatch.delenv("ABM_S3_BUCKET", raising=False)
    voxcpm_catalog.invalidate_cache()
    voxcpm_tts.invalidate_clone_cache()


def esito_ok(**extra):
    d = {"audio_b64": base64.b64encode(b"\x01\x02" * 100).decode("ascii"),
         "sample_rate": 48000, "chars": 42, "audio_seconds": 3.0,
         "tts_seconds": 1.0, "failed_indices": []}
    d.update(extra)
    return d


def test_le_righe_del_capitolo_comprendono_i_tentativi_buttati(tmp_path,
                                                               monkeypatch,
                                                               catalogo):
    # Un rimbalzo brucia GPU e non produce un carattere: e' esattamente il
    # job che il conto sui caratteri non vede.
    esiti = [voxcpm_tts.VoxcpmRimbalzato("respinto", "job-0"), esito_ok()]

    def finto_run_job(payload, on_billing=None, **kw):
        if on_billing is not None:
            on_billing(riga(exec_s=7.0, worker="w1"))
        e = esiti.pop(0)
        if isinstance(e, Exception):
            raise e
        return e

    monkeypatch.setattr(voxcpm_tts, "run_job", finto_run_job)
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    stats = voxcpm_tts.synthesize_chapter(
        ["Prima frase.", "Seconda frase."], VOCE,
        str(tmp_path / "cap.pcm"))
    assert stats["bounced"] == 1
    assert len(stats["runpod"]) == 2      # il rimbalzo e la consegna
    assert voxcpm_tts.gpu_cost_usd(stats["runpod"])["exec_seconds"] == 14.0
