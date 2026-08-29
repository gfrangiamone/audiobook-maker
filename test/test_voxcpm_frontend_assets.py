"""Il tab premium sa di VoxCPM: markup, filtri, campione al posto dell'anteprima.

Asserzioni statiche sul sorgente, come test_speechify_frontend_assets.py: nel
progetto non c'e' un runner JS, e questi test difendono la presenza dei
meccanismi, non il loro comportamento a runtime.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")


def test_il_markup_ha_carattere_e_campione():
    assert 'id="voxcpmCharacterRow"' in HTML
    assert 'id="voxcpmCharacter"' in HTML
    assert 'id="voxcpmSampleRow"' in HTML
    assert 'id="voxcpmSample"' in HTML


def test_carattere_precede_la_voce_nel_markup():
    # CARATTERE filtra VOCE: nell'ordine di lettura il filtro viene prima
    # della cosa filtrata, come gia' l'accento per Simba.
    i_car = HTML.find('id="voxcpmCharacterRow"')
    i_voce = HTML.find('id="vvPremium"')
    assert i_car != -1 and i_voce != -1 and i_car < i_voce


def test_il_campione_e_un_player_non_un_bottone():
    # §5.2: si ascolta un file che esiste gia', non si genera nulla.
    i = HTML.find('id="voxcpmSampleRow"')
    blocco = HTML[i:i + 600]
    assert "<audio" in blocco
    assert "onclick" not in blocco


def test_il_modello_compare_fra_i_premium():
    assert "lbl_model_voxcpm" in JS
    assert "updModelsPremium" in JS
    assert "_isVoxcpmModelSelected" in JS
    assert "_isVoxcpmVoiceId" in JS


def test_il_modello_dipende_dalla_disponibilita_del_motore():
    # Motore non configurato -> nessuna voce e nessun modello: la stessa
    # regola per cui Simba compare solo se il catalogo espone voci speechify.
    assert "_voxcpm" in JS
    assert "voxcpm:" in JS


def test_i_caratteri_arrivano_dal_catalogo():
    # D10: un carattere nuovo non deve richiedere un rilascio. Se comparisse
    # un array di caratteri nel sorgente, sarebbe la firma dell'errore.
    assert "_VOXCPM_PERSONAS" not in JS
    assert "_VOXCPM_ACCENTS" not in JS
    for cablato in ("audiobook-slow", "grave-narrator", "warm-pro",
                    "neutral-pro", "casual-drawl"):
        assert cablato not in JS, f"carattere cablato nel sorgente: {cablato}"
    # Negativa e reale: nel blocco di funzioni VoxCPM non deve comparire un
    # letterale array di stringhe-carattere/locale (la forma di un catalogo
    # cablato, es. ["warm-young", "grave-narrator", ...] o ["en-US","en-GB"]).
    i_blocco = JS.find("function _isVoxcpmVoiceId")
    j_blocco = JS.find("function _populateSpeechifyEmotions", i_blocco)
    assert i_blocco != -1 and j_blocco != -1 and i_blocco < j_blocco
    blocco = JS[i_blocco:j_blocco]
    array_cablato = re.search(r"\[\s*['\"][a-zA-Z][\w]*-[\w-]+['\"]\s*,", blocco)
    assert array_cablato is None, f"array cablato nel blocco VoxCPM: {array_cablato}"
    # Positiva: i due popolatori leggono .persona/.locale dalle voci del
    # catalogo (l'unica fonte ammessa), non da una tabella locale.
    i_car = JS.find("function _populateVoxcpmCharacters")
    assert i_car != -1
    assert "v.persona" in JS[i_car:i_car + 900]
    i_acc = JS.find("function _populateVoxcpmAccents")
    assert i_acc != -1
    assert "v.locale" in JS[i_acc:i_acc + 900]


def test_i_locali_voxcpm_arrivano_dal_catalogo():
    # Idem per gli accenti: nessun gemello di _SPEECHIFY_ACCENTS.
    assert "_VOXCPM_ACCENTS" not in JS
    assert "_populateVoxcpmAccents" in JS


def test_la_selezione_sopravvive_ai_rebuild():
    # Stessa ragione documentata per _speechifyVoiceSel: il dropdown si
    # ricostruisce a ogni cambio di tab/modello e senza una fonte di verita'
    # fuori dal DOM la scelta dell'utente si perde.
    for nome in ("_voxcpmAccentSel", "_voxcpmVoiceSel", "_voxcpmCharacterSel"):
        assert nome in JS


def test_carattere_si_allinea_alla_voce_e_non_si_svuota():
    # §5.3: alla selezione di una voce, CARATTERE mostra il valore di quella
    # voce. E' un'etichetta, non un'alternativa.
    assert "_syncVoxcpmCharacterToVoice" in JS


def test_il_campione_si_ferma_lasciando_voxcpm():
    # Il campione non deve continuare a suonare dietro una riga hidden: sia
    # cambiando modello (VoxCPM -> Gemini/Simba) sia cambiando tab
    # (Premium -> Standard) il player va messo in pausa.
    i_pause = JS.find("function _pauseVoxcpmSample")
    assert i_pause != -1
    assert "voxcpmSample" in JS[i_pause:i_pause + 300]
    assert ".pause()" in JS[i_pause:i_pause + 300]

    i_model = JS.find("function _onPremiumModelChanged")
    j_model = JS.find("\nfunction ", i_model + 1)
    assert i_model != -1 and j_model != -1
    assert "_pauseVoxcpmSample" in JS[i_model:j_model]

    i_tab = JS.find("function switchAudioTab")
    j_tab = JS.find("\nfunction ", i_tab + 1)
    assert i_tab != -1 and j_tab != -1
    assert "_pauseVoxcpmSample" in JS[i_tab:j_tab]


def test_l_anteprima_lascia_il_posto_al_campione():
    assert "voxcpmSampleRow" in JS
    assert "sample_url" in JS
    # Il bottone anteprima non deve restare attivo su una voce VoxCPM: il
    # backend la respinge con 400 (Task 10) e l'utente vedrebbe un errore.
    i = JS.find("function _updatePreviewBtn")
    assert "_isVoxcpmVoiceId" in JS[i:i + 700]


def test_il_modale_di_pagamento_non_dimentica_voxcpm_eur():
    # Review finale, Important F2: /api/combined_estimate restituisce anche
    # voxcpm_eur (motore mutuamente esclusivo con Gemini/Speechify) e il
    # server addebita l'importo completo. Se openPaymentModal sommasse solo
    # gemini_eur + speechify_eur, il prezzo mostrato per una voce VoxCPM
    # sarebbe "—" pur essendoci un totale a pagamento.
    i = JS.find("function openPaymentModal")
    j = JS.find("\nfunction ", i + 1)
    assert i != -1 and j != -1
    corpo = JS[i:j]
    assert "voxcpm_eur" in corpo
