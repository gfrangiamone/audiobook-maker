"""
audio_utils.py — Utility audio indipendenti per Audiobook Maker.

Funzioni:
  - Estrazione copertina da EPUB (con e senza Pillow)
  - Generazione copertina fallback (Pillow)
  - Inclusione copertina nel ZIP
  - Preparazione cover 1400x1400 per M4B (EPUB hi-res → thumb → branded fallback)
  - Generazione silenzio MP3 (ffmpeg o fallback binario)
  - Concatenazione MP3 (ffmpeg o fallback binario)
  - Durata audio in ms (ffprobe)
  - Bitrate audio in kbps (ffprobe, fallback 48 kbps = default edge-tts)
  - Normalizzazione codice lingua ISO 639-1 → 639-2/B, estrazione anno da dc:date
  - Conversione MP3 → M4B con capitoli, copertina e metadati completi
    (title/album/artist/album_artist/date/genre/language/comment/media_type=2)
  - Generazione RSS podcast iTunes/PSP-1
  - Sanitizzazione nome file

Nessuna dipendenza da altri moduli del progetto.
"""

import os
import shutil
import sys
import uuid

# Windows: evita che ffmpeg/ffprobe apra finestre console nascoste
_SUBPROCESS_FLAGS = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def _check_audio_dependencies():
    """Verifica la presenza di ffmpeg e ffprobe nel PATH di sistema.
    
    Ritorna una tupla (ffmpeg_ok, ffprobe_ok).
    """
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None
    return ffmpeg_ok, ffprobe_ok


# ---------------------------------------------------------------------------
# ZIP / EPUB helpers
# ---------------------------------------------------------------------------

def _zip_safe_read(zf, path):
    """Read a file from a ZipFile, handling path separator mismatches.

    ZIP entries always use forward slashes, but OPF href or os.path.join
    may produce backslashes on Windows. Tries: exact path → normalized →
    basename match.
    """
    if path in zf.namelist():
        return zf.read(path)
    normalized = path.replace("\\", "/")
    if normalized in zf.namelist():
        return zf.read(normalized)
    target = os.path.basename(normalized).lower()
    for entry in zf.namelist():
        if os.path.basename(entry).lower() == target:
            return zf.read(entry)
    raise KeyError(f"No item matching '{path}' in archive")


def _extract_cover_from_epub(epub_path, output_path, target_size=1400):
    """Extract cover image from EPUB and resize to square for iTunes compliance.

    Tries: OPF metadata cover -> common filenames -> first large image.
    Returns output_path on success, None on failure.
    Requires Pillow.
    """
    import zipfile
    import io
    import xml.etree.ElementTree as ET

    try:
        from PIL import Image
    except ImportError:
        return None

    def _find_cover_in_opf(zf):
        opf_path = None
        try:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile = container.find(".//c:rootfile", ns)
            if rootfile is not None:
                opf_path = rootfile.get("full-path")
        except (KeyError, ET.ParseError):
            pass
        if not opf_path:
            for n in zf.namelist():
                if n.endswith(".opf"):
                    opf_path = n
                    break
        if not opf_path:
            return None
        try:
            opf = ET.fromstring(zf.read(opf_path))
        except (KeyError, ET.ParseError):
            return None
        opf_dir = os.path.dirname(opf_path)
        cover_id = None
        for meta in opf.iter():
            if meta.tag.endswith("}meta") or meta.tag == "meta":
                if meta.get("name") == "cover":
                    cover_id = meta.get("content")
                    break
        manifest_items = {}
        for item in opf.iter():
            if item.tag.endswith("}item") or item.tag == "item":
                item_id = item.get("id", "")
                href = item.get("href", "")
                props = item.get("properties", "")
                mt = item.get("media-type", "")
                manifest_items[item_id] = (href, mt, props)
        for item_id, (href, mt, props) in manifest_items.items():
            if "cover-image" in props and mt.startswith("image/"):
                return (opf_dir + '/' + href).replace('\\', '/') if opf_dir else href
        if cover_id and cover_id in manifest_items:
            href, mt, _ = manifest_items[cover_id]
            if mt.startswith("image/"):
                return (opf_dir + '/' + href).replace('\\', '/') if opf_dir else href
        return None

    def _find_cover_by_name(zf):
        for n in zf.namelist():
            base = os.path.basename(n).lower()
            if base in ("cover.jpg", "cover.jpeg", "cover.png",
                        "cover-image.jpg", "cover-image.png"):
                return n
        return None

    def _find_largest_image(zf):
        best, best_size = None, 0
        for n in zf.namelist():
            low = n.lower()
            if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                sz = zf.getinfo(n).file_size
                if sz > best_size:
                    best, best_size = n, sz
        return best if best_size > 5000 else None

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            img_path = (_find_cover_in_opf(zf)
                        or _find_cover_by_name(zf)
                        or _find_largest_image(zf))
            if not img_path:
                return None
            img_data = _zip_safe_read(zf, img_path)

        img = Image.open(io.BytesIO(img_data))
        img = img.convert("RGB")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((target_size, target_size), Image.LANCZOS)
        img.save(output_path, "JPEG", quality=85)
        return output_path
    except Exception:
        return None


def _generate_fallback_cover(output_path, title="", author="", target_size=1400):
    """Generate a simple branded cover when no EPUB cover is available."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    try:
        sz = target_size
        img = Image.new("RGB", (sz, sz), (245, 240, 232))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, sz, int(sz * 0.38)], fill=(194, 154, 108))

        font_title = font_author = font_small = None
        for fpath in ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                      "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
                      "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/arial.ttf"]:
            if os.path.exists(fpath):
                font_title = ImageFont.truetype(fpath, sz // 14)
                font_author = ImageFont.truetype(fpath, sz // 22)
                font_small = ImageFont.truetype(fpath, sz // 32)
                break
        if not font_title:
            font_title = font_author = font_small = ImageFont.load_default()

        def _wrap(text, font, max_w):
            words, lines, cur = text.split(), [], ""
            for w in words:
                test = f"{cur} {w}".strip()
                if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
            return lines or [text]

        margin = int(sz * 0.1)
        max_w = sz - margin * 2
        y = int(sz * 0.42)
        for line in _wrap(title or "Audiobook", font_title, max_w):
            bbox = draw.textbbox((0, 0), line, font=font_title)
            draw.text(((sz - bbox[2] + bbox[0]) // 2, y), line,
                      fill=(60, 50, 40), font=font_title)
            y += int((bbox[3] - bbox[1]) * 1.3)

        if author:
            y += int(sz * 0.03)
            for line in _wrap(author, font_author, max_w):
                bbox = draw.textbbox((0, 0), line, font=font_author)
                draw.text(((sz - bbox[2] + bbox[0]) // 2, y), line,
                          fill=(120, 100, 80), font=font_author)
                y += int((bbox[3] - bbox[1]) * 1.3)

        label = "Audiobook Maker"
        bbox = draw.textbbox((0, 0), label, font=font_small)
        draw.text(((sz - bbox[2] + bbox[0]) // 2, sz - int(sz * 0.08)),
                  label, fill=(180, 165, 145), font=font_small)
        img.save(output_path, "JPEG", quality=85)
        return output_path
    except Exception:
        return None


def _extract_cover_for_preview(epub_path, output_dir):
    """Extract cover image from EPUB for UI preview. Works with or without Pillow.

    Returns (output_path, mime_type) on success, (None, None) on failure.
    - With Pillow: resizes to 400px thumbnail JPEG
    - Without Pillow: extracts raw image bytes as-is
    """
    import zipfile
    import xml.etree.ElementTree as ET

    def _find_cover_path_in_zip(zf):
        opf_path = None
        try:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile = container.find(".//c:rootfile", ns)
            if rootfile is not None:
                opf_path = rootfile.get("full-path")
        except (KeyError, ET.ParseError):
            pass
        if not opf_path:
            for n in zf.namelist():
                if n.endswith(".opf"):
                    opf_path = n
                    break
        if opf_path:
            try:
                opf = ET.fromstring(zf.read(opf_path))
                opf_dir = os.path.dirname(opf_path)
                cover_id = None
                for meta in opf.iter():
                    tag = meta.tag.split("}")[-1] if "}" in meta.tag else meta.tag
                    if tag == "meta" and meta.get("name") == "cover":
                        cover_id = meta.get("content")
                        break
                manifest = {}
                for item in opf.iter():
                    tag = item.tag.split("}")[-1] if "}" in item.tag else item.tag
                    if tag == "item":
                        manifest[item.get("id", "")] = (
                            item.get("href", ""), item.get("media-type", ""),
                            item.get("properties", ""))
                for iid, (href, mt, props) in manifest.items():
                    if "cover-image" in props and mt.startswith("image/"):
                        return (opf_dir + '/' + href).replace('\\', '/') if opf_dir else href
                if cover_id and cover_id in manifest:
                    href, mt, _ = manifest[cover_id]
                    if mt.startswith("image/"):
                        return (opf_dir + '/' + href).replace('\\', '/') if opf_dir else href
            except (KeyError, ET.ParseError):
                pass

        for n in zf.namelist():
            base = os.path.basename(n).lower()
            if base in ("cover.jpg", "cover.jpeg", "cover.png",
                        "cover-image.jpg", "cover-image.png"):
                return n

        best, best_size = None, 0
        for n in zf.namelist():
            low = n.lower()
            if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                sz = zf.getinfo(n).file_size
                if sz > best_size:
                    best, best_size = n, sz
        return best if best_size > 5000 else None

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            img_zip_path = _find_cover_path_in_zip(zf)
            if not img_zip_path:
                print(f"[cover] No cover image found in {os.path.basename(epub_path)}")
                return None, None
            img_data = _zip_safe_read(zf, img_zip_path)
            print(f"[cover] Found: {img_zip_path} ({len(img_data)} bytes)")
    except Exception as e:
        print(f"[cover] ZIP read error: {e}")
        return None, None

    is_png = img_data[:8] == b'\x89PNG\r\n\x1a\n'
    mime = "image/png" if is_png else "image/jpeg"
    ext = ".png" if is_png else ".jpg"

    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_data))
        img = img.convert("RGB")
        img.thumbnail((400, 600), Image.LANCZOS)
        out_path = os.path.join(output_dir, "cover_thumb.jpg")
        img.save(out_path, "JPEG", quality=85)
        print(f"[cover] Thumbnail saved with Pillow: {os.path.getsize(out_path)} bytes")
        return out_path, "image/jpeg"
    except ImportError:
        print("[cover] Pillow not available, using raw image")
    except Exception as e:
        print(f"[cover] Pillow resize failed: {e}, using raw image")

    out_path = os.path.join(output_dir, "cover_thumb" + ext)
    with open(out_path, "wb") as f:
        f.write(img_data)
    print(f"[cover] Raw image saved: {out_path} ({len(img_data)} bytes)")
    return out_path, mime


def _include_cover_in_dir(job, target_dir):
    """Copy book cover image into target_dir so it gets included in the ZIP.

    Tries the cover_thumb extracted during analysis first; if not available,
    attempts extraction from the source EPUB/ABM file.
    """
    try:
        cover_src = job.get("cover_thumb", "")
        if cover_src and os.path.exists(cover_src):
            ext = os.path.splitext(cover_src)[1] or ".jpg"
            dest = os.path.join(str(target_dir), f"cover{ext}")
            shutil.copy2(cover_src, dest)
            print(f"[zip-cover] Included cover from thumb: {dest}")
            return True

        epub_path = job.get("epub_path", "")
        if epub_path and os.path.exists(epub_path):
            dest = os.path.join(str(target_dir), "cover.jpg")
            if _extract_cover_from_epub(epub_path, dest, target_size=1400):
                print(f"[zip-cover] Included cover extracted from EPUB: {dest}")
                return True
            raw_path, _ = _extract_cover_for_preview(epub_path, str(target_dir))
            if raw_path and os.path.exists(raw_path):
                raw_ext = os.path.splitext(raw_path)[1] or ".jpg"
                final = os.path.join(str(target_dir), f"cover{raw_ext}")
                if raw_path != final:
                    shutil.copy2(raw_path, final)
                    os.remove(raw_path)
                print(f"[zip-cover] Included cover (raw) from EPUB: {final}")
                return True
    except Exception as e:
        print(f"[zip-cover] Could not include cover: {e}")
    return False


# ---------------------------------------------------------------------------
# Silence & MP3 concatenation
# ---------------------------------------------------------------------------

def _generate_silence_mp3(output_path, duration_sec=3):
    """Genera un file MP3 di silenzio della durata specificata."""
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"anullsrc=r=24000:cl=mono",
             "-t", str(duration_sec), "-c:a", "libmp3lame",
             "-b:a", "48k", "-q:a", "9", output_path],
            capture_output=True, text=True, **_SUBPROCESS_FLAGS
        )
        if result.returncode == 0 and os.path.exists(output_path):
            return True
    except (FileNotFoundError, OSError):
        pass
    # Fallback: silenzio MP3 minimo (frame MPEG1 Layer3 32kbps mono @ 24000Hz)
    # 1 frame = 1152 samples → ~48ms → ~21 frame/s → n_frames per duration_sec
    frame_header = b'\xff\xf3\x90\x04'
    frame_body = b'\x00' * 413
    frame = frame_header + frame_body
    n_frames = int(duration_sec * 24000 / 1152) + 1
    with open(output_path, 'wb') as f:
        for _ in range(n_frames):
            f.write(frame)
    return os.path.exists(output_path)


def _concatenate_mp3(parts, output):
    """Concatena una lista di file MP3 in un singolo file output."""
    try:
        import subprocess
        list_file = output + ".filelist.txt"
        with open(list_file, "w") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_file, "-c", "copy", output],
            capture_output=True, text=True, **_SUBPROCESS_FLAGS
        )
        os.remove(list_file)
        if result.returncode == 0:
            return
    except (FileNotFoundError, OSError):
        pass
    with open(output, "wb") as outf:
        for p in parts:
            with open(p, "rb") as inf:
                outf.write(inf.read())


def _get_audio_duration_ms(file_path):
    """Restituisce la durata del file audio in millisecondi usando ffprobe."""
    try:
        import subprocess
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, **_SUBPROCESS_FLAGS)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip()) * 1000
    except Exception as e:
        print(f"[_get_audio_duration_ms] Error reading {file_path}: {e}")
    return 0


def _get_audio_bitrate(file_path):
    """Restituisce il bitrate del file audio in kbps usando ffprobe.

    Usato per adattare il bitrate AAC del file M4B a quello dell'MP3 sorgente,
    evitando che il file M4B risulti più grande della somma degli MP3 originali.
    edge-tts genera MP3 a 48kbps (audio-24khz-48kbitrate-mono-mp3) per default.
    Fallback: 48 kbps.
    """
    try:
        import subprocess
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, **_SUBPROCESS_FLAGS)
        if result.returncode == 0 and result.stdout.strip():
            bps = int(float(result.stdout.strip()))
            # Converti bps → kbps, clampa a range ragionevole [32, 320]
            kbps = max(32, min(320, round(bps / 1000)))
            print(f"[_get_audio_bitrate] {os.path.basename(file_path)}: {bps} bps → {kbps} kbps")
            return kbps
    except Exception as e:
        print(f"[_get_audio_bitrate] Error reading {file_path}: {e}")
    # Fallback: default edge-tts (audio-24khz-48kbitrate-mono-mp3)
    return 48


def _validate_m4b_file(file_path):
    """Verifica l'integrità di un file M4B generato.

    Un ffmpeg uscito con returncode=0 non garantisce che il file sia decodificabile:
    casi rari (disk pressure, OOM, buffer flush parziale, fallback cover non pulito)
    possono lasciare un container MP4 troncato o senza stream audio valido.

    Questa validazione usa ffprobe per verificare:
      1. Il file è parsabile come MP4/M4B (format_name contiene 'mp4' / 'm4a' / 'ipod')
      2. Esiste almeno uno stream audio (codec_type=audio)
      3. La durata del file è > 0

    Se ffprobe non è disponibile, la validazione viene saltata (ritorna True per
    non spezzare sistemi senza ffprobe — il controllo di returncode resta comunque).

    Ritorna True se il file è valido o non validabile, False se corrotto.
    """
    if not file_path or not os.path.exists(file_path):
        return False
    if os.path.getsize(file_path) < 1024:
        # File troppo piccolo per essere un M4B valido
        print(f"[_validate_m4b_file] file troppo piccolo: {os.path.getsize(file_path)} bytes")
        return False
    try:
        import subprocess
        # Show format + streams in un'unica chiamata
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=format_name,duration:stream=codec_type,codec_name",
            "-of", "default=noprint_wrappers=1",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, **_SUBPROCESS_FLAGS)
        if result.returncode != 0:
            print(f"[_validate_m4b_file] ffprobe rc={result.returncode}: "
                  f"{result.stderr[-300:] if result.stderr else '(no output)'}")
            return False
        out = (result.stdout or "").lower()
        # Container MP4/M4B valido (ffprobe lo etichetta 'mov,mp4,m4a,3gp,3g2,mj2')
        has_mp4 = ("mp4" in out) or ("m4a" in out) or ("ipod" in out) or ("mov" in out)
        has_audio = "codec_type=audio" in out
        # Durata > 0 (accettiamo anche assenza, alcuni file M4B possono non esporla)
        duration_ok = True
        for line in out.splitlines():
            if line.startswith("duration="):
                val = line.split("=", 1)[1].strip()
                try:
                    duration_ok = float(val) > 0.1
                except ValueError:
                    duration_ok = False
                break
        if not has_mp4 or not has_audio or not duration_ok:
            print(f"[_validate_m4b_file] validazione fallita: "
                  f"mp4={has_mp4}, audio={has_audio}, duration_ok={duration_ok}")
            return False
        return True
    except FileNotFoundError:
        # ffprobe non disponibile: skip validation (non spezzare il flusso)
        return True
    except Exception as e:
        print(f"[_validate_m4b_file] eccezione durante validazione: {e}")
        # In caso di errore imprevisto preferiamo segnalare il file come invalido
        return False


def _prepare_m4b_cover_path(job, book_title, book_author, work_dir):
    """Prepara una cover ad alta risoluzione (1400x1400) per l'embedding nel M4B.

    Strategia di ricerca cover, in ordine di preferenza:
      1. Cache: se `job["cover_hires"]` esiste già → riusa
      2. EPUB sorgente: estrae una versione 1400x1400 quadrata via _extract_cover_from_epub
      3. Cover esistente (`job["cover_thumb"]`, tipica di ABM o EPUB già processati): usa as-is
      4. Ultima risorsa: genera una cover branded "Audiobook Maker" 1400x1400 via
         _generate_fallback_cover (richiede Pillow). Garantisce che ogni M4B abbia
         sempre una copertina anche per PDF/TXT o EPUB senza cover.

    Aggiorna `job["cover_hires"]` con il path risolto per evitare rigenerazioni.
    Restituisce il path alla cover, o None se Pillow non è installato e non esiste
    alcuna cover preesistente.
    """
    # 1. Cache
    cached = job.get("cover_hires")
    if cached and os.path.exists(cached):
        return cached

    dest = os.path.join(str(work_dir), "cover_m4b.jpg")

    # 2. Estrazione hi-res da EPUB sorgente
    source_path = job.get("epub_path", "")
    if source_path and os.path.exists(source_path) and source_path.lower().endswith(".epub"):
        try:
            if _extract_cover_from_epub(source_path, dest, target_size=1400):
                print(f"[_prepare_m4b_cover_path] EPUB hi-res cover → {dest}")
                job["cover_hires"] = dest
                return dest
        except Exception as e:
            print(f"[_prepare_m4b_cover_path] EPUB hi-res failed: {e}")

    # 3. Cover thumb preesistente (ABM, o EPUB fallback)
    existing = job.get("cover_thumb", "")
    if existing and os.path.exists(existing):
        print(f"[_prepare_m4b_cover_path] using existing thumb → {existing}")
        job["cover_hires"] = existing
        return existing

    # 4. Branded fallback (PDF / TXT / EPUB senza cover)
    try:
        if _generate_fallback_cover(dest, title=book_title or "",
                                    author=book_author or "", target_size=1400):
            print(f"[_prepare_m4b_cover_path] branded fallback cover → {dest}")
            job["cover_hires"] = dest
            return dest
    except Exception as e:
        print(f"[_prepare_m4b_cover_path] fallback gen failed: {e}")

    print("[_prepare_m4b_cover_path] Nessuna cover disponibile (Pillow mancante?)")
    return None


# Mappa ISO 639-1 (2 lettere) → ISO 639-2/B (3 lettere). Usata per il tag
# language dei container MP4 (Apple Books e iTunes preferiscono ISO 639-2).
_ISO_639_1_TO_2 = {
    "it": "ita", "en": "eng", "fr": "fra", "es": "spa", "de": "deu",
    "pt": "por", "zh": "zho", "ja": "jpn", "ru": "rus", "ar": "ara",
    "ko": "kor", "nl": "nld", "pl": "pol", "tr": "tur", "sv": "swe",
    "no": "nor", "da": "dan", "fi": "fin", "cs": "ces", "el": "ell",
    "he": "heb", "hu": "hun", "ro": "ron", "uk": "ukr", "vi": "vie",
    "th": "tha", "id": "ind", "ms": "msa", "hi": "hin", "bn": "ben",
    "fa": "fas", "ur": "urd", "ca": "cat", "sk": "slk", "sr": "srp",
    "hr": "hrv", "sl": "slv", "bg": "bul", "et": "est", "lv": "lav",
    "lt": "lit", "ga": "gle", "cy": "cym", "is": "isl", "mt": "mlt",
}


def _normalize_language_iso(lang_code):
    """Normalizza un codice lingua a ISO 639-2/B (3 lettere).

    Accetta formati comuni EPUB/HTML: "it", "it-IT", "it_IT", "ita", "en-US".
    Ritorna il codice 3-lettere in lowercase, o stringa vuota se non mappabile.
    """
    if not lang_code:
        return ""
    short = lang_code.split("-")[0].split("_")[0].strip().lower()
    if len(short) == 3:
        return short  # Già ISO 639-2
    if len(short) == 2 and short in _ISO_639_1_TO_2:
        return _ISO_639_1_TO_2[short]
    return ""


def _extract_year_from_date(date_str):
    """Estrae l'anno (YYYY) da una stringa data EPUB in vari formati.

    Accetta: "2024", "2024-03-15", "March 2024", "2024-03", "1999/05/21".
    Ritorna l'anno come stringa "YYYY" (4 cifre), o stringa vuota se non
    identificabile.
    """
    if not date_str:
        return ""
    import re
    m = re.search(r"\b(1[0-9]{3}|2[0-9]{3})\b", str(date_str))
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# M4B conversion
# ---------------------------------------------------------------------------

def _convert_mp3_to_m4b(mp3_path, m4b_path, chapters=None, title=None, author=None,
                        cover_path=None, date=None, language=None,
                        description=None, genre="Audiobook"):
    """Converte un file MP3 in M4B (AAC) con metadati capitoli e cover usando ffmpeg.

    Scrive nel file M4B i seguenti tag (tutti quelli disponibili):
      [format-level, FFMETADATA1]
      - title           ← titolo del libro
      - album           ← titolo del libro (convenzione Apple Books)
      - artist          ← autore
      - album_artist    ← autore (campo "autore" in Apple Books)
      - date            ← anno di pubblicazione (YYYY, estratto da date string)
      - genre           ← "Audiobook" di default (parametrizzabile)
      - comment         ← breve descrizione del libro (troncata a 1000 char)
      - description     ← alias di comment per compat (Apple Books)
      [format-level, -metadata CLI]
      - media_type=2    ← iTunes stik atom: Apple Books classifica come "Audiobook"
      [stream-level, -metadata:s:a:0 CLI]
      - language        ← codice ISO 639-2/B 3-lettere (es. "ita", "eng")
                          Per MP4/M4B il tag language è per-stream, non globale.

    Nota: il tag `encoder` NON viene impostato perché ffmpeg lo sovrascrive sempre
    con il proprio valore (es. "Lavf62.3.100").

    I tag sono incorporati sia quando sono presenti chapter markers sia quando non lo sono
    (ad es. quando ffprobe non è disponibile e tutte le durate risultano zero).

    Il bitrate AAC viene rilevato automaticamente dall'MP3 sorgente tramite ffprobe,
    così il file M4B risulta di dimensioni sostanzialmente equivalenti alla somma degli
    MP3 originali (AAC è leggermente più efficiente di MP3 a parità di bitrate).
    Fallback bitrate: 48 kbps (default edge-tts: audio-24khz-48kbitrate-mono-mp3).

    Timeout aumentato a 3600s per supportare audiolibri lunghi (post-ottimizzazione AI il
    testo può espandersi significativamente, aumentando la durata della codifica AAC).
    Fallback automatico senza cover se l'embedding cover fallisce.
    I capitoli con durata zero (ffprobe non disponibile) vengono filtrati per evitare
    metadati invalidi che causerebbero il fallimento di ffmpeg.
    """
    try:
        import subprocess

        def escape_meta(s):
            return str(s).replace('\\', '\\\\').replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\n', ' ')

        # Rileva bitrate sorgente per mantenere dimensioni M4B ≈ somma MP3 originali
        source_kbps = _get_audio_bitrate(mp3_path)
        aac_bitrate = f"{source_kbps}k"
        print(f"[_convert_mp3_to_m4b] bitrate sorgente={source_kbps} kbps → AAC target={aac_bitrate}")

        # Normalizza metadati opzionali
        year = _extract_year_from_date(date) if date else ""
        lang_iso = _normalize_language_iso(language) if language else ""
        desc_trunc = (description or "").strip()[:1000] if description else ""

        # Filtra capitoli con durata zero (ffprobe non disponibile → tutte le durate = 0)
        valid_chapters = None
        if chapters:
            valid_chapters = [ch for ch in chapters if ch.get("end", 0) > ch.get("start", 0)]
            if not valid_chapters:
                valid_chapters = None  # Genera M4B senza chapter markers

        # Crea il file di metadati FFMETADATA1 se abbiamo qualsiasi metadato globale o capitoli.
        # Nota: il file viene creato SEMPRE quando almeno un metadato è disponibile,
        # anche in assenza di chapter markers (ad es. ffprobe non installato).
        has_global_meta = bool(title or author or year or lang_iso or desc_trunc or genre)
        metadata_file = None
        if has_global_meta or valid_chapters:
            metadata_file = m4b_path + ".metadata.txt"
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write(";FFMETADATA1\n")
                if title:
                    f.write(f"title={escape_meta(title)}\n")
                    # album = titolo del libro (convenzione standard per audiolibri)
                    f.write(f"album={escape_meta(title)}\n")
                if author:
                    # artist e album_artist: entrambi necessari per massima compatibilità
                    # con Apple Books, iTunes, lettori M4B/IPOD
                    f.write(f"artist={escape_meta(author)}\n")
                    f.write(f"album_artist={escape_meta(author)}\n")
                if year:
                    f.write(f"date={escape_meta(year)}\n")
                if genre:
                    f.write(f"genre={escape_meta(genre)}\n")
                # Nota: `language` va scritto come tag dello stream audio nei container
                # MP4/M4B (tag per-stream), non come metadato globale. Viene applicato più
                # avanti tramite -metadata:s:a:0 language=... nel comando ffmpeg.
                if desc_trunc:
                    # comment e description: massima compatibilità lettori audiobook
                    f.write(f"comment={escape_meta(desc_trunc)}\n")
                    f.write(f"description={escape_meta(desc_trunc)}\n")
                # Nota: il tag `encoder` viene sempre sovrascritto da ffmpeg con la
                # propria versione (es. "Lavf62.3.100"), quindi non ha senso scriverlo.
                if valid_chapters:
                    for ch in valid_chapters:
                        f.write("\n[CHAPTER]\n")
                        f.write("TIMEBASE=1/1000\n")
                        f.write(f"START={int(round(ch['start']))}\n")
                        f.write(f"END={int(round(ch['end']))}\n")
                        f.write(f"title={escape_meta(ch['title'])}\n")

        def _build_cmd(use_cover):
            """Costruisce il comando ffmpeg con o senza cover art."""
            c = ["ffmpeg", "-y", "-i", mp3_path]
            n_inputs = 1
            m_idx = -1
            c_idx = -1

            if metadata_file:
                c += ["-i", metadata_file]
                m_idx = n_inputs
                n_inputs += 1

            if use_cover and cover_path and os.path.exists(cover_path):
                c += ["-i", cover_path]
                c_idx = n_inputs
                n_inputs += 1

            c += ["-map", "0:a"]

            if c_idx != -1:
                # mjpeg è più compatibile di copy per cover JPEG/PNG in container IPOD/M4B
                c += ["-map", f"{c_idx}:v", "-c:v", "mjpeg", "-q:v", "2",
                      "-disposition:v:0", "attached_pic"]

            if m_idx != -1:
                c += ["-map_metadata", str(m_idx), "-map_chapters", str(m_idx)]

            # Tag iTunes specifico: media_type=2 (stik atom) → Apple Books lo classifica
            # come "Audiobook" invece che "Music". Applicato DOPO -map_metadata per non
            # essere sovrascritto dal mapping del file di metadati.
            c += ["-metadata", "media_type=2"]

            # language va applicato come tag dello stream audio (MP4/M4B usa language
            # per-stream, non per-format). Usa ISO 639-2/B (3 lettere).
            if lang_iso:
                c += ["-metadata:s:a:0", f"language={lang_iso}"]

            # Codec AAC: bitrate adattivo rilevato dall'MP3 sorgente (default 48k = edge-tts)
            if c_idx == -1:
                c += ["-vn"]
            c += ["-c:a", "aac", "-b:a", aac_bitrate, "-f", "ipod", m4b_path]
            return c

        # Timeout elevato: la codifica AAC di audiolibri lunghi (post-ottimizzazione AI)
        # può richiedere molti minuti su server modesti.
        M4B_TIMEOUT = 3600  # 1 ora

        # Tentativo 1: con cover art
        cmd = _build_cmd(use_cover=True)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=M4B_TIMEOUT, **_SUBPROCESS_FLAGS)

        # Fallback: se la conversione con cover fallisce, riprova senza cover
        if result.returncode != 0 and cover_path and os.path.exists(cover_path):
            print(f"[_convert_mp3_to_m4b] cover fallita (rc={result.returncode}), "
                  f"riprovo senza cover")
            if os.path.exists(m4b_path):
                try:
                    os.remove(m4b_path)
                except OSError:
                    pass
            cmd = _build_cmd(use_cover=False)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=M4B_TIMEOUT, **_SUBPROCESS_FLAGS)

        if metadata_file and os.path.exists(metadata_file):
            os.remove(metadata_file)

        if result.returncode != 0:
            print(f"[_convert_mp3_to_m4b] ffmpeg error (rc={result.returncode}): "
                  f"{result.stderr[-500:] if result.stderr else '(no output)'}")
            # Rimuovi eventuale file parziale lasciato da ffmpeg
            if os.path.exists(m4b_path):
                try:
                    os.remove(m4b_path)
                except OSError:
                    pass
            return False
        if os.path.exists(m4b_path):
            # Validazione integrità: ffmpeg rc=0 non garantisce file decodificabile.
            # Se ffprobe rileva container corrotto o stream audio mancante, rimuoviamo
            # il file parziale per evitare di esporre un M4B rotto al download.
            if not _validate_m4b_file(m4b_path):
                print(f"[_convert_mp3_to_m4b] file generato ma non valido, rimuovo: "
                      f"{os.path.basename(m4b_path)}")
                try:
                    os.remove(m4b_path)
                except OSError:
                    pass
                return False
            print(f"[_convert_mp3_to_m4b] OK → {os.path.basename(m4b_path)} "
                  f"({os.path.getsize(m4b_path)//1024} KB, "
                  f"title={title!r}, author={author!r}, year={year!r}, "
                  f"lang={lang_iso!r}, genre={genre!r}, "
                  f"cover={'yes' if (cover_path and os.path.exists(cover_path)) else 'no'}, "
                  f"chapters={len(valid_chapters) if valid_chapters else 0})")
            return True
        return False
    except subprocess.TimeoutExpired:
        print(f"[_convert_mp3_to_m4b] timeout dopo {M4B_TIMEOUT}s — file troppo grande?")
        # Rimuovi file parziale lasciato dal subprocess killato
        if os.path.exists(m4b_path):
            try:
                os.remove(m4b_path)
            except OSError:
                pass
        return False
    except FileNotFoundError:
        print("[_convert_mp3_to_m4b] ffmpeg non trovato nel PATH")
        return False
    except Exception as e:
        print(f"[_convert_mp3_to_m4b] exception: {e}")
        if os.path.exists(m4b_path):
            try:
                os.remove(m4b_path)
            except OSError:
                pass
        return False


# ---------------------------------------------------------------------------
# Podcast RSS
# ---------------------------------------------------------------------------

def _generate_podcast_rss(info, mp3_files, output_path, base_url="", cover_filename="", rss_filename="podcast.xml"):
    """Generate an RSS 2.0 podcast feed XML file compliant with iTunes specs."""
    from datetime import datetime, timezone, timedelta
    import xml.etree.ElementTree as ET

    def _mp3_duration_seconds(path):
        try:
            import subprocess
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, **_SUBPROCESS_FLAGS
            )
            if r.returncode == 0 and r.stdout.strip():
                return int(float(r.stdout.strip()))
        except (FileNotFoundError, OSError, ValueError):
            pass
        try:
            return max(1, os.path.getsize(path) * 8 // 48000)
        except OSError:
            return 0

    def _fmt_duration(secs):
        h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _rfc2822(dt):
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return (f"{days[dt.weekday()]}, {dt.day:02d} {months[dt.month-1]} "
                f"{dt.year} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} +0000")

    itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    atom_ns = "http://www.w3.org/2005/Atom"
    podcast_ns = "https://podcastindex.org/namespace/1.0"
    content_ns = "http://purl.org/rss/1.0/modules/content/"
    ET.register_namespace("itunes", itunes_ns)
    ET.register_namespace("atom", atom_ns)
    ET.register_namespace("podcast", podcast_ns)
    ET.register_namespace("content", content_ns)

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = info.title or "Audiobook"
    ET.SubElement(channel, "description").text = (
        f"Audiobook: {info.title}" + (f" — {info.author}" if info.author else "")
    )
    ET.SubElement(channel, "language").text = info.language or "en"
    channel_link = base_url or "https://example.com"
    ET.SubElement(channel, "link").text = channel_link
    ET.SubElement(channel, "generator").text = "Audiobook Maker"
    now = datetime.now(timezone.utc)
    ET.SubElement(channel, "pubDate").text = _rfc2822(now)
    ET.SubElement(channel, "lastBuildDate").text = _rfc2822(now)

    rss_url = (base_url.rstrip("/") + "/" + rss_filename) if base_url else rss_filename
    atom_link = ET.SubElement(channel, f"{{{atom_ns}}}link")
    atom_link.set("href", rss_url)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    author_name = info.author or "Unknown"
    ET.SubElement(channel, f"{{{itunes_ns}}}author").text = author_name
    ET.SubElement(channel, f"{{{itunes_ns}}}summary").text = (
        f"Audiobook: {info.title}" + (f" by {info.author}" if info.author else "")
    )
    cat = ET.SubElement(channel, f"{{{itunes_ns}}}category")
    cat.set("text", "Arts")
    sub = ET.SubElement(cat, f"{{{itunes_ns}}}category")
    sub.set("text", "Books")
    ET.SubElement(channel, f"{{{itunes_ns}}}explicit").text = "false"
    ET.SubElement(channel, f"{{{itunes_ns}}}type").text = "serial"

    owner = ET.SubElement(channel, f"{{{itunes_ns}}}owner")
    ET.SubElement(owner, f"{{{itunes_ns}}}name").text = author_name
    ET.SubElement(owner, f"{{{itunes_ns}}}email").text = "podcast@example.com"

    cover_url = ""
    if cover_filename:
        cover_url = (base_url.rstrip("/") + "/" + cover_filename) if base_url else cover_filename
        img_el = ET.SubElement(channel, f"{{{itunes_ns}}}image")
        img_el.set("href", cover_url)
        p_img = ET.SubElement(channel, f"{{{podcast_ns}}}image")
        p_img.set("href", cover_url)

    ET.SubElement(channel, f"{{{podcast_ns}}}guid").text = (
        str(uuid.uuid5(uuid.NAMESPACE_URL, channel_link + "/" + (info.title or "audiobook")))
    )

    chapter_by_seq = {pos + 1: ch for pos, ch in enumerate(info.chapters)}
    chapter_by_idx = {ch.index: ch for ch in info.chapters}

    for ep_num, mp3_path in enumerate(mp3_files, 1):
        fname = os.path.basename(mp3_path)
        file_size = os.path.getsize(mp3_path) if os.path.exists(mp3_path) else 0
        duration_secs = _mp3_duration_seconds(mp3_path)

        ch_title = f"Episode {ep_num}"
        ch_desc = ""
        try:
            idx_str = fname.split("_")[0]
            idx = int(idx_str)
            matched_ch = chapter_by_seq.get(idx) or chapter_by_idx.get(idx)
            if matched_ch is not None:
                ch_title = matched_ch.title
                ch_desc = f"Chapter {idx}: {ch_title}"
        except (ValueError, IndexError):
            pass

        pub_date = now - timedelta(hours=len(mp3_files) - ep_num)
        file_url = (base_url.rstrip("/") + "/" + fname) if base_url else fname

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ch_title
        ET.SubElement(item, "description").text = ch_desc or ch_title
        ET.SubElement(item, f"{{{itunes_ns}}}episode").text = str(ep_num)
        ET.SubElement(item, f"{{{itunes_ns}}}episodeType").text = "full"
        ET.SubElement(item, f"{{{itunes_ns}}}duration").text = _fmt_duration(duration_secs)
        ET.SubElement(item, f"{{{itunes_ns}}}author").text = info.author or "Unknown"
        ET.SubElement(item, f"{{{itunes_ns}}}summary").text = ch_desc or ch_title
        ET.SubElement(item, f"{{{itunes_ns}}}explicit").text = "false"
        if cover_url:
            item_img = ET.SubElement(item, f"{{{itunes_ns}}}image")
            item_img.set("href", cover_url)
        ET.SubElement(item, "pubDate").text = _rfc2822(pub_date)
        ET.SubElement(item, "link").text = file_url
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = str(
            uuid.uuid5(uuid.NAMESPACE_URL, channel_link + "/" + fname)
        )
        enc = ET.SubElement(item, "enclosure")
        enc.set("url", file_url)
        enc.set("length", str(file_size))
        enc.set("type", "audio/mpeg")

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------

def _safe_filename(name):
    """Sanitizza un nome file rimuovendo caratteri non consentiti."""
    import re
    # Remove filesystem forbidden chars and dots (dots break extension detection in downloads)
    name = re.sub(r'[<>:"/\\|?*.]', '', name)
    # Replace spaces with underscores
    name = re.sub(r'\s+', '_', name.strip())
    # Security: prevent filename starting with '-' to avoid CLI argument injection
    if name.startswith('-'):
        name = '_' + name
    return name[:100]


# ---------------------------------------------------------------------------
# PCM helpers (Gemini TTS native output: 24kHz mono 16-bit)
# ---------------------------------------------------------------------------

def pcm_size_to_seconds(byte_size, sample_rate=24000, channels=1, sample_width=2):
    """Converte byte di PCM raw in secondi di durata.

    sample_width: byte per sample (16-bit = 2).
    """
    if byte_size <= 0:
        return 0.0
    bytes_per_second = sample_rate * channels * sample_width
    return byte_size / bytes_per_second


def pcm_concat(pcm_paths, output_path, skip_missing=False):
    """Concatena raw PCM byte-wise (tutti i file devono avere stesso formato).

    Non c'e' header da gestire: PCM raw e' solo sequenza di campioni.
    Crea il file di output anche se la lista e' vuota.

    Args:
        pcm_paths: lista path PCM in ordine.
        output_path: file di destinazione.
        skip_missing: se True, file non esistenti vengono saltati con log;
                      altrimenti raise FileNotFoundError.
    """
    out = open(output_path, "wb")
    try:
        for p in pcm_paths:
            if not os.path.exists(p):
                if skip_missing:
                    print(f"[pcm_concat] skip missing: {p}")
                    continue
                raise FileNotFoundError(p)
            with open(p, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
    finally:
        out.close()


def pcm_to_mp3(pcm_paths, output_path, sample_rate=24000, channels=1,
               sample_width=2, bitrate="64k"):
    """Concatena raw PCM e codifica in MP3 con singola passata ffmpeg.

    Args:
        pcm_paths: lista path PCM (24kHz mono 16-bit by default).
        output_path: file MP3 risultante.
        sample_rate, channels, sample_width: formato sorgente.
        bitrate: bitrate MP3 (es. '64k').

    Returns:
        True se ok, False se nessun input o ffmpeg fallisce.
    """
    if not pcm_paths:
        return False
    ffmpeg_ok, _ = _check_audio_dependencies()
    if not ffmpeg_ok:
        print("[pcm_to_mp3] ffmpeg not available")
        return False

    import subprocess
    tmp_pcm = output_path + ".tmp.pcm"
    try:
        pcm_concat(pcm_paths, tmp_pcm)
        cmd = [
            "ffmpeg", "-y",
            "-f", "s16le",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-i", tmp_pcm,
            "-c:a", "libmp3lame",
            "-b:a", bitrate,
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=600, **_SUBPROCESS_FLAGS)
        if result.returncode != 0:
            print(f"[pcm_to_mp3] ffmpeg failed: {result.stderr.decode('utf-8', errors='ignore')[:500]}")
            return False
        return True
    except Exception as e:
        print(f"[pcm_to_mp3] error: {e}")
        return False
    finally:
        try:
            os.remove(tmp_pcm)
        except OSError:
            pass
