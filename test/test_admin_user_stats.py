"""Statistiche utente: analisi del business log, endpoint admin, modale.

La coorte PREMIUM segue la variante B (allineata a
`generation_engine.is_premium_job`): voce a pagamento OPPURE pagamento
incassato sulla sessione.
"""
import json
import re
from collections import Counter
from datetime import datetime
from unittest.mock import patch

import pytest

import audiobook_app
import payment
import user_stats


# ---------------------------------------------------------------------------
# user_stats: parsing e coorti
# ---------------------------------------------------------------------------

def test_split_line_tollera_il_cancelletto_nel_nome_file():
    """Uno split secco su ' # ' sfasa i campi e fa sparire la sessione."""
    line = ('job1 # 2026-08-01 10:00:00 # "Riftwar Saga # 2 Empire.epub" # COMPLETE'
            ' # cid1 # 1.2.3.4 # gemini:flash25:Zephyr # it # web')
    f = user_stats.split_line(line)
    assert f == ("job1", "2026-08-01 10:00:00", "Riftwar Saga # 2 Empire.epub",
                 "COMPLETE", "cid1", "1.2.3.4", "gemini:flash25:Zephyr", "it", "web")


def test_split_line_riga_corta_non_esplode():
    f = user_stats.split_line('job1 # 2026-08-01 10:00:00 # "x.epub" # GENERATE')
    assert f is not None
    assert f[3] == "GENERATE"
    assert f[8] == ""


def test_split_line_riga_incompleta_scartata():
    assert user_stats.split_line("solo testo") is None


def test_cohort_voce_premium():
    assert user_stats.cohort_of({"voice": "gemini:flash25:Zephyr", "events": set()}) == "premium"
    assert user_stats.cohort_of({"voice": "speechify:scott", "events": set()}) == "premium"


def test_cohort_pagamento_su_voce_standard():
    """Variante B: l'ottimizzazione AI pagata conta come premium anche su Edge."""
    s = {"voice": "it-IT-DiegoNeural", "events": {"GENERATE", "PAYMENT_CAPTURED"}}
    assert user_stats.cohort_of(s) == "premium"


def test_cohort_free():
    assert user_stats.cohort_of({"voice": "it-IT-DiegoNeural", "events": {"COMPLETE"}}) == "free"


def test_user_key_usa_ip_solo_in_fallback():
    s = {"client_id": "cid1", "client_ip": "1.2.3.4"}
    assert user_stats.user_key(s) == "cid1"
    assert user_stats.user_key({"client_id": "", "client_ip": "1.2.3.4"}) == "ip:1.2.3.4"
    assert user_stats.user_key({"client_id": "", "client_ip": "1.2.3.4"}, ip_fallback=False) == ""


def test_concentration_quantili_su_distribuzione_nota():
    # 10 generazioni: un utente ne fa 5, uno 3, due 1.
    c = user_stats.concentration(Counter({"a": 5, "b": 3, "c": 1, "d": 1}))
    assert c["generazioni"] == 10 and c["utenti"] == 4
    assert c["quantili"]["50%"]["utenti"] == 1        # 5/10 con il solo top
    assert c["quantili"]["70%"]["utenti"] == 2        # 8/10 con i primi due
    assert c["quantili"]["90%"]["utenti"] == 3        # 9/10 con i primi tre
    assert c["top_share"]["top1"] == 50.0
    assert c["istogramma"] == {"1": 2, "2": 0, "3-5": 2, "6-10": 0, ">10": 0}


def test_concentration_vuota_non_divide_per_zero():
    c = user_stats.concentration(Counter())
    assert c["generazioni"] == 0 and c["utenti"] == 0 and c["gini"] == 0.0


LOG = """\
j1 # 2026-08-01 10:00:00 # "a.epub" # GENERATE # cidA # 1.1.1.1 # gemini:flash25:Zephyr # it # web
j1 # 2026-08-01 10:20:00 # "a.epub" # COMPLETE # cidA # 1.1.1.1 # gemini:flash25:Zephyr # it # web
j2 # 2026-08-01 11:00:00 # "b # 2.epub" # GENERATE # cidA # 1.1.1.1 # it-IT-DiegoNeural # it # web
j2 # 2026-08-01 11:10:00 # "b # 2.epub" # COMPLETE # cidA # 1.1.1.1 # it-IT-DiegoNeural # it # web
j3 # 2026-08-02 09:00:00 # "c.epub" # PAYMENT_CAPTURED # cidB # 2.2.2.2 # it-IT-DiegoNeural # it # web
j3 # 2026-08-02 09:05:00 # "c.epub" # GENERATE # cidB # 2.2.2.2 # it-IT-DiegoNeural # it # web
j3 # 2026-08-02 09:40:00 # "c.epub" # COMPLETE # cidB # 2.2.2.2 # it-IT-DiegoNeural # it # web
j4 # 2026-08-02 10:00:00 # "d.epub" # GENERATE # cidC # 3.3.3.3 # it-IT-DiegoNeural # it # web
"""


@pytest.fixture
def logfile(tmp_path):
    p = tmp_path / "activity_2026-08.log"
    p.write_text(LOG, encoding="utf-8")
    return p


def test_analyze_coorti_e_overlap(logfile):
    res = user_stats.analyze(str(logfile))

    prem, free, tot = (res["coorti"][k] for k in ("premium", "free", "totale"))
    # j1 (voce gemini) e j3 (pagamento incassato) sono premium; j2 e j4 free.
    assert prem["generazioni_avviate"] == 2 and prem["generazioni"] == 2
    assert free["generazioni_avviate"] == 2 and free["generazioni"] == 1
    assert tot["generazioni_avviate"] == 4 and tot["generazioni"] == 3
    assert free["tasso_completamento_pct"] == 50.0
    assert prem["utenti"] == 2 and free["utenti"] == 1
    assert res["clienti_paganti"] == 1
    assert res["overlap"] == {"solo_premium": 1, "solo_free": 0, "entrambi": 1}


def test_analyze_conta_le_sessioni_con_cancelletto(logfile):
    """j2 ha un '#' nel titolo: deve comunque risultare completata."""
    res = user_stats.analyze(str(logfile))
    assert res["sessioni_totali"] == 4
    assert res["coorti"]["free"]["generazioni"] == 1


def test_empty_result_ha_la_stessa_forma():
    empty = user_stats.empty_result("activity_2026-01.log")
    assert set(empty["coorti"]) == set(user_stats.COORTI)
    assert empty["coorti"]["premium"]["generazioni_avviate"] == 0
    assert empty["overlap"] == {"solo_premium": 0, "solo_free": 0, "entrambi": 0}


# ---------------------------------------------------------------------------
# user_stats: concentrazione in valore (euro)
# ---------------------------------------------------------------------------

def test_concentration_value_su_distribuzione_nota():
    c = user_stats.concentration_value({"a": 50.0, "b": 30.0, "c": 10.0, "d": 10.0})
    assert c["totale_eur"] == 100.0 and c["utenti"] == 4
    assert c["medio_per_utente_eur"] == 25.0
    assert c["mediana_per_utente_eur"] == 20.0
    assert c["quantili"]["50%"]["utenti"] == 1
    assert c["quantili"]["70%"]["utenti"] == 2
    assert c["quantili"]["90%"]["utenti"] == 3
    assert c["quantili"]["90%"]["pct_spesa"] == 90.0
    assert c["top_share"]["top1"] == 50.0
    assert c["gini"] == 0.35
    assert c["istogramma"] == {"< 1": 0, "1-3": 0, "3-10": 0, "10-30": 2, "> 30": 2}


def test_concentration_value_vuota_non_divide_per_zero():
    c = user_stats.concentration_value({})
    assert c["totale_eur"] == 0.0 and c["utenti"] == 0 and c["gini"] == 0.0


def _ts(day, hour=12):
    return datetime(2026, 8, day, hour, 0).timestamp()


def test_spend_by_user_attribuisce_via_job_id(logfile):
    sessions = user_stats.parse_sessions(str(logfile))
    pays = [
        {"job_id": "j1", "amount_eur": 3.0, "captured_at": _ts(1)},
        {"job_id": "j3", "amount_eur": 2.5, "captured_at": _ts(2)},
        {"job_id": "j1", "amount_eur": 1.5, "captured_at": _ts(3)},
    ]
    per_user, meta = user_stats.spend_by_user(sessions, pays, ym="2026-08")
    assert per_user == {"cidA": 4.5, "cidB": 2.5}
    assert meta["pagamenti"] == 3 and meta["totale_eur"] == 7.0
    assert meta["non_attribuiti"] == 0


def test_spend_by_user_esclude_altri_mesi_e_unfunded(logfile):
    sessions = user_stats.parse_sessions(str(logfile))
    pays = [
        {"job_id": "j1", "amount_eur": 3.0, "captured_at": _ts(1)},
        {"job_id": "j1", "amount_eur": 9.0,
         "captured_at": datetime(2026, 7, 1, 12, 0).timestamp()},
        {"job_id": "j3", "amount_eur": 4.0, "captured_at": _ts(2),
         "pending_unfunded": True},
        {"job_id": "sconosciuto", "amount_eur": 1.0, "captured_at": _ts(2)},
    ]
    per_user, meta = user_stats.spend_by_user(sessions, pays, ym="2026-08")
    assert per_user == {"cidA": 3.0}
    # l'eCheck non compensato non e' denaro incassato
    assert meta["totale_eur"] == 4.0 and meta["pagamenti"] == 2
    assert meta["unfunded"] == 1 and meta["unfunded_eur"] == 4.0
    assert meta["non_attribuiti"] == 1 and meta["non_attribuiti_eur"] == 1.0


def test_analyze_espone_la_concentrazione_di_spesa(logfile):
    pays = [{"job_id": "j3", "amount_eur": 2.5, "captured_at": _ts(2)}]
    res = user_stats.analyze(str(logfile), payments=pays)
    assert res["spesa"]["totale_eur"] == 2.5
    assert res["spesa"]["utenti"] == 1
    assert res["spesa"]["quantili"]["90%"]["utenti"] == 1


def test_analyze_senza_pagamenti_ha_comunque_la_chiave(logfile):
    res = user_stats.analyze(str(logfile))
    assert res["spesa"]["totale_eur"] == 0.0 and res["spesa"]["pagamenti"] == 0


def test_ym_dal_nome_del_file():
    assert user_stats._ym_from_name("/opt/x/activity_2026-08.log") == "2026-08"
    assert user_stats._ym_from_name("altro.log") == ""


def test_load_payments_file_assente(tmp_path):
    assert user_stats.load_payments(str(tmp_path / "manca.json")) == []


def test_empty_result_ha_la_spesa_azzerata():
    empty = user_stats.empty_result("activity_2026-01.log")
    assert empty["spesa"]["totale_eur"] == 0.0
    assert empty["spesa"]["istogramma"] == {}


# ---------------------------------------------------------------------------
# Endpoint /api/admin/user_stats
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    audiobook_app._USER_STATS_CACHE.clear()
    with patch("audiobook_app._admin_auth_ok", return_value=True):
        yield audiobook_app.app.test_client()
    audiobook_app._USER_STATS_CACHE.clear()


def test_endpoint_richiede_auth_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    with patch("audiobook_app._admin_auth_ok", return_value=False):
        r = audiobook_app.app.test_client().get("/api/admin/user_stats?ym=2026-08")
    assert r.status_code == 403


@pytest.mark.parametrize("ym", ["", "2026-13", "2026-8", "agosto", "../../etc/passwd",
                                "2026-08; rm", "2026-00"])
def test_endpoint_rifiuta_mesi_non_validi(admin_client, ym):
    r = admin_client.get("/api/admin/user_stats?ym=" + ym)
    assert r.status_code == 400, r.get_data(as_text=True)


def test_endpoint_mese_senza_log(admin_client):
    r = admin_client.get("/api/admin/user_stats?ym=2026-01")
    assert r.status_code == 200
    d = r.get_json()
    assert d["log_missing"] is True and d["ym"] == "2026-01"
    assert d["coorti"]["totale"]["generazioni"] == 0


def test_endpoint_analizza_il_log_del_mese(admin_client, tmp_path):
    (tmp_path / "activity_2026-08.log").write_text(LOG, encoding="utf-8")

    r = admin_client.get("/api/admin/user_stats?ym=2026-08")

    assert r.status_code == 200
    d = r.get_json()
    assert d["ym"] == "2026-08"
    assert d["coorti"]["premium"]["generazioni"] == 2
    # mai il path assoluto del server nella risposta
    assert d["file"] == "activity_2026-08.log"


def test_endpoint_incrocia_gli_incassi_di_payment(admin_client, tmp_path, monkeypatch):
    """Gli importi non stanno nel log: arrivano da `payment._payments`."""
    (tmp_path / "activity_2026-08.log").write_text(LOG, encoding="utf-8")
    monkeypatch.setattr(payment, "_payments", {
        "ORD1": {"job_id": "j3", "amount_eur": 2.5, "captured_at": _ts(2),
                 "email": "cliente@example.com"},
    })

    d = admin_client.get("/api/admin/user_stats?ym=2026-08").get_json()

    assert d["spesa"]["totale_eur"] == 2.5
    assert d["spesa"]["utenti"] == 1
    # nessuna email del cliente puo' uscire dall'endpoint
    assert "example.com" not in json.dumps(d)


def test_endpoint_invalida_la_cache_su_nuovo_incasso(admin_client, tmp_path, monkeypatch):
    (tmp_path / "activity_2026-08.log").write_text(LOG, encoding="utf-8")
    monkeypatch.setattr(payment, "_payments", {})
    assert admin_client.get("/api/admin/user_stats?ym=2026-08").get_json()["spesa"]["totale_eur"] == 0.0

    monkeypatch.setattr(payment, "_payments", {
        "ORD1": {"job_id": "j1", "amount_eur": 4.0, "captured_at": _ts(1)},
    })
    d = admin_client.get("/api/admin/user_stats?ym=2026-08").get_json()

    assert d["spesa"]["totale_eur"] == 4.0


def test_endpoint_riusa_la_cache_sul_file_immutato(admin_client, tmp_path):
    (tmp_path / "activity_2026-08.log").write_text(LOG, encoding="utf-8")
    admin_client.get("/api/admin/user_stats?ym=2026-08")

    with patch.object(user_stats, "analyze",
                      side_effect=AssertionError("cache non usata")):
        r = admin_client.get("/api/admin/user_stats?ym=2026-08")

    assert r.status_code == 200
    assert r.get_json()["coorti"]["premium"]["generazioni"] == 2


def test_endpoint_errore_di_analisi_non_espone_il_traceback(admin_client, tmp_path):
    (tmp_path / "activity_2026-08.log").write_text(LOG, encoding="utf-8")
    with patch.object(user_stats, "analyze", side_effect=RuntimeError("boom")):
        r = admin_client.get("/api/admin/user_stats?ym=2026-08")
    assert r.status_code == 500
    assert "Traceback" not in r.get_data(as_text=True)


# ---------------------------------------------------------------------------
# UI: modale "Statistiche utente"
# ---------------------------------------------------------------------------

def test_due_bottoni_distinti_nellintestazione(admin_log_page):
    html = admin_log_page
    assert "Statistiche funzionamento" in html and "showStats()" in html
    assert "Statistiche utente" in html and "showUserStats()" in html


def test_modale_utenza_separata_dal_pannello_di_carico(admin_log_page):
    """L'analisi e' mensile: non sta fra i tab a finestra 24h/7d/28d."""
    html = admin_log_page
    assert 'id="usersModal"' in html
    assert 'id="usCards"' in html
    assert 'data-tab="users"' not in html


def test_modale_utenza_ha_un_bottone_per_ogni_mese_con_log(admin_log_page):
    html = admin_log_page
    months = re.findall(r'data-usym="([0-9]{4}-[0-9]{2})"', html)
    assert months, html[:200]
    assert len(set(months)) == len(months)
    # il mese mostrato dalla pagina parte selezionato
    assert re.search(r'class="lsw-btn usw-btn active" data-usym="[0-9]{4}-[0-9]{2}"', html)


def test_modale_utenza_interroga_lendpoint_mensile(admin_log_page):
    html = admin_log_page
    assert "/api/admin/user_stats?ym=" in html
    assert "function lsUsersRender(" in html
    assert "function loadUserStats(ym, btn, force)" in html


def test_modale_utenza_mostra_le_tre_coorti(admin_log_page):
    html = admin_log_page
    assert "function lsCoh(" in html
    for label in ("'Premium'", "'Free'", "'Totale'"):
        assert "lsRow(" + label in html


def test_modale_utenza_mostra_la_concentrazione_di_spesa(admin_log_page):
    html = admin_log_page
    assert "Concentrazione della spesa" in html
    assert "Utenti per il ' + k + ' della spesa" in html
    assert "Peso dei grandi spenditori" in html
    assert "Utenti per fascia di spesa" in html


def test_click_fuori_chiude_entrambe_le_modali(admin_log_page):
    html = admin_log_page
    assert "if (event.target == document.getElementById('usersModal')) hideUserStats();" in html


# ---------------------------------------------------------------------------
# user_stats: lingua del libro
# ---------------------------------------------------------------------------

LOG_LINGUE = (
    'p1 # 2026-08-01 10:00:00 # "a.epub" # COMPLETE # cidA # 1.1.1.1'
    ' # gemini:flash31:Despina # de # \n'
    'p2 # 2026-08-01 11:00:00 # "b.epub" # COMPLETE # cidA # 1.1.1.1'
    ' # speechify:scott # en-US # web\n'
    'p3 # 2026-08-01 12:00:00 # "c.epub" # COMPLETE # cidB # 2.2.2.2'
    ' # gemini:flash31:Despina # de # web\n'
    'f1 # 2026-08-01 13:00:00 # "d.epub" # COMPLETE # cidC # 3.3.3.3'
    ' # it-IT-DiegoNeural # it # web\n'
    'x1 # 2026-08-01 14:00:00 # "e.epub" # COMPLETE # cidD # 4.4.4.4'
    ' # gemini:flash31:Despina #  # web\n'
    'f2 # 2026-08-01 15:00:00 # "f.epub" # COMPLETE # cidC # 3.3.3.3'
    ' # it-IT-DiegoNeural # it # web\n'
    'f3 # 2026-08-01 16:00:00 # "g.epub" # COMPLETE # cidE # 5.5.5.5'
    ' # en-US-GuyNeural # en-GB # web\n'
    'f4 # 2026-08-01 17:00:00 # "h.epub" # COMPLETE # cidE # 5.5.5.5'
    ' # en-US-GuyNeural #  # web\n'
)


@pytest.fixture
def logfile_lingue(tmp_path):
    p = tmp_path / "activity_2026-08.log"
    p.write_text(LOG_LINGUE, encoding="utf-8")
    return p


def test_split_line_regge_il_campo_finale_vuoto():
    """Con `platform` vuota la riga finisce con ' # ': lo strip a monte si
    mangiava l'ultimo separatore e l'ancoraggio a destra slittava."""
    line = ('j1 # 2026-08-01 10:00:00 # "a.epub" # COMPLETE # cid1 # 1.2.3.4'
            ' # en-US-GuyNeural # en # ')
    assert user_stats.split_line(line.strip())[7:] == ("en", "")


def test_split_line_cancelletto_nel_titolo_e_platform_vuota():
    """Il caso peggiore: senza il ripristino l'operazione diventava titolo."""
    line = ('j1 # 2026-08-01 10:00:00 # "Riftwar # 2.epub" # GENERATE # cid1'
            ' # 1.2.3.4 # gemini:flash31:Despina # de # ')
    f = user_stats.split_line(line.strip())
    assert f[2] == "Riftwar # 2.epub" and f[3] == "GENERATE"
    assert f[7] == "de" and f[8] == ""


@pytest.mark.parametrize("raw,atteso", [
    ("it", "it"), ("en-US", "en"), ("ZH", "zh"), ("pt_BR", "pt"),
    ("", "?"), ("   ", "?"), ("x", "?"),
    # il campo ospita anche messaggi liberi (rifiuto di capture duplicata)
    ("job RRE already has a consumed capture (37J); refusing duplicate", "?"),
])
def test_lang_key_normalizza_e_scarta_il_testo_libero(raw, atteso):
    assert user_stats._lang_key(raw) == atteso


def test_ripartizione_quote_cumulate_e_hhi():
    r = user_stats.ripartizione({"en": 60, "de": 30, "it": 10}, key_name="lingua")
    assert r["totale"] == 100 and r["chiavi"] == 3
    assert [x["lingua"] for x in r["righe"]] == ["en", "de", "it"]
    assert r["righe"][0]["pct"] == 60.0 and r["righe"][1]["pct_cumulata"] == 90.0
    # 50% e 70% coperti da 1 e 2 lingue; il 90% cade esattamente sulla seconda
    assert r["quantili"] == {"50%": 1, "70%": 2, "90%": 2}
    assert r["hhi"] == 60 ** 2 + 30 ** 2 + 10 ** 2


def test_ripartizione_vuota_non_divide_per_zero():
    r = user_stats.ripartizione({}, key_name="lingua")
    assert r["totale"] == 0 and r["righe"] == [] and r["hhi"] == 0
    assert r["quantili"] == {"50%": 0, "70%": 0, "90%": 0}


def test_language_stats_conta_solo_le_voci_premium(logfile_lingue):
    sessions = user_stats.parse_sessions(str(logfile_lingue))
    lg = user_stats.language_stats(sessions, [], ym="2026-08")
    righe = {r["lingua"]: r["valore"] for r in lg["libri"]["righe"]}
    # le voci standard stanno nell'altra classifica. x1 non dichiara la
    # lingua: finisce in "?".
    assert righe == {"de": 2, "en": 1, "?": 1}
    assert lg["libri"]["totale"] == 4
    assert lg["meta"]["libri_senza_lingua"] == 1


def test_language_stats_separa_i_libri_a_voce_free(logfile_lingue):
    sessions = user_stats.parse_sessions(str(logfile_lingue))
    lg = user_stats.language_stats(sessions, [], ym="2026-08")
    righe = {r["lingua"]: r["valore"] for r in lg["libri_free"]["righe"]}
    # f1+f2 in italiano, f3 in en-GB (normalizzato en), f4 senza lingua
    assert righe == {"it": 2, "en": 1, "?": 1}
    assert lg["libri_free"]["totale"] == 4
    assert lg["meta"]["libri_free_senza_lingua"] == 1
    # le due coorti non si contaminano
    assert lg["libri"]["totale"] == 4
    assert lg["libri_free"]["quantili"]["50%"] == 1


def test_language_stats_incassi_per_lingua_del_libro(logfile_lingue):
    sessions = user_stats.parse_sessions(str(logfile_lingue))
    pays = [
        {"job_id": "p1", "amount_eur": 10.0, "captured_at": _ts(1)},
        {"job_id": "p3", "amount_eur": 5.0, "captured_at": _ts(1)},
        # incasso su voce standard: nel fatturato per lingua ci va comunque
        {"job_id": "f1", "amount_eur": 2.0, "captured_at": _ts(1)},
        # job non nel log del mese: lingua sconosciuta
        {"job_id": "ignoto", "amount_eur": 1.0, "captured_at": _ts(1)},
        # eCheck non compensato: escluso
        {"job_id": "p2", "amount_eur": 99.0, "captured_at": _ts(1),
         "pending_unfunded": True},
    ]
    lg = user_stats.language_stats(sessions, pays, ym="2026-08")
    righe = {r["lingua"]: r["valore"] for r in lg["incassi"]["righe"]}
    assert righe == {"de": 15.0, "it": 2.0, "?": 1.0}
    assert lg["incassi"]["totale"] == 18.0
    assert lg["meta"]["senza_lingua"] == 1 and lg["meta"]["senza_lingua_eur"] == 1.0
    pag = {r["lingua"]: r["pagamenti"] for r in lg["incassi"]["righe"]}
    assert pag["de"] == 2


def test_analyze_espone_le_lingue(logfile_lingue):
    pays = [{"job_id": "p1", "amount_eur": 10.0, "captured_at": _ts(1)}]
    res = user_stats.analyze(str(logfile_lingue), payments=pays)
    assert res["lingue"]["libri"]["righe"][0]["lingua"] == "de"
    assert res["lingue"]["incassi"]["totale"] == 10.0


def test_empty_result_ha_le_lingue_azzerate():
    lg = user_stats.empty_result()["lingue"]
    assert lg["libri"]["totale"] == 0 and lg["incassi"]["righe"] == []
    assert lg["libri_free"]["totale"] == 0 and lg["libri_free"]["righe"] == []
    assert lg["meta"]["senza_lingua_eur"] == 0.0
    assert lg["meta"]["libri_free_senza_lingua"] == 0


def test_endpoint_espone_le_lingue(admin_client, tmp_path):
    (tmp_path / "activity_2026-08.log").write_text(LOG_LINGUE, encoding="utf-8")
    d = admin_client.get("/api/admin/user_stats?ym=2026-08",
                         headers={"X-Admin-Token": "tok-test"}).get_json()
    assert d["lingue"]["libri"]["totale"] == 4
    assert d["lingue"]["libri"]["quantili"]["90%"] >= 1
    assert d["lingue"]["libri_free"]["totale"] == 4


def test_modale_utenza_mostra_la_ripartizione_per_lingua(admin_log_page):
    html = admin_log_page
    assert "Lingua del libro" in html
    assert "Libri completati a voce premium" in html
    assert "Libri completati a voce free" in html
    assert "Incassi per lingua del libro" in html
    assert "Quante lingue fanno il grosso" in html
    assert "HHI libri premium" in html
    assert "HHI libri free" in html
