"""TXT non UTF-8 (02/11/2026): un libro russo in cp1251 letto come latin-1
diventava "Ãîâàðä Ô. Ëàâêðàôò" e la voce russa lo sintetizzava lettera per
lettera, 467 chunk "riusciti" e incomprensibili. La codifica dei TXT e dei
capitoli ABM si riconosce senza rompere i testi latini con qualche accento."""
import json
import zipfile

import pytest

import plain_parsers

decode = plain_parsers.decode_text_bytes

RU = "Говард Ф. Лавкрафт. Морок над Инсмутом. В то утро я проснулся рано, и в окне стоял туман. "
EL = "Ήταν μια φορά κι έναν καιρό ένας βασιλιάς που ζούσε σε ένα μεγάλο παλάτι. "
AR = "كان يا ما كان في قديم الزمان رجل يعيش في المدينة القديمة مع أولاده. "
PL = "Pociąg przyjechał na stację w Łodzi o świcie, a ludzie wysiadali powoli i cicho. "
IT = "Era una sera d'autunno e la città dormiva. Perché no? Più tardi andò via. "
FR = "Étendue nonchalamment sur son lit, elle rêvait à l'été et au château de sa grand-mère. "
ES = "¿Qué hora es? Mañana iremos al río con el niño, dijo la señora. "
DE = "„Wundern Sie sich jedoch nicht“, sagte er – über die Brücke gehen wir später. "


@pytest.mark.parametrize("text, enc", [
    (RU, "cp1251"), (RU, "koi8-r"), (EL, "cp1253"), (AR, "cp1256"),
])
def test_non_latin_codepages_are_recognised(text, enc):
    body = text * 30
    assert decode(body.encode(enc)) == body


@pytest.mark.parametrize("text, enc", [
    (IT, "latin-1"), (FR, "latin-1"), (ES, "latin-1"), (DE, "cp1252"), (PL, "cp1250"),
])
def test_latin_texts_keep_their_accents(text, enc):
    body = text * 30
    assert decode(body.encode(enc)) == body


def test_short_latin_text_is_not_taken_for_another_codepage():
    assert decode("Perché no? Andò via, città.".encode("latin-1")) == "Perché no? Andò via, città."
    # 0x81 non esiste in cp1252: latin-1 come ultimo ripiego
    assert decode(b"caf\xe9 \x81") == "caf\xe9 \x81"


def test_utf8_and_boms():
    assert decode(RU.encode("utf-8")) == RU
    assert decode(b"\xef\xbb\xbf" + IT.encode("utf-8")) == IT
    assert decode(RU.encode("utf-16")) == RU
    assert decode(RU.encode("utf-32")) == RU


def test_parse_txt_reads_cp1251_book(tmp_path):
    p = tmp_path / "morok.txt"
    p.write_bytes((RU * 30).encode("cp1251"))
    info = plain_parsers.parse_txt(str(p))
    text = info.chapters[0].text
    assert "Лавкрафт" in text and "Ã" not in text


def test_parse_abm_chapter_in_cp1251(tmp_path):
    p = tmp_path / "libro.abm"
    manifest = {"format": "audiobook-maker-project", "title": "T", "language": "ru",
                "chapters": [{"index": 1, "title": "Глава 1", "filename": "ch1.txt"}]}
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("chapters/ch1.txt", (RU * 30).encode("cp1251"))
    info, _cover = plain_parsers.parse_abm(str(p))
    assert "Лавкрафт" in info.chapters[0].text
