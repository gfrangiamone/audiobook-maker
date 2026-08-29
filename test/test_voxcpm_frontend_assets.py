"""Il tab premium sa di VoxCPM: markup, filtri, campione al posto dell'anteprima.

Asserzioni statiche sul sorgente, come test_speechify_frontend_assets.py: nel
progetto non c'e' un runner JS, e questi test difendono la presenza dei
meccanismi, non il loro comportamento a runtime.
"""
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
    assert "personas" in JS
    for cablato in ("audiobook-slow", "grave-narrator", "warm-pro",
                    "neutral-pro", "casual-drawl"):
        assert cablato not in JS, f"carattere cablato nel sorgente: {cablato}"


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


def test_l_anteprima_lascia_il_posto_al_campione():
    assert "voxcpmSampleRow" in JS
    assert "sample_url" in JS
    # Il bottone anteprima non deve restare attivo su una voce VoxCPM: il
    # backend la respinge con 400 (Task 10) e l'utente vedrebbe un errore.
    i = JS.find("function _updatePreviewBtn")
    assert "_isVoxcpmVoiceId" in JS[i:i + 700]
