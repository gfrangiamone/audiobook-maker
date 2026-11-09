"""EPUB di Wikisource in francese (ws-export): lettrine, apici delle
abbreviazioni, spazi tipografici e titoli a piu' righe. I classici francesi
del catalogo gratuito (09/11/2026) si leggevano "N ous étions", "e n'est pas",
"MBovary", "IILE PÈRE ET LE FILS" e perdevano il punto di ogni domanda."""
import epub_to_tts as E


def _text(body):
    return " ".join(E.html_to_text(f"<html><body>{body}</body></html>").split())


def test_lettrine_di_testo_si_unisce_al_maiuscoletto():
    body = ('<p><span class="lettrine" style="display:block"><br/></span>'
            '<span class="dropinitial" style="display: block; float: left">N </span>'
            '<span class="sc">ous</span> étions à l’étude.</p>')
    assert _text(body) == "Nous étions à l’étude."


def test_lettrine_seguita_da_un_altra_parola_resta_staccata():
    body = '<p><span class="dropinitial">À </span> peine arrivé chez lui.</p>'
    assert _text(body) == "À peine arrivé chez lui."


def test_lettrine_con_apostrofo():
    body = '<p><span class="dropinitial">D </span>’<span class="sc">abord</span>, il ne savait.</p>'
    assert _text(body) == "D’abord, il ne savait."


def test_lettrine_in_immagine_si_legge_dall_alt():
    body = ('<p><span class="dropinitial" style="float: left"><span typeof="mw:File"><a href="x">'
            '<img src="c.jpg" alt="C"/></a></span> </span><span class="sc">e</span> n’est pas sans émotion.</p>')
    assert _text(body) == "Ce n’est pas sans émotion."


def test_lettrine_illustrata_senza_classe():
    body = ('<p><span style="float:left"><span typeof="mw:File"><a href="x"><img src="t.png" alt="lettrine T"/>'
            '</a></span></span> <span class="sc">rois</span> jours après.</p>')
    assert _text(body) == "Trois jours après."


def test_immagine_con_alt_di_una_lettera_fuori_da_una_parola_non_si_legge():
    assert _text('<p><img src="a.png" alt="A"/> Le jardin.</p>') == "Le jardin."


def test_abbreviazione_con_apice_si_legge_per_esteso():
    body = ('<p>Au mois de mars, <abbr class="abbr" title="Madame">M<sup style="font-size:70%;">me</sup></abbr>'
            '<span typeof="mw:Entity"> </span>Bovary était enceinte.</p>')
    assert _text(body) == "Au mois de mars, Madame Bovary était enceinte."


def test_suffissi_in_apice_restano_le_note_no():
    body = ('<p>De M<sup>me</sup> Bonacieux, au XIX<sup>e</sup> siècle, le 1<sup>er</sup> octobre'
            '<sup class="mw-ref reference"><a href="#cite_note-1">1</a></sup>, un mot<sup>a</sup>.</p>')
    assert _text(body) == "De Mme Bonacieux, au XIXe siècle, le 1er octobre, un mot."


def test_apice_o_dopo_un_numero_e_il_segno_di_ordinale():
    assert _text("<p>1<sup>o</sup> Il faut partir; N<sup>o</sup> 5.</p>") == "1° Il faut partir; N° 5."


def test_spazio_fra_elementi_in_linea_resta():
    body = '<p>Ils forment 42<span typeof="mw:Entity"> </span>feuillets <i>in</i> <i>quarto</i>.</p>'
    assert _text(body) == "Ils forment 42 feuillets in quarto."


def test_titolo_su_piu_blocchi_non_si_incolla():
    assert _text('<h3> II<div style="padding-bottom: 1.6em;"> </div>'
                 '<span>LE PÈRE ET LE FILS.</span></h3>') == "II. LE PÈRE ET LE FILS."
    assert _text("<h4> I<br/><br/>DE CHARYBDE EN SCYLLA</h4>") == "I. DE CHARYBDE EN SCYLLA"
    assert _text("<h3>OÙ L’ON COMMENCE À<br/>NE PAS COMPRENDRE</h3>") == "OÙ L’ON COMMENCE À NE PAS COMPRENDRE"


def test_domanda_con_spazio_fine_tiene_il_punto():
    text = E.clean_text_for_tts("Qui est à bord ? Il dit « Faust » ? En 1830 ?", lang="fr")
    assert text.count("?") == 3 and "bord?" in text and '"Faust"?' in text


def test_virgolette_tedesche_tengono_gli_spazi():
    text = E.clean_text_for_tts("»Nun,« sagte ich, »wenn es sein muß.«", lang="de")
    assert '"Nun," sagte ich, "wenn' in text


def test_puntini_e_domanda_restano_domanda():
    text = E.clean_text_for_tts("¿Qué… ? Nada… Bien!!! Mais… ! Aiuto!... ladri!...", lang="es")
    assert "??" not in text and "¿Qué?" in text and "Nada.." in text and "Bien!!" in text and "Mais!" in text
    assert "Aiuto!.. ladri!.." in text


def test_domanda_in_cirillico_tiene_il_punto():
    assert "что?" in E.clean_text_for_tts("Это что? Да.", lang="ru")


def test_residui_di_istruzioni_di_pagina_restano_fuori():
    assert "?" not in E.clean_text_for_tts('Una riga ?dp n="28" folio="22" ? qui. Altro ?? testo.', lang="it")


def test_asterischi_dei_nomi_taciuti_non_si_leggono():
    text = E.clean_text_for_tts("Chez la duchesse de *** ; et Mme de B*** a résisté.", lang="fr")
    assert "*" not in text and "duchesse de;" in text and "de B a résisté" in text
