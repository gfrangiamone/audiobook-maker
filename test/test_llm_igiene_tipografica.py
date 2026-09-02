"""Igiene tipografica dell'output LLM: gli spazi attorno alla punteggiatura.

Il modello riconsegna ogni tanto la virgola attaccata alla parola dopo, dove
l'originale aveva lo spazio (osservato il 2 settembre 2026 nella bibliografia
di «Zebra e altri racconti»: `Garzanti,Danny l'eletto`). Dopo l'LLM nessuno
stadio guardava piu' la tipografia, quindi il difetto arrivava intatto
nell'.abm e al TTS.
"""
import generation_engine as ge


def test_virgola_attaccata_riprende_lo_spazio():
    testo = "Garzanti,Danny l'eletto;Rizzoli,Il libro della luce"
    atteso = "Garzanti, Danny l'eletto; Rizzoli, Il libro della luce"
    assert ge._sanitize_llm_output(testo) == atteso


def test_spazio_di_troppo_prima_della_punteggiatura():
    testo = "Il romanzo , uscito nel 1998 , vinse il premio ."
    atteso = "Il romanzo, uscito nel 1998, vinse il premio."
    assert ge._sanitize_llm_output(testo) == atteso


def test_i_numeri_non_vengono_toccati():
    """Decimali, migliaia e orari hanno una cifra dopo il segno: restano."""
    testo = ("Il biglietto costa 1,50 euro; il libro 280.000 lire, "
             "e la conferenza comincia alle 12:30.")
    assert ge._sanitize_llm_output(testo) == testo


def test_sigle_e_url_restano_intatti():
    """Il punto non e' fra i segni trattati: le sigle puntate sopravvivono."""
    testo = ("Il C.E.O. ha citato http://esempio.it/pagina come fonte, "
             "vedi anche C:\\Archivio.")
    assert ge._sanitize_llm_output(testo) == testo


def test_cinese_e_giapponese_non_prendono_spazi():
    """Chi non spazia le parole usa la punteggiatura a larghezza piena."""
    testo = "他说，这是一本好书。"
    assert ge._sanitize_llm_output(testo) == testo


def test_accenti_e_cirillico_prendono_lo_spazio():
    testo = "Perche,ecco;Ольга,Пётр"
    atteso = "Perche, ecco; Ольга, Пётр"
    assert ge._sanitize_llm_output(testo) == atteso


def test_la_deduplica_resta_al_suo_posto():
    """L'igiene e' l'ultimo passo: non deve disturbare i passi precedenti."""
    testo = "Prima riga,seconda parte.\n\nPrima riga,seconda parte."
    assert ge._sanitize_llm_output(testo) == "Prima riga, seconda parte."
