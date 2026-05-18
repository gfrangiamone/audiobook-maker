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


def _pick_chunk_max_chars(voice_id, language):
    """Sceglie il limite caratteri/chunk in base al motore e alla lingua.

    Gemini: delega a gemini_tts.get_max_chunk_chars(lang) (default 4000
    latine / 3000 CJK, override env ABM_GEMINI_MAX_CHUNK_CHARS_<LANG>).
    Tier 1 limita a 100 RPD/modello: chunk piu' grossi = meno richieste
    per libro.

    Edge/Google: 2000 sempre (motori senza vincoli stringenti di RPD).
    """
    if isinstance(voice_id, str) and voice_id.startswith("gemini:"):
        lang_code = (language or "").lower().split("-")[0]
        try:
            import gemini_tts
            return gemini_tts.get_max_chunk_chars(lang_code)
        except Exception:
            # Fallback prudente se il modulo non e' disponibile.
            return 4000 if lang_code not in {"zh", "ja", "hi", "ar"} else 3000
    return CHUNK_MAX_CHARS


# Margine di sicurezza riservato ai prefissi che synthesize() prepende al testo
# (style_instruction max 300 char + envelope "[style: ...] " + rate directive
# fino a ~30 char). Lasciamo 400 byte di buffer sul cap API per evitare che il
# chunk passi lo splitter ma fallisca check_text_byte_size() in gemini_tts.
_GEMINI_BYTE_SAFETY_MARGIN = 400


def _pick_chunk_max_bytes(voice_id):
    """Cap byte UTF-8 per chunk per voci Gemini, None per altri motori.

    Il cap API e' MAX_BYTES_PER_CALL (default 8000, configurabile via env);
    lo splitter usa un cap ridotto del margine di sicurezza riservato ai
    prefissi style/rate che synthesize() aggiunge in coda al testo.
    """
    if not (isinstance(voice_id, str) and voice_id.startswith("gemini:")):
        return None
    try:
        import gemini_tts
        cap = int(gemini_tts.MAX_BYTES_PER_CALL)
    except Exception:
        cap = 8000
    return max(1000, cap - _GEMINI_BYTE_SAFETY_MARGIN)


# Minimo di caratteri per frase standalone: sotto questa soglia accorpiamo
# alla frase successiva per garantire abbastanza contesto al motore TTS.
_TTS_MIN_SENT_CHARS = 80
# Limite superiore di sicurezza: frasi enormi non vengono ulteriormente spezzate
# (ci pensa il chunking a monte).
_TTS_MAX_SENT_CHARS = 1500


# ---------------------------------------------------------------------------
# Text splitting
# ---------------------------------------------------------------------------

def split_text_into_chunks(text, max_chars=CHUNK_MAX_CHARS, max_bytes=None):
    """Spezza il testo in chunk <= max_chars (e <= max_bytes UTF-8) senza mai
    tagliare a meta' frase.

    Strategia: tokenizza il testo in frasi (terminatori . ! ? ... + spazio/newline),
    poi accumula frasi nel chunk corrente finche' uno dei due limiti non viene
    raggiunto.

    max_bytes: cap byte UTF-8 opzionale (necessario per Gemini, che limita
        a byte e non a caratteri). Se None, viene applicato solo il cap chars.
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
            continue
        candidate = current + " " + sent
        chars_ok = len(candidate) <= max_chars
        bytes_ok = (max_bytes is None) or (len(candidate.encode("utf-8")) <= max_bytes)
        if chars_ok and bytes_ok:
            current = candidate
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


def _plan_chunks(info, max_chars=CHUNK_MAX_CHARS, max_bytes=None):
    """Costruisce la lista di chunk da generare per tutti i capitoli di un BookInfo.

    max_chars: limite caratteri/chunk (default CHUNK_MAX_CHARS=2000).
               Per voci Gemini su lingue CJK/Hindi/Arabo passare 1500.
    max_bytes: cap byte UTF-8 opzionale (None per Edge/Google, MAX_BYTES_PER_CALL
               meno margine di sicurezza per Gemini).
    """
    plan = []
    for ch in info.chapters:
        clean_text = _strip_parenthetical(ch.text)
        clean_text = _ensure_heading_pause(clean_text)
        full_text = f"{ch.title}.\n\n{clean_text}"
        chunks = split_text_into_chunks(full_text, max_chars=max_chars, max_bytes=max_bytes)
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


def _synthesize_pcm_pieces_and_concat(pieces, voice_id, output_path, style_instruction, max_retries):
    """Sintetizza una lista di sotto-chunk con synthesize() e concatena i PCM
    raw nel file output_path. Aggrega i risultati metrici sommando token/byte.

    Ritorna il dict aggregato in stile synthesize(). False se anche un solo
    sotto-chunk fallisce (in quel caso il caller decide se silenziare o
    propagare).
    """
    import gemini_tts as _gemini

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    aggregate = {
        "success": True,
        "bytes_written": 0,
        "audio_seconds_real": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "model_key": None,
        "voice_name": None,
        "attempts_used": 0,
        "split_pieces": len(pieces),
    }

    tmp_parts = []
    try:
        with open(output_path, "wb") as fout:
            for idx, piece_text in enumerate(pieces):
                tmp_path = output_path + f".part{idx:03d}.pcm"
                tmp_parts.append(tmp_path)
                last_error = None
                piece_ok = False
                for attempt in range(max_retries):
                    try:
                        result = _gemini.synthesize(
                            piece_text, voice_id, output_path=tmp_path,
                            style_instruction=style_instruction,
                        )
                        piece_ok = True
                        aggregate["bytes_written"] += int(result.get("bytes_written", 0))
                        aggregate["audio_seconds_real"] += float(result.get("audio_seconds_real", 0.0))
                        aggregate["input_tokens"] += int(result.get("input_tokens", 0))
                        aggregate["output_tokens"] += int(result.get("output_tokens", 0))
                        aggregate["model_key"] = result.get("model_key") or aggregate["model_key"]
                        aggregate["voice_name"] = result.get("voice_name") or aggregate["voice_name"]
                        aggregate["attempts_used"] = max(aggregate["attempts_used"], int(result.get("attempts_used", 1)))
                        break
                    except (_gemini.GeminiQuotaExhausted, _gemini.GeminiBudgetExceeded):
                        raise
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                if not piece_ok:
                    snippet = piece_text[:60].replace('\n', ' ')
                    print(f"[gemini-tts] Split-piece {idx+1}/{len(pieces)} failed "
                          f"({len(piece_text)} chars: \"{snippet}...\"): {last_error}")
                    return False
                with open(tmp_path, "rb") as fpart:
                    fout.write(fpart.read())
        return aggregate
    finally:
        for p in tmp_parts:
            try:
                os.remove(p)
            except OSError:
                pass


def generate_chunk_pcm_gemini(text, voice_id, output_path, max_retries=1, style_instruction=None):
    """Genera PCM 24kHz mono 16-bit da testo via Gemini TTS con retry e fallback.

    NOTE: il retry interno con backoff vive ora in `gemini_tts.synthesize()`
    (che è quota-aware e rispetta `retryDelay` dei 429). Qui manteniamo un
    re-try sottile (default 1) per gestire errori non-API/transient di rete
    a livello superiore. Errori di tipo `GeminiQuotaExhausted` o
    `GeminiBudgetExceeded` vengono ri-sollevati senza fallback silenzio
    perché significano "il chunk non va silenziato, va sospeso il job".

    Args:
        text: testo da sintetizzare.
        voice_id: 'gemini:<model_key>:<voice_name>' (es. 'gemini:flash25:Zephyr').
        output_path: percorso file PCM in output.
        max_retries: numero di tentativi (default 1; il backoff vero è in synthesize).
        style_instruction: optional style/tone hint prepended to the prompt.

    Returns:
        dict on success, False on total failure (silence PCM written).

    Raises:
        gemini_tts.GeminiQuotaExhausted: quota raggiunta; il caller deve
            sospendere il job invece di silenziare il chunk.
        gemini_tts.GeminiBudgetExceeded: budget €/giorno o per-job sforato.
    """
    import gemini_tts as _gemini  # late import: keeps module optional

    clean = _sanitize_tts_text(text)
    if clean is None:
        _generate_silence_pcm(output_path, duration_sec=1)
        return False

    # Emergency byte-split: se il chunk supera il byte-cap effettivo (cap API
    # meno margine per i prefissi style/rate), invece di farlo silenziare
    # spezziamo su confine frase e facciamo N chiamate API. Costa +RPD ma
    # garantisce zero buchi audio (principio: qualita' > numero chiamate).
    effective_cap = _pick_chunk_max_bytes(voice_id)
    clean_bytes = len(clean.encode("utf-8"))
    if effective_cap is not None and clean_bytes > effective_cap:
        max_chars_for_split = max(1000, effective_cap // 2)
        pieces = split_text_into_chunks(clean, max_chars=max_chars_for_split, max_bytes=effective_cap)
        if len(pieces) >= 2:
            print(f"[gemini-tts] Emergency byte-split: {clean_bytes} bytes > {effective_cap} cap, "
                  f"splitting into {len(pieces)} sub-chunks")
            agg = _synthesize_pcm_pieces_and_concat(
                pieces, voice_id, output_path, style_instruction, max_retries,
            )
            if agg is not False:
                return agg
            # Fall-through: se lo split fallisce, scriviamo silenzio sotto.
            _generate_silence_pcm(output_path, duration_sec=1)
            return False

    last_error = None
    for attempt in range(max_retries):
        try:
            result = _gemini.synthesize(
                clean, voice_id, output_path=output_path,
                style_instruction=style_instruction,
            )
            return result
        except (_gemini.GeminiQuotaExhausted, _gemini.GeminiBudgetExceeded):
            # Non silenziare: il caller decide se sospendere il job.
            raise
        except Exception as e:
            last_error = e
            snippet = clean[:60].replace('\n', ' ')
            print(f"[gemini-tts] Attempt {attempt+1}/{max_retries} failed for chunk "
                  f"({len(clean)} chars: \"{snippet}...\"): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    print(f"[gemini-tts] WARNING: All {max_retries} attempts failed, "
          f"generating silence ({len(clean)} chars). Last error: {last_error}")
    _generate_silence_pcm(output_path, duration_sec=1)
    return False


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
