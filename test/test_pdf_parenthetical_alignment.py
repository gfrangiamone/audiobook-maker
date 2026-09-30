"""Il testo tra parentesi di un PDF segue l'opzione dell'utente, come EPUB e TXT.

`_clean_pdf_text` non deve piu' cancellare in modo incondizionato il contenuto
tra () e []: la rimozione avviene a valle in `_strip_parenthetical`, secondo
`read_round_parens` / `read_square_brackets`. Restano tolte solo le note
bibliografiche ([12], [a], (see ...)), come per l'EPUB.
"""
import pdf_to_tts as P
from tts_split import prepare_tts_text


LITRPG = ("[All of your past achievements have satisfied a hidden condition.]\n"
          "Lloyd read the message (Relationship Point) twice.")


def test_pdf_clean_keeps_parenthetical_content():
    out = P._clean_pdf_text(LITRPG)
    assert "[All of your past achievements" in out
    assert "(Relationship Point)" in out


def test_pdf_clean_still_drops_note_markers():
    out = P.clean_text_for_tts(P._clean_pdf_text("A claim[12] was made (see Fig. 3) here."))
    assert "[12]" not in out
    assert "Fig" not in out


def test_user_option_decides_downstream():
    cleaned = P._clean_pdf_text(LITRPG)
    kept = prepare_tts_text(cleaned, strip_round=False, strip_square=False)
    assert "hidden condition" in kept and "Relationship Point" in kept
    stripped = prepare_tts_text(cleaned)
    assert "hidden condition" not in stripped and "Relationship Point" not in stripped
