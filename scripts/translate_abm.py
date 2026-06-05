#!/usr/bin/env python3
"""
translate_abm.py — Traduzione standalone di un progetto .abm in un'altra lingua.

CLI sottile sopra translation_core.py (libreria condivisa con la web app).
Prende un file .abm, lingua origine e destinazione, e produce un nuovo
.abm/.epub/.txt tradotto via LLM. Con --optimize integra nello stesso
passaggio LLM l'ottimizzazione del testo per la narrazione TTS.

Uso:
    python scripts/translate_abm.py libro.abm it en [--optimize]
        [--format abm|epub|txt] [--output out.abm] [--dry-run]

Configurazione: vedi translation_core.py e PARAMETRI_CONFIGURAZIONE.md
(env ABM_TRANSLATE_* con fallback ABM_LLM_*).

Report costi (solo CLI):
    ABM_TRANSLATE_INPUT_USD_PER_MTOK   (default 0.10 — gemini-2.5-flash-lite)
    ABM_TRANSLATE_OUTPUT_USD_PER_MTOK  (default 0.40 — gemini-2.5-flash-lite)
    ABM_TRANSLATE_USD_EUR_RATE         (default 0.86)
"""

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

import translation_core as tc  # noqa: E402

INPUT_USD_PER_MTOK = float(os.environ.get("ABM_TRANSLATE_INPUT_USD_PER_MTOK", "0.10"))
OUTPUT_USD_PER_MTOK = float(os.environ.get("ABM_TRANSLATE_OUTPUT_USD_PER_MTOK", "0.40"))
USD_EUR_RATE = float(os.environ.get("ABM_TRANSLATE_USD_EUR_RATE", "0.86"))


# ---------------------------------------------------------------------------
# Parsing .abm (self-contained, mirror semplificato di parse_abm dell'app)
# ---------------------------------------------------------------------------

def _safe_member(name):
    """True se il path dentro lo zip è sicuro (no zip-slip)."""
    norm = name.replace("\\", "/")
    return not (norm.startswith("/") or ".." in norm.split("/") or ":" in norm)


def parse_abm(path):
    """Ritorna (manifest, chapters, cover) dal file .abm.

    chapters: lista di dict {index, title, text}
    cover: (bytes, filename) oppure None
    """
    if not zipfile.is_zipfile(str(path)):
        raise ValueError("File .abm non valido: non è un archivio ZIP")

    with zipfile.ZipFile(str(path), "r") as zf:
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError:
            raise ValueError("File .abm non valido: manifest.json mancante")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"File .abm non valido: manifest.json malformato ({e})")

        if manifest.get("format") != "audiobook-maker-project":
            raise ValueError("File .abm non valido: formato non riconosciuto nel manifest")

        chapters_meta = manifest.get("chapters", [])
        if not chapters_meta:
            raise ValueError("File .abm non valido: nessun capitolo nel manifest")

        chapters = []
        for cm in chapters_meta:
            fname = cm.get("filename", "")
            raw_path = fname if fname.startswith("chapters/") else f"chapters/{fname}"
            if not _safe_member(raw_path):
                print(f"  [abm] WARNING: path capitolo non sicuro '{raw_path}', saltato")
                continue
            try:
                text = zf.read(raw_path).decode("utf-8").strip()
            except KeyError:
                print(f"  [abm] WARNING: file capitolo '{raw_path}' assente, saltato")
                continue
            except UnicodeDecodeError:
                text = zf.read(raw_path).decode("latin-1", errors="replace").strip()
            if not text:
                continue
            chapters.append({
                "index": cm.get("index", len(chapters) + 1),
                "title": cm.get("title", f"Chapter {cm.get('index', '?')}"),
                "text": text,
            })

        if not chapters:
            raise ValueError("File .abm non valido: nessun capitolo leggibile")

        cover = None
        if manifest.get("has_cover") and manifest.get("cover_file"):
            cf = manifest["cover_file"]
            if _safe_member(cf):
                try:
                    data = zf.read(cf)
                    if len(data) > 100:
                        cover = (data, cf)
                except KeyError:
                    pass

    return manifest, chapters, cover


# ---------------------------------------------------------------------------
# Validazione lingue edge-tts
# ---------------------------------------------------------------------------

def get_edge_languages():
    """Set dei codici lingua delle voci standard edge-tts (query live,
    fallback statico se offline)."""
    try:
        import asyncio
        import edge_tts

        async def _fetch():
            vman = await edge_tts.VoicesManager.create()
            return {v["Locale"].split("-")[0].lower() for v in vman.voices}

        langs = asyncio.run(_fetch())
        if langs:
            return langs, "live"
    except Exception as e:
        print(f"[langs] Query live edge-tts fallita ({type(e).__name__}: {e}), "
              f"uso lista statica di fallback")
    return tc.EDGE_LANGS_FALLBACK, "fallback"


# ---------------------------------------------------------------------------
# Report costi
# ---------------------------------------------------------------------------

def print_cost_report(usage, dry_run):
    """Stampa il riepilogo costi dell'esecuzione (da UsageTracker.report())."""
    r = usage.report()
    if r["calls"] == 0:
        if dry_run:
            print("[costo] DRY-RUN senza testo: nessun costo")
        return
    pt, ct = r["prompt_tokens"], r["completion_tokens"]
    in_usd = pt / 1e6 * INPUT_USD_PER_MTOK
    out_usd = ct / 1e6 * OUTPUT_USD_PER_MTOK
    tot_usd = in_usd + out_usd
    tot_eur = tot_usd * USD_EUR_RATE
    tag = " (STIMA da caratteri)" if r["estimated"] else ""
    head = "[costo] DRY-RUN — costo che AVREBBE avuto l'operazione:" \
        if dry_run else "[costo] Costo dell'operazione:"
    print(head)
    print(f"[costo]   Token input: {pt:,} | output: {ct:,}{tag} "
          f"su {r['calls']} chiamate LLM")
    print(f"[costo]   ${in_usd:.4f} input + ${out_usd:.4f} output = "
          f"${tot_usd:.4f} USD  ~  €{tot_eur:.4f} EUR "
          f"(tasso {USD_EUR_RATE}, tariffe {INPUT_USD_PER_MTOK}/"
          f"{OUTPUT_USD_PER_MTOK} $/Mtok)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Traduce un progetto .abm in un'altra lingua via LLM.")
    ap.add_argument("abm_file", help="File .abm di input")
    ap.add_argument("source_lang", help="Lingua di origine (codice ISO, es. it)")
    ap.add_argument("target_lang",
                    help="Lingua di destinazione (codice ISO, tra le lingue "
                         "delle voci standard edge-tts)")
    ap.add_argument("--optimize", action="store_true",
                    help="Integra l'ottimizzazione AI del testo per TTS")
    ap.add_argument("--format", choices=("abm", "epub", "txt"), default="abm",
                    help="Formato di output: abm (default), epub o txt")
    ap.add_argument("--output", help="Path del file di output "
                                     "(default: <input>_<target>.<formato>)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pipeline completa senza chiamate LLM (pass-through)")
    args = ap.parse_args()

    in_path = Path(args.abm_file)
    if not in_path.is_file():
        sys.exit(f"Errore: file non trovato: {in_path}")

    source = args.source_lang.strip().lower().split("-")[0]
    target = args.target_lang.strip().lower().split("-")[0]
    if not re.fullmatch(r"[a-z]{2,3}", source):
        sys.exit(f"Errore: codice lingua origine non valido: '{args.source_lang}'")
    if not re.fullmatch(r"[a-z]{2,3}", target):
        sys.exit(f"Errore: codice lingua destinazione non valido: '{args.target_lang}'")
    if source == target:
        sys.exit("Errore: lingua di origine e destinazione coincidono")

    edge_langs, langs_source = get_edge_languages()
    if target not in edge_langs:
        sys.exit(f"Errore: lingua destinazione '{target}' non disponibile tra "
                 f"le voci standard edge-tts (lista {langs_source}). "
                 f"Lingue valide: {', '.join(sorted(edge_langs))}")

    usage = tc.UsageTracker()
    client_provider = None
    model = tc.model_name()
    if not args.dry_run:
        try:
            backend = tc.resolve_backend()
        except tc.TranslationConfigError as e:
            sys.exit(f"Errore: {e}")
        client_provider, model, base_url = tc.make_client_provider(backend)

    manifest, chapters, cover = parse_abm(in_path)
    total_chars = sum(len(ch["text"]) for ch in chapters)
    print(f"Progetto: \"{manifest.get('title', in_path.stem)}\" — "
          f"{len(chapters)} capitoli, {total_chars} caratteri")
    print(f"Traduzione {source} -> {target}"
          + (" + ottimizzazione TTS" if args.optimize else "")
          + (" [DRY-RUN]" if args.dry_run else ""))
    if not args.dry_run:
        print(f"Backend: {backend} | Modello: {model} @ {base_url}")

    system_prompt = tc.build_system_prompt(source, target, args.optimize)

    out_chapters = []
    for i, ch in enumerate(chapters, 1):
        chunks = tc.split_text_into_chunks(ch["text"], tc.chunk_chars())
        print(f"[{i}/{len(chapters)}] \"{ch['title']}\" "
              f"({len(ch['text'])} caratteri, {len(chunks)} chunk)")
        translated_parts = []
        for j, chunk in enumerate(chunks, 1):
            label = f"[cap {i}/{len(chapters)} chunk {j}/{len(chunks)}]"
            if args.dry_run:
                usage.track(system_prompt, chunk, chunk)
                translated_parts.append(chunk)
            else:
                translated_parts.append(tc.call_llm(
                    client_provider, system_prompt, chunk,
                    model=model, usage=usage, label=label,
                    progress_cb=lambda n, _l=label: print(
                        f"\r  {_l} ricevuti {n} caratteri...", end="", flush=True)))
                print()
        out_chapters.append({
            "index": ch["index"],
            "title": ch["title"],
            "text": "\n\n".join(translated_parts),
        })

    print("Traduzione titoli capitoli...")
    titles = [ch["title"] for ch in out_chapters]
    translated_titles = tc.translate_titles(
        client_provider, titles, source, target,
        model=model, usage=usage, dry_run=args.dry_run)
    for ch, t in zip(out_chapters, translated_titles):
        ch["title"] = t.strip() or ch["title"]

    out_path = Path(args.output) if args.output \
        else in_path.with_name(f"{in_path.stem}_{target}.{args.format}")
    tc.writer_for_format(args.format)(
        out_path, manifest, out_chapters, cover, source, target, args.optimize)
    print(f"Fatto: {out_path}")
    print_cost_report(usage, args.dry_run)


if __name__ == "__main__":
    main()
