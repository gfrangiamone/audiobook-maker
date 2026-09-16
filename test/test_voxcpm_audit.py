"""Il record di audit di un job VoxCPM.

Il costo qui e' tempo di GPU, non una fattura: si verifica che finisca nel
campo che l'aggregato legge come costo vivo, e che i secondi di GPU restino
scritti per poter ricalcolare domani.
"""
import json

import pytest

import generation_engine
import gemini_cost_audit
import audiobook_app

VOCE = "voxcpm:v2:it-IT/Stefano"


class _Info:
    language = "it-IT"
    title = "Libro di prova"


@pytest.fixture
def audit_isolato(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    return tmp_path


def leggi(dir_dati):
    righe = []
    for fp in sorted(dir_dati.glob("gemini_cost_audit_*.jsonl")):
        with open(fp, encoding="utf-8") as f:
            righe.extend(json.loads(r) for r in f if r.strip())
    return righe


def job_finito(charged=1.00):
    return {
        "voxcpm_actual": {"chars": 250_000, "audio_seconds": 9000.0,
                          "tts_seconds": 315.0, "jobs": 12, "redone": 1,
                          "bounced": 3, "failed_chunks": 0},
        "payment": {"total_eur": charged, "method": "paypal",
                    "source": "order", "token": "tok-1234567890"},
        "rate": "+0%",
    }


MIG = "NVIDIA RTX PRO 6000 Blackwell MIG 1g.24gb"


def job_con_fattura(charged=1.00):
    """Due job sullo stesso worker: il primo lo ha acceso, il secondo no."""
    j = job_finito(charged)
    j["voxcpm_actual"]["runpod"] = [
        {"exec_s": 600.0, "queue_s": 160.0, "worker": "w1", "gpu": MIG},
        {"exec_s": 600.0, "queue_s": 2.0, "worker": "w1", "gpu": MIG},
    ]
    return j


def test_il_costo_viene_dai_secondi_quando_ci_sono(audit_isolato, monkeypatch):
    # 1200 s di esecuzione piu' 148 s di accensione, a 0,69 $/h. Il conto sui
    # caratteri darebbe $0,2275 per gli stessi 250.000 caratteri: sono due
    # numeri diversi, e questo e' quello che RunPod fattura.
    monkeypatch.delenv("ABM_VOXCPM_USD_PER_HOUR", raising=False)
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.86")
    generation_engine._write_voxcpm_audit("job-1", job_con_fattura(), VOCE,
                                          "it", "completed")
    r = leggi(audit_isolato)[0]
    assert r["cost_basis"] == "gpu_seconds"
    assert r["gpu_seconds"] == 1348.0
    assert r["gpu_exec_seconds"] == 1200.0
    assert r["gpu_cold_start_seconds"] == 148.0
    assert r["gpu_cold_starts"] == 1
    assert r["gpu_card"] == MIG
    assert r["gpu_usd_per_hour"] == 0.69
    atteso_usd = 1348.0 / 3600.0 * 0.69
    assert r["cost_usd_actual"] == round(atteso_usd, 6)
    assert r["google_cost_eur_actual"] == round(atteso_usd * 0.86, 4)
    assert r["margin_eur_actual"] == round(1.00 - r["google_cost_eur_actual"], 4)


def test_la_tariffa_dichiarata_finisce_nel_record(audit_isolato, monkeypatch):
    # Chi rilegge lo storico deve poter dire con che listino e' stato fatto
    # il conto, senza andare a cercare com'era configurato quel giorno.
    monkeypatch.setenv("ABM_VOXCPM_USD_PER_HOUR", "1.22")
    generation_engine._write_voxcpm_audit("job-1", job_con_fattura(), VOCE,
                                          "it", "completed")
    r = leggi(audit_isolato)[0]
    assert r["gpu_usd_per_hour"] == 1.22
    assert r["cost_usd_actual"] == round(1348.0 / 3600.0 * 1.22, 6)


def test_senza_righe_si_ripiega_sui_caratteri(audit_isolato):
    # Un job vecchio, o un percorso che non ha raccolto la fattura: meglio la
    # stima di prima che uno zero, che nell'aggregato leggerebbe come margine
    # pieno su un lavoro che invece e' costato.
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["cost_basis"] == "chars"
    assert 0.15 < r["google_cost_eur_actual"] < 0.25
    assert r["gpu_seconds"] == 315.0      # il cronometro dell'handler
    assert r["gpu_exec_seconds"] == 0.0


def test_i_secondi_dell_handler_restano_a_parte(audit_isolato, monkeypatch):
    # Il cronometro interno del worker misura la sola sintesi e non vede ne'
    # l'accensione ne' l'overhead di RunPod: e' un dato di salute del motore,
    # non una fattura. Tenerlo separato rende visibile la differenza.
    monkeypatch.delenv("ABM_VOXCPM_USD_PER_HOUR", raising=False)
    generation_engine._write_voxcpm_audit("job-1", job_con_fattura(), VOCE,
                                          "it", "completed")
    r = leggi(audit_isolato)[0]
    assert r["gpu_handler_seconds"] == 315.0
    assert r["gpu_seconds"] == 1348.0


def test_il_record_dichiara_il_provider(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["provider"] == "voxcpm"
    assert r["model_key"] == "v2"
    assert r["outcome"] == "completed"
    assert r["language"] == "it"


def test_il_costo_gpu_va_nel_campo_del_costo_vivo(audit_isolato):
    # 250.000 caratteri a $0,91/Mchar = $0,2275, convertiti in EUR.
    r = generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE,
                                              "it", "completed") or leggi(audit_isolato)[0]
    r = leggi(audit_isolato)[0]
    assert 0.15 < r["google_cost_eur_actual"] < 0.25
    assert r["user_price_eur_charged"] == 1.00
    assert r["margin_eur_actual"] == round(1.00 - r["google_cost_eur_actual"], 4)


def test_i_secondi_di_gpu_restano_scritti(audit_isolato):
    # Il costo e' una stima ancorata a una misura: se il prezzo della scheda
    # cambia, l'audit storico si ricalcola solo se i secondi ci sono.
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["gpu_seconds"] == 315.0
    assert r["cost_usd_per_mchar"] == 0.91
    assert r["worker_jobs"] == 12
    assert r["worker_bounced"] == 3


def test_il_dovuto_si_ricalcola_dai_caratteri_reali(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(charged=0.40),
                                          VOCE, "it", "completed")
    r = leggi(audit_isolato)[0]
    assert r["user_price_eur_should_have_been"] == 1.00
    assert r["delta_eur"] == 0.60      # 1,00 dovuto - 0,40 incassato


def test_una_voce_di_un_altro_motore_non_scrive_nulla(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(),
                                          "speechify:simba-3.2:harper_32",
                                          "en", "completed")
    assert leggi(audit_isolato) == []


def test_un_job_senza_misure_non_solleva(audit_isolato):
    # Best-effort e non fatale, come i due omologhi: un audit che esplode non
    # deve portarsi via un audiolibro gia' consegnato.
    generation_engine._write_voxcpm_audit("job-1", {}, VOCE, "it",
                                          "failed_no_output_refunded")
    r = leggi(audit_isolato)[0]
    assert r["chars_total"] == 0
    assert r["google_cost_eur_actual"] == 0.0


def test_l_aggregato_vede_i_record_voxcpm(audit_isolato):
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    a = gemini_cost_audit.aggregate(model="v2")
    assert a["count"] == 1
    assert a["revenue_eur"] == 1.00
    assert a["margin_eur"] > 0.7


def test_un_job_gratis_sopra_soglia_lascia_traccia(audit_isolato, capsys):
    # Stessa vigilanza del ramo Speechify: un job completato sopra soglia con
    # zero incassato e' un margine negativo che qualcuno deve vedere.
    generation_engine._write_voxcpm_audit("job-1", job_finito(charged=0.0),
                                          VOCE, "it", "completed")
    assert "AUDIT WARNING" in capsys.readouterr().out


def test_la_stima_pre_generazione_finisce_nel_campo_est(audit_isolato):
    # Review Task 11, Minor 1: job["voxcpm_estimate"] e' persistito da
    # /api/generate e /api/optimize proprio per questo campo (parita' con
    # _write_speechify_audit che legge job["speechify_estimate"]): prima di
    # questa correzione google_cost_eur_est restava sempre 0.0.
    job = job_finito()
    job["voxcpm_estimate"] = {"chars_total": 250_000, "cost_usd": 0.2275,
                              "list_price_eur": 1.00, "user_price_eur": 1.00,
                              "is_free": False, "language": "it",
                              "model_key": "v2", "model_label": "VoxCPM v2"}
    generation_engine._write_voxcpm_audit("job-1", job, VOCE, "it", "completed")
    r = leggi(audit_isolato)[0]
    assert r["google_cost_eur_est"] > 0.0
    assert r["audio_seconds_est"] == 0.0   # VoxCPM e' char-based, nessuna stima di durata


def test_nessuna_stima_disponibile_resta_a_zero(audit_isolato):
    # Non-regressione: senza job["voxcpm_estimate"] (job creati prima di
    # /api/optimize, o path che non lo popola) il campo est resta 0.0 come
    # prima, non solleva.
    generation_engine._write_voxcpm_audit("job-1", job_finito(), VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["google_cost_eur_est"] == 0.0


def test_capitolo_perso_a_meta_libro_lascia_traccia_nell_audit_del_rimborso(audit_isolato):
    # Review Task 11, Important 1 (seconda meta'): il job passato all'audit
    # e' esattamente cio' che _voxcpm_pre_pass ha accumulato incrementalmente
    # in job["voxcpm_actual"] prima di sollevare VoxcpmJobError - qui si
    # verifica solo che _write_voxcpm_audit non azzeri quelle statistiche
    # parziali quando l'outcome e' un fallimento rimborsato.
    job = {
        "voxcpm_actual": {"chars": 3, "audio_seconds": 2.0, "tts_seconds": 1.0,
                          "jobs": 2, "redone": 0, "bounced": 0, "failed_chunks": 0},
        "payment": {"total_eur": 0.0, "method": "", "source": "", "token": ""},
        "rate": "+0%",
    }
    generation_engine._write_voxcpm_audit("job-1", job, VOCE, "it",
                                          "failed_refunded")
    r = leggi(audit_isolato)[0]
    assert r["outcome"] == "failed_refunded"
    assert r["chars_total"] == 3
    assert r["worker_jobs"] == 2


def test_riga_live_di_un_job_voxcpm_in_corso_usa_il_tariffario_voxcpm(monkeypatch):
    # Review Task 11, Important 2: prima della correzione un job VoxCPM in
    # corso finiva nel ramo "else: # Speechify / Simba" di
    # _synth_running_gemini_audit_records, leggeva job["speechify_actual"]
    # (vuoto per un job VoxCPM) e prezzava con speechify_tts.compute_user_
    # price_eur(0) -> riga a costo 0 e delta_eur = -incassato.
    # rate_eur_per_mchar() e' 0.0 (motore "nascosto") senza questo env var:
    # senza tariffa il dovuto resta 0 a prescindere dal ramo, e la prova
    # perderebbe di senso.
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    jid = "Jvoxlive"
    job = {
        "status": "generating",
        "voice": VOCE,
        "info": _Info(),
        # 250k char, come job_finito(): abbastanza sopra la soglia gratuita
        # da rendere il "dovuto" un numero positivo confrontabile, non 0.
        "voxcpm_actual": {"chars": 250_000, "audio_seconds": 9000.0,
                          "tts_seconds": 315.0, "jobs": 12, "redone": 1,
                          "bounced": 3, "failed_chunks": 0},
        "payment": {"total_eur": 0.9, "method": "paypal"},
        "rate": "+0%",
    }
    monkeypatch.setitem(audiobook_app.jobs, jid, job)
    try:
        rows = audiobook_app._synth_running_gemini_audit_records()
        row = next(r for r in rows if r.get("job_id") == jid)
        assert row["model_key"] == "v2"
        assert row["outcome"] == "running"
        assert row["chars_total"] == 250_000
        assert row["user_price_eur_charged"] == 0.9
        # Con job["speechify_actual"] assente (ramo sbagliato) sarebbe stato
        # costo 0 e dovuto 0: qui devono essere entrambi positivi.
        assert row["google_cost_eur_actual"] > 0
        assert row["user_price_eur_should_have_been"] > 0
    finally:
        audiobook_app.jobs.pop(jid, None)


def test_i_rientri_per_giro_finiscono_nel_record(audit_isolato):
    # `worker_code_tagliate` conta chi non e' rientrato, `worker_verify_giri`
    # quanti giri sono stati spesi: nessuno dei due dice se un giro in piu'
    # pagherebbe. Lo dice la curva, e deve restare scritta nello storico.
    job = job_con_fattura()
    job["voxcpm_actual"].update({"verifica_sospetti": 8, "verifica_giri": 3,
                                 "verifica_rientri": [5, 2, 0]})
    generation_engine._write_voxcpm_audit("job-1", job, VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["worker_verify_rientri"] == [5, 2, 0]
    assert r["worker_verify_giri"] == 3
    assert r["worker_verify_sospetti"] == 8


def test_job_senza_rientri_non_inventa_zeri(audit_isolato):
    # Un job girato su un'immagine che non manda la curva: lista vuota. Una
    # lista di zeri nello storico si leggerebbe come "nessun recupero".
    generation_engine._write_voxcpm_audit("job-1", job_con_fattura(), VOCE,
                                          "it", "completed")
    r = leggi(audit_isolato)[0]
    assert r["worker_verify_rientri"] == []


def test_gli_allarmi_spenti_dalla_grafia_arrivano_nel_record(audit_isolato):
    # Numeri e grafia sono due vizi distinti del riconoscitore: il primo sta
    # nelle tabelle delle cifre, il secondo nell'orecchio del modello («di se»
    # per «disse»). Nello storico devono restare due colonne, perche' un
    # totale unico non direbbe quale delle due regole ha smesso di reggere.
    job = job_con_fattura()
    job["voxcpm_actual"].update({"verifica_numerali": 24,
                                 "verifica_falsi_numerali": 9,
                                 "verifica_falsi_grafia": 7})
    generation_engine._write_voxcpm_audit("job-2", job, VOCE, "it",
                                          "completed")
    r = leggi(audit_isolato)[0]
    assert r["worker_verify_falsi_numerali"] == 9
    assert r["worker_verify_falsi_grafia"] == 7


def test_il_worker_senza_grafia_scrive_zero(audit_isolato):
    # Immagine precedente alla regola: la chiave manca e lo zero e' la
    # risposta giusta — non ha taciuto niente perche' non c'era.
    generation_engine._write_voxcpm_audit("job-3", job_con_fattura(), VOCE,
                                          "it", "completed")
    assert leggi(audit_isolato)[0]["worker_verify_falsi_grafia"] == 0


def leggi_code_tagliate(dir_dati):
    righe = []
    for fp in sorted(dir_dati.glob("voxcpm_code_tagliate_*.jsonl")):
        with open(fp, encoding="utf-8") as f:
            righe.extend(json.loads(r) for r in f if r.strip())
    return righe


def _job_con_code_tagliate():
    job = job_con_fattura()
    job["voxcpm_actual"].update({
        "code_tagliate": 2,
        "code_tagliate_dettaglio": [
            {"capitolo": 0, "chunk": 0, "coda_attesa": "in fondo al viale.",
             "detto": "in fondo al", "scoperti": 3, "caduta": -14.0,
             "mozza": True, "conclamato": True},
            {"capitolo": 3, "chunk": 17, "coda_attesa": "nel 1967.",
             "detto": "nel millenovecento", "scoperti": 2, "caduta": -4.0,
             "mozza": False, "numeri": True, "grafia": "parola"},
        ]})
    return job


def test_le_code_tagliate_finiscono_in_un_dataset_a_parte(audit_isolato):
    # Una riga per difetto, non per job: e' l'unico modo di distinguere una
    # frase davvero mozza da un falso allarme del rilevatore, e senza le due
    # stringhe affiancate tarare le soglie sarebbe tirare a indovinare.
    generation_engine._write_voxcpm_audit("job-9", _job_con_code_tagliate(),
                                          VOCE, "it", "completed")
    righe = leggi_code_tagliate(audit_isolato)
    assert [r["chunk"] for r in righe] == [0, 17]
    assert righe[0]["capitolo"] == 0
    assert righe[0]["coda_attesa"] == "in fondo al viale."
    assert righe[0]["detto"] == "in fondo al"
    assert righe[0]["job_id"] == "job-9"
    assert righe[0]["voice_id"] == VOCE
    assert righe[0]["outcome"] == "completed"
    assert righe[1]["numeri"] is True
    # Anche il verdetto della regola della grafia passa la lista bianca: senza
    # di lui, riaprendo il dataset non si saprebbe perche' quell'allarme e'
    # rimasto acceso o si e' spento.
    assert righe[1]["grafia"] == "parola"
    # Il conteggio resta dov'era: il dataset lo affianca, non lo sostituisce.
    assert leggi(audit_isolato)[0]["worker_code_tagliate"] == 2


def test_il_dataset_delle_code_tagliate_si_scrive_anche_sui_falliti(
        audit_isolato):
    # Il difetto va guardato soprattutto sui job morti: sono quelli in cui il
    # worker ha faticato di piu'.
    generation_engine._write_voxcpm_audit("job-9", _job_con_code_tagliate(),
                                          VOCE, "it", "failed")
    assert [r["outcome"] for r in leggi_code_tagliate(audit_isolato)] == [
        "failed", "failed"]


def test_senza_code_tagliate_il_dataset_non_nasce(audit_isolato):
    # Sui libri sani il file non deve nemmeno esistere.
    generation_engine._write_voxcpm_audit("job-9", job_con_fattura(), VOCE,
                                          "it", "completed")
    assert list(audit_isolato.glob("voxcpm_code_tagliate_*.jsonl")) == []


def test_la_coda_tagliata_prende_il_minuto_nel_libro():
    # Il capitolo M4B comincia 1,5 s prima del suo PCM (silenzio d'apertura):
    # la posizione nel capitolo la conta, quella nel libro parte dal PCM.
    job = {"voxcpm_actual": {"code_tagliate_dettaglio": [
        {"capitolo": 3, "testa": 40, "chunk": 7, "inizio_s": 62.25},
        {"capitolo": 4, "testa": 55, "chunk": 1},
        {"capitolo": 9, "testa": 99, "chunk": 2, "inizio_s": 5.0},
    ]}}
    generation_engine._voxcpm_posiziona_code(job, {40: (600000, 598500),
                                                   55: (900000, 899000)})
    righe = job["voxcpm_actual"]["code_tagliate_dettaglio"]
    assert righe[0]["posizione_s"] == pytest.approx(662.25, abs=0.06)
    assert righe[0]["nel_capitolo_s"] == pytest.approx(63.8, abs=0.1)
    assert "posizione_s" not in righe[1]
    assert "posizione_s" not in righe[2]


def test_il_minuto_finisce_nel_dataset_delle_code(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    job = {"voxcpm_actual": {"code_tagliate_dettaglio": [
        {"capitolo": 3, "testa": 40, "chunk": 7, "coda_attesa": "fine.",
         "detto": "fi", "titolo": "Tre", "inizio_s": 62.25,
         "posizione_s": 662.3, "nel_capitolo_s": 63.8}]}}
    generation_engine._write_voxcpm_tails_dataset(
        "j1", job, "voxcpm:v2:it-IT/Matteo", "it", "completed")
    (fp,) = list(tmp_path.glob("voxcpm_code_tagliate_*.jsonl"))
    rec = json.loads(fp.read_text(encoding="utf-8").strip())
    assert rec["titolo"] == "Tre"
    assert rec["posizione_s"] == 662.3
    assert rec["nel_capitolo_s"] == 63.8
    assert "testa" not in rec
