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
import subprocess
import sys
import time
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
    from secure_archive import (safe_xml_fromstring, safe_zip_path,
                                check_zip_bomb, ZipSafetyError)

    try:
        from PIL import Image
    except ImportError:
        return None

    def _safe_href(opf_dir, href):
        """Normalizza l'href OPF e rifiuta path-traversal."""
        joined = (opf_dir + '/' + href).replace('\\', '/') if opf_dir else href.replace('\\', '/')
        try:
            return safe_zip_path(joined)
        except ZipSafetyError as e:
            print(f"[cover] unsafe OPF href skipped: {e}")
            return None

    def _find_cover_in_opf(zf):
        opf_path = None
        try:
            container = safe_xml_fromstring(zf.read("META-INF/container.xml"))
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile = container.find(".//c:rootfile", ns)
            if rootfile is not None:
                opf_path = rootfile.get("full-path")
        except Exception:
            pass
        if not opf_path:
            for n in zf.namelist():
                if n.endswith(".opf"):
                    opf_path = n
                    break
        if not opf_path:
            return None
        try:
            opf = safe_xml_fromstring(zf.read(opf_path))
        except Exception:
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
                return _safe_href(opf_dir, href)
        if cover_id and cover_id in manifest_items:
            href, mt, _ = manifest_items[cover_id]
            if mt.startswith("image/"):
                return _safe_href(opf_dir, href)
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
            try:
                check_zip_bomb(zf)
            except ZipSafetyError as _ze:
                print(f"[cover] EPUB rejected: {_ze}")
                return None
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
    from secure_archive import (safe_xml_fromstring, safe_zip_path,
                                check_zip_bomb, ZipSafetyError)

    def _safe_href2(opf_dir, href):
        joined = (opf_dir + '/' + href).replace('\\', '/') if opf_dir else href.replace('\\', '/')
        try:
            return safe_zip_path(joined)
        except ZipSafetyError as e:
            print(f"[cover] unsafe OPF href skipped: {e}")
            return None

    def _find_cover_path_in_zip(zf):
        opf_path = None
        try:
            container = safe_xml_fromstring(zf.read("META-INF/container.xml"))
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile = container.find(".//c:rootfile", ns)
            if rootfile is not None:
                opf_path = rootfile.get("full-path")
        except Exception:
            pass
        if not opf_path:
            for n in zf.namelist():
                if n.endswith(".opf"):
                    opf_path = n
                    break
        if opf_path:
            try:
                opf = safe_xml_fromstring(zf.read(opf_path))
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
                        return _safe_href2(opf_dir, href)
                if cover_id and cover_id in manifest:
                    href, mt, _ = manifest[cover_id]
                    if mt.startswith("image/"):
                        return _safe_href2(opf_dir, href)
            except Exception:
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
            try:
                check_zip_bomb(zf)
            except ZipSafetyError as _ze:
                print(f"[cover] EPUB rejected: {_ze}")
                return None, None
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
# FFMETADATA1 (capitoli + tag globali) — condiviso fra conversione M4B e kit
# ---------------------------------------------------------------------------

def _escape_ffmeta(s):
    """Escape dei caratteri speciali del formato FFMETADATA1 (=, ;, #, \\, newline)."""
    return (str(s).replace('\\', '\\\\').replace('=', '\\=')
            .replace(';', '\\;').replace('#', '\\#').replace('\n', ' '))


def _build_ffmetadata_text(chapters=None, title=None, author=None,
                           year=None, genre=None, description=None):
    """Costruisce il contenuto di un file ;FFMETADATA1 (tag globali + capitoli).

    `chapters` deve essere già filtrato (solo capitoli con end>start) oppure None.
    `year`/`description` sono i valori già normalizzati/troncati dal chiamante.
    `language` NON viene scritto qui: nei container MP4/M4B è un tag per-stream,
    applicato via `-metadata:s:a:0 language=...` nel comando ffmpeg.

    Ritorna la stringa completa del file (sempre almeno l'header ";FFMETADATA1").
    """
    esc = _escape_ffmeta
    lines = [";FFMETADATA1"]
    if title:
        lines.append(f"title={esc(title)}")
        # album = titolo del libro (convenzione standard per audiolibri)
        lines.append(f"album={esc(title)}")
    if author:
        # artist e album_artist: entrambi per massima compatibilità (Apple Books, iTunes)
        lines.append(f"artist={esc(author)}")
        lines.append(f"album_artist={esc(author)}")
    if year:
        lines.append(f"date={esc(year)}")
    if genre:
        lines.append(f"genre={esc(genre)}")
    if description:
        # comment e description: massima compatibilità lettori audiobook
        lines.append(f"comment={esc(description)}")
        lines.append(f"description={esc(description)}")
    out = "\n".join(lines) + "\n"
    if chapters:
        for ch in chapters:
            out += "\n[CHAPTER]\n"
            out += "TIMEBASE=1/1000\n"
            out += f"START={int(round(ch['start']))}\n"
            out += f"END={int(round(ch['end']))}\n"
            out += f"title={esc(ch['title'])}\n"
    return out


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
        # Nota: `language` (lang_iso) NON entra nel file FFMETADATA (è un tag
        # per-stream, applicato via -metadata:s:a:0 nel comando ffmpeg), ma la sua
        # presenza giustifica comunque la creazione del file di metadati.
        has_global_meta = bool(title or author or year or lang_iso or desc_trunc or genre)
        metadata_file = None
        if has_global_meta or valid_chapters:
            metadata_file = m4b_path + ".metadata.txt"
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write(_build_ffmetadata_text(
                    chapters=valid_chapters, title=title, author=author,
                    year=year, genre=genre, description=desc_trunc))

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


def _monitored_m4b_run(tag, convert, output_path, on_phase, status_out,
                       prep_msg, encoding_msg):
    """Corpo comune dei wrapper monitored di conversione M4B.

    Choreography condivisa: on_phase a 0 (prep) → 5 (encoding) → 98 (validazione)
    → 100 (ok), con status_out popolato a fine corsa
    ({"status": "ok"|"fail"|"timeout"|"invalid", "pct": int, "msg": str}).
    Il file di output invalido (ffprobe KO) viene rimosso best-effort.

    Args:
        tag: nome del wrapper per il log degli errori di on_phase.
        convert: thunk senza argomenti che esegue la conversione e ritorna bool.
        output_path: file M4B atteso, validato con _validate_m4b_file.
        on_phase: callable(pct, msg) o None per no-op.
        status_out: dict opzionale per lo status finale, None per ignorarlo.
        prep_msg, encoding_msg: messaggi specifici del wrapper per le fasi 0 e 5.
    """
    def _emit(pct, msg):
        if on_phase:
            try:
                on_phase(pct, msg)
            except Exception as e:
                print(f"[{tag}] on_phase error: {e}")

    def _finish(status, pct, msg):
        if status_out is not None:
            status_out["status"] = status
            status_out["pct"] = pct
            status_out["msg"] = msg

    _emit(0, prep_msg)
    _emit(5, encoding_msg)
    try:
        result = convert()
    except subprocess.TimeoutExpired:
        _emit(0, "Conversione M4B timeout")
        _finish("timeout", 0, "Conversione M4B timeout")
        _discard_failed_output(output_path, tag)
        return False
    except Exception:
        _emit(0, "Conversione M4B fallita")
        _finish("fail", 0, "Conversione M4B fallita")
        _discard_failed_output(output_path, tag)
        return False

    if not result:
        _emit(0, "Conversione M4B fallita")
        _finish("fail", 0, "Conversione M4B fallita")
        # Il convert dovrebbe aver gia' ripulito, ma un M4B parziale sopravvissuto
        # qui verrebbe raccolto a valle come se fosse il risultato buono.
        _discard_failed_output(output_path, tag)
        return False

    # Validazione ffprobe (98 → 100)
    _emit(98, "Conversione M4B — validazione finale…")
    if _validate_m4b_file(output_path):
        _emit(100, "Conversione M4B completata")
        _finish("ok", 100, "Conversione M4B completata")
        return True

    # File invalido: tentiamo rimozione (best-effort, come l'originale).
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass
    _emit(0, "Conversione M4B — file invalido")
    _finish("invalid", 0, "Conversione M4B — file invalido")
    return False


def _convert_mp3_to_m4b_monitored(mp3_path, m4b_path, on_phase=None, status_out=None, **kwargs):
    """Wrapper monitored di _convert_mp3_to_m4b: chiama on_phase(pct, msg) ai punti chiave.

    Args:
        mp3_path, m4b_path: come _convert_mp3_to_m4b.
        on_phase: callable(pct: int, msg: str) o None per no-op.
        status_out: dict opzionale che verrà popolato con
            {"status": "ok"|"fail"|"timeout"|"invalid", "pct": int, "msg": str}
            al termine della conversione. None per non ricevere lo status.
        **kwargs: tutti gli altri parametri di _convert_mp3_to_m4b.

    Returns: bool come _convert_mp3_to_m4b.
    """
    # Skip rapido: sorgente mancante → niente callback, fail.
    if not os.path.exists(mp3_path):
        if status_out is not None:
            status_out["status"] = "fail"
            status_out["pct"] = 0
            status_out["msg"] = "source missing"
        return False
    return _monitored_m4b_run(
        "_convert_mp3_to_m4b_monitored",
        lambda: _convert_mp3_to_m4b(mp3_path, m4b_path, **kwargs),
        m4b_path, on_phase, status_out,
        "Conversione M4B — preparazione metadati…",
        "Conversione M4B — encoding AAC…")


# ---------------------------------------------------------------------------
# M4B rebuild kit (ripiego quando la conversione M4B server-side fallisce)
# ---------------------------------------------------------------------------

def _ms_to_hms(ms):
    """Converte millisecondi in stringa hh:mm:ss.mmm (per il chapters.json leggibile)."""
    try:
        ms = int(round(ms))
    except (TypeError, ValueError):
        ms = 0
    if ms < 0:
        ms = 0
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{msec:03d}"


def build_m4b_rebuild_kit(mp3_path, output_zip, chapters=None, title=None,
                          author=None, cover_path=None, date=None,
                          language=None, description=None, genre="Audiobook"):
    """Crea uno ZIP con cui l'utente può ricostruire l'M4B in autonomia.

    Usato come ripiego quando la conversione M4B lato server fallisce: invece del
    solo MP3, all'utente viene consegnato un pacchetto auto-contenuto.

    Contenuto dello ZIP:
      - audiolibro.mp3        copia del fallback MP3 (audio concatenato)
      - chapters.json         capitoli leggibili: titolo + start/end ms + hh:mm:ss
      - chapters.ffmetadata   stesso formato ;FFMETADATA1 usato internamente
      - cover.jpg             copertina, se disponibile
      - build_m4b.sh          comando ffmpeg pronto (Linux/macOS)
      - build_m4b.bat         comando ffmpeg pronto (Windows)
      - README.txt            istruzioni brevi (IT + EN), richiede ffmpeg

    Lo script riproduce esattamente il comando ffmpeg dell'app (AAC + capitoli +
    cover + media_type=2 + language per-stream), così l'M4B ricostruito è fedele.

    Ritorna True se lo ZIP è stato creato, False altrimenti.
    """
    try:
        import json
        import zipfile

        if not mp3_path or not os.path.exists(mp3_path):
            print(f"[build_m4b_rebuild_kit] MP3 sorgente mancante: {mp3_path}")
            return False

        valid_chapters = None
        if chapters:
            valid_chapters = [ch for ch in chapters if ch.get("end", 0) > ch.get("start", 0)]
            if not valid_chapters:
                valid_chapters = None

        year = _extract_year_from_date(date) if date else ""
        lang_iso = _normalize_language_iso(language) if language else ""
        desc_trunc = (description or "").strip()[:1000] if description else ""

        source_kbps = _get_audio_bitrate(mp3_path)
        aac_bitrate = f"{source_kbps}k"

        ffmeta_text = _build_ffmetadata_text(
            chapters=valid_chapters, title=title, author=author,
            year=year, genre=genre, description=desc_trunc)

        # Nome file M4B di destinazione suggerito allo script (sanitizzato).
        out_basename = _safe_filename(title) or "audiolibro"

        # chapters.json leggibile
        chapters_json = {
            "title": title or "",
            "author": author or "",
            "language": lang_iso or (language or ""),
            "year": year,
            "source_mp3": "audiolibro.mp3",
            "aac_bitrate": aac_bitrate,
            "chapters": [
                {
                    "index": i + 1,
                    "title": ch.get("title", f"Chapter {i + 1}"),
                    "start_ms": int(round(ch.get("start", 0))),
                    "end_ms": int(round(ch.get("end", 0))),
                    "start": _ms_to_hms(ch.get("start", 0)),
                    "end": _ms_to_hms(ch.get("end", 0)),
                }
                for i, ch in enumerate(valid_chapters or [])
            ],
        }

        has_cover = bool(cover_path and os.path.exists(cover_path))

        # Comando ffmpeg (con/senza cover), identico nella sostanza a _convert_mp3_to_m4b.
        lang_opt = f' -metadata:s:a:0 language={lang_iso}' if lang_iso else ''
        if has_cover:
            ffmpeg_args = (
                '-y -i audiolibro.mp3 -i chapters.ffmetadata -i cover.jpg '
                '-map 0:a -map 2:v -c:v mjpeg -q:v 2 -disposition:v:0 attached_pic '
                f'-map_metadata 1 -map_chapters 1 -metadata media_type=2{lang_opt} '
                f'-c:a aac -b:a {aac_bitrate} -f ipod'
            )
        else:
            ffmpeg_args = (
                '-y -i audiolibro.mp3 -i chapters.ffmetadata '
                f'-map 0:a -map_metadata 1 -map_chapters 1 -metadata media_type=2{lang_opt} '
                f'-vn -c:a aac -b:a {aac_bitrate} -f ipod'
            )

        sh_script = (
            "#!/usr/bin/env bash\n"
            "# Ricostruisce l'audiolibro M4B (con capitoli e copertina) dai file di\n"
            "# questo pacchetto. Richiede ffmpeg installato e nel PATH.\n"
            "# Rebuilds the M4B audiobook (chapters + cover) from this package.\n"
            "# Requires ffmpeg installed and on PATH.\n"
            "set -e\n"
            f'cd "$(dirname "$0")"\n'
            f'ffmpeg {ffmpeg_args} "{out_basename}.m4b"\n'
            f'echo "OK: {out_basename}.m4b"\n'
        )
        bat_script = (
            "@echo off\r\n"
            "REM Ricostruisce l'audiolibro M4B (capitoli + copertina). Richiede ffmpeg nel PATH.\r\n"
            "REM Rebuilds the M4B audiobook (chapters + cover). Requires ffmpeg on PATH.\r\n"
            'cd /d "%~dp0"\r\n'
            f'ffmpeg {ffmpeg_args} "{out_basename}.m4b"\r\n'
            "if %ERRORLEVEL% NEQ 0 ( echo ERRORE: ffmpeg ha fallito & pause & exit /b 1 )\r\n"
            f'echo OK: {out_basename}.m4b\r\n'
            "pause\r\n"
        )

        readme = (
            "RICOSTRUZIONE AUDIOLIBRO M4B / REBUILD M4B AUDIOBOOK\n"
            "====================================================\n\n"
            "[IT]\n"
            "La conversione automatica in M4B non e' riuscita sul server, quindi ti\n"
            "consegniamo l'audio in MP3 insieme a tutto il necessario per generare\n"
            "l'M4B (con capitoli e copertina) sul tuo computer.\n\n"
            "Requisito: ffmpeg installato (https://ffmpeg.org/download.html).\n\n"
            "Come fare:\n"
            "  - Windows: doppio clic su build_m4b.bat\n"
            "  - macOS / Linux: apri un terminale nella cartella ed esegui:\n"
            "        bash build_m4b.sh\n\n"
            "Otterrai il file " + out_basename + ".m4b nella stessa cartella.\n\n"
            "Contenuto:\n"
            "  - audiolibro.mp3      l'audio completo\n"
            "  - chapters.json       elenco capitoli leggibile (titoli + tempi)\n"
            "  - chapters.ffmetadata metadati capitoli per ffmpeg\n"
            + ("  - cover.jpg           copertina\n" if has_cover else "")
            + "  - build_m4b.sh/.bat   script di ricostruzione\n\n"
            "[EN]\n"
            "Automatic M4B conversion failed on the server, so we provide the audio as\n"
            "MP3 plus everything needed to build the M4B (with chapters and cover) on\n"
            "your own computer.\n\n"
            "Requirement: ffmpeg installed (https://ffmpeg.org/download.html).\n\n"
            "How to:\n"
            "  - Windows: double-click build_m4b.bat\n"
            "  - macOS / Linux: open a terminal in this folder and run:\n"
            "        bash build_m4b.sh\n\n"
            "You will get " + out_basename + ".m4b in the same folder.\n"
        )

        # Scrittura atomica: prima un .tmp, poi rename sul path finale.
        tmp_zip = output_zip + ".tmp"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(mp3_path, "audiolibro.mp3")
            zf.writestr("chapters.json", json.dumps(chapters_json, ensure_ascii=False, indent=2))
            zf.writestr("chapters.ffmetadata", ffmeta_text)
            if has_cover:
                zf.write(cover_path, "cover.jpg")
            zf.writestr("build_m4b.sh", sh_script)
            zf.writestr("build_m4b.bat", bat_script)
            zf.writestr("README.txt", readme)
        os.replace(tmp_zip, output_zip)

        print(f"[build_m4b_rebuild_kit] OK -> {os.path.basename(output_zip)} "
              f"({os.path.getsize(output_zip)//1024} KB, "
              f"chapters={len(valid_chapters or [])}, cover={has_cover})")
        return True
    except Exception as e:
        print(f"[build_m4b_rebuild_kit] errore: {e}")
        try:
            if 'tmp_zip' in dir() and os.path.exists(tmp_zip):
                os.remove(tmp_zip)
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

# Limite di lunghezza dei nomi file generati, in BYTE UTF-8. I filesystem
# (ext4: 255 byte per componente del path) contano byte, non caratteri: un
# titolo CJK (3 byte/carattere) o con emoji (4 byte) supera i 255 byte molto
# prima dei 255 caratteri e fa fallire l'apertura del file con
# OSError [Errno 36] File name too long, uccidendo il thread del job. Il
# margine rispetto ai 255 byte copre estensione e suffissi aggiunti dai
# chiamanti (numerazione capitoli, _podcast.xml, ...).
MAX_FILENAME_BYTES = 150


def truncate_filename(name, max_bytes=MAX_FILENAME_BYTES):
    """Tronca un nome file a max_bytes in UTF-8 senza spezzare i caratteri."""
    if not name:
        return name
    raw = name.encode("utf-8")
    if len(raw) <= max_bytes:
        return name
    # errors='ignore' scarta l'eventuale carattere multibyte tagliato a meta'.
    return raw[:max_bytes].decode("utf-8", "ignore")


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
    # Doppio limite: 100 caratteri (storico) e MAX_FILENAME_BYTES byte UTF-8.
    return truncate_filename(name[:100])


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


def trim_pcm_trailing_silence(pcm_path, sample_rate=24000, channels=1, sample_width=2,
                              threshold=200, max_trim_ms=800):
    """Tronca in-place il silenzio finale di un file PCM raw mono 16-bit (s16le).

    Scansiona dalla coda del file fino a `max_trim_ms` di campioni e rimuove
    i samples finali consecutivi con |valore| < threshold. Usato per ridurre
    le pause percepibili tra chunk Gemini TTS consecutivi (ogni chunk tende ad
    avere trailing silence di durata variabile).

    Args:
        pcm_path: file PCM raw (s16le).
        sample_rate, channels, sample_width: formato. Solo mono 16-bit supportato.
        threshold: ampiezza assoluta (0-32767) sotto cui un sample e' "silenzio".
                   200 ≈ -44 dB (sicuro contro tagli sull'attacco di parola).
        max_trim_ms: cap massimo (ms) di silenzio da rimuovere. 0 = disabilita.

    Returns:
        int: millisecondi effettivamente troncati (0 se nessun trim o errore).
    """
    if max_trim_ms <= 0 or sample_width != 2 or channels != 1:
        return 0
    if not os.path.exists(pcm_path):
        return 0
    try:
        size = os.path.getsize(pcm_path)
        if size < 4:
            return 0
        max_trim_bytes = int(max_trim_ms * sample_rate / 1000) * channels * sample_width
        scan_bytes = min(size, max_trim_bytes)
        # Allinea su confine sample
        scan_bytes -= scan_bytes % (channels * sample_width)
        if scan_bytes <= 0:
            return 0
        import struct
        with open(pcm_path, "rb") as f:
            f.seek(size - scan_bytes)
            tail = f.read(scan_bytes)
        n_samples = len(tail) // 2
        if n_samples == 0:
            return 0
        samples = struct.unpack(f"<{n_samples}h", tail)
        cut_samples = 0
        for i in range(n_samples - 1, -1, -1):
            if abs(samples[i]) >= threshold:
                break
            cut_samples += 1
        if cut_samples == 0:
            return 0
        cut_bytes = cut_samples * sample_width * channels
        with open(pcm_path, "rb+") as f:
            f.truncate(size - cut_bytes)
        return int(cut_samples * 1000 / sample_rate)
    except Exception as e:
        print(f"[trim_pcm_trailing_silence] error on {pcm_path}: {e}")
        return 0


def pcm_concat(pcm_paths, output_path, skip_missing=False, gap_ms=0,
               sample_rate=24000, channels=1, sample_width=2):
    """Concatena raw PCM byte-wise (tutti i file devono avere stesso formato).

    Non c'e' header da gestire: PCM raw e' solo sequenza di campioni.
    Crea il file di output anche se la lista e' vuota.

    Args:
        pcm_paths: lista path PCM in ordine.
        output_path: file di destinazione.
        skip_missing: se True, file non esistenti vengono saltati con log;
                      altrimenti raise FileNotFoundError.
        gap_ms: silenzio (ms) inserito tra ogni coppia di PCM consecutivi
                effettivamente scritti. 0 = nessun gap (concat byte-a-byte).
                Utile per dare respiro acustico tra chunk TTS consecutivi.
        sample_rate, channels, sample_width: formato sorgente, usato solo per
                calcolare la dimensione del gap in byte.
    """
    out = open(output_path, "wb")
    gap_bytes = b""
    if gap_ms and gap_ms > 0:
        n_samples = int(gap_ms * sample_rate / 1000)
        gap_bytes = b"\x00" * (n_samples * channels * sample_width)
    try:
        wrote_any = False
        for p in pcm_paths:
            if not os.path.exists(p):
                if skip_missing:
                    print(f"[pcm_concat] skip missing: {p}")
                    continue
                raise FileNotFoundError(p)
            if wrote_any and gap_bytes:
                out.write(gap_bytes)
            wrote_any = True
            with open(p, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
    finally:
        out.close()


def _pcm_expected_duration_sec(pcm_paths, sample_rate=24000, channels=1,
                               sample_width=2, gap_ms=0):
    """Durata attesa (secondi) del PCM concatenato, calcolata dai soli byte su disco.

    Il PCM raw non ha header: durata = byte / (sample_rate * channels * width).
    Serve a due cose distinte: dimensionare la sorveglianza dell'encode sulla
    lunghezza reale del libro, e verificare a valle che il file codificato non
    sia stato troncato. Ritorna 0.0 se non calcolabile (nessun file leggibile).
    """
    total = 0
    n_files = 0
    for p in pcm_paths or []:
        try:
            total += os.path.getsize(p)
            n_files += 1
        except OSError:
            continue
    if total <= 0:
        return 0.0
    gap_sec = (max(0, n_files - 1) * max(0, int(gap_ms or 0))) / 1000.0
    return pcm_size_to_seconds(total, sample_rate=sample_rate, channels=channels,
                               sample_width=sample_width) + gap_sec


def _kill_process_tree(proc):
    """Termina un subprocess bloccato, con escalation kill dopo grace period."""
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:
            pass


def _tail_text_file(path, max_chars=1500):
    """Coda di un file di testo (per lo stderr di ffmpeg): la riga utile sta in fondo."""
    try:
        with open(path, "rb") as f:
            size = os.path.getsize(path)
            if size > max_chars * 4:
                f.seek(size - max_chars * 4)
            data = f.read()
        text = data.decode("utf-8", errors="ignore")
        return text[-max_chars:]
    except OSError:
        return ""


def _run_ffmpeg_encode(cmd, output_path, tag, expected_sec=0.0,
                       stall_timeout=300.0, poll_interval=5.0):
    """Esegue ffmpeg sorvegliando lo STALLO dell'output invece del wall-clock.

    Un timeout fisso su `subprocess.run` e' peggio del problema che vorrebbe
    risolvere: su un audiolibro lungo ffmpeg viene ucciso a meta' opera e il
    file troncato resta sul disco, indistinguibile da uno completo (incidente
    2026-08-16: M4B ucciso a 3600 s, MP3 di ripiego ucciso a 600 s e consegnato
    all'utente come se fosse l'audiolibro intero). Qui invece: finche' ffmpeg
    scrive, ha diritto a tutto il tempo che gli serve; se non scrive piu' nulla
    per `stall_timeout` secondi e' davvero bloccato e va terminato.

    Args:
        cmd: comando ffmpeg completo.
        output_path: file che ffmpeg sta scrivendo (sorvegliato per la crescita).
        tag: nome del chiamante, per i log.
        expected_sec: durata attesa dell'audio, usata per il tetto assoluto.
        stall_timeout: secondi senza crescita dell'output oltre i quali si uccide.
        poll_interval: cadenza di campionamento.

    Returns:
        (ok: bool, stderr_tail: str, reason: str) — reason vale "" se ok,
        altrimenti "rc=N" | "stall" | "hard_timeout" | il testo dell'eccezione.
    """
    import tempfile
    # stderr su file e non su PIPE: ffmpeg ne produce abbastanza da riempire il
    # buffer della pipe e bloccarsi in scrittura se nessuno legge (deadlock
    # classico di Popen+PIPE senza communicate(), che qui non possiamo usare
    # perche' dobbiamo restare noi a sorvegliare il processo).
    err_fd, err_path = tempfile.mkstemp(prefix="ffmpeg_", suffix=".err")
    os.close(err_fd)
    # Tetto assoluto, molto largo: rete di sicurezza per il caso patologico di
    # un output che cresce di pochi byte alla volta senza mai concludere.
    hard_timeout = max(7200.0, (expected_sec or 0.0) * 4)
    proc = None
    try:
        with open(err_path, "wb") as errf:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errf,
                                    **_SUBPROCESS_FLAGS)
        started = time.monotonic()
        last_size = -1
        last_growth = started
        while True:
            try:
                rc = proc.wait(timeout=poll_interval)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.monotonic()
            try:
                size = os.path.getsize(output_path)
            except OSError:
                size = -1
            if size > last_size:
                last_size = size
                last_growth = now
            if now - last_growth > stall_timeout:
                elapsed = now - started
                print(f"[{tag}] ffmpeg bloccato: nessuna crescita dell'output da "
                      f"{stall_timeout:.0f}s (elapsed {elapsed:.0f}s, "
                      f"size={last_size}) — termino")
                _kill_process_tree(proc)
                return False, _tail_text_file(err_path), "stall"
            if now - started > hard_timeout:
                print(f"[{tag}] ffmpeg oltre il tetto assoluto di {hard_timeout:.0f}s "
                      f"(expected_audio={expected_sec:.0f}s) — termino")
                _kill_process_tree(proc)
                return False, _tail_text_file(err_path), "hard_timeout"
        if rc != 0:
            return False, _tail_text_file(err_path), f"rc={rc}"
        return True, "", ""
    except Exception as e:
        if proc and proc.poll() is None:
            _kill_process_tree(proc)
        return False, _tail_text_file(err_path), str(e)
    finally:
        try:
            os.remove(err_path)
        except OSError:
            pass


def _encoded_duration_ok(output_path, expected_sec, tag, tolerance=0.02):
    """Verifica che il file codificato duri quanto il PCM da cui proviene.

    Un encode interrotto (processo ucciso, disco pieno, stream troncato) lascia
    un file perfettamente riproducibile ma incompleto: nessun returncode e
    nessun controllo di integrita' del container lo distingue da uno buono.
    L'unico invariante affidabile e' la durata, che conosciamo esattamente dai
    byte PCM sorgente.

    Ritorna True anche quando la verifica non e' possibile (ffprobe assente o
    durata attesa sconosciuta): meglio non bloccare un output valido che non
    possiamo misurare.
    """
    if not expected_sec or expected_sec <= 0:
        return True
    _, ffprobe_ok = _check_audio_dependencies()
    if not ffprobe_ok:
        return True
    actual_ms = _get_audio_duration_ms(output_path)
    if not actual_ms:
        print(f"[{tag}] durata non leggibile su {os.path.basename(output_path)} "
              f"(attesi {expected_sec:.0f}s) — considero l'encode fallito")
        return False
    actual_sec = actual_ms / 1000.0
    if actual_sec < expected_sec * (1.0 - tolerance):
        missing = expected_sec - actual_sec
        print(f"[{tag}] OUTPUT TRONCATO: {os.path.basename(output_path)} dura "
              f"{actual_sec:.0f}s invece di {expected_sec:.0f}s "
              f"(mancano {missing:.0f}s, {missing / expected_sec:.1%})")
        return False
    return True


def _discard_failed_output(output_path, tag):
    """Rimuove un output di encode fallito: non deve mai finire in consegna.

    Un file parziale lasciato sul disco viene raccolto dai passi successivi
    (offload su cold storage, rebuild kit, email di completamento) come se
    fosse il risultato buono.
    """
    if not output_path or not os.path.exists(output_path):
        return
    try:
        size = os.path.getsize(output_path)
        os.remove(output_path)
        print(f"[{tag}] rimosso output parziale {os.path.basename(output_path)} "
              f"({size} bytes)")
    except OSError as e:
        print(f"[{tag}] impossibile rimuovere l'output parziale "
              f"{os.path.basename(output_path)}: {e}")


def pcm_to_mp3(pcm_paths, output_path, sample_rate=24000, channels=1,
               sample_width=2, bitrate="64k", gap_ms=0):
    """Concatena raw PCM e codifica in MP3 con singola passata ffmpeg.

    Args:
        pcm_paths: lista path PCM (24kHz mono 16-bit by default).
        output_path: file MP3 risultante.
        sample_rate, channels, sample_width: formato sorgente.
        bitrate: bitrate MP3 (es. '64k').
        gap_ms: silenzio inter-chunk in ms (vedi pcm_concat).

    Returns:
        True se ok, False se nessun input, se ffmpeg fallisce o se l'MP3
        prodotto e' piu' corto del PCM sorgente (encode interrotto). In tutti i
        casi di fallimento l'eventuale file parziale viene rimosso.
    """
    if not pcm_paths:
        return False
    ffmpeg_ok, _ = _check_audio_dependencies()
    if not ffmpeg_ok:
        print("[pcm_to_mp3] ffmpeg not available")
        return False

    tmp_pcm = output_path + ".tmp.pcm"
    try:
        pcm_concat(pcm_paths, tmp_pcm, gap_ms=gap_ms, sample_rate=sample_rate,
                   channels=channels, sample_width=sample_width)
        expected_sec = _pcm_expected_duration_sec(
            [tmp_pcm], sample_rate=sample_rate, channels=channels,
            sample_width=sample_width)
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
        ok, stderr_tail, reason = _run_ffmpeg_encode(
            cmd, output_path, "pcm_to_mp3", expected_sec=expected_sec)
        if not ok:
            print(f"[pcm_to_mp3] ffmpeg failed ({reason}). stderr_tail:\n{stderr_tail}")
            _discard_failed_output(output_path, "pcm_to_mp3")
            return False
        if not _encoded_duration_ok(output_path, expected_sec, "pcm_to_mp3"):
            _discard_failed_output(output_path, "pcm_to_mp3")
            return False
        return True
    except Exception as e:
        print(f"[pcm_to_mp3] error: {e}")
        _discard_failed_output(output_path, "pcm_to_mp3")
        return False
    finally:
        try:
            os.remove(tmp_pcm)
        except OSError:
            pass


def pcm_to_aac_m4b(pcm_paths, output_path, sample_rate=24000, channels=1,
                   sample_width=2, bitrate="96k", chapters=None, title=None,
                   author=None, cover_path=None, date=None, language=None,
                   description=None, genre="Audiobook", gap_ms=0):
    """Codifica PCM concatenato direttamente in M4B (AAC) con capitoli/cover/metadati.

    Vantaggio vs pcm_to_mp3 + mp3_to_m4b: una sola encode AAC (no doppia lossy).

    Args:
        pcm_paths: lista PCM in ordine.
        output_path: file .m4b destinazione.
        bitrate: AAC bitrate (default '96k' mono).
        chapters: [{'title', 'start' ms, 'end' ms}, ...] opzionale.
        title/author/cover_path/date/language/description/genre: metadati M4B.

    Returns:
        True se ok, False altrimenti.
    """
    if not pcm_paths:
        return False
    ffmpeg_ok, _ = _check_audio_dependencies()
    if not ffmpeg_ok:
        print("[pcm_to_aac_m4b] ffmpeg not available")
        return False

    tmp_pcm = output_path + ".tmp.pcm"
    metadata_file = None
    try:
        pcm_concat(pcm_paths, tmp_pcm, gap_ms=gap_ms, sample_rate=sample_rate,
                   channels=channels, sample_width=sample_width)
        expected_sec = _pcm_expected_duration_sec(
            [tmp_pcm], sample_rate=sample_rate, channels=channels,
            sample_width=sample_width)

        year = _extract_year_from_date(date) if date else ""
        lang_iso = _normalize_language_iso(language) if language else ""
        desc_trunc = (description or "").strip()[:1000] if description else ""

        valid_chapters = None
        if chapters:
            valid_chapters = [ch for ch in chapters if ch.get("end", 0) > ch.get("start", 0)]
            if not valid_chapters:
                valid_chapters = None

        # FFMETADATA1 condiviso con _convert_mp3_to_m4b/build_m4b_rebuild_kit:
        # un solo builder evita che un fix ai tag debba essere replicato qui.
        # Il file viene creato solo se c'e' almeno un tag globale o capitoli
        # (altrimenti -map_metadata punterebbe a un input senza contenuto).
        has_global_meta = bool(title or author or year or lang_iso or desc_trunc or genre)
        if has_global_meta or valid_chapters:
            metadata_file = output_path + ".metadata.txt"
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write(_build_ffmetadata_text(
                    chapters=valid_chapters, title=title, author=author,
                    year=year, genre=genre, description=desc_trunc or None,
                ))

        cmd = [
            "ffmpeg", "-y",
            "-f", "s16le",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-i", tmp_pcm,
        ]
        if metadata_file:
            cmd.extend(["-i", metadata_file])
        if cover_path and os.path.exists(cover_path):
            cmd.extend(["-i", cover_path])

        # Mapping streams: prima dei map_metadata/chapters (output options).
        # Bug fix: con cover presente, mettere -map_metadata tra -i metadata e -i cover
        # faceva interpretare a ffmpeg map_metadata come opzione di INPUT per cover.jpg,
        # generando "Option map_metadata cannot be applied to input url ...".
        cmd.extend(["-map", "0:a"])
        if cover_path and os.path.exists(cover_path):
            cover_idx = 2 if metadata_file else 1
            cmd.extend(["-map", f"{cover_idx}:v",
                        "-disposition:v", "attached_pic", "-c:v", "copy"])

        if metadata_file:
            cmd.extend(["-map_metadata", "1", "-map_chapters", "1"])

        cmd.extend(["-c:a", "aac", "-b:a", bitrate])
        if lang_iso:
            cmd.extend(["-metadata:s:a:0", f"language={lang_iso}"])
        cmd.extend(["-metadata", "media_type=2", "-f", "ipod", output_path])

        # ffmpeg stampa per primi banner di versione + 'configuration: ...' che
        # occupano facilmente 1-2 KB. La riga utile (es. "Conversion failed!",
        # "Error opening output file", "Unknown encoder 'aac'") sta in coda:
        # tagliare dall'inizio nasconderebbe sempre la causa reale.
        ok, stderr_tail, reason = _run_ffmpeg_encode(
            cmd, output_path, "pcm_to_aac_m4b", expected_sec=expected_sec)
        if not ok:
            print(f"[pcm_to_aac_m4b] ffmpeg failed ({reason}). "
                  f"cmd={cmd!r}\nstderr_tail:\n{stderr_tail}")
            _discard_failed_output(output_path, "pcm_to_aac_m4b")
            return False
        if not _encoded_duration_ok(output_path, expected_sec, "pcm_to_aac_m4b"):
            _discard_failed_output(output_path, "pcm_to_aac_m4b")
            return False
        return True
    except Exception as e:
        print(f"[pcm_to_aac_m4b] error: {e}")
        _discard_failed_output(output_path, "pcm_to_aac_m4b")
        return False
    finally:
        for f in (tmp_pcm, metadata_file):
            if f:
                try:
                    os.remove(f)
                except OSError:
                    pass


def pcm_to_aac_m4b_monitored(pcm_paths, output_path, on_phase=None, status_out=None, **kwargs):
    """Wrapper monitored di pcm_to_aac_m4b con callback on_phase(pct, msg) e status_out.

    Args:
        pcm_paths, output_path: come pcm_to_aac_m4b.
        on_phase: callable(pct: int, msg: str) o None.
        status_out: dict opzionale popolato a fine conversione con
            {"status": "ok"|"fail"|"timeout"|"invalid", "pct": int, "msg": str}.
        **kwargs: tutti gli altri parametri di pcm_to_aac_m4b.

    Returns: bool come pcm_to_aac_m4b.
    """
    return _monitored_m4b_run(
        "pcm_to_aac_m4b_monitored",
        lambda: pcm_to_aac_m4b(pcm_paths, output_path, **kwargs),
        output_path, on_phase, status_out,
        "Conversione M4B — preparazione…",
        "Conversione M4B — encoding AAC (PCM→AAC diretto)…")
