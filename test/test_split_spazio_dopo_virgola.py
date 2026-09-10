# -*- coding: utf-8 -*-
"""Lo spazio dopo la virgola sopravvive alla spezzatura delle frasi lunghe.

Osservato il 2 settembre 2026 su «Zebra e altri racconti»: la bibliografia e'
una frase sola di 500 caratteri, e al TTS arrivava come «tra cui,pubblicati da
Garzanti,Danny l'eletto (1983),La scelta di Reuven (1987)» mentre il testo
ottimizzato aveva gli spazi al posto giusto. La colpa non era del modello: il
breakpoint debole `(?<=[,;:])\\s+` consuma lo spazio che segue la virgola, e i
pezzi venivano riattaccati senza restituirlo.

Solo le frasi oltre il tetto passano di li', quindi il difetto si vedeva
soltanto nei periodi lunghi: elenchi, bibliografie, didascalie.
"""
from tts_split import split_text_into_chunks

MAX = 300

# Una frase sola, senza terminatori interni, oltre il tetto: l'unico caso in
# cui la spezzatura debole entra in gioco.
ELENCO = ("Chaim Potok e' autore di numerosi romanzi tra cui, pubblicati da "
          "Garzanti, Danny l'eletto, La scelta di Reuven, L'arpa di Davita, "
          "Il mio nome e' Asher Lev, Il dono di Asher Lev, Io sono l'argilla, "
          "Il maestro della guerra, Novembre alle porte, In principio, e "
          "altri titoli ancora che portano la frase oltre il tetto.")


def _attaccate(testo):
    """Virgola, punto e virgola o due punti seguiti subito da una lettera."""
    return [testo[i - 12:i + 12] for i in range(1, len(testo))
            if testo[i - 1] in ",;:" and testo[i].isalpha()]


def test_la_virgola_tiene_il_suo_spazio_nelle_frasi_lunghe():
    for chunk in split_text_into_chunks(ELENCO, MAX):
        assert not _attaccate(chunk), chunk


def test_le_frasi_corte_non_cambiano():
    corta = "Uno, due, tre, quattro."
    assert split_text_into_chunks(corta, MAX) == [corta]


def test_il_tetto_regge_con_lo_spazio_in_piu():
    """Lo spazio restituito conta nei caratteri: nessun chunk deve sforare."""
    for chunk in split_text_into_chunks(ELENCO, MAX):
        assert len(chunk) <= MAX


def test_nessuna_parola_si_perde():
    ricomposto = " ".join(split_text_into_chunks(ELENCO, MAX))
    assert ricomposto.split() == ELENCO.split()


def test_il_cinese_non_prende_spazi():
    """Il breakpoint CJK e' a larghezza zero: non c'era spazio da restituire."""
    cinese = "他说，" + "这是一本很好的书，" * 30 + "值得一读。"
    for chunk in split_text_into_chunks(cinese, MAX):
        assert " " not in chunk, chunk
