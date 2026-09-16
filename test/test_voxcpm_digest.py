# -*- coding: utf-8 -*-
"""Il digest quotidiano VoxCPM: i conti dei ritentativi e la mail all'admin.

Il punto delicato non e' la mail, e' l'aritmetica. Il worker rimette i chunk
«rinunciati» (quelli che il tetto dei sospetti ha lasciato fuori) dentro
`chunks_difettosi`, percio' dal libro mastro un ritentativo mai tentato e uno
fallito si contano uguali. Questi test fissano la separazione: tentati =
necessari - non tentati, e i falliti si pescano solo fra i tentati.
"""
import json
from datetime import date

import pytest

GIORNO = "2026-09-01"
ALTRO = "2026-09-02"


def _scrivi(tmp_path, record):
    """Scrive i record cosi' come sono: il ts deve poterlo decidere il test."""
    fp = tmp_path / "gemini_cost_audit_2026-09.jsonl"
    with open(fp, "a", encoding="utf-8") as f:
        for rec in record:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _rec(job_id, ts=GIORNO, provider="voxcpm", **extra):
    rec = {"job_id": job_id, "provider": provider, "language": "it",
           "chars_total": 10000, "outcome": "completed",
           "ts": ts + "T12:00:00+00:00"}
    rec.update(extra)
    return rec


@pytest.fixture()
def digest(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    import voxcpm_digest as vd
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(vd, "_DATA_DIR", tmp_path)
    return vd


# ---------------------------------------------------------------------------
# L'aritmetica
# ---------------------------------------------------------------------------

def test_sopra_il_tetto_i_non_tentati_non_contano_come_falliti(digest,
                                                               tmp_path):
    """8 sospetti, 5 lasciati fuori dal tetto, 6 code ancora tagliate.

    I tentati sono 3. Delle 6 code rimaste, 5 sono i rinunciati: ne resta
    una sola imputabile a un tentativo andato a vuoto, quindi 2 riusciti.
    Senza la separazione, i falliti sarebbero sembrati 6 su 8.
    """
    _scrivi(tmp_path, [_rec("sopra", worker_code_tagliate=6,
                            worker_verify_chunks=120,
                            worker_verify_sospetti=8,
                            worker_verify_rinunciati=5,
                            worker_verify_giri=1)])
    r = digest.riepilogo(GIORNO)
    assert (r["necessari"], r["non_tentati"]) == (8, 5)
    assert (r["tentati"], r["riusciti"], r["falliti"]) == (3, 2, 1)
    assert r["code_tagliate"] == 6
    assert r["chunk_verificati"] == 120


def test_un_capitolo_recuperato_del_tutto_non_lascia_falliti(digest, tmp_path):
    _scrivi(tmp_path, [_rec("sano", worker_code_tagliate=0,
                            worker_verify_chunks=40,
                            worker_verify_sospetti=4,
                            worker_verify_rinunciati=0,
                            worker_verify_giri=2)])
    r = digest.riepilogo(GIORNO)
    assert (r["tentati"], r["riusciti"], r["falliti"]) == (4, 4, 0)
    assert r["job_con_difetti"] == 0
    assert r["tasso_recupero"] == 100.0


def test_il_job_senza_sospetti_non_finisce_in_tabella(digest, tmp_path):
    """Un giorno sano e' una tabella vuota: nessuna riga da leggere."""
    _scrivi(tmp_path, [_rec("perfetto", worker_code_tagliate=0,
                            worker_verify_chunks=30,
                            worker_verify_sospetti=0,
                            worker_verify_rinunciati=0,
                            worker_verify_giri=0)])
    r = digest.riepilogo(GIORNO)
    assert r["job_totali"] == 1
    assert r["job"] == []
    assert r["tasso_recupero"] is None


def test_i_record_ciechi_portano_le_code_ma_non_i_ritentativi(digest,
                                                              tmp_path):
    """Prima di questa versione il worker non dichiarava i rinunciati.

    Quei record hanno `worker_code_tagliate` ma nessun `worker_verify_*`:
    contarli fra i tentativi darebbe un tasso di recupero falso, ignorarne
    le code tagliate nasconderebbe difetti veri.
    """
    _scrivi(tmp_path, [_rec("cieco", worker_code_tagliate=3)])
    r = digest.riepilogo(GIORNO)
    assert r["job_senza_misure"] == 1
    assert r["code_tagliate"] == 3
    assert r["job_con_difetti"] == 1
    assert (r["necessari"], r["tentati"], r["falliti"]) == (0, 0, 0)
    assert r["tasso_recupero"] is None


def test_le_code_non_possono_essere_meno_dei_rinunciati(digest, tmp_path):
    """Difesa contro un record incoerente: nessun conto va sotto zero."""
    _scrivi(tmp_path, [_rec("storto", worker_code_tagliate=1,
                            worker_verify_sospetti=4,
                            worker_verify_rinunciati=4,
                            worker_verify_giri=1)])
    r = digest.riepilogo(GIORNO)
    assert (r["tentati"], r["riusciti"], r["falliti"]) == (0, 0, 0)


def test_gli_allarmi_spenti_dai_numeri_si_sommano(digest, tmp_path):
    """I ritentativi che la regola dei numeri ha evitato di comprare.

    Non sono difetti recuperati: sono difetti che non c'erano. Restano fuori
    da necessari, tentati e falliti, e vivono in una colonna loro — che
    serve ad accorgersi se la regola smette di lavorare.
    """
    _scrivi(tmp_path, [_rec("numeri", worker_code_tagliate=1,
                            worker_verify_chunks=200,
                            worker_verify_sospetti=3,
                            worker_verify_rinunciati=0,
                            worker_verify_giri=1,
                            worker_verify_numerali=24,
                            worker_verify_falsi_numerali=9)])
    r = digest.riepilogo(GIORNO)
    assert (r["numerali"], r["falsi_numerali"]) == (24, 9)
    assert (r["necessari"], r["tentati"], r["falliti"]) == (3, 3, 1)
    assert r["job_senza_numeri"] == 0


def test_gli_allarmi_spenti_dalla_grafia_hanno_una_colonna_loro(digest,
                                                                tmp_path):
    """La regola della grafia si conta a parte da quella dei numeri.

    I due vizi del riconoscitore sono diversi — le tabelle delle cifre da un
    lato, l'orecchio del modello dall'altro — e si guastano separatamente:
    sommarli nasconderebbe quale dei due ha smesso di reggere.
    """
    _scrivi(tmp_path, [_rec("grafia", worker_code_tagliate=0,
                            worker_verify_chunks=1911,
                            worker_verify_sospetti=9,
                            worker_verify_rinunciati=0,
                            worker_verify_giri=3,
                            worker_verify_numerali=0,
                            worker_verify_falsi_numerali=0,
                            worker_verify_falsi_grafia=8)])
    r = digest.riepilogo(GIORNO)
    assert r["falsi_grafia"] == 8
    assert (r["numerali"], r["falsi_numerali"]) == (0, 0)
    corpo = digest.html(r)
    assert "regola della grafia" in corpo
    assert "taciuti altri <strong>8</strong>" in corpo


def test_il_worker_senza_la_regola_della_grafia_non_inventa_allarmi(digest,
                                                                    tmp_path):
    # Immagine precedente: la chiave manca, e lo zero e' la risposta giusta.
    # Il riquadro sulla grafia non deve nemmeno comparire.
    _scrivi(tmp_path, [_rec("vecchio", worker_code_tagliate=1,
                            worker_verify_chunks=90,
                            worker_verify_sospetti=2,
                            worker_verify_rinunciati=0,
                            worker_verify_giri=1)])
    r = digest.riepilogo(GIORNO)
    assert r["falsi_grafia"] == 0
    assert "regola della grafia" not in digest.html(r)


def test_il_worker_di_ieri_e_cieco_solo_sui_numeri(digest, tmp_path):
    """Un worker che misura i ritentativi ma non ancora i numeri.

    I suoi conti sui ritentativi valgono tutti; i suoi allarmi da grafia
    sono diventati rigenerazioni vere, e il digest lo dichiara invece di
    mettere uno zero che sembrerebbe «nessun numero in giro».
    """
    _scrivi(tmp_path, [_rec("vecchio", worker_code_tagliate=2,
                            worker_verify_chunks=90,
                            worker_verify_sospetti=4,
                            worker_verify_rinunciati=0,
                            worker_verify_giri=2)])
    r = digest.riepilogo(GIORNO)
    assert r["job_senza_numeri"] == 1
    assert (r["numerali"], r["falsi_numerali"]) == (0, 0)
    assert r["tentati"] == 4


# ---------------------------------------------------------------------------
# Cosa entra nel conto
# ---------------------------------------------------------------------------

def test_gli_altri_provider_e_gli_altri_giorni_restano_fuori(digest, tmp_path):
    _scrivi(tmp_path, [
        _rec("mio", worker_code_tagliate=2, worker_verify_sospetti=2,
             worker_verify_rinunciati=0, worker_verify_giri=1),
        _rec("gemini", provider="gemini", worker_code_tagliate=99),
        _rec("domani", ts=ALTRO, worker_code_tagliate=99,
             worker_verify_sospetti=99, worker_verify_rinunciati=0),
    ])
    r = digest.riepilogo(GIORNO)
    assert r["job_totali"] == 1
    assert r["code_tagliate"] == 2


def test_la_tabella_mette_davanti_i_job_piu_difettosi(digest, tmp_path):
    _scrivi(tmp_path, [
        _rec("poche", worker_code_tagliate=1, worker_verify_sospetti=1,
             worker_verify_rinunciati=0, worker_verify_giri=1),
        _rec("molte", worker_code_tagliate=9, worker_verify_sospetti=9,
             worker_verify_rinunciati=0, worker_verify_giri=2),
    ])
    r = digest.riepilogo(GIORNO)
    assert [j["job_id"] for j in r["job"]] == ["molte", "poche"]


def test_la_coda_dei_job_si_riassume_in_una_riga(digest, tmp_path):
    _scrivi(tmp_path, [
        _rec("job%02d" % i, worker_code_tagliate=1,
             worker_verify_sospetti=1, worker_verify_rinunciati=0,
             worker_verify_giri=1)
        for i in range(digest.MAX_RIGHE + 3)])
    r = digest.riepilogo(GIORNO)
    corpo = digest.html(r)
    assert len(r["job"]) == digest.MAX_RIGHE + 3
    assert "e altri 3 job con difetti" in corpo


def test_il_giorno_vuoto_non_e_un_errore(digest):
    r = digest.riepilogo(GIORNO)
    assert r["job_totali"] == 0
    assert "nessuna generazione" in digest.oggetto(r)
    assert "Nessun job VoxCPM" in digest.html(r)


# ---------------------------------------------------------------------------
# Il marker: una volta sola per giorno, riavvii compresi
# ---------------------------------------------------------------------------

def test_si_riepiloga_ieri_mai_oggi(digest):
    assert digest.giorno_arretrato(oggi=date(2026, 9, 3)) == "2026-09-02"


def test_dopo_il_segno_il_giorno_non_torna(digest):
    assert digest.ultimo_inviato() == ""
    digest.segna_inviato("2026-09-02")
    assert digest.ultimo_inviato() == "2026-09-02"
    assert digest.giorno_arretrato(oggi=date(2026, 9, 3)) is None
    # Il giorno dopo riparte, e riprende solo ieri: niente arretrati a valanga.
    assert digest.giorno_arretrato(oggi=date(2026, 9, 10)) == "2026-09-09"


def test_il_marker_sopravvive_a_un_riavvio(digest, tmp_path):
    digest.segna_inviato("2026-09-01")
    assert (tmp_path / "voxcpm_digest_last.txt").read_text(
        encoding="utf-8") == "2026-09-01"


# ---------------------------------------------------------------------------
# La mail
# ---------------------------------------------------------------------------

def test_l_oggetto_dice_quante_code_restano(digest, tmp_path):
    _scrivi(tmp_path, [_rec("x", worker_code_tagliate=6,
                            worker_verify_sospetti=8,
                            worker_verify_rinunciati=5,
                            worker_verify_giri=1)])
    r = digest.riepilogo(GIORNO)
    # 2 recuperate; ne restano 6 = 1 fallita + 5 mai tentate.
    assert digest.oggetto(r) == (
        "VoxCPM %s: 2 code recuperate, 6 rimaste" % GIORNO)


def test_l_oggetto_di_una_giornata_pulita_non_allarma(digest, tmp_path):
    _scrivi(tmp_path, [_rec("x", worker_code_tagliate=0,
                            worker_verify_sospetti=3,
                            worker_verify_rinunciati=0,
                            worker_verify_giri=1)])
    r = digest.riepilogo(GIORNO)
    assert digest.oggetto(r) == (
        "VoxCPM %s: 3 code recuperate su 3" % GIORNO)


def test_l_html_porta_i_quattro_numeri_e_l_avviso_sui_ciechi(digest, tmp_path):
    _scrivi(tmp_path, [
        _rec("misurato", worker_code_tagliate=6, worker_verify_chunks=120,
             worker_verify_sospetti=8, worker_verify_rinunciati=5,
             worker_verify_giri=1),
        _rec("cieco", worker_code_tagliate=2),
    ])
    corpo = digest.html(digest.riepilogo(GIORNO))
    assert "ritentativi necessari" in corpo
    assert "non tentati" in corpo
    assert "su 120 chunk ascoltati" in corpo
    assert "1 job su 2 vengono da un worker" in corpo
    assert "ABM_VOXCPM_DIGEST=0" in corpo


def test_l_html_dice_quanti_allarmi_hanno_spento_i_numeri(digest, tmp_path):
    _scrivi(tmp_path, [
        _rec("numeri", worker_code_tagliate=1, worker_verify_chunks=200,
             worker_verify_sospetti=3, worker_verify_rinunciati=0,
             worker_verify_giri=1, worker_verify_numerali=24,
             worker_verify_falsi_numerali=9),
        _rec("vecchio", worker_code_tagliate=0, worker_verify_chunks=50,
             worker_verify_sospetti=1, worker_verify_rinunciati=0,
             worker_verify_giri=1),
    ])
    corpo = digest.html(digest.riepilogo(GIORNO))
    assert "numeri riconosciuti" in corpo
    assert "su 24 code con un numero" in corpo
    assert "taciuto <strong>9</strong>" in corpo
    assert "1 job vengono da un worker precedente" in corpo


def test_l_html_non_si_fida_del_job_id(digest, tmp_path):
    _scrivi(tmp_path, [_rec("<script>x", worker_code_tagliate=1,
                            worker_verify_sospetti=1,
                            worker_verify_rinunciati=0,
                            worker_verify_giri=1)])
    corpo = digest.html(digest.riepilogo(GIORNO))
    assert "<script>x" not in corpo
    assert "&lt;script&gt;x" in corpo


# ---------------------------------------------------------------------------
# Le code da ascoltare
# ---------------------------------------------------------------------------

def _coda(tmp_path, job_id="libro", ts=GIORNO, outcome="completed", **extra):
    riga = {"ts": ts + "T21:00:00+00:00", "job_id": job_id, "language": "it",
            "outcome": outcome, "capitolo": 7, "chunk": 23,
            "coda_attesa": "e se ne ando'.", "detto": "e se ne",
            "scoperti": 1, "scoperti_grezzi": 1, "mozza": False,
            "conclamato": False, "fioco": False}
    riga.update(extra)
    with open(tmp_path / "voxcpm_code_tagliate_2026-09.jsonl", "a",
              encoding="utf-8") as f:
        f.write(json.dumps(riga, ensure_ascii=False) + "\n")


def test_le_code_con_testo_mancante_vanno_ascoltate(digest, tmp_path):
    _scrivi(tmp_path, [_rec("libro", worker_code_tagliate=3)])
    _coda(tmp_path, capitolo=7, chunk=23, posizione_s=3725.4,
          nel_capitolo_s=61.2, titolo="Capitolo otto")
    # Spenta a torto da una regola: la misura grezza dice che manca testo.
    _coda(tmp_path, capitolo=2, chunk=4, scoperti=0, scoperti_grezzi=2,
          grafia="parola")
    # Falso allarme del solo segnale: l'ASR ha sentito tutto.
    _coda(tmp_path, capitolo=5, chunk=5, scoperti=0, scoperti_grezzi=0)
    r = digest.riepilogo(GIORNO)
    assert r["code_da_ascoltare"] == 2
    (job,) = r["da_ascoltare"]
    assert [(c["capitolo"], c["chunk"]) for c in job["code"]] == [(2, 4), (7, 23)]
    assert "2 code da ascoltare" in digest.oggetto(r)
    corpo = digest.html(r)
    assert "1:02:05" in corpo and "1:01 nel capitolo" in corpo
    assert "cap. 8" in corpo and "Capitolo otto" in corpo
    assert "allarme spento dalla regola grafia" in corpo


def test_marchiata_mozza_va_ascoltata_anche_senza_scoperti(digest, tmp_path):
    _scrivi(tmp_path, [_rec("libro", worker_code_tagliate=1)])
    _coda(tmp_path, scoperti=0, scoperti_grezzi=0, mozza=True, inizio_s=42)
    r = digest.riepilogo(GIORNO)
    assert r["code_da_ascoltare"] == 1
    assert "circa 0:42 nel capitolo" in digest.html(r)


def test_libri_non_consegnati_e_altri_giorni_restano_fuori(digest, tmp_path):
    _scrivi(tmp_path, [_rec("libro", worker_code_tagliate=1)])
    _coda(tmp_path, job_id="rimborsato", outcome="failed_refunded")
    _coda(tmp_path, job_id="domani", ts=ALTRO)
    r = digest.riepilogo(GIORNO)
    assert r["da_ascoltare"] == [] and r["code_da_ascoltare"] == 0
    assert "Da ascoltare" not in digest.html(r)
    assert "da ascoltare" not in digest.oggetto(r)


def test_senza_dataset_nessuna_coda(digest, tmp_path):
    _scrivi(tmp_path, [_rec("libro")])
    assert digest.riepilogo(GIORNO)["da_ascoltare"] == []
