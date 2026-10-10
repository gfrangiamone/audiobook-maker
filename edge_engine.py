"""edge_engine — sintesi di un chunk con Microsoft Edge TTS (F1d, 2026-10-10; prima in tts_split).

`generate_chunk_mp3` (async): testo -> MP3 via edge-tts con retry/backoff
(`_edge_tts_call`), timeout per chiamata (`ABM_EDGE_TTS_TIMEOUT`), rilevamento
dell'output troncato dalla sola dimensione del file e silenzio esplicito quando
tutti i tentativi falliscono. Le voci Multilingual passano frase per frase
(`tts_split._split_sentences_for_tts`) e i pezzi vengono concatenati.

Dipende da `tts_split` (solo splitting, chiamato qualificato cosi' i test che
lo sostituiscono continuano a vederlo), `text_reflow` (`_sanitize_tts_text`),
`audio_utils` (silenzio e concat MP3), `retry_util`, `edge_tts`.
"""
import asyncio
import os
import tempfile

import edge_tts

import retry_util as _retry
import tts_split
from audio_utils import _concatenate_mp3, _generate_silence_mp3
from env_utils import env_int
from text_reflow import _sanitize_tts_text
from voice_utils import rate_speed_factor as _rate_speed_factor_vu

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


async def _edge_tts_call(text, voice, rate, output_path, max_retries=3):
    """Singola chiamata edge-tts con retry/backoff esponenziale.

    Oltre alle eccezioni, tratta come fallimento anche un output MP3 TRONCATO:
    save() puo' ritornare senza errore mentre lo stream Azure si e' chiuso a
    meta', lasciando un file valido ma incompleto (coda del testo persa, nessun
    log). In quel caso ritenta con una connessione nuova. Il controllo e' a costo
    zero (dimensione file vs lunghezza testo, vedi `_edge_output_looks_truncated`)
    quindi si applica anche alle micro-chiamate per frase del path Multilingual.

    In caso di fallimento totale scrive un breve silenzio e ritorna False: cosi'
    un troncamento persistente diventa un failed_chunk contato + silenzio
    esplicito, non testo mancante nascosto (che passava inosservato con
    failed_chunks=0 e job COMPLETE).
    """
    snippet = text[:60].replace('\n', ' ')

    async def _once(attempt):
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

    def _log(attempt, e, _wait):
        if not isinstance(e, _EdgeTruncated):
            print(f"[tts] Attempt {attempt+1}/{max_retries} failed "
                  f"({len(text)} chars: \"{snippet}...\"): {e}")

    try:
        return await _retry.retry_call_async(_once, attempts=max_retries, wait=1.0, on_retry=_log)
    except Exception as e:      # noqa: BLE001 - esauriti i tentativi: silenzio esplicito
        last_error = e if not isinstance(e, _EdgeTruncated) else str(e)
        if not isinstance(e, _EdgeTruncated):
            print(f"[tts] Attempt {max_retries}/{max_retries} failed "
                  f"({len(text)} chars: \"{snippet}...\"): {e}")
    print(f"[tts] WARNING: all {max_retries} attempts failed "
          f"({len(text)} chars). Last: {last_error}")
    _generate_silence_mp3(output_path, duration_sec=1)
    return False


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

    # Percorso "split-per-frase" solo per voci Multilingual
    if tts_split._is_multilingual_voice(voice):
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
