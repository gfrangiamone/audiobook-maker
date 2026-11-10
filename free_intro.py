"""free_intro — inserto iniziale dei libri gratuiti letti con edge-tts.

Un audiolibro letto da una voce standard (edge-tts) per chi non ha un
abbonamento comincia con una frase che dichiara il servizio, nella lingua del
libro: «Questo libro e' stato generato gratuitamente tramite il servizio
audiobook maker punto com. Buon ascolto!». Il pagamento di traduzione od
ottimizzazione AI non lo toglie: la sintesi resta gratuita. Testi per lingua in
`i18n/free_intro.json`; una lingua che non c'e' esce senza inserto.

La frase e' letta da Gemini 3.8 (`MODEL_KEY`) con la voce fissa `VOCE` in tutte
le lingue, non da edge, la cui lettura dell'inserto suonava male (10/11/2026).
Niente ripiego su edge: se Gemini non da' audio il libro esce senza inserto e
la lingua resta in pausa `_PAUSA_S` secondi, cosi' un guasto di Gemini non
aggiunge una chiamata fallita a ogni libro.

Cache in `<data dir>/_free_intros/`: un MP3 per lingua, modello e testo
(`<lingua>-<sha1>.mp3`, accanto un `.json` con la voce), 24 kHz mono come gli
MP3 di edge perche' si concatena al libro senza ricodifica, e portato alla
loudness delle voci edge (`_LUFS`) perche' non stacchi dal libro. Sintetizzato alla
prima occorrenza e poi copiato. Il `_` in testa lo tiene fuori dalle job dir
(`cleanup._is_job_dir`). Un testo o un modello cambiato produce un file nuovo e
toglie i vecchi della stessa lingua: al piu' un file per lingua, nessuna
retention a tempo. All'avvio `start_refresh` rifa' subito quelli superati,
senza aspettare il prossimo libro della lingua.
"""
import hashlib
import os
import shutil
import threading
import time
from datetime import datetime, timezone

import ffmpeg_tools
import gemini_tts
import i18n
from audio_utils import pcm_to_mp3
from env_utils import env_bool
from fileio import atomic_produce, data_path, load_json, write_json_safe
from tts_split import _is_multilingual_voice
from voice_utils import engine_for_voice

# Titolo del capitolo M4B, del file nello ZIP e dell'episodio del podcast.
# Il file e' il numero 000: i capitoli partono da 001, e `podcast_rss` legge
# il titolo di un file 000 dal suo nome.
CHAPTER_TITLE = "audiobook-maker.com"
FILE_NAME = f"000_{CHAPTER_TITLE}.mp3"
CACHE_DIRNAME = "_free_intros"
# Flag del job: utente con abbonamento pagato al momento della richiesta.
SUBSCRIBER_KEY = "gen_subscriber"
MODEL_KEY = "flash38"
# Voce dell'inserto in tutte le lingue (scelta dell'utente, 10/11/2026). Non
# entra nella chiave della cache: per cambiarla vanno tolti i file in cache.
VOCE = "Orus"
# Bitrate degli MP3 di edge (audio-24khz-48kbitrate-mono-mp3).
_MP3_BITRATE = "48k"
# Loudness delle voci edge (Jenny -20,1, Denise -20,0, Diego -20,7, Katja -21,2
# LUFS, 10/11/2026): Gemini esce 1-4 LU piu' forte e l'inserto stacchererebbe
# dal libro. Correzione massima `_GAIN_MAX_DB`: oltre e' un difetto, non un livello.
_LUFS = -20.0
_GAIN_MAX_DB = 12.0
_TENTATIVI = 2
_PAUSA_S = 600

_locks_guard = threading.Lock()
_locks = {}
_pausa_fino = {}


def enabled():
    return env_bool("ABM_FREE_INTRO_ENABLE", True)


def intro_lang(voice, job_lang=""):
    """Lingua dell'inserto: quella della voce; per una Multilingual, che legge
    la lingua del testo, quella del job."""
    if _is_multilingual_voice(voice) and job_lang:
        return i18n.norm_lang(job_lang)
    return i18n.norm_lang(voice)


def _entry(lang):
    """{"text"} della lingua, o None se manca il testo."""
    e = i18n.load("free_intro").get(lang)
    return e if isinstance(e, dict) and e.get("text") else None


def _gain_db(pcm):
    """Guadagno che porta il PCM di Gemini a `_LUFS`; 0 se non misurabile."""
    lufs = ffmpeg_tools.loudness_lufs(pcm, in_rate=gemini_tts.AUDIO_SAMPLE_RATE)
    if lufs is None:
        return 0.0
    return max(-_GAIN_MAX_DB, min(_GAIN_MAX_DB, _LUFS - lufs))


def _synth(text, lang, voice, out_path):
    """MP3 di `text` letto da Gemini con la voce `voice`, a `_LUFS`; False se
    Gemini non e' disponibile o non da' audio. Solleva gli errori della sintesi."""
    if not gemini_tts.is_available() or gemini_tts.model_unavailable(MODEL_KEY):
        return False
    pcm, pcm_norm = f"{out_path}.pcm", f"{out_path}.norm.pcm"
    try:
        gemini_tts.synthesize(text, f"gemini:{MODEL_KEY}:{voice}", output_path=pcm,
                              accent_directive=gemini_tts.build_accent_directive(lang) or None,
                              max_attempts=_TENTATIVI)
        if not ffmpeg_tools.pcm_transcode(pcm, pcm_norm, in_rate=gemini_tts.AUDIO_SAMPLE_RATE,
                                          out_rate=gemini_tts.AUDIO_SAMPLE_RATE,
                                          filters=f"volume={_gain_db(pcm):.2f}dB",
                                          tag="free-intro"):
            return False
        return pcm_to_mp3([pcm_norm], out_path, bitrate=_MP3_BITRATE)
    finally:
        for p in (pcm, pcm_norm):
            try:
                os.remove(p)
            except OSError:
                pass


def _cache_file(lang, text):
    digest = hashlib.sha1(f"{MODEL_KEY}\n{text}".encode("utf-8")).hexdigest()[:12]
    return data_path(CACHE_DIRNAME) / f"{lang}-{digest}.mp3"


def _lang_lock(lang):
    with _locks_guard:
        return _locks.setdefault(lang, threading.Lock())


def _drop_stale(lang, keep):
    """Toglie i file della lingua scritti per un testo o un modello diverso."""
    for f in keep.parent.glob(f"{lang}-*"):
        if f.stem != keep.stem:
            try:
                f.unlink()
            except OSError as e:
                print(f"[free-intro] {f.name} non rimosso: {e}", flush=True)


def _cached_or_synth(lang, entry):
    """(path, voce, dalla cache) dell'inserto della lingua; lo sintetizza se
    manca. None se Gemini non da' audio o la lingua e' in pausa dopo un
    fallimento (niente in cache)."""
    path = _cache_file(lang, entry["text"])
    meta = path.with_suffix(".json")
    with _lang_lock(lang):
        if path.is_file() and path.stat().st_size > 0:
            return path, load_json(meta, {}, expect=dict).get("voice", ""), True
        if time.monotonic() < _pausa_fino.get(lang, 0.0):
            return None
        try:
            ok = atomic_produce(path, lambda tmp: _synth(entry["text"], lang, VOCE, tmp))
        except Exception as e:      # noqa: BLE001 - libro senza inserto, si riprova dopo la pausa
            print(f"[free-intro] {lang} con {VOCE}: {e}", flush=True)
            ok = False
        if not ok:
            _pausa_fino[lang] = time.monotonic() + _PAUSA_S
            return None
        voice_id = f"gemini:{MODEL_KEY}:{VOCE}"
        write_json_safe(meta, {"lang": lang, "voice": voice_id, "text": entry["text"],
                               "created": datetime.now(timezone.utc).isoformat()})
        _drop_stale(lang, path)
    return path, voice_id, False


def prepare(job, voice, job_lang, dest):
    """Copia in `dest` l'MP3 dell'inserto del libro letto da `voice`, o None
    se non va messo (voce non edge, abbonato, lingua senza testo, spento).

    Ritorna {"path", "lang", "voice", "cached"}. Non solleva: senza inserto il
    libro esce lo stesso.
    """
    if not enabled() or engine_for_voice(voice) != "edge" or job.get(SUBSCRIBER_KEY):
        return None
    lang = intro_lang(voice, job_lang)
    entry = _entry(lang)
    if entry is None:
        print(f"[free-intro] nessun testo per la lingua {lang!r} ({voice}): libro senza inserto",
              flush=True)
        return None
    try:
        got = _cached_or_synth(lang, entry)
        if got is None:
            print(f"[free-intro] inserto {lang} senza audio: libro senza inserto", flush=True)
            return None
        path, used_voice, cached = got
        shutil.copyfile(path, dest)
    except Exception as e:      # noqa: BLE001 - l'inserto non deve fermare il libro
        print(f"[free-intro] inserto {lang} non preparato: {e}", flush=True)
        return None
    return {"path": str(dest), "lang": lang, "voice": used_voice, "cached": cached}


def refresh_cached():
    """Rifa' gli inserti in cache scritti per un altro testo o modello (i
    vecchi letti da edge). Ritorna le lingue rifatte."""
    if not enabled():
        return []
    rifatte = []
    for lang in sorted({f.name.split("-", 1)[0] for f in data_path(CACHE_DIRNAME).glob("*.mp3")}):
        entry = _entry(lang)
        if entry is None or _cache_file(lang, entry["text"]).is_file():
            continue
        if _cached_or_synth(lang, entry):
            rifatte.append(lang)
        else:
            print(f"[free-intro] inserto {lang} non rifatto: resta quello vecchio, non usato",
                  flush=True)
    return rifatte


def start_refresh():
    """`refresh_cached` in un thread daemon: all'avvio, una volta."""
    def _run():
        try:
            rifatte = refresh_cached()
        except Exception as e:      # noqa: BLE001 - ci riprova il prossimo libro della lingua
            print(f"[free-intro] refresh della cache non riuscito: {e}", flush=True)
            return
        if rifatte:
            print(f"[free-intro] inserti rifatti con {MODEL_KEY}: {', '.join(rifatte)}", flush=True)
    threading.Thread(target=_run, daemon=True, name="free-intro-refresh").start()
