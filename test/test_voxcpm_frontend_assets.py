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


def test_il_markup_ha_il_campione_e_non_il_carattere():
    # §17.4: la combo CARATTERE e' stata tolta — ogni voce ha esattamente un
    # carattere, quindi filtrava senza aggiungere scelta e faceva confusione.
    # Il carattere resta scritto accanto al nome della voce.
    assert 'id="voxcpmCharacterRow"' not in HTML
    assert 'id="voxcpmCharacter"' not in HTML
    assert 'id="voxcpmSampleRow"' in HTML
    assert 'id="voxcpmSample"' in HTML


def test_la_velocita_precede_l_ascolto_nel_markup():
    # §17.4: lo slider della velocita' agisce sulle clip (playbackRate),
    # quindi nell'ordine di lettura viene prima di cio' che modifica —
    # altrimenti non si capisce che effetto produrra' sul libro.
    i_speed = HTML.find('id="speedSlider"')
    i_box = HTML.find('id="voxcpmSampleRow"')
    assert i_speed != -1 and i_box != -1 and i_speed < i_box


def test_l_ascolto_e_un_box_compatto_con_volume_unico():
    # §17.4: niente player nativi doppi — bottoni custom cablati in JS
    # (addEventListener, mai onclick inline), tre <audio> nudi e un solo
    # regolatore di volume per tutti.
    i = HTML.find('id="voxcpmSampleRow"')
    j = HTML.find('id="advOptions"', i)
    assert i != -1 and j != -1
    blocco = HTML[i:j]
    assert "voxcpm-listen-box" in blocco
    assert 'id="voxcpmVolume"' in blocco
    assert blocco.count("<audio") == 3     # comune, su misura, campione
    assert "controls" not in blocco
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
    # Positiva: il popolatore degli accenti legge .locale dalle voci del
    # catalogo (l'unica fonte ammessa), non da una tabella locale.
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
    for nome in ("_voxcpmAccentSel", "_voxcpmVoiceSel"):
        assert nome in JS
    # La combo CARATTERE non esiste piu' (§17.4): con lei se ne va anche la
    # selezione persistita e la sincronia voce -> carattere.
    assert "_voxcpmCharacterSel" not in JS
    assert "_syncVoxcpmCharacterToVoice" not in JS


def test_voxcpm_e_il_primo_modello_proposto():
    # §17.4: dove la lingua ha voci in catalogo, «Audiobook Maker (VOXCPM2)»
    # e' il primo modello della lista e la proposta di default (la stessa
    # regola con cui Simba era proposto sull'inglese); dove non le ha, il
    # modello resta nascosto (gia' verificato sopra).
    i = JS.find("function updModelsPremium")
    j = JS.find("\nfunction ", i + 1)
    assert i != -1 and j != -1
    corpo = JS[i:j]
    i_vox = corpo.find("addOpt('voxcpm'")
    i_gem = corpo.find("addOpt('flash25'")
    assert i_vox != -1 and i_gem != -1 and i_vox < i_gem
    assert "target='voxcpm'" in corpo
    assert "Audiobook Maker (VOXCPM2)" in corpo


def test_lo_slider_velocita_agisce_sulle_clip():
    # §17.4: la velocita' scelta per il libro si sente nelle clip. La
    # mappatura e' la stessa dell'atempo applicato al PCM del libro
    # (apply_rate in voxcpm_tts.py): playbackRate = 1 + pct/100.
    assert "playbackRate" in JS
    i = JS.find("function _wireVoxcpmListen")
    assert i != -1
    corpo = JS[i:i + 2500]
    assert "voxcpmVolume" in corpo     # un solo volume per i tre player
    assert "speedSlider" in corpo      # la velocita' agisce in diretta


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
