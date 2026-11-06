"""plain_parsers — parser dei file di testo semplice (TXT) e di progetto (ABM).

Modulo foglia (stdlib + `charset_normalizer` + `book_model`, `text_reflow`,
`secure_archive`). Fino a
F1b (2026-10-10) `parse_txt` e `parse_abm` vivevano in `generation_engine`,
che li riesporta con gli stessi nomi; `audiobook_app` li importa da qui.

Cambio voluto di F1b: anche TXT e ABM passano da
`text_reflow.expand_abbreviations` (le stesse abbreviazioni che EPUB e PDF
espandono in `clean_text_for_tts`), cosi' "ecc." o "Dr." si leggono allo
stesso modo da qualunque formato. Dal 06/11/2026 l'espansione segue la
lingua del libro: l'ABM la dichiara nel manifest, il TXT no e si espande
dopo il rilevamento della lingua in /api/analyze. Il resto della pulizia EPUB/PDF (rumore
di impaginazione, numeri di pagina) non si applica: un TXT scritto a mano o
un ABM gia' ottimizzato non ne hanno bisogno.
"""
import codecs
import json
import zipfile
from pathlib import Path

import charset_normalizer

import text_reflow
from book_model import BookInfo, Chapter
from secure_archive import ZipSafetyError, check_zip_bomb, safe_zip_path


# Codepage a 8 bit di alfabeti non latini: un TXT russo in cp1251 letto come
# latin-1 diventava "Ãîâàðä Ô. Ëàâêðàôò" e la voce russa lo leggeva lettera per
# lettera senza che nessun chunk fallisse (02/11/2026, royallib.com).
_NON_LATIN_CODEPAGES = ("cp1251", "koi8_r", "koi8_u", "cp866", "mac_cyrillic",
                        "iso8859_5", "cp1253", "iso8859_7", "cp1255", "iso8859_8",
                        "cp1256", "iso8859_6", "cp874", "cp1258")
# Quota di byte >= 0x80 fra le lettere oltre la quale il testo non e' una
# lingua latina con qualche accento (francese, polacco, ceco stanno sotto il 20%).
_NON_LATIN_HIGH_RATIO = 0.4
# "ł" e "ą" in cp1250 sono "³" e "¹" in cp1252: in polacco fanno ~3% delle
# lettere, nella prosa occidentale quasi mai.
_CP1250_POLISH_MARKS = ("³", "¹")
_CP1250_POLISH_MIN_RATIO = 0.005


def decode_text_bytes(data):
    """Decodifica il testo di un TXT o di un capitolo ABM.

    UTF-8 (con o senza BOM) e BOM UTF-16/32 prima di tutto; poi, se quasi tutte
    le lettere sono byte alti, una codepage non latina scelta da
    charset_normalizer; altrimenti cp1252 (cp1250 se il testo ha l'aspetto del
    polacco), con latin-1 come ultimo ripiego. charset_normalizer non si usa sui
    testi latini: un italiano in latin-1 lo scambia per cp1250 ("città" -> "cittŕ")."""
    for bom, enc in ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
                     (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            return data.decode(enc, errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    high = sum(1 for b in data if b >= 0x80)
    ascii_letters = sum(1 for b in data if 0x41 <= b <= 0x5A or 0x61 <= b <= 0x7A)
    if high and high / (high + ascii_letters) > _NON_LATIN_HIGH_RATIO:
        best = charset_normalizer.from_bytes(data, cp_isolation=list(_NON_LATIN_CODEPAGES)).best()
        if best is not None:
            return str(best)

    try:
        text = data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")
    letters = sum(1 for ch in text if ch.isalpha())
    marks = sum(text.count(m) for m in _CP1250_POLISH_MARKS)
    if letters and marks / letters > _CP1250_POLISH_MIN_RATIO:
        return data.decode("cp1250", errors="replace")
    return text


def parse_txt(file_path):
    """Parse a plain text file into a one-chapter BookInfo."""
    path = Path(file_path)
    text = decode_text_bytes(path.read_bytes()).strip()
    if not text:
        raise ValueError("Text file is empty")

    # Stesse ricomposizioni di PDF/EPUB: trattini morbidi, parole sillabate a
    # fine riga, e paragrafi spezzati a metà frase se il difetto è sistematico
    # (TXT esportato da PDF con una riga vuota dopo ogni riga stampata).
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text_reflow.dehyphenate_breaks(text_reflow.strip_soft_hyphens(text))
    reflowed = text_reflow.reflow_book([text])
    if reflowed is not None:
        text = reflowed[0]
    # Abbreviazioni: un TXT non dichiara la lingua, si espandono quando
    # /api/analyze la rileva (text_reflow.expand_book_abbreviations).

    # Title = filename without extension
    title = path.stem.replace("_", " ").replace("-", " ").strip() or "Text"
    return BookInfo.from_text(title, "", text)


def parse_abm(file_path):
    """Parse an .abm project file (ZIP with manifest + chapter texts + optional cover).

    Returns (info, cover_info) where info is a BookInfo and cover_info is
    {"data": bytes, "filename": str} or None.
    """
    path = Path(file_path)
    if not zipfile.is_zipfile(str(path)):
        raise ValueError("Invalid .abm file: not a valid ZIP archive")

    with zipfile.ZipFile(str(path), "r") as zf:
        # Zip-bomb / total-size guard PRIMA di leggere qualsiasi cosa
        try:
            check_zip_bomb(zf)
        except ZipSafetyError as e:
            raise ValueError(f"Invalid .abm file: {e}")
        # Read and validate manifest
        try:
            manifest_data = zf.read("manifest.json")
        except KeyError:
            raise ValueError("Invalid .abm file: manifest.json not found")

        try:
            manifest = json.loads(manifest_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid .abm file: malformed manifest.json ({e})")

        if manifest.get("format") != "audiobook-maker-project":
            raise ValueError("Invalid .abm file: unrecognized format in manifest.json")

        title = manifest.get("title", path.stem)
        author = manifest.get("author", "")
        language = manifest.get("language", "")

        # Read chapters in manifest order
        chapters_meta = manifest.get("chapters", [])
        if not chapters_meta:
            raise ValueError("Invalid .abm file: no chapters listed in manifest")

        chapters = []
        for cm in chapters_meta:
            fname = cm.get("filename", "")
            ch_title = cm.get("title", f"Chapter {cm.get('index', '?')}")
            ch_index = cm.get("index", len(chapters) + 1)

            raw_path = f"chapters/{fname}" if not fname.startswith("chapters/") else fname
            try:
                # Zip-slip: rifiuta path che escono dalla virtual root "chapters/"
                ch_path = safe_zip_path(raw_path, base="chapters")
            except ZipSafetyError as e:
                print(f"[abm] WARNING: skipping unsafe chapter path '{raw_path}': {e}")
                continue
            try:
                ch_text = decode_text_bytes(zf.read(ch_path)).strip()
            except KeyError:
                print(f"[abm] WARNING: chapter file '{ch_path}' not found in archive, skipping")
                continue

            if not ch_text:
                continue

            chapters.append(Chapter(index=ch_index, title=ch_title,
                                    text=text_reflow.expand_abbreviations(ch_text, language)))

        if not chapters:
            raise ValueError("Invalid .abm file: no readable chapter content found")

        info = BookInfo(title=title, author=author, language=language, chapters=chapters).recompute_totals()

        # Extract cover if present
        cover_info = None
        if manifest.get("has_cover") and manifest.get("cover_file"):
            cover_file_raw = manifest["cover_file"]
            try:
                cover_file = safe_zip_path(cover_file_raw)
            except ZipSafetyError as e:
                print(f"[abm] WARNING: skipping unsafe cover path '{cover_file_raw}': {e}")
                cover_file = None
            if cover_file:
                try:
                    cover_data = zf.read(cover_file)
                    if len(cover_data) > 100:  # sanity check
                        cover_info = {"data": cover_data, "filename": cover_file}
                except KeyError:
                    pass

    return info, cover_info
