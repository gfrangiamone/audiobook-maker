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
import unicodedata

import edge_tts

# Predicato voce PREMIUM Gemini: definizione unica in voice_utils (modulo foglia).
from voice_utils import is_gemini_voice as _is_gemini_voice
from voice_utils import is_speechify_voice as _is_speechify_voice
from voice_utils import is_voxcpm_voice as _is_voxcpm_voice

try:
    import google_tts
except ImportError:
    google_tts = None

from audio_utils import _generate_silence_mp3, _concatenate_mp3

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

CHUNK_MAX_CHARS = 2000

# Timeout (secondi) per una singola chiamata edge-tts. edge-tts non applica
# receive_timeout alla websocket (ws_connect senza timeout in aiohttp): su
# connessione half-open save() resterebbe sospeso per sempre, bloccando il
# thread del job senza errori (incidente 2026-06-11). Il timeout trasforma
# l'hang in TimeoutError, gestito dal retry/fallback di _edge_tts_call.
EDGE_TTS_CHUNK_TIMEOUT = int(os.environ.get("ABM_EDGE_TTS_TIMEOUT", "120"))

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
    try:
        m = re.match(r'\s*([+-]?\d+)\s*%', str(rate))
        if m:
            return max(0.25, 1.0 + int(m.group(1)) / 100.0)
    except (TypeError, ValueError):
        pass
    return 1.0


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


def _pick_chunk_max_chars(voice_id, language):
    """Sceglie il limite caratteri/chunk in base al motore e alla lingua.

    Gemini: delega a gemini_tts.get_max_chunk_chars(lang) (default 700 char
    per stabilita` acustica; override env ABM_GEMINI_CHUNK_CHARS o
    ABM_GEMINI_MAX_CHUNK_CHARS_<LANG>). Richiede Tier 2/3.

    Speechify: speechify_tts.chunk_max_chars() (default 1800, override env
    ABM_SPEECHIFY_CHUNK_CHARS, clampato per sicurezza). L'endpoint rifiuta con
    HTTP 400 un `input` SSML > 2000 char; il testo del chunk piu' l'overhead dei
    tag SSML (<speak>/<prosody>/<speechify:style>) deve stare sotto 2000, quindi
    il cap sul testo resta sotto quel limite (default 1800, ~100 char di margine
    per i tag; il clamp lato speechify_tts impedisce override pericolosi).

    VoxCPM: voxcpm_tts.chunk_max_chars() (default 300, override env
    ABM_VOXCPM_CHUNK_CHARS). Non e' un limite dell'API ma di qualita': il
    modello riancora il timbro al campione solo all'inizio di ogni chunk, e su
    chunk lunghi la voce deriva. Il worker non rispezza i chunk che riceve.

    Edge/Google: 2000 sempre (motori senza vincoli stringenti di RPD).
    """
    if _is_gemini_voice(voice_id):
        lang_code = (language or "").lower().split("-")[0]
        try:
            import gemini_tts
            return gemini_tts.get_max_chunk_chars(lang_code)
        except Exception:
            return 700
    if _is_speechify_voice(voice_id):
        try:
            import speechify_tts
            return speechify_tts.chunk_max_chars()
        except Exception:
            return 1800
    if _is_voxcpm_voice(voice_id):
        try:
            import voxcpm_tts
            return voxcpm_tts.chunk_max_chars()
        except Exception:
            return 300
    return CHUNK_MAX_CHARS


def _pick_chunk_max_bytes(voice_id):
    """Cap byte UTF-8 per chunk per voci Gemini, None per altri motori.

    Si applica al SOLO testo da sintetizzare, in linea con la semantica di
    MAX_BYTES_PER_CALL: e` un target qualita` acustica sul testo audio, non
    sul payload API. I prefissi style/rate aggiunti da synthesize() sono
    direttive di prompt e non concorrono al budget byte qui.
    """
    if not _is_gemini_voice(voice_id):
        return None
    try:
        import gemini_tts
        return int(gemini_tts.MAX_BYTES_PER_CALL)
    except Exception:
        return 700


# Minimo di caratteri per frase standalone: sotto questa soglia accorpiamo
# alla frase successiva per garantire abbastanza contesto al motore TTS.
_TTS_MIN_SENT_CHARS = 80


# ---------------------------------------------------------------------------
# Text splitting
# ---------------------------------------------------------------------------

# Terminatori di frase. Latino: . ! ? … seguiti da whitespace (consumato).
# CJK (giapponese/cinese): 。！？｡ NON seguiti da spazio (split a larghezza zero
# subito dopo il terminatore, che resta nella frase precedente via lookbehind).
# Senza il ramo CJK il testo giapponese/cinese non ha alcun punto di taglio
# (niente spazi) e diventa un'unica "frase" gigante che sfora il cap byte dell'API.
_SENT_SPLIT_RE = re.compile(
    r'(?<=[.!?…])\s+'                       # latino: terminatore + whitespace
    r'|(?<=[。！？｡])'          # CJK: 。 ！ ？ ｡  (zero-width)
)
# Breakpoint "deboli" per spezzare una frase troppo lunga senza terminatori:
# virgole/segni latini e CJK.
_SOFT_BREAK_RE = re.compile(
    r'(?<=[,;:])\s+'                             # latino
    r'|(?<=[、，；：・])'    # CJK: 、 ， ； ： ・
)


def _within(s, max_chars, max_bytes):
    """True se `s` rispetta sia il cap caratteri sia (se dato) il cap byte UTF-8."""
    return (len(s) <= max_chars and
            (max_bytes is None or len(s.encode("utf-8")) <= max_bytes))


def _hard_split_oversized(s, max_chars, max_bytes):
    """Spezza una singola frase oltre i limiti in pezzi <= (max_chars, max_bytes).

    1) prova i breakpoint deboli (virgole CJK/latine);
    2) per i residui ancora oversize (es. lunghe sequenze CJK senza punteggiatura)
       taglio duro carattere-per-carattere rispettando SEMPRE il cap byte —
       garantisce che nessun pezzo superi mai il limite dell'API.
    """
    parts = [p for p in _SOFT_BREAK_RE.split(s) if p]
    merged = []
    cur = ""
    for p in parts:
        # Il breakpoint latino si porta via lo spazio che seguiva la virgola
        # (`(?<=[,;:])\s+` lo consuma): rimettendo insieme due pezzi va
        # restituito, o al TTS arriva «tra cui,pubblicati da Garzanti,Danny»
        # dove il testo diceva «tra cui, pubblicati da Garzanti, Danny». Il
        # breakpoint CJK e' a larghezza zero, non aveva spazi da consumare:
        # li' i pezzi si riattaccano come stavano.
        giunto = " " if cur and cur[-1] in ",;:" else ""
        cand = (cur + giunto + p) if cur else p
        if _within(cand, max_chars, max_bytes):
            cur = cand
        else:
            if cur:
                merged.append(cur)
            cur = p
    if cur:
        merged.append(cur)
    out = []
    for p in merged:
        if _within(p, max_chars, max_bytes):
            out.append(p)
            continue
        buf = ""
        for ch in p:
            cand = buf + ch
            if _within(cand, max_chars, max_bytes):
                buf = cand
            else:
                if buf:
                    out.append(buf)
                buf = ch
        if buf:
            out.append(buf)
    return out


def split_text_into_chunks(text, max_chars=CHUNK_MAX_CHARS, max_bytes=None):
    """Spezza il testo in chunk <= max_chars (e <= max_bytes UTF-8).

    Strategia: tokenizza in frasi (terminatori latini E CJK), pre-spezza ogni
    frase che da sola supera i limiti (caso tipico CJK: testo senza spazi ->
    frasi enormi), poi accumula le frasi adiacenti finche' uno dei due cap viene
    raggiunto. Invariante: nessun chunk supera mai max_bytes — elimina i rifiuti
    "Payload exceeds API hard cap" su giapponese/cinese.

    max_bytes: cap byte UTF-8 opzionale (necessario per Gemini, che limita a
        byte; per il giapponese ogni carattere pesa ~3 byte). Se None, solo chars.
    """
    if not text or not text.strip():
        return [text] if text else [""]
    raw_sentences = _SENT_SPLIT_RE.split(text.strip())
    sentences = [s.strip() for s in raw_sentences if s and s.strip()]
    if not sentences:
        sentences = [text.strip()]
    # Pre-bound: ogni frase oversize viene spezzata sotto i cap.
    bounded = []
    for s in sentences:
        if _within(s, max_chars, max_bytes):
            bounded.append(s)
        else:
            bounded.extend(_hard_split_oversized(s, max_chars, max_bytes))
    chunks = []
    current = ""
    for sent in bounded:
        if not current:
            current = sent
            continue
        candidate = current + " " + sent
        if _within(candidate, max_chars, max_bytes):
            current = candidate
        else:
            chunks.append(current)
            current = sent
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

def _strip_parenthetical(text, strip_round=True, strip_square=True):
    """Rimuove il contenuto tra parentesi tonde e/o quadre (anche annidate).

    strip_round:  se True rimuove il contenuto tra parentesi tonde ().
    strip_square: se True rimuove il contenuto tra parentesi quadre [].

    Se entrambi False la funzione non rimuove alcun contenuto: applica comunque
    la sola normalizzazione whitespace/punteggiatura finale, cosi` l'unica
    differenza tra le modalita` e` la presenza/assenza del testo tra parentesi
    (nessun altro effetto collaterale sul testo). Default: rimuove entrambe
    (comportamento storico).
    """
    if strip_round or strip_square:
        prev = None
        while prev != text:
            prev = text
            if strip_round:
                text = re.sub(r'\([^()]*\)', '', text)
            if strip_square:
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


def _normalize_for_title_match(s):
    """Normalizza una stringa per fuzzy-match titolo: minuscolo, senza diacritici,
    senza punteggiatura/quote, whitespace compatto.

    Es: 'AINULINDALË"LA MUSICA"' -> 'ainulindale la musica'
    """
    if not s:
        return ""
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return s.strip()


def _title_already_in_text(title, text, lookahead_chars=300):
    """True se il titolo del capitolo compare gia` in testa al testo del capitolo,
    a meno di diacritici/punteggiatura/quote/prefissi numerici.

    Evita la duplicazione quando l'estrazione capitoli include gia` un heading
    nel body identico al titolo derivato dai metadati (es. EPUB + filename
    normalizzato).
    """
    if not title or not text:
        return False
    norm_title = _normalize_for_title_match(title)
    # Rimuovi prefisso numerico tipo "003 ", "01 ", "chapter 3 ", "capitolo 4 "
    tokens = norm_title.split()
    while tokens and (tokens[0].isdigit() or tokens[0] in ("chapter", "capitolo", "cap", "ch")):
        tokens.pop(0)
    norm_title_core = ' '.join(tokens)
    # Titolo troppo corto/generico (<= 4 char): meglio non dedupliccare per evitare falsi positivi
    if not norm_title_core or len(norm_title_core) <= 4:
        return False
    head = text[:lookahead_chars]
    norm_head = _normalize_for_title_match(head)
    return norm_title_core in norm_head


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


def _plan_chunks(info, max_chars=CHUNK_MAX_CHARS, max_bytes=None,
                 strip_round=True, strip_square=True):
    """Costruisce la lista di chunk da generare per tutti i capitoli di un BookInfo.

    max_chars: limite caratteri/chunk (default CHUNK_MAX_CHARS=2000).
               Per voci Gemini su lingue CJK/Hindi/Arabo passare 1500.
    max_bytes: cap byte UTF-8 opzionale (None per Edge/Google, MAX_BYTES_PER_CALL
               meno margine di sicurezza per Gemini).
    strip_round/strip_square: se False, il testo tra parentesi tonde/quadre viene
               letto dal TTS invece di essere rimosso (default: rimuove entrambe).
    """
    plan = []
    for ch in info.chapters:
        clean_text = _strip_parenthetical(ch.text, strip_round=strip_round,
                                          strip_square=strip_square)
        clean_text = _ensure_heading_pause(clean_text)
        # Titolo sintetico (placeholder "Section N" generato dal parser per uno
        # spine item senza titolo reale, es. front-matter): NON leggerlo, non e'
        # un titolo del libro. Altrimenti dedup heading: se il titolo compare
        # gia` in testa al testo (a meno di diacritici/punteggiatura/quote/
        # prefissi numerici), evita di prependerlo per non farlo leggere due volte.
        if getattr(ch, "synthetic_title", False) or _title_already_in_text(ch.title, clean_text):
            full_text = clean_text
        else:
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
    last_error = None
    for attempt in range(max_retries):
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
            await asyncio.wait_for(
                communicate.save(output_path), timeout=EDGE_TTS_CHUNK_TIMEOUT
            )
            if _edge_output_looks_truncated(output_path, text, rate):
                try:
                    size = os.path.getsize(output_path)
                except OSError:
                    size = 0
                snippet = text[:60].replace('\n', ' ')
                print(f"[tts] Attempt {attempt+1}/{max_retries} TRUNCATED output "
                      f"({len(text)} chars -> {size}B ~{size/_EDGE_MP3_BYTES_PER_SEC:.1f}s: "
                      f"\"{snippet}...\"): retry")
                last_error = "truncated_output (stream chiuso a meta')"
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue
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


def _generate_silence_pcm(output_path, duration_sec=1, sample_rate=None):
    """Scrive N secondi di silenzio PCM mono 16-bit (zero bytes).

    sample_rate=None usa il default Gemini (24kHz). I chiamanti PCM a rate
    diverso (es. Speechify Simba-3.2, 48kHz nativo) passano il rate reale.
    """
    sr = sample_rate or _PCM_SAMPLE_RATE
    n_bytes = int(duration_sec * sr * _PCM_CHANNELS * _PCM_SAMPLE_WIDTH)
    with open(output_path, "wb") as f:
        if n_bytes > 0:
            f.write(b"\x00" * n_bytes)


# Voci edge-tts di fallback per lingua: usate quando Gemini rifiuta un chunk in
# modo definitivo (tipicamente content policy / safety su testi sensibili) per
# non lasciare un buco di silenzio nell'audiolibro. Chiave = codice lingua a 2
# lettere; valore = voce edge-tts standard neutra per quella lingua.
#
# LEGACY: mappa female-only conservata per retrocompatibilita' (ultimo fallback
# quando il genere della voce Gemini e' ignoto). La selezione vera passa ora da
# `_pick_edge_fallback_voice`, che rispetta genere e accento della voce Gemini
# scelta (vedi sotto): un chunk rifiutato di una voce MASCHILE en-GB non deve
# essere recuperato con una voce femminile en-US (salto di genere + accento).
_EDGE_FALLBACK_VOICES = {
    "it": "it-IT-ElsaNeural",
    "en": "en-US-AriaNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "ar": "ar-EG-SalmaNeural",
    "hi": "hi-IN-SwaraNeural",
    "nl": "nl-NL-ColetteNeural",
    "pl": "pl-PL-ZofiaNeural",
    "tr": "tr-TR-EmelNeural",
}
_EDGE_FALLBACK_DEFAULT = "en-US-AriaNeural"

# Voce edge-tts di fallback per (lingua, codice-accento) -> {genere: voce}.
# I codici-accento sono gli stessi di gemini_tts.ACCENT_VARIANTS (us/gb/au/in,
# es/419, br/pt, fr/ca, cn/tw, de/at/ch, eg/sa/ae): cosi' un chunk rifiutato da
# Gemini viene recuperato con una voce edge dello STESSO accento regionale, non
# solo della stessa lingua. Mantenere allineato con gemini_tts.ACCENT_VARIANTS.
_EDGE_FALLBACK_ACCENT = {
    ("en", "us"): {"Male": "en-US-GuyNeural",     "Female": "en-US-AriaNeural"},
    ("en", "gb"): {"Male": "en-GB-RyanNeural",    "Female": "en-GB-SoniaNeural"},
    ("en", "au"): {"Male": "en-AU-WilliamNeural", "Female": "en-AU-NatashaNeural"},
    ("en", "in"): {"Male": "en-IN-PrabhatNeural", "Female": "en-IN-NeerjaNeural"},
    ("es", "es"):  {"Male": "es-ES-AlvaroNeural", "Female": "es-ES-ElviraNeural"},
    ("es", "419"): {"Male": "es-MX-JorgeNeural",  "Female": "es-MX-DaliaNeural"},
    ("pt", "br"): {"Male": "pt-BR-AntonioNeural", "Female": "pt-BR-FranciscaNeural"},
    ("pt", "pt"): {"Male": "pt-PT-DuarteNeural",  "Female": "pt-PT-RaquelNeural"},
    ("fr", "fr"): {"Male": "fr-FR-HenriNeural",   "Female": "fr-FR-DeniseNeural"},
    ("fr", "ca"): {"Male": "fr-CA-JeanNeural",    "Female": "fr-CA-SylvieNeural"},
    ("zh", "cn"): {"Male": "zh-CN-YunxiNeural",   "Female": "zh-CN-XiaoxiaoNeural"},
    ("zh", "tw"): {"Male": "zh-TW-YunJheNeural",  "Female": "zh-TW-HsiaoChenNeural"},
    ("de", "de"): {"Male": "de-DE-ConradNeural",  "Female": "de-DE-KatjaNeural"},
    ("de", "at"): {"Male": "de-AT-JonasNeural",   "Female": "de-AT-IngridNeural"},
    ("de", "ch"): {"Male": "de-CH-JanNeural",     "Female": "de-CH-LeniNeural"},
    ("ar", "eg"): {"Male": "ar-EG-ShakirNeural",  "Female": "ar-EG-SalmaNeural"},
    ("ar", "sa"): {"Male": "ar-SA-HamedNeural",   "Female": "ar-SA-ZariyahNeural"},
    ("ar", "ae"): {"Male": "ar-AE-HamdanNeural",  "Female": "ar-AE-FatimaNeural"},
}

# Voce edge-tts di fallback per lingua -> {genere: voce}. Usata quando la lingua
# non ha varianti d'accento (mono-variante) o l'accento richiesto non e' mappato:
# garantisce comunque la coerenza di GENERE con la voce Gemini scelta.
_EDGE_FALLBACK_GENDER = {
    "en": {"Male": "en-US-GuyNeural",     "Female": "en-US-AriaNeural"},
    "es": {"Male": "es-ES-AlvaroNeural",  "Female": "es-ES-ElviraNeural"},
    "fr": {"Male": "fr-FR-HenriNeural",   "Female": "fr-FR-DeniseNeural"},
    "de": {"Male": "de-DE-ConradNeural",  "Female": "de-DE-KatjaNeural"},
    "pt": {"Male": "pt-BR-AntonioNeural", "Female": "pt-BR-FranciscaNeural"},
    "zh": {"Male": "zh-CN-YunxiNeural",   "Female": "zh-CN-XiaoxiaoNeural"},
    "ar": {"Male": "ar-EG-ShakirNeural",  "Female": "ar-EG-SalmaNeural"},
    "it": {"Male": "it-IT-DiegoNeural",   "Female": "it-IT-ElsaNeural"},
    "ru": {"Male": "ru-RU-DmitryNeural",  "Female": "ru-RU-SvetlanaNeural"},
    "ja": {"Male": "ja-JP-KeitaNeural",   "Female": "ja-JP-NanamiNeural"},
    "ko": {"Male": "ko-KR-InJoonNeural",  "Female": "ko-KR-SunHiNeural"},
    "hi": {"Male": "hi-IN-MadhurNeural",  "Female": "hi-IN-SwaraNeural"},
    "nl": {"Male": "nl-NL-MaartenNeural", "Female": "nl-NL-ColetteNeural"},
    "pl": {"Male": "pl-PL-MarekNeural",   "Female": "pl-PL-ZofiaNeural"},
    "tr": {"Male": "tr-TR-AhmetNeural",   "Female": "tr-TR-EmelNeural"},
}


def _pick_edge_fallback_voice(lang2, gender=None, accent_code=None):
    """Sceglie la voce edge-tts di fallback coerente per genere e accento con la
    voce Gemini rifiutata. Priorita':
      1. (lingua, accento) + genere  -> stesso accento regionale e stesso genere
      2. lingua + genere             -> almeno stesso genere (accento standard)
      3. mappa legacy female-only    -> retrocompat (genere ignoto)
      4. default globale
    `gender`: 'Male'/'Female' (case-insensitive) o None. None -> Female
    (comportamento storico). `accent_code`: codice come in ACCENT_VARIANTS.
    """
    lang2 = (lang2 or "").split("-")[0].lower()
    g = "Male" if str(gender or "").strip().lower().startswith("m") else "Female"
    if accent_code:
        ac = str(accent_code).strip().lower()
        by_acc = _EDGE_FALLBACK_ACCENT.get((lang2, ac))
        if by_acc and by_acc.get(g):
            return by_acc[g]
    by_lang = _EDGE_FALLBACK_GENDER.get(lang2)
    if by_lang and by_lang.get(g):
        return by_lang[g]
    if lang2 in _EDGE_FALLBACK_VOICES:
        return _EDGE_FALLBACK_VOICES[lang2]
    return _EDGE_FALLBACK_DEFAULT


def _mp3_to_pcm_24k(mp3_path, pcm_path):
    """Converte un MP3 in PCM raw 24kHz mono 16-bit (stesso formato dei chunk
    Gemini, cosi' il PCM edge si concatena senza discontinuita' di sample rate).
    Ritorna True se il PCM prodotto e' non vuoto. Best-effort: log su errore."""
    import subprocess
    try:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", mp3_path,
            "-ar", str(_PCM_SAMPLE_RATE), "-ac", str(_PCM_CHANNELS),
            "-f", "s16le", pcm_path,
        ]
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return os.path.exists(pcm_path) and os.path.getsize(pcm_path) > 0
    except Exception as e:
        print(f"[gemini-tts] edge-fallback mp3->pcm failed: {e}")
        return False


def _edge_fallback_to_pcm(text, fallback_lang, rate, output_path,
                          gender=None, accent_code=None):
    """Sintetizza `text` con una voce edge-tts standard e scrive il risultato
    come PCM 24kHz mono in output_path. Usato quando Gemini rifiuta il chunk in
    modo definitivo: una voce standard e' preferibile a un buco di silenzio.

    La voce edge e' scelta per essere coerente in GENERE e ACCENTO con la voce
    Gemini originariamente selezionata (`gender`/`accent_code`), cosi' un chunk
    rifiutato di una voce maschile en-GB non viene recuperato con una voce
    femminile en-US (salto di genere + accento udibile).

    Ritorna un dict in stile synthesize() (marcato fallback_engine='edge') su
    successo, oppure False. Non solleva: ogni errore -> False (il caller scrive
    comunque il silenzio a monte).
    """
    lang2 = (fallback_lang or "").split("-")[0].lower()
    voice = _pick_edge_fallback_voice(lang2, gender=gender, accent_code=accent_code)
    tmp_mp3 = output_path + ".edgefallback.mp3"
    # Loop asyncio dedicato e isolato: generate_chunk_mp3 e' async ma qui siamo
    # in contesto sincrono, fuori dal loop del thread di generazione. Un loop
    # nuovo evita di interferire con quello usato dai chunk edge nativi.
    _loop = None
    try:
        _loop = asyncio.new_event_loop()
        _loop.run_until_complete(
            generate_chunk_mp3(text, voice, rate or "+0%", tmp_mp3, max_retries=3)
        )
    except Exception as e:
        print(f"[gemini-tts] edge-fallback synth failed (voice={voice}): {e}")
        return False
    finally:
        if _loop is not None:
            try:
                _loop.close()
            except Exception:
                pass
    if not (os.path.exists(tmp_mp3) and os.path.getsize(tmp_mp3) > 0):
        return False
    ok = _mp3_to_pcm_24k(tmp_mp3, output_path)
    try:
        os.remove(tmp_mp3)
    except Exception:
        pass
    if not ok:
        return False
    try:
        bytes_written = os.path.getsize(output_path)
    except Exception:
        bytes_written = 0
    print(f"[gemini-tts] edge-fallback OK: chunk recuperato con voce {voice} "
          f"({bytes_written} bytes PCM)")
    return {
        "success": True,
        "bytes_written": bytes_written,
        "audio_seconds_real": bytes_written / float(
            _PCM_SAMPLE_RATE * _PCM_CHANNELS * _PCM_SAMPLE_WIDTH),
        "input_tokens": 0,
        "output_tokens": 0,
        "model_key": None,
        "voice_name": voice,
        "fallback_engine": "edge",
    }


def _synthesize_pcm_pieces_and_concat(pieces, voice_id, output_path, style_instruction, max_retries,
                                      debug_prompt_path=None, rate="+0%", accent_directive=None,
                                      job_id=None):
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
        # Coerenza con synthesize(): il backend che ha davvero eseguito e la
        # provenienza dei token. Se anche un solo pezzo ha token derivati
        # (Cloudflare, che non li misura) l'aggregato non e' misurato.
        # NB: "backend" resta l'ultimo pezzo scritto (last-write-wins) per
        # compatibilita' con i chiamanti esistenti - su un chunk misto (il
        # circuit breaker scatta a meta') puo' quindi riportare "vertex" anche
        # se dei pezzi precedenti sono girati su Cloudflare. Per qualunque
        # decisione che debba sapere "Cloudflare e' stato toccato in questo
        # chunk" usare `cf_used` sotto, non `backend`: quello e' un OR fra
        # tutti i pezzi, mai sovrascritto dall'ultimo. Il ledger del credito
        # Cloudflare non dipende da questo campo (ogni pezzo si addebita da
        # solo dentro synthesize()): serve alla contabilita'/diagnostica a
        # valle che leggono l'aggregato invece dei singoli pezzi.
        "backend": None,
        "cf_used": False,
        "tokens_measured": True,
    }

    tmp_parts = []
    try:
        with open(output_path, "wb") as fout:
            for idx, piece_text in enumerate(pieces):
                tmp_path = output_path + f".part{idx:03d}.pcm"
                tmp_parts.append(tmp_path)
                last_error = None
                piece_ok = False
                # Per-piece debug prompt path (es. prompt5.txt -> prompt5.part000.txt)
                piece_debug_path = None
                if debug_prompt_path:
                    base, ext = os.path.splitext(debug_prompt_path)
                    piece_debug_path = f"{base}.part{idx:03d}{ext or '.txt'}"
                for attempt in range(max_retries):
                    try:
                        result = _gemini.synthesize(
                            piece_text, voice_id, output_path=tmp_path,
                            style_instruction=style_instruction,
                            rate=rate,
                            debug_prompt_path=piece_debug_path,
                            accent_directive=accent_directive,
                            job_id=job_id,
                        )
                        piece_ok = True
                        aggregate["bytes_written"] += int(result.get("bytes_written", 0))
                        aggregate["audio_seconds_real"] += float(result.get("audio_seconds_real", 0.0))
                        aggregate["input_tokens"] += int(result.get("input_tokens", 0))
                        aggregate["output_tokens"] += int(result.get("output_tokens", 0))
                        aggregate["model_key"] = result.get("model_key") or aggregate["model_key"]
                        aggregate["voice_name"] = result.get("voice_name") or aggregate["voice_name"]
                        aggregate["attempts_used"] = max(aggregate["attempts_used"], int(result.get("attempts_used", 1)))
                        aggregate["backend"] = result.get("backend") or aggregate["backend"]
                        if result.get("backend") == "cloudflare":
                            aggregate["cf_used"] = True
                        if not result.get("tokens_measured"):
                            aggregate["tokens_measured"] = False
                        break
                    except (_gemini.GeminiQuotaExhausted, _gemini.GeminiBudgetExceeded,
                            _gemini.GeminiUnavailable):
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


def generate_chunk_pcm_gemini(text, voice_id, output_path, max_retries=1, style_instruction=None,
                              debug_prompt_path=None, rate="+0%", accent_directive=None,
                              failure_info=None, fallback_lang=None, accent_code=None,
                              job_id=None):
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
        job_id: opzionale, id del job in corso; propagato a
            gemini_tts.synthesize() per tracciare quale job ha visto
            l'eventuale avaria del backend (vedi tts_backend_state).

    Returns:
        dict on success, False on total failure (silence PCM written).

    Raises:
        gemini_tts.GeminiQuotaExhausted: quota raggiunta; il caller deve
            sospendere il job invece di silenziare il chunk.
        gemini_tts.GeminiBudgetExceeded: budget €/giorno o per-job sforato.
    """
    import gemini_tts as _gemini  # late import: keeps module optional

    def _fail(reason, detail=""):
        if isinstance(failure_info, dict):
            failure_info["reason"] = reason
            failure_info["detail"] = str(detail)[:300]
        return False

    clean = _sanitize_tts_text(text)
    if clean is None:
        _generate_silence_pcm(output_path, duration_sec=1)
        return _fail("empty_after_sanitize")

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
                debug_prompt_path=debug_prompt_path, rate=rate,
                accent_directive=accent_directive, job_id=job_id,
            )
            if agg is not False:
                return agg
            # Fall-through: se lo split fallisce, scriviamo silenzio sotto.
            _generate_silence_pcm(output_path, duration_sec=1)
            return _fail("byte_split_failed", f"{len(pieces)} sub-chunk")

    last_error = None
    for attempt in range(max_retries):
        try:
            result = _gemini.synthesize(
                clean, voice_id, output_path=output_path,
                style_instruction=style_instruction,
                rate=rate,
                debug_prompt_path=debug_prompt_path,
                accent_directive=accent_directive,
                job_id=job_id,
            )
            return result
        except (_gemini.GeminiQuotaExhausted, _gemini.GeminiBudgetExceeded,
                _gemini.GeminiUnavailable):
            # Non silenziare: il caller decide se sospendere il job.
            # GeminiUnavailable (kill-switch/capability) e' istantaneo e
            # permanente per il processo: silenziarlo significherebbe
            # silenziare l'INTERO libro (incidente 2026-06).
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
    # Prima del silenzio: tenta una voce edge-tts standard, cosi' un chunk
    # rifiutato da Gemini (tipicamente content policy / safety su testi
    # sensibili) non lascia un buco muto nell'audiolibro. Solo se conosciamo la
    # lingua di lettura. Su successo il chunk NON conta come failed.
    if fallback_lang:
        # Genere della voce Gemini scelta (voice_id = 'gemini:<model>:<Voice>'):
        # serve a scegliere una voce edge dello stesso genere ed evitare il
        # salto maschile<->femminile percepito dall'utente.
        gemini_gender = None
        try:
            _vname = str(voice_id).split(":")[-1]
            gemini_gender = _gemini.GEMINI_VOICE_GENDER.get(_vname)
        except Exception:
            gemini_gender = None
        fb = _edge_fallback_to_pcm(clean, fallback_lang, rate, output_path,
                                   gender=gemini_gender, accent_code=accent_code)
        if fb is not False:
            if isinstance(failure_info, dict):
                failure_info["fallback_engine"] = "edge"
                failure_info["reason"] = "gemini_failed_edge_fallback"
                failure_info["detail"] = str(last_error)[:300] if last_error else ""
            return fb
    _generate_silence_pcm(output_path, duration_sec=1)
    return _fail("synthesize_failed", str(last_error) if last_error else "")


def generate_chunk_pcm_speechify(text, voice_id, output_path, emotion=None,
                                 rate="+0%", max_retries=1, failure_info=None):
    """Genera PCM 16-bit mono da testo via Speechify Simba-3.2 con fallback silenzio.

    SpeechifyUnavailable viene ri-sollevata (errore permanente: silenziarlo
    silenzierebbe l'intero libro). Su testo vuoto o fallimento totale scrive
    silenzio PCM e ritorna False.
    """
    import speechify_tts as _spx

    def _fail(reason, detail=""):
        if isinstance(failure_info, dict):
            failure_info["reason"] = reason
            failure_info["detail"] = str(detail)[:300]
        return False

    clean = _sanitize_tts_text(text)
    if clean is None:
        # Speechify Simba-3.2 e' nativo a 48000 Hz: il silenzio di fallback deve
        # usare lo stesso sample rate, altrimenti a 24000 durerebbe ~0.5s reali
        # nello stream a 48kHz e sballerebbe i marker M4B.
        _generate_silence_pcm(output_path, duration_sec=1, sample_rate=48000)
        return _fail("empty_after_sanitize")

    last_error = None
    for attempt in range(max_retries):
        try:
            return _spx.synthesize(clean, voice_id, output_path,
                                   emotion=emotion, rate=rate)
        except _spx.SpeechifyUnavailable:
            raise  # non silenziare: il caller decide
        except Exception as e:
            last_error = e
            snippet = clean[:60].replace('\n', ' ')
            print(f"[speechify] Attempt {attempt+1}/{max_retries} failed "
                  f"({len(clean)} chars: \"{snippet}...\"): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    print(f"[speechify] WARNING: all {max_retries} attempts failed, silence "
          f"({len(clean)} chars). Last error: {last_error}")
    _generate_silence_pcm(output_path, duration_sec=1, sample_rate=48000)
    return _fail("synthesize_failed", str(last_error) if last_error else "")


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
