"""cover_utils — copertine: estrazione dall'EPUB, anteprima, ripiego generato,
copia nella cartella di consegna (F2b, 2026-10-10; prima in `audio_utils`).

Modulo foglia: stdlib, `PIL` (facoltativa: senza, l'estrazione fallisce in
modo pulito) e `secure_archive` per leggere gli archivi in sicurezza. Nessun
ffmpeg qui. I nomi restano quelli storici (`_extract_cover_from_epub`,
`_generate_fallback_cover`, `_extract_cover_for_preview`,
`_include_cover_in_dir`, `_zip_safe_read`): spostamento puro.
"""
import io
import os
import shutil


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
