# -*- coding: utf-8 -*-
"""La quarta di copertina e il frontespizio non finiscono nell'audiolibro.

Osservato il 2 settembre 2026 su «Zebra e altri racconti»: l'EPUB apre con
due sezioni di apparato che il filtro lasciava passare.

  [0] titolo generico, 210 char: frontespizio piu' colophon. I segnali di
      colophon cercavano «all rights reserved» e «©» ma non la parola
      «copyright» scritta per esteso, che e' la forma di quasi tutti gli
      EPUB italiani.
  [1] titolo «Trama», 1203 char: sinossi, nota bibliografica sull'autore e
      dedica. La famiglia della quarta di copertina non era in lista.

La seconda e' anche quella su cui il TTS degenerava: 276 caratteri di
elenco di titoli e date, che il modello recitava come fonemi. Toglierla
dalla lettura e' la cura giusta a monte — un audiolibro non legge la
quarta di copertina.
"""
import epub_to_tts
import pdf_to_tts

# Le due sezioni come arrivano dall'EPUB reale, accorciate ma con i
# segnali intatti.
FRONTESPIZIO = (
    "Chaim Potok\n\nZebra e altri racconti\n\n"
    "Titolo originale: Zebra and Other Stories\n\n"
    "Traduzione dall'inglese di Laura Noulian gli elefanti\n\n"
    "Copyright 1998 by Chaim Potok\n\n"
    "Copyright 1999, 2002 Garzanti Libri s. p. a."
)

TRAMA = (
    "Zebra racconta l'\"eta' difficile\" di sei adolescenti colti in un "
    "momento di crisi. Zebra, ovvero Adam Martin Zebrin, e' un ragazzo che "
    "per un incidente ha perso una mano. Moon si confronta con uno "
    "sfortunato coetaneo pakistano. Chaim Potok (New York 1929) e' autore "
    "di numerosi romanzi tra cui, pubblicati da Garzanti, Danny l'eletto "
    "(1983), La scelta di Reuven (1987), L'arpa di Davita (1989)."
)

# Prosa narrativa oltre le soglie di lunghezza di is_content_chapter.
NARRATIVA = (
    "Si chiamava Adam Martin Zebrin, ma tutti nel quartiere lo conoscevano "
    "col nome di Zebra. Non ricordava quando avessero cominciato a "
    "chiamarlo cosi'. Forse quando lui aveva cominciato a correre, o forse "
    "comincio' a correre quando loro cominciarono a chiamarlo Zebra."
)


def test_la_trama_non_va_letta():
    assert epub_to_tts.is_content_chapter(TRAMA, "Trama") is False


def test_il_frontespizio_col_copyright_non_va_letto():
    """Titolo generico: a scartarlo devono bastare i segnali nel testo."""
    assert epub_to_tts.is_content_chapter(FRONTESPIZIO, "Sezione 1") is False


def test_le_altre_forme_della_quarta():
    for titolo in ("Sinossi", "Quarta di copertina", "Risvolto di copertina",
                   "Back cover", "Synopsis", "Klappentext",
                   "Quatrieme de couverture", "Contraportada"):
        assert epub_to_tts._is_title_content(titolo) is False, titolo


def test_il_pdf_usa_le_stesse_parole():
    for titolo in ("Trama", "Quarta di copertina", "Back cover"):
        assert epub_to_tts._title_is_non_content(
            titolo, pdf_to_tts.NON_CONTENT_TITLES) is True, titolo


def test_il_racconto_resta():
    assert epub_to_tts.is_content_chapter(NARRATIVA, "ZEBRA") is True


def test_trama_dentro_un_titolo_vero_non_scarta():
    """«Trama» e' ambiguo: vale come titolo intero, non come parola.

    Un romanzo puo' intitolare un capitolo «La trama del destino»: quello
    e' contenuto, e il match esatto lo lascia passare.
    """
    for titolo in ("La trama del destino", "Sinossi dei Vangeli",
                   "Trama e ordito"):
        assert epub_to_tts._is_title_content(titolo) is True, titolo


def test_il_colophon_non_scarta_la_narrativa():
    """Una parola sola non basta: i segnali richiesti restano due."""
    quasi = ("Il notaio lesse il titolo originale dell'atto, poi ripiego' "
             "il foglio e lo ripose nella cartella di cuoio consumato che "
             "teneva sempre accanto a se' durante le lunghe udienze "
             "invernali del tribunale di provincia.")
    assert epub_to_tts.is_content_chapter(quasi, "Il notaio") is True
