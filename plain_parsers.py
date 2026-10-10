"""plain_parsers — parser dei file di testo semplice (TXT) e di progetto (ABM).

Modulo foglia (stdlib + `book_model`, `text_reflow`, `secure_archive`). Fino a
F1b (2026-10-10) `parse_txt` e `parse_abm` vivevano in `generation_engine`,
che li riesporta con gli stessi nomi; `audiobook_app` li importa da qui.

Cambio voluto di F1b: anche TXT e ABM passano da
`text_reflow.expand_abbreviations` (le stesse abbreviazioni che EPUB e PDF
espandono in `clean_text_for_tts`), cosi' "ecc." o "Dr." si leggono allo
stesso modo da qualunque formato. Il resto della pulizia EPUB/PDF (rumore
di impaginazione, numeri di pagina) non si applica: un TXT scritto a mano o
un ABM gia' ottimizzato non ne hanno bisogno.
"""
import json
import zipfile
from pathlib import Path

import text_reflow
from book_model import BookInfo, Chapter
from secure_archive import ZipSafetyError, check_zip_bomb, safe_zip_path


def parse_txt(file_path):
    """Parse a plain text file into a one-chapter BookInfo."""
    path = Path(file_path)
    # Try UTF-8 first, fall back to latin-1
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        text = path.read_text(encoding="latin-1", errors="replace")

    text = text.strip()
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
    text = text_reflow.expand_abbreviations(text)

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
                ch_text = zf.read(ch_path).decode("utf-8").strip()
            except KeyError:
                print(f"[abm] WARNING: chapter file '{ch_path}' not found in archive, skipping")
                continue
            except UnicodeDecodeError:
                ch_text = zf.read(ch_path).decode("latin-1", errors="replace").strip()

            if not ch_text:
                continue

            chapters.append(Chapter(index=ch_index, title=ch_title,
                                    text=text_reflow.expand_abbreviations(ch_text)))

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
