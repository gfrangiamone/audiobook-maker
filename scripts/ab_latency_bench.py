#!/usr/bin/env python3
"""A/B di LATENZA fra Vertex e Cloudflare sul percorso di produzione.

Misura il tempo di parete di `gemini_tts.synthesize()` - la stessa funzione
che chiama un job vero, non un clone - chunk per chunk, sui due backend, con
lo stesso testo e lo stesso piano di chunk della produzione.

PERCHE' NON IL BANCO ESISTENTE: `scripts/cf_tts_bench.ps1 -Compare vertex`
confronta la QUALITA' su fixture da poche centinaia di caratteri, con una
implementazione HTTP propria, e a `-Level book` il confronto e' vietato per
non raddoppiare il costo. Qui serve il TEMPO su un testo di lunghezza
realistica, misurato sul codice che gira davvero in prod (retry e throttle
inclusi: sono parte dell'attesa dell'utente).

ORDINE ALTERNATO: per ogni chunk esegue entrambi i backend, invertendo
l'ordine a chunk alterni. Un run a blocchi (prima tutti CF, poi tutti Vertex)
attribuirebbe al secondo backend qualunque deriva della rete nel frattempo.

PREREQUISITI: entrambi i backend configurati nella stessa sessione. Nota che
`gemini_tts.is_available()` e' un check GLOBALE che non vede mai Cloudflare:
senza Vertex (o una API key) anche il solo ramo Cloudflare solleva
GeminiUnavailable. Il modo piu' rapido di avere tutto configurato:

    .\\scripts\\run_local.ps1 -NoStart      # imposta le env nella sessione
    python scripts\\ab_latency_bench.py --chars 4000

COSTA DAVVERO: sintetizza il testo una volta per backend. La spesa Cloudflare
entra nel ledger del credito (stesso ABM_DATA_DIR della sessione). La stima
viene stampata e confermata prima di qualunque chiamata.
"""
import argparse
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gemini_tts          # noqa: E402
import tts_backend_state   # noqa: E402
import tts_split           # noqa: E402

MODEL_KEY = "flash31"

# Prosa neutra, tre paragrafi. Ciclata fino a --chars quando manca
# --text-file: per la latenza il contenuto e' indifferente, ma la ripetizione
# va dichiarata nel report perche' l'audio suona ripetitivo.
SAMPLE = [
    "La casa in fondo alla strada era rimasta vuota per tutto l'inverno. "
    "Nessuno ne parlava, ma ogni tanto qualcuno rallentava il passo davanti "
    "al cancello, come per accertarsi che fosse ancora chiuso.",
    "Il mercato apriva presto, quando la luce era ancora incerta e i banchi "
    "sembravano tutti uguali. Bastava mezz'ora perche' le voci si "
    "sovrapponessero e il posto diventasse irriconoscibile.",
    "Aveva imparato a riconoscere il rumore del treno molto prima di vederlo. "
    "Prima una vibrazione appena percettibile, poi il fischio, poi la lunga "
    "esitazione dei freni contro le rotaie.",
]


def build_text(path, chars):
    if path:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()[:chars], False
    out, total, i = [], 0, 0
    while total < chars:
        p = SAMPLE[i % len(SAMPLE)]
        out.append(p)
        total += len(p) + 1
        i += 1
    return " ".join(out)[:chars], i > len(SAMPLE)


def force_backend(backend):
    """Impone il backend per il prossimo synthesize().

    `_resolve_backend` memorizza la scelta in `_BACKEND` per model_key e non
    rilegge piu' l'ambiente: senza invalidare quella cache (e `_available`,
    che dipende dalla stessa risoluzione) il secondo ramo dell'A/B girerebbe
    in silenzio sul backend del primo. Tocca due privati di un modulo di
    produzione: e' il prezzo di misurare il percorso vero invece di un clone.
    """
    os.environ["ABM_GEMINI_BACKEND"] = backend
    gemini_tts._BACKEND.clear()
    gemini_tts._available = None
    return gemini_tts._resolve_backend(MODEL_KEY)


def preconditions():
    """Fallisce PRIMA di spendere: un A/B a meta' costa e non dice nulla."""
    errs = []
    if not (os.environ.get("ABM_CF_ACCOUNT_ID") and os.environ.get("ABM_CF_API_TOKEN")):
        errs.append("Cloudflare non configurato (ABM_CF_ACCOUNT_ID / ABM_CF_API_TOKEN)")
    creds = os.environ.get("ABM_GOOGLE_CREDENTIALS_FILE") or ""
    if not (os.environ.get("ABM_GCP_PROJECT_ID") and creds and os.path.isfile(creds)):
        errs.append("Vertex non configurato (ABM_GCP_PROJECT_ID / "
                    "ABM_GOOGLE_CREDENTIALS_FILE, file esistente). Serve anche "
                    "per il solo ramo Cloudflare: is_available() e' globale e "
                    "non vede mai Cloudflare.")
    try:
        if tts_backend_state.is_tripped(MODEL_KEY):
            errs.append(f"circuit breaker SCATTATO su {MODEL_KEY}: Cloudflare "
                        "verrebbe forzato su Vertex e misureresti Vertex due "
                        "volte. Reset dalla console admin prima di misurare.")
    except Exception as exc:
        errs.append(f"stato del breaker illeggibile: {exc}")
    return errs


def synth_once(backend, text, voice_id, out_path, style, rate):
    """Una chiamata sul percorso di prod, cronometrata dal chiamante."""
    risolto = force_backend(backend)
    if risolto != backend:
        return {"ms": 0.0, "audio_sec": 0.0, "tok_out": 0, "attempts": 0,
                "ok": False, "backend_reale": risolto,
                "err": f"backend risolto '{risolto}' invece di '{backend}': "
                       "chiamata NON effettuata"}
    t0 = time.perf_counter()
    err, res = None, {}
    try:
        res = gemini_tts.synthesize(text, voice_id, rate=rate, output_path=out_path,
                                    style_instruction=style)
    except Exception as exc:
        err = f"{type(exc).__name__}: {str(exc)[:160]}"
    return {
        "ms": (time.perf_counter() - t0) * 1000.0,
        "audio_sec": res.get("audio_seconds_real") or 0.0,
        "tok_out": res.get("output_tokens") or 0,
        "attempts": res.get("attempts_used") or 0,
        "backend_reale": res.get("backend"),
        "ok": bool(res.get("success")) and err is None,
        "err": err,
    }


def aggregate(rows, chars_tot):
    ok = [r for r in rows if r["ok"]]
    if not ok:
        return None
    ms = sorted(r["ms"] for r in ok)
    audio = sum(r["audio_sec"] for r in ok)
    wall = sum(ms) / 1000.0
    return {
        "chunk_ok": len(ok), "chunk_ko": len(rows) - len(ok),
        "wall_sec": wall, "audio_sec": audio,
        "med_ms": statistics.median(ms), "min_ms": ms[0], "max_ms": ms[-1],
        "p95_ms": ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))],
        "retry": sum(1 for r in ok if r["attempts"] > 1),
        # Quante volte piu' veloce del tempo reale: e' la grandezza che decide
        # quanto aspetta l'utente su un libro intero.
        "x_realtime": (audio / wall) if wall > 0 else 0.0,
        "char_per_sec": (chars_tot / wall) if wall > 0 else 0.0,
        "backend_reali": sorted({r["backend_reale"] or "?" for r in ok}),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="A/B latenza Vertex vs Cloudflare")
    ap.add_argument("--text-file", help="Testo UTF-8 (consigliato: un capitolo vero)")
    ap.add_argument("--chars", type=int, default=4000, help="Caratteri (default 4000)")
    ap.add_argument("--voice", default="Zephyr")
    ap.add_argument("--lang", default="it")
    ap.add_argument("--rate", default="+0%")
    ap.add_argument("--style", default=None)
    ap.add_argument("--max-chunks", type=int, default=12,
                    help="Tetto duro sui chunk misurati (default 12)")
    ap.add_argument("--only", choices=("cloudflare", "vertex"), default=None,
                    help="Misura un solo backend (niente A/B)")
    ap.add_argument("--keep-audio", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="Piano dei chunk e stima di costo, nessuna chiamata")
    ap.add_argument("--yes", action="store_true", help="Salta la conferma")
    args = ap.parse_args(argv)

    data_dir = os.environ.get("ABM_DATA_DIR")
    if data_dir and os.path.isdir(data_dir):
        # Senza init la cache del breaker resta vuota e is_tripped() mente:
        # misureresti Cloudflare dove la prod usa gia' Vertex.
        tts_backend_state.init(data_dir)
    else:
        print("[attenzione] ABM_DATA_DIR assente: stato del breaker non "
              "caricato, il controllo di trip non e' attendibile.")

    voice_id = f"gemini:{MODEL_KEY}:{args.voice}"
    backends = [args.only] if args.only else ["cloudflare", "vertex"]

    text, ripetuto = build_text(args.text_file, args.chars)
    if not text:
        print("[errore] testo vuoto")
        return 1
    max_chars = tts_split._pick_chunk_max_chars(voice_id, args.lang)
    chunks = tts_split.split_text_into_chunks(text, max_chars=max_chars)[:args.max_chunks]
    chars_tot = sum(len(c) for c in chunks)
    testo_misurato = " ".join(chunks)

    tok_in = gemini_tts.estimate_input_tokens(testo_misurato, args.lang)
    tok_out = gemini_tts.estimate_output_tokens(testo_misurato, language=args.lang,
                                                model_key=MODEL_KEY, voice=args.voice)
    print(f"chunk: {len(chunks)} da max {max_chars} char  |  caratteri misurati: {chars_tot}")
    if not os.environ.get("ABM_GEMINI_CHUNK_CHARS"):
        # In prod la variabile vale 450 (non il default 700 del codice): con
        # chunk piu' piccoli le chiamate sono piu' numerose e la latenza per
        # chunk piu' bassa, quindi i due run non sono confrontabili fra loro.
        print("nota: ABM_GEMINI_CHUNK_CHARS non impostata (default codice 700). "
              "Per riprodurre la prod esportala a 450 prima del run.")
    if ripetuto:
        print("nota: campione incorporato ciclato (audio ripetitivo, la latenza "
              "non ne risente). Con --text-file usi il testo vero.")
    stima = 0.0
    for b in backends:
        usd = gemini_tts.actual_cost_breakdown(tok_in, tok_out, MODEL_KEY, b)["total_usd"]
        stima += usd
        print(f"  stima {b:<10} USD {usd:.4f}")
    print(f"  TOTALE stimato USD {stima:.4f} (spesa reale, non simulata)")

    if args.dry_run:
        print("--dry-run: nessuna chiamata effettuata.")
        return 0
    errs = preconditions()
    if args.only == "vertex":
        errs = [e for e in errs if not e.startswith("Cloudflare")]
    if errs:
        print("\n[errore] prerequisiti mancanti, nessuna chiamata effettuata:")
        for e in errs:
            print(f"  - {e}")
        return 1
    if not args.yes:
        if input("procedo? [s/N] ").strip().lower() not in ("s", "si", "y", "yes"):
            print("annullato.")
            return 1

    tmp = tempfile.mkdtemp(prefix="ab_lat_")
    backend_originale = os.environ.get("ABM_GEMINI_BACKEND")
    rows = {b: [] for b in backends}
    try:
        for i, chunk in enumerate(chunks):
            # Ordine invertito a chunk alterni: neutralizza il warm-up e la
            # deriva della rete, che altrimenti finirebbero su un backend solo.
            for b in (backends if i % 2 == 0 else list(reversed(backends))):
                r = synth_once(b, chunk, voice_id,
                               os.path.join(tmp, f"{i:03d}_{b}.pcm"),
                               args.style, args.rate)
                rows[b].append(r)
                nota = ""
                if r["ok"] and r["backend_reale"] != b:
                    nota = f"  <-- ESEGUITO SU {(r['backend_reale'] or '?').upper()}"
                elif r["attempts"] > 1:
                    nota = f"  ({r['attempts']} tentativi)"
                if r["err"]:
                    nota = f"  ERRORE {r['err']}"
                print(f"  chunk {i + 1:>2}/{len(chunks)} {b:<10} "
                      f"{r['ms'] / 1000:6.2f}s  audio {r['audio_sec']:5.1f}s{nota}")
    finally:
        if backend_originale is None:
            os.environ.pop("ABM_GEMINI_BACKEND", None)
        else:
            os.environ["ABM_GEMINI_BACKEND"] = backend_originale
        gemini_tts._BACKEND.clear()
        gemini_tts._available = None

    print("\n=== RISULTATO ===")
    agg = {}
    for b in backends:
        a = agg[b] = aggregate(rows[b], chars_tot)
        if not a:
            print(f"{b}: nessun chunk riuscito")
            continue
        print(f"{b}: {a['wall_sec']:.1f}s totali su {a['chunk_ok']} chunk "
              f"(ko {a['chunk_ko']}, con retry {a['retry']})  "
              f"mediana {a['med_ms'] / 1000:.2f}s  p95 {a['p95_ms'] / 1000:.2f}s  "
              f"min {a['min_ms'] / 1000:.2f}s  max {a['max_ms'] / 1000:.2f}s")
        print(f"     {a['x_realtime']:.2f}x tempo reale  |  "
              f"{a['char_per_sec']:.0f} char/s  |  audio {a['audio_sec']:.0f}s  |  "
              f"backend reali: {', '.join(a['backend_reali'])}")
    if len(backends) == 2 and all(agg.get(b) for b in backends):
        cf, vx = agg["cloudflare"], agg["vertex"]
        r = cf["med_ms"] / vx["med_ms"] if vx["med_ms"] else 0
        verso = "PIU' LENTO" if r > 1 else "piu' veloce"
        print(f"\nCloudflare e' {r:.2f}x {verso} di Vertex sulla mediana per chunk.")
        # Il dato che conta per l'attesa percepita: proiezione su un libro.
        if cf["x_realtime"] and vx["x_realtime"]:
            ore = 6
            print(f"Proiezione su {ore}h di audio: Cloudflare "
                  f"{ore * 3600 / cf['x_realtime'] / 60:.0f} min, Vertex "
                  f"{ore * 3600 / vx['x_realtime'] / 60:.0f} min (chunk "
                  "sequenziali, come in produzione).")
    if args.keep_audio:
        print(f"\naudio PCM in {tmp}")
    else:
        for f in os.listdir(tmp):
            try:
                os.remove(os.path.join(tmp, f))
            except OSError:
                pass
        os.rmdir(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
