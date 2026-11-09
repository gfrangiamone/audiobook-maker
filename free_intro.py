"""free_intro — inserto iniziale dei libri gratuiti letti con edge-tts.

Un audiolibro letto da una voce standard (edge-tts) per chi non ha un
abbonamento comincia con una frase che dichiara il servizio, nella lingua del
libro: «Questo libro e' stato generato gratuitamente tramite il servizio
audiobook maker punto com. Buon ascolto!». Il pagamento di traduzione od
ottimizzazione AI non lo toglie: la sintesi resta gratuita. Testo e voce di
ripiego per lingua in `i18n/free_intro.json`; una lingua che non c'e' esce
senza inserto.

La frase e' letta dalla voce edge standard piu' usata per quella lingua nei
GENERATE degli ultimi `_USO_GIORNI` giorni del business log, non da quella del
libro; senza dati, o se quella voce non da' audio, dalla voce del JSON. Le
Multilingual restano fuori: su una frase breve indovinano la lingua e sbandano.

Cache in `<data dir>/_free_intros/`: un MP3 per lingua e testo
(`<lingua>-<sha1 del testo>.mp3`, accanto un `.json` con la voce), sintetizzato
alla prima occorrenza e poi copiato. Il `_` in testa lo tiene fuori dalle job
dir (`cleanup._is_job_dir`). Un testo cambiato produce un file nuovo e toglie i
vecchi della stessa lingua: al piu' un file per lingua, nessuna retention a
tempo.
"""
import asyncio
import hashlib
import shutil
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

import activity_log
import edge_engine
import i18n
from env_utils import env_bool
from fileio import atomic_produce, data_path, load_json, write_json_safe
from tts_split import _is_multilingual_voice
from user_stats import GENERATE_OP
from voice_utils import engine_for_voice, voice_id_shape_ok

# Titolo del capitolo M4B, del file nello ZIP e dell'episodio del podcast.
# Il file e' il numero 000: i capitoli partono da 001, e `podcast_rss` legge
# il titolo di un file 000 dal suo nome.
CHAPTER_TITLE = "audiobook-maker.com"
FILE_NAME = f"000_{CHAPTER_TITLE}.mp3"
CACHE_DIRNAME = "_free_intros"
# Flag del job: utente con abbonamento pagato al momento della richiesta.
SUBSCRIBER_KEY = "gen_subscriber"
_USO_GIORNI = 90

_locks_guard = threading.Lock()
_locks = {}


def enabled():
    return env_bool("ABM_FREE_INTRO_ENABLE", True)


def intro_lang(voice, job_lang=""):
    """Lingua dell'inserto: quella della voce; per una Multilingual, che legge
    la lingua del testo, quella del job."""
    if _is_multilingual_voice(voice) and job_lang:
        return i18n.norm_lang(job_lang)
    return i18n.norm_lang(voice)


def _entry(lang):
    """{"text", "voice"} della lingua, o None se manca il testo."""
    e = i18n.load("free_intro").get(lang)
    return e if isinstance(e, dict) and e.get("text") else None


def _is_standard_voice_of(voice, lang):
    return (engine_for_voice(voice) == "edge" and voice_id_shape_ok(voice)
            and not _is_multilingual_voice(voice) and i18n.norm_lang(voice) == lang)


def most_used_voice(lang, now=None):
    """Voce edge standard piu' usata per `lang` nei GENERATE degli ultimi
    `_USO_GIORNI` giorni (a parita', la prima in ordine alfabetico), o None."""
    since = (now or datetime.now()) - timedelta(days=_USO_GIORNI)
    uso = Counter(row.voice for row in activity_log.iter_rows(since, ops={GENERATE_OP})
                  if _is_standard_voice_of(row.voice, lang))
    return min(uso, key=lambda v: (-uso[v], v)) if uso else None


def _candidate_voices(lang, entry):
    try:
        top = most_used_voice(lang)
    except Exception as e:      # noqa: BLE001 - senza log resta la voce del JSON
        print(f"[free-intro] uso voci {lang} non letto: {e}", flush=True)
        top = None
    return [v for v in dict.fromkeys((top, entry.get("voice"))) if v]


def _synth(text, voice, out_path):
    """MP3 di `text` letto da `voice`; False se edge-tts non da' audio (il suo
    secondo di silenzio di ripiego non e' un inserto)."""
    loop = asyncio.new_event_loop()
    try:
        ok = loop.run_until_complete(edge_engine.generate_chunk_mp3(text, voice, "+0%", out_path))
    finally:
        loop.close()
    return ok is not False


def _cache_file(lang, text):
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return data_path(CACHE_DIRNAME) / f"{lang}-{digest}.mp3"


def _lang_lock(lang):
    with _locks_guard:
        return _locks.setdefault(lang, threading.Lock())


def _drop_stale(lang, keep):
    """Toglie i file della lingua scritti per un testo diverso da quello di `keep`."""
    for f in keep.parent.glob(f"{lang}-*"):
        if f.stem != keep.stem:
            try:
                f.unlink()
            except OSError as e:
                print(f"[free-intro] {f.name} non rimosso: {e}", flush=True)


def _cached_or_synth(lang, entry):
    """(path, voce, dalla cache) dell'inserto della lingua; lo sintetizza se
    manca. None se nessuna voce candidata da' audio (niente in cache)."""
    path = _cache_file(lang, entry["text"])
    meta = path.with_suffix(".json")
    with _lang_lock(lang):
        if path.is_file() and path.stat().st_size > 0:
            return path, load_json(meta, {}, expect=dict).get("voice", ""), True
        for voice in _candidate_voices(lang, entry):
            try:
                if atomic_produce(path, lambda tmp, v=voice: _synth(entry["text"], v, tmp)):
                    break
            except Exception as e:      # noqa: BLE001 - si prova la voce successiva
                print(f"[free-intro] {lang} con {voice}: {e}", flush=True)
        else:
            return None
        write_json_safe(meta, {"lang": lang, "voice": voice, "text": entry["text"],
                               "created": datetime.now(timezone.utc).isoformat()})
        _drop_stale(lang, path)
    return path, voice, False


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
