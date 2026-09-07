"""Un PDF di sole immagini non deve produrre un errore in italiano.

Incidente 07/09/2026: un utente pakistano converte delle JPEG in PDF, lo carica
e riceve "PDF parse error: Nessun contenuto testuale trovato nel PDF" — messaggio
grezzo del parser, in italiano, senza dirgli cosa fare. Ora il backend risponde
col codice stabile `pdf_no_text` e il frontend lo traduce (chiave err_pdf_no_text,
presente in tutte e 7 le lingue) spiegando la via d'uscita: passare da un OCR.
"""
import pathlib
import re

import pytest

fitz = pytest.importorskip("fitz")

from pdf_to_tts import parse_pdf


def _image_only_pdf(path):
    """PDF con una pagina senza alcun testo (equivalente a una scansione)."""
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(50, 50, 300, 400), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    doc.save(str(path))
    doc.close()
    return path


def test_parse_pdf_raises_recognisable_code(tmp_path):
    pdf = _image_only_pdf(tmp_path / "scan.pdf")
    with pytest.raises(ValueError) as ei:
        parse_pdf(str(pdf))
    msg = str(ei.value)
    assert "pdf_no_text" in msg, "manca il codice che /api/analyze intercetta"
    assert "Nessun" not in msg, "fallback ancora in italiano"


def test_analyze_maps_the_code(tmp_path):
    """/api/analyze non deve rigirare l'eccezione grezza all'utente."""
    src = pathlib.Path("audiobook_app.py").read_text(encoding="utf-8")
    i = src.index('label = "ABM" if is_abm')
    block = src[i:i + 700]
    assert '"pdf_no_text" in str(e)' in block
    assert '{"error": "pdf_no_text"}' in block


def test_frontend_localises_the_code():
    js = pathlib.Path("static/js/app.js").read_text(encoding="utf-8")
    assert "d.error==='pdf_no_text'" in js
    assert "t('err_pdf_no_text')" in js


def test_message_present_in_all_seven_languages():
    data = pathlib.Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    found = re.findall(r'err_pdf_no_text:"([^"]*)"', data)
    assert len(found) == 7, f"chiave presente in {len(found)} lingue su 7"
    assert all(len(m) > 40 for m in found), "traduzione vuota o troncata"
    # Nessuna lingua deve aver ereditato il testo di un'altra.
    assert len(set(found)) == 7, "due lingue condividono lo stesso testo"


def test_no_italian_left_in_pdf_parser_user_errors():
    src = pathlib.Path("pdf_to_tts.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if "raise ValueError(" in line or "raise FileNotFoundError(" in line:
            assert "Nessun" not in line and "vuoto" not in line and "non trovato" not in line, \
                f"messaggio utente ancora in italiano: {line.strip()}"
