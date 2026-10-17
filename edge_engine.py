"""edge_engine — sintesi di un chunk con Microsoft Edge TTS (F1d, 2026-10-10; prima in tts_split).

`generate_chunk_mp3` (async): testo -> MP3 via edge-tts con retry/backoff
(`_edge_tts_call`), timeout per chiamata (`ABM_EDGE_TTS_TIMEOUT`), rilevamento
dell'output troncato dalla sola dimensione del file e silenzio esplicito quando
tutti i tentativi falliscono. NoAudioReceived ha piu' tentativi degli altri
errori; poi una voce Multilingual ripiega su una standard della stessa lingua,
una standard su una voce della stessa locale, prima del silenzio
(`_fallback_voice`). Ogni tentativo e ogni esito finale vanno a
`edge_health`, che allerta l'admin se il tasso di errore supera la soglia.
Le voci Multilingual passano frase per frase
(`tts_split._split_sentences_for_tts`) e i pezzi vengono concatenati.

Dipende da `tts_split` (solo splitting, chiamato qualificato cosi' i test che
lo sostituiscono continuano a vederlo), `text_reflow` (`_sanitize_tts_text`),
`audio_utils` (silenzio e concat MP3), `retry_util`, `edge_tts`.
"""
import asyncio
import os
import tempfile
import threading
import time

import edge_tts
import edge_tts.communicate as _edge_communicate
from edge_tts.constants import TRUSTED_CLIENT_TOKEN
from edge_tts.exceptions import NoAudioReceived

import edge_health
import retry_util as _retry
import tts_split
from audio_utils import _concatenate_mp3, _generate_silence_mp3
from env_utils import env_int, env_str
from text_reflow import _sanitize_tts_text
from voice_utils import rate_speed_factor as _rate_speed_factor_vu

# Endpoint websocket di edge-tts. Dal 10/10/2026 speech.platform.bing.com
# risponde 403 a ~1 richiesta su 4 (rollout Microsoft, issue upstream
# rany2/edge-tts#490): decine di migliaia di chunk al giorno finivano in
# silenzio. api.msedgeservices.com da prod: 30/30 ok contro 22/30, ma limita i
# burst con 429. edge-tts 7.3.0 (token Sec-MS-GEC v2) risolve i 403 sul
# legacy: `ABM_EDGE_TTS_ENDPOINT=legacy` torna all'URL della libreria; un URL
# completo lo sostituisce. Da togliere quando il legacy risulta stabile in prod
# (scripts/edge_endpoint_probe.py).
_EDGE_WSS_MSEDGE = ("wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
                    "?Ocp-Apim-Subscription-Key=" + TRUSTED_CLIENT_TOKEN)
_EDGE_WSS_LEGACY = _edge_communicate.WSS_URL


def _edge_wss_url(setting):
    """URL websocket per `ABM_EDGE_TTS_ENDPOINT` (vuoto -> msedgeservices)."""
    s = (setting or "").strip()
    if s.lower() == "legacy":
        return _EDGE_WSS_LEGACY
    if s.lower().startswith("wss://"):
        return s
    return _EDGE_WSS_MSEDGE


# edge_tts.communicate legge WSS_URL dal proprio modulo a ogni connessione.
_edge_communicate.WSS_URL = _edge_wss_url(env_str("ABM_EDGE_TTS_ENDPOINT"))

# Timeout (secondi) per una singola chiamata edge-tts. edge-tts non applica
# receive_timeout alla websocket (ws_connect senza timeout in aiohttp): su
# connessione half-open save() resterebbe sospeso per sempre, bloccando il
# thread del job senza errori (incidente 2026-06-11). Il timeout trasforma
# l'hang in TimeoutError, gestito dal retry/fallback di _edge_tts_call.
EDGE_TTS_CHUNK_TIMEOUT = env_int("ABM_EDGE_TTS_TIMEOUT", 120)

# --- Sanity-check output edge-tts (anti-troncamento silenzioso) --------------
# edge-tts/Azure a volte chiude lo stream WebSocket a meta' e communicate.save()
# ritorna SENZA sollevare eccezione lasciando un MP3 valido ma incompleto: la
# coda del testo sparisce senza alcun errore loggato (stessa famiglia dell'hang
# websocket, incidente 2026-06). Nessun controllo lo intercettava -> testo
# saltato a meta' capitolo, failed_chunks=0, job COMPLETE (incidente
# fuGEZzhdnswI1_P7m6xMVw, "L'Eternel Adolescent", cap. 10 troncato).
#
# Rilevazione a COSTO ZERO dalla dimensione del file: l'output edge-tts e' CBR
# 48 kbps mono (audio-24khz-48kbitrate-mono-mp3), quindi durata_sec = bytes/6000
# (verificato empiricamente: bytes/s = 6000.0 esatto su piu' campioni). Se la
# durata stimata e' sotto il minimo fisico per quel numero di caratteri, il file
# e' troncato -> il caller lo tratta come fallimento e ritenta con connessione
# nuova. Niente ffprobe: il path Multilingual fa molte micro-chiamate per frase.
_EDGE_MP3_BYTES_PER_SEC = 6000            # 48 kbps CBR / 8 bit
# Tetto ultra-conservativo di velocita' di lettura (char/s a rate 0%). Il parlato
# reale edge-tts sta ~20-22 char/s (misurato); 40 lascia ~2x di margine -> un MP3
# "piu' corto di cosi'" NON puo' contenere tutto il testo (zero falsi positivi
# per tutte le lingue alfabetiche; CJK legge ancor meno char/s -> sempre sotto).
_EDGE_MAX_CHARS_PER_SEC = 40
# Sotto questa soglia di caratteri la durata e' dominata da pause/overhead
# (attacco/coda, respiro): niente check, la varianza darebbe falsi positivi.
_EDGE_SANITY_MIN_CHARS = 40


def _rate_speed_factor(rate):
    """Fattore di velocita' dal parametro rate edge-tts ("+10%" -> 1.10).

    A rate alto l'MP3 e' legittimamente piu' corto: scala la soglia
    anti-troncamento in proporzione per non generare falsi positivi. Clamp a
    0.25 per evitare divisioni instabili su rate estremi.
    """
    return _rate_speed_factor_vu(rate, floor=0.25)


def _edge_output_looks_truncated(output_path, text, rate="+0%"):
    """True se l'MP3 edge-tts e' troppo corto per contenere `text` completo.

    Confronta la durata stimata dal file (CBR 48 kbps -> bytes/6000) con il
    minimo fisico per quel numero di caratteri alla massima velocita' plausibile
    (scalata per il rate). Conservativo: rifiuta solo file palesemente
    incompleti. File assente/illeggibile => considerato troncato.
    """
    n = len((text or "").strip())
    if n < _EDGE_SANITY_MIN_CHARS:
        return False
    try:
        size = os.path.getsize(output_path)
    except OSError:
        return True
    est_sec = size / _EDGE_MP3_BYTES_PER_SEC
    min_sec = n / (_EDGE_MAX_CHARS_PER_SEC * _rate_speed_factor(rate))
    return est_sec < min_sec


class _EdgeTruncated(Exception):
    """L'MP3 di edge-tts e' arrivato troncato: si ritenta come un errore."""


# Il nuovo endpoint limita i burst con 429 (issue #490): la pausa standard da
# 1-2 s non basta a farlo rientrare.
_EDGE_429_WAIT = 3.0

# 16/10/2026: NoAudioReceived intermittente lato Microsoft su intere lingue
# (cs-CZ 1-5 risposte su 10, ru-RU a tratti, en-US ~10%), con voci standard:
# tre tentativi a 1-2 s di distanza lasciavano in silenzio centinaia di chunk
# all'ora. Su NoAudioReceived i tentativi salgono a _EDGE_NOAUDIO_ATTEMPTS,
# con attesa esponenziale fino a _EDGE_NOAUDIO_WAIT_CAP secondi.
_EDGE_NOAUDIO_ATTEMPTS = 6
_EDGE_NOAUDIO_WAIT_CAP = 8.0


def _edge_retry_wait(attempt, exc):
    if getattr(exc, "status", None) == 429:
        return _EDGE_429_WAIT * (attempt + 1)
    if isinstance(exc, NoAudioReceived):
        return _retry.backoff(attempt, base=1.0, cap=_EDGE_NOAUDIO_WAIT_CAP)
    return _retry.backoff(attempt, base=1.0)


# --- Ripiego per le voci Multilingual che Microsoft non serve ----------------
# 16/10/2026: pt-BR-ThalitaMultilingualNeural (3/3) e
# de-DE-SeraphinaMultilingualNeural (2/3) rispondono NoAudioReceived anche a
# richieste isolate, mentre le altre 26 voci provate da prod passano: il 2% dei
# chunk finiva in silenzio. Esauriti i tentativi con NoAudioReceived su una voce
# Multilingual, il testo si ritenta con una voce standard della stessa lingua
# e dello stesso genere. La voce resta "rotta" per _EDGE_BROKEN_VOICE_SEC: le
# frasi successive del libro vanno subito al ripiego, senza tre tentativi persi
# ciascuna e senza alternare le due voci frase per frase.
# Stesso giorno, verso opposto: le voci standard cs-CZ e ru-RU senza audio per
# gran parte delle richieste, mentre le Multilingual leggevano lo stesso testo
# ceco 6/6. Una voce standard rotta ripiega prima sulla stessa locale.
# 15-17/10/2026, 263.618 chunk edge: il 98% dei silenzi in 9 voci (en-US-Emma
# 18,6%, sk-SK-Lukas 34,7%, ru-RU-Dmitry 5,8%, cs-CZ-Vlasta 18%), mentre le
# sorelle della stessa locale erano a 0 (Viktoria 0/1008, Svetlana 0/4663):
# niente legame con lunghezza dei chunk o ritmo delle richieste.
_EDGE_BROKEN_VOICE_SEC = 900
# Catalogo voci fallito: non si riscarica prima di questi secondi.
_EDGE_CATALOG_RETRY_SEC = 300

_fallback_lock = threading.Lock()
_broken_voices = {}             # voce Multilingual -> epoch fino a cui e' rotta
_voice_catalog = None           # lista di dict di edge_tts.list_voices()
_catalog_failed_at = 0.0


async def _edge_voice_catalog():
    """Catalogo voci edge-tts, scaricato una volta per processo ([] se non raggiungibile)."""
    global _voice_catalog, _catalog_failed_at
    with _fallback_lock:
        if _voice_catalog is not None:
            return _voice_catalog
        if time.time() - _catalog_failed_at < _EDGE_CATALOG_RETRY_SEC:
            return []
    try:
        voices = await asyncio.wait_for(edge_tts.list_voices(), timeout=EDGE_TTS_CHUNK_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - senza catalogo niente ripiego: resta il silenzio
        print(f"[tts] catalogo voci edge-tts non disponibile: {e}")
        with _fallback_lock:
            _catalog_failed_at = time.time()
        return []
    with _fallback_lock:
        _voice_catalog = list(voices or [])
        return _voice_catalog


def _pick_standard_voice(voice, catalog):
    """Voce standard (non Multilingual) per sostituire `voice`, o None.

    Ordine: stesso nome senza "Multilingual" (en-US-AvaMultilingualNeural ->
    en-US-AvaNeural), poi stessa locale e stesso genere, poi stessa locale."""
    by_name = {v.get("ShortName"): v for v in catalog}
    same = by_name.get(voice.replace("MultilingualNeural", "Neural"))
    if same is not None and not tts_split._is_multilingual_voice(same["ShortName"]):
        return same["ShortName"]
    orig = by_name.get(voice) or {}
    locale = orig.get("Locale") or "-".join(voice.split("-")[:2])
    cands = sorted((v for v in catalog
                    if v.get("Locale") == locale
                    and not tts_split._is_multilingual_voice(v.get("ShortName"))),
                   key=lambda v: v.get("ShortName") or "")
    gender = orig.get("Gender")
    for v in cands:
        if v.get("Gender") == gender:
            return v["ShortName"]
    return cands[0]["ShortName"] if cands else None


def _pick_standard_replacement(voice, catalog):
    """Voce non segnata rotta per sostituire la standard `voice`, o None.

    Ordine: stessa locale (Multilingual o standard), poi Multilingual della
    stessa lingua, poi Multilingual en-US, poi qualunque Multilingual. Dentro
    la stessa locale prima lo stesso genere, e a parita' la Multilingual. Una
    standard sana della stessa locale batte una Multilingual di un'altra: la
    Multilingual deve indovinare la lingua, la madrelingua no (sk, cs, ru, el
    non hanno Multilingual)."""
    by_name = {v.get("ShortName"): v for v in catalog}
    orig = by_name.get(voice) or {}
    locale = orig.get("Locale") or "-".join(voice.split("-")[:2])
    lang = locale.split("-")[0]
    gender = orig.get("Gender")

    def _rank(v):
        loc = v.get("Locale") or ""
        group = (0 if loc == locale else 1 if loc.split("-")[0] == lang
                 else 2 if loc == "en-US" else 3)
        return (group, v.get("Gender") != gender,
                not tts_split._is_multilingual_voice(v.get("ShortName")),
                v.get("ShortName") or "")

    cands = [v for v in catalog
             if v.get("ShortName") != voice
             and not _voice_is_broken(v.get("ShortName"))
             and (tts_split._is_multilingual_voice(v.get("ShortName"))
                  or v.get("Locale") == locale)]
    return min(cands, key=_rank)["ShortName"] if cands else None


def _voice_is_broken(voice, now=None):
    now = time.time() if now is None else now
    with _fallback_lock:
        return _broken_voices.get(voice, 0.0) > now


def _mark_voice_broken(voice, now=None):
    now = time.time() if now is None else now
    with _fallback_lock:
        _broken_voices[voice] = now + _EDGE_BROKEN_VOICE_SEC
        for v in [v for v, until in _broken_voices.items() if until <= now]:
            del _broken_voices[v]


async def _fallback_voice(voice, last_error):
    """Voce con cui ritentare dopo un fallimento, o None.

    Multilingual -> standard della stessa lingua, standard -> stessa locale
    (`_pick_standard_replacement`). Solo se la voce e' gia' segnata rotta o
    i tentativi sono finiti con NoAudioReceived (un 403/429/timeout non
    dipende dalla voce: cambiarla non servirebbe)."""
    if not (isinstance(last_error, NoAudioReceived) or _voice_is_broken(voice)):
        return None
    catalog = await _edge_voice_catalog()
    if tts_split._is_multilingual_voice(voice):
        return _pick_standard_voice(voice, catalog)
    return _pick_standard_replacement(voice, catalog)


async def _edge_tts_call(text, voice, rate, output_path, max_retries=3):
    """Chiamata edge-tts per un testo, con ripiego di voce e silenzio finale.

    Prova `voice` con retry (`_edge_tts_attempts`); se Microsoft non la serve
    (NoAudioReceived a ogni tentativo) ritenta con la voce di ripiego
    (`_fallback_voice`: Multilingual <-> standard). Una voce gia' segnata
    rotta va subito al ripiego. Se fallisce anche quello, silenzio esplicito e
    False. Ogni chiamata conta una volta in `edge_health.record_call`.
    """
    last_error = None
    skip_original = _voice_is_broken(voice)
    if not skip_original:
        ok, last_error = await _edge_tts_attempts(text, voice, rate, output_path, max_retries)
        if ok:
            edge_health.record_call(True)
            return True
    fallback = await _fallback_voice(voice, last_error)
    if fallback and not _voice_is_broken(voice):
        print(f"[tts] voce {voice} senza audio: ripiego su {fallback} "
              f"per {_EDGE_BROKEN_VOICE_SEC} s")
        _mark_voice_broken(voice)
    # voce segnata rotta ma catalogo irraggiungibile: si riprova la voce originale
    target = fallback or (voice if skip_original else None)
    if target:
        ok, last_error = await _edge_tts_attempts(text, target, rate, output_path, max_retries)
        if ok:
            edge_health.record_call(True)
            return True
    print(f"[tts] WARNING: all {max_retries} attempts failed "
          f"({len(text)} chars). Last: {last_error}")
    edge_health.record_call(False)
    _generate_silence_mp3(output_path, duration_sec=1)
    return False


async def _edge_tts_attempts(text, voice, rate, output_path, max_retries=3):
    """Tentativi edge-tts con retry/backoff esponenziale: ritorna (ok, ultimo errore).

    Oltre alle eccezioni, tratta come fallimento anche un output MP3 TRONCATO:
    save() puo' ritornare senza errore mentre lo stream Azure si e' chiuso a
    meta', lasciando un file valido ma incompleto (coda del testo persa, nessun
    log). In quel caso ritenta con una connessione nuova. Il controllo e' a costo
    zero (dimensione file vs lunghezza testo, vedi `_edge_output_looks_truncated`)
    quindi si applica anche alle micro-chiamate per frase del path Multilingual.

    In caso di fallimento totale ritorna (False, errore) e `_edge_tts_call`
    scrive il silenzio: cosi' un troncamento persistente diventa un failed_chunk
    contato + silenzio esplicito, non testo mancante nascosto (che passava
    inosservato con failed_chunks=0 e job COMPLETE).
    """
    snippet = text[:60].replace('\n', ' ')

    async def _synth(attempt):
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        await asyncio.wait_for(
            communicate.save(output_path), timeout=EDGE_TTS_CHUNK_TIMEOUT
        )
        if _edge_output_looks_truncated(output_path, text, rate):
            try:
                size = os.path.getsize(output_path)
            except OSError:
                size = 0
            print(f"[tts] Attempt {attempt+1}/{max_retries} TRUNCATED output "
                  f"({len(text)} chars -> {size}B ~{size/_EDGE_MP3_BYTES_PER_SEC:.1f}s: "
                  f"\"{snippet}...\"): retry")
            raise _EdgeTruncated("truncated_output (stream chiuso a meta')")
        return True

    async def _once(attempt):
        try:
            ok = await _synth(attempt)
        except _EdgeTruncated:
            edge_health.record_attempt("truncated")
            raise
        except Exception as e:  # noqa: BLE001 - contato e rilanciato al retry
            edge_health.record_attempt(edge_health.error_signature(e))
            raise
        edge_health.record_attempt()
        return ok

    # NoAudioReceived ha tentativi in piu' (vedi _EDGE_NOAUDIO_ATTEMPTS); gli
    # altri errori si fermano a max_retries.
    attempts = max(max_retries, _EDGE_NOAUDIO_ATTEMPTS)
    done = [0]

    async def _counted(attempt):
        done[0] = attempt + 1
        return await _once(attempt)

    def _retryable(e):
        return isinstance(e, NoAudioReceived) or done[0] < max_retries

    def _log(attempt, e, _wait):
        if not isinstance(e, _EdgeTruncated):
            print(f"[tts] Attempt {attempt+1}/{attempts} failed "
                  f"({len(text)} chars: \"{snippet}...\"): {e}")

    try:
        await _retry.retry_call_async(_counted, attempts=attempts, is_retryable=_retryable,
                                      wait=_edge_retry_wait, on_retry=_log)
        return True, None
    except Exception as e:      # noqa: BLE001 - esauriti i tentativi: decide il chiamante
        if isinstance(e, _EdgeTruncated):
            return False, str(e)
        print(f"[tts] Attempt {done[0]}/{attempts} failed "
              f"({len(text)} chars: \"{snippet}...\"): {e}")
        return False, e


async def generate_chunk_mp3(text, voice, rate, output_path, max_retries=3):
    """Genera MP3 da testo via edge-tts con retry e fallback.

    Per le voci *Multilingual* (es. it-IT-GiuseppeMultilingualNeural) il motore
    Azure fa auto-detection della lingua per clausola e può "sbandare" su testi
    monolingua. Mitigazione: spezza in frasi e sintetizza una per volta.
    I singoli MP3 vengono poi concatenati nel file finale.
    """
    clean = _sanitize_tts_text(text)
    if clean is None:
        _generate_silence_mp3(output_path, duration_sec=1)
        return

    # Percorso "split-per-frase" per le voci Multilingual, anche quando lo e'
    # solo il ripiego di una voce standard rotta (`_fallback_voice`)
    speaking = voice
    if not tts_split._is_multilingual_voice(voice) and _voice_is_broken(voice):
        speaking = await _fallback_voice(voice, None) or voice
    if tts_split._is_multilingual_voice(speaking):
        sentences = tts_split._split_sentences_for_tts(clean)
        if len(sentences) >= 2:
            tmpdir = tempfile.mkdtemp(prefix="abmtts_")
            try:
                parts = []
                any_failed = False
                for i, sent in enumerate(sentences):
                    part_path = os.path.join(tmpdir, f"s{i:04d}.mp3")
                    ok = await _edge_tts_call(sent, voice, rate, part_path, max_retries=max_retries)
                    if not ok:
                        any_failed = True
                    parts.append(part_path)
                _concatenate_mp3(parts, output_path)
                if any_failed:
                    return False
                return True
            finally:
                try:
                    for f in os.listdir(tmpdir):
                        try:
                            os.remove(os.path.join(tmpdir, f))
                        except OSError:
                            pass
                    os.rmdir(tmpdir)
                except OSError:
                    pass
        # fallthrough: singola frase → chiamata unica

    # Percorso standard: chiamata singola con retry
    ok = await _edge_tts_call(clean, voice, rate, output_path, max_retries=max_retries)
    return ok if ok is False else None
