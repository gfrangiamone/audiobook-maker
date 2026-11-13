"""catalog_intro — inserto iniziale degli audiolibri del catalogo gratuito.

Spec catalogo §5.6 (decisione D13). Con `ABM_CATALOG_INTRO_DIR` impostata, e mai
in produzione, l'M4B di un libro a file unico comincia con un capitolo breve
letto da Gemini 3.8 che dichiara la produzione con i servizi premium di
audiobook-maker.com e invita a visitare il sito.

La cartella contiene `manifest.json` e i PCM prodotti dal repo del catalogo
(`abm-free-catalog/tools/make_intros.py`), uno per variante di lingua e sesso:

    {"<lingua>[-<accento>]": {"chapter": "Introduzione",
                              "f": {"file": "it-f.pcm", "sha256": "...",
                                    "voice": "gemini:flash38:Sulafat",
                                    "seconds": 13.8, "lufs": -17.7},
                              "m": {...}}}

I PCM sono s16le 24 kHz mono, come escono da Gemini. Per il libro si sceglie la
variante della sua lingua e del suo accento (`it`, `pt-br`, `es-419`, ...) con il
sesso della sua voce, la si porta alla loudness misurata sul libro e al suo
sample rate (VoxCPM 48 kHz) e la si mette prima del primo capitolo.
"""
import os

import ffmpeg_tools
import gemini_tts
import pocket_tts
import voxcpm_catalog
from env_utils import env_str, is_public_https_url
from fileio import file_sha256, load_json
from voice_utils import VOXCPM_CATALOG_PREFIX, engine_for_voice

INTRO_RATE = ffmpeg_tools.PCM_SAMPLE_RATE      # i PCM del manifest escono da Gemini
# Audio del libro su cui si misura la loudness: abbastanza per una misura
# stabile, poco per una misura rapida anche su un libro di molte ore.
_MISURA_S = 180
# Correzione massima: oltre, l'inserto o il libro hanno un difetto da vedere a
# orecchio, non da compensare.
_GAIN_MAX_DB = 12.0
_SESSI = {"Female": "f", "Male": "m"}
_avvisato = set()


def intro_dir():
    """Cartella degli inserti, o None (spenta, o produzione)."""
    d = env_str("ABM_CATALOG_INTRO_DIR")
    if not d:
        return None
    if is_public_https_url(env_str("ABM_BASE_URL")):
        if "prod" not in _avvisato:
            _avvisato.add("prod")
            print("[catalog-intro] ABM_CATALOG_INTRO_DIR ignorata in produzione", flush=True)
        return None
    return d


def _accento_da_locale(lang, locale):
    """Codice accento di gemini_tts per una voce `ll-RR` ('pt-PT' -> 'pt'),
    o None per le lingue senza varianti."""
    codici = [c for c, _ in gemini_tts.accent_options(lang)]
    if not codici or "-" not in (locale or ""):
        return None
    regione = locale.split("-", 1)[1].lower()
    if regione in codici:
        return regione
    # Spagnolo d'America (es-AR, es-MX, es-CO, ...): una variante sola.
    return "419" if "419" in codici else None


def voice_traits(voice_id, lang, gemini_accent=None):
    """(sesso 'f'/'m', accento) della voce del libro; (None, None) se ignoti."""
    engine = engine_for_voice(voice_id)
    if engine == "gemini":
        sesso = gemini_tts.GEMINI_VOICE_GENDER.get(voice_id.split(":")[-1])
        accento = gemini_accent or gemini_tts.default_accent_code(lang)
    elif engine in ("voxcpm", "pocket"):
        # Le voci Pocket sono quelle del catalogo VoxCPM (voci_inventate), con
        # lo stesso locale e lo stesso nome: sesso e accento vengono da li'.
        try:
            if engine == "pocket":
                _, locale, name = pocket_tts.parse_voice_id(voice_id)
                voice_id = f"{VOXCPM_CATALOG_PREFIX}{locale}/{name}"
            rec = voxcpm_catalog.parse_voice_id(voice_id)
        except ValueError:
            rec = {}
        sesso = rec.get("gender")
        accento = _accento_da_locale(lang, rec.get("locale"))
    else:
        return None, None
    return _SESSI.get(sesso), accento


def pick(manifest, lang, accent, sesso):
    """Chiave del manifest per il libro: prima `<lingua>-<accento>`, poi `<lingua>`."""
    for key in ((f"{lang}-{accent}" if accent else None), lang):
        if key and isinstance(manifest.get(key), dict) and sesso in manifest[key]:
            return key
    return None


def _loudness_libro(parts, sample_rate, work_dir):
    """LUFS dei primi `_MISURA_S` secondi di audio del libro (file PCM `parts`)."""
    budget = int(_MISURA_S * sample_rate * ffmpeg_tools.PCM_SAMPLE_WIDTH)
    campione = os.path.join(str(work_dir), "_intro_misura.pcm")
    try:
        with open(campione, "wb") as out:
            for p in parts:
                if budget <= 0:
                    break
                try:
                    with open(p, "rb") as f:
                        dati = f.read(budget)
                except OSError:
                    continue
                out.write(dati)
                budget -= len(dati)
        return ffmpeg_tools.loudness_lufs(campione, in_rate=sample_rate)
    finally:
        try:
            os.remove(campione)
        except OSError:
            pass


def prepare(voice_id, lang, *, sample_rate, book_parts, work_dir, gemini_accent=None):
    """PCM dell'inserto pronto per il libro, o None se non va messo.

    Ritorna {"path", "chapter", "key", "voice", "sha256", "gain_db"}: `path` e'
    un PCM s16le mono a `sample_rate` in `work_dir`, alla loudness misurata su
    `book_parts`. Non solleva: senza inserto il libro esce lo stesso.
    """
    d = intro_dir()
    if d is None:
        return None
    try:
        manifest = load_json(os.path.join(d, "manifest.json"), {}, expect=dict)
        sesso, accento = voice_traits(voice_id, lang, gemini_accent)
        key = pick(manifest, lang, accento, sesso) if sesso else None
        if key is None:
            print(f"[catalog-intro] nessun inserto per lingua={lang} accento={accento} "
                  f"sesso={sesso} ({voice_id})", flush=True)
            return None
        v = manifest[key][sesso]
        src = os.path.join(d, v["file"])
        if file_sha256(src) != v.get("sha256"):
            print(f"[catalog-intro] {v['file']}: sha256 diverso dal manifest, inserto saltato",
                  flush=True)
            return None
        gain = 0.0
        libro = _loudness_libro(book_parts, sample_rate, work_dir)
        if libro is not None and v.get("lufs") is not None:
            gain = max(-_GAIN_MAX_DB, min(_GAIN_MAX_DB, libro - float(v["lufs"])))
        dst = os.path.join(str(work_dir), "_intro.pcm")
        if not ffmpeg_tools.pcm_transcode(src, dst, in_rate=INTRO_RATE, out_rate=sample_rate,
                                          filters=f"volume={gain:.2f}dB", tag="catalog-intro"):
            return None
    except Exception as e:      # noqa: BLE001 - l'inserto non deve fermare il libro
        print(f"[catalog-intro] inserto non preparato: {e}", flush=True)
        return None
    return {"path": dst, "chapter": manifest[key].get("chapter") or "Intro", "key": key,
            "voice": v.get("voice"), "sha256": v.get("sha256"), "gain_db": round(gain, 2)}
