"""
tts_split.py — Splitting testo e generazione TTS per Audiobook Maker.

Funzioni:
  - split_text_into_chunks: divide testo in chunk senza spezzare frasi (TTS)
  - _split_sentences_for_tts: tokenizza in frasi, accorpando quelle troppo corte
  - _is_multilingual_voice: rileva voci Azure Multilingual soggette a lingua-drift
  - _strip_parenthetical: rimuove contenuto tra parentesi tonde/quadre
  - _ensure_heading_pause: aggiunge punto finale agli heading per pausa TTS
  - _plan_chunks: costruisce il piano di chunk per un intero BookInfo
  - _edge_tts_call: singola chiamata edge-tts con retry/backoff
  - generate_chunk_mp3: genera MP3 da testo via edge-tts (con anti-drift Multilingual)
  - generate_chunk_mp3_google: genera MP3 da testo via Google Cloud TTS Chirp3-HD

Dipende da audio_utils per _generate_silence_mp3 e _concatenate_mp3.
"""

import asyncio
import os
import re
import tempfile
import time

import edge_tts

try:
    import google_tts
except ImportError:
    google_tts = None

from audio_utils import _generate_silence_mp3, _concatenate_mp3

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

CHUNK_MAX_CHARS = 2000

# Minimo di caratteri per frase standalone: sotto questa soglia accorpiamo
# alla frase successiva per garantire abbastanza contesto al motore TTS.
_TTS_MIN_SENT_CHARS = 80
# Limite superiore di sicurezza: frasi enormi non vengono ulteriormente spezzate
# (ci pensa il chunking a monte).
_TTS_MAX_SENT_CHARS = 1500


# ---------------------------------------------------------------------------
# Text splitting
# ---------------------------------------------------------------------------

def split_text_into_chunks(text, max_chars=CHUNK_MAX_CHARS):
    """Spezza il testo in chunk <= max_chars senza mai tagliare a metà frase.

    Strategia: tokenizza il testo in frasi (terminatori . ! ? … + spazio/newline),
    poi accumula frasi nel chunk corrente finché il limite non viene raggiunto.
    """
    if not text or not text.strip():
        return [text] if text else [""]
    # Tokenizza in frasi: split su terminatori seguiti da spazio o newline,
    # preservando il terminatore nella frase precedente (lookbehind).
    raw_sentences = re.split(r'(?<=[.!?\u2026])\s+', text.strip())
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    if not sentences:
        return [text.strip()]
    chunks = []
    current = ""
    for sent in sentences:
        if not current:
            current = sent
        elif len(current) + 1 + len(sent) <= max_chars:
            current = current + " " + sent
        else:
            chunks.append(current)
            current = sent
        # Se una singola frase supera max_chars non la spezziamo — il TTS gestisce.
    if current:
        chunks.append(current)
    return chunks if chunks else [text.strip()]


def _split_sentences_for_tts(text: str):
    """Split un chunk in frasi, accorpando quelle troppo corte per dare contesto
    sufficiente al motore TTS Multilingual.

    Ritorna una lista di stringhe pronte per TTS (nessuna sarà vuota).
    """
    if not text:
        return []
    # Terminatore + eventuali virgolette/chiuse + whitespace obbligatorio
    pattern = re.compile(r'(?<=[.?!\u2026])[\'"»\u201c\u201d\)\]]*\s+')
    raw = pattern.split(text)
    raw = [s for s in (s.strip() for s in raw) if s]
    if not raw:
        return [text.strip()] if text.strip() else []
    merged = []
    buf = ""
    for s in raw:
        if not buf:
            buf = s
        else:
            buf = buf + " " + s
        if len(buf) >= _TTS_MIN_SENT_CHARS:
            merged.append(buf)
            buf = ""
    if buf:
        if merged and len(buf) < _TTS_MIN_SENT_CHARS:
            merged[-1] = merged[-1] + " " + buf
        else:
            merged.append(buf)
    return [m for m in merged if m]


def _is_multilingual_voice(voice: str) -> bool:
    """True se la voce edge-tts è una 'Multilingual' soggetta a lingua-drift."""
    return "multilingual" in (voice or "").lower()


# ---------------------------------------------------------------------------
# Text preprocessing
# ---------------------------------------------------------------------------

def _strip_parenthetical(text):
    """Rimuove il contenuto tra parentesi tonde e quadre (anche annidate)."""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'\([^()]*\)', '', text)
        text = re.sub(r'\[[^\[\]]*\]', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([,;:.!?])', r'\1', text)
    return text.strip()


def _ensure_heading_pause(text):
    """Aggiunge un punto finale alle righe che sembrano heading nel testo,
    così il TTS inserisce una pausa naturale prima del corpo del paragrafo.

    Un heading è una riga breve (<=120 char) isolata da righe vuote che non
    termina già con punteggiatura (.!?…:;).
    """
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if (stripped
                and len(stripped) <= 120
                and not re.search(r'[.!?\u2026:;]\s*$', stripped)):
            idx = len(result)
            prev_empty = (idx == 0) or (not result[-1].strip())
            if prev_empty:
                result.append(line.rstrip() + ".")
                continue
        result.append(line)
    return "\n".join(result)


def _sanitize_tts_text(text: str):
    """Pulisce il testo per TTS: rimuove caratteri di controllo/zero-width,
    collassa whitespace eccessivo, normalizza newline.

    Ritorna il testo pulito, oppure None se vuoto o diventato vuoto dopo pulizia
    (il chiamante deve generare silenzio in quel caso).
    """
    clean = text.strip()
    if not clean:
        return None
    clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u2028-\u202f\ufeff\ufffe\uffff]', '', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    clean = re.sub(r' {3,}', ' ', clean)
    if not clean.strip():
        return None
    return clean


def _plan_chunks(info):
    """Costruisce la lista di chunk da generare per tutti i capitoli di un BookInfo."""
    plan = []
    for ch in info.chapters:
        clean_text = _strip_parenthetical(ch.text)
        clean_text = _ensure_heading_pause(clean_text)
        full_text = f"{ch.title}.\n\n{clean_text}"
        chunks = split_text_into_chunks(full_text)
        for ci, chunk_text in enumerate(chunks):
            plan.append({
                "chapter_index": ch.index,
                "chapter_title": ch.title,
                "chunk_index": ci,
                "chunks_in_chapter": len(chunks),
                "text": chunk_text,
                "chars": len(chunk_text),
            })
    return plan


# ---------------------------------------------------------------------------
# edge-tts generation
# ---------------------------------------------------------------------------

async def _edge_tts_call(text, voice, rate, output_path, max_retries=3):
    """Singola chiamata edge-tts con retry/backoff esponenziale.

    In caso di fallimento totale scrive un breve silenzio e ritorna False.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
            await communicate.save(output_path)
            return True
        except Exception as e:
            last_error = e
            wait = 2 ** attempt
            snippet = text[:60].replace('\n', ' ')
            print(f"[tts] Attempt {attempt+1}/{max_retries} failed "
                  f"({len(text)} chars: \"{snippet}...\"): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)
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
    if _is_multilingual_voice(voice):
        sentences = _split_sentences_for_tts(clean)
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


# ---------------------------------------------------------------------------
# Gemini TTS generation (PCM native)
# ---------------------------------------------------------------------------

_PCM_SAMPLE_RATE = 24000
_PCM_CHANNELS = 1
_PCM_SAMPLE_WIDTH = 2  # bytes per sample (16-bit)


def _generate_silence_pcm(output_path, duration_sec=1):
    """Scrive N secondi di silenzio PCM 24kHz mono 16-bit (zero bytes)."""
    n_bytes = int(duration_sec * _PCM_SAMPLE_RATE * _PCM_CHANNELS * _PCM_SAMPLE_WIDTH)
    with open(output_path, "wb") as f:
        if n_bytes > 0:
            f.write(b"\x00" * n_bytes)


# ---------------------------------------------------------------------------
# Google Cloud TTS generation
# ---------------------------------------------------------------------------

def generate_chunk_mp3_google(text, voice, rate, output_path, max_retries=3):
    """Genera MP3 da testo via Google Cloud TTS Chirp3-HD con retry e fallback."""
    clean = _sanitize_tts_text(text)
    if clean is None:
        _generate_silence_mp3(output_path, duration_sec=1)
        return

    last_error = None
    for attempt in range(max_retries):
        try:
            google_tts.synthesize(clean, voice, rate, output_path)
            return
        except Exception as e:
            last_error = e
            snippet = clean[:60].replace('\n', ' ')
            print(f"[google-tts] Attempt {attempt+1}/{max_retries} failed for chunk "
                  f"({len(clean)} chars: \"{snippet}...\"): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    print(f"[google-tts] WARNING: All {max_retries} attempts failed, "
          f"generating silence ({len(clean)} chars). Last error: {last_error}")
    _generate_silence_mp3(output_path, duration_sec=1)
    return False
