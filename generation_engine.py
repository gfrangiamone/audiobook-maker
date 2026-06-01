"""
generation_engine.py — Ottimizzazione LLM e generazione audio per Audiobook Maker.

Funzioni principali:
  - configure(): inietta i riferimenti globali condivisi (jobs, upload_dir, ecc.)
  - _CancelledError, _SimpleChapter, _SimpleBookInfo: classi helper
  - parse_txt, parse_abm: parser file di testo/progetto
  - _init_llm, _llm_available: inizializzazione client LLM
  - _call_llm, _optimize_chapter_text: ottimizzazione LLM
  - _generate_optimized_abm: genera snapshot .abm post-ottimizzazione
  - _send_completion_email, _send_optimization_email: email di completamento
  - _refund_job_payment: rimborso pagamento in caso di errore/cancellazione
  - run_optimization: background thread per ottimizzazione LLM
  - run_generation: background thread per generazione TTS

Dipende da: email_service, payment, audio_utils, tts_split.
Il modulo non importa da audiobook_app per evitare import circolari.
Usa configure() per ricevere i riferimenti ai dati condivisi.
"""

import asyncio
import json
import os
import re
import shutil
import threading
import time
import uuid
from copy import copy
from pathlib import Path

import email_service
import payment
import cancel_policy
import storage_backend
import storage_tiering
try:
    import gemini_tts
except ImportError:
    gemini_tts = None
import gemini_cost_audit
from audio_utils import (
    _safe_filename, _include_cover_in_dir,
    _generate_silence_mp3, _concatenate_mp3,
    _get_audio_duration_ms, _convert_mp3_to_m4b,
    _prepare_m4b_cover_path,
    _generate_podcast_rss,
    pcm_size_to_seconds,
    pcm_to_mp3, pcm_to_aac_m4b,
    trim_pcm_trailing_silence,
)
from tts_split import (
    _plan_chunks, generate_chunk_mp3, generate_chunk_mp3_google,
    _pick_chunk_max_chars, _pick_chunk_max_bytes,
    generate_chunk_pcm_gemini, _generate_silence_pcm,
)

# ---------------------------------------------------------------------------
# LLM (text-optimization) config — engine-agnostic, env-driven
# ---------------------------------------------------------------------------
# Tutti i parametri sono override-able via ABM_LLM_* environment variables.
# I default attuali sono tarati su DeepSeek-Chat (provider corrente). Cambiare
# provider richiede solo di rivalorizzare le env var (no code change).

def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default

def _env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default

def _env_bool(name, default):
    return os.environ.get(name, "true" if default else "false").strip().lower() in ("true", "1", "yes", "on")

# Connection
LLM_API_KEY  = os.environ.get("ABM_LLM_API_KEY", "")
LLM_API_BASE = os.environ.get("ABM_LLM_API_BASE", "https://api.deepseek.com")
LLM_MODEL    = os.environ.get("ABM_LLM_MODEL", "deepseek-chat")

# Generation behavior
LLM_THINKING         = _env_bool("ABM_LLM_THINKING", False)
LLM_REASONING_EFFORT = os.environ.get("ABM_LLM_REASONING_EFFORT", "none").strip().lower()
LLM_TEMPERATURE      = _env_float("ABM_LLM_TEMPERATURE", 0.3)
LLM_MAX_TOKENS       = _env_int("ABM_LLM_MAX_TOKENS", 65536)

# Token-economy helpers
LLM_CHARS_PER_TOKEN        = _env_float("ABM_LLM_CHARS_PER_TOKEN", 3.5)
LLM_MAX_CONTEXT_TOKENS     = _env_int("ABM_LLM_MAX_CONTEXT_TOKENS", 1000000)
LLM_RESERVED_PROMPT_TOKENS = _env_int("ABM_LLM_RESERVED_PROMPT_TOKENS", 4000)
LLM_OUTPUT_SAFETY_MARGIN   = _env_float("ABM_LLM_OUTPUT_SAFETY_MARGIN", 0.85)

# Reliability / pacing
LLM_REQUEST_TIMEOUT_SEC   = _env_float("ABM_LLM_REQUEST_TIMEOUT_SEC", 120.0)
LLM_MAX_RETRIES           = _env_int("ABM_LLM_MAX_RETRIES", 4)
LLM_INTER_CHUNK_SLEEP_SEC = _env_float("ABM_LLM_INTER_CHUNK_SLEEP_SEC", 0.5)
LLM_HEARTBEAT_TIMEOUT_SEC = _env_float("ABM_LLM_HEARTBEAT_TIMEOUT_SEC", 60.0)
LLM_TRIVIAL_INPUT_MIN_CHARS = _env_int("ABM_LLM_TRIVIAL_INPUT_MIN_CHARS", 80)
LLM_LEAK_MAX_RETRIES = _env_int("ABM_LLM_LEAK_MAX_RETRIES", 2)

# Derived (computed, not directly configurable)
LLM_RESERVED_OUTPUT_TOKENS = LLM_MAX_TOKENS  # output cap reserves itself in context
LLM_MAX_INPUT_TOKENS = LLM_MAX_CONTEXT_TOKENS - LLM_RESERVED_OUTPUT_TOKENS - LLM_RESERVED_PROMPT_TOKENS
LLM_MAX_INPUT_CHARS = int(LLM_MAX_INPUT_TOKENS * LLM_CHARS_PER_TOKEN)
# Safe chunk size in chars: garantisce che l'output entri in MAX_TOKENS.
# Con default 65536 token output → ~195k char/chunk. Prompt ricaricato identico
# per ogni chunk → regole sempre rispettate anche su libri lunghi.
LLM_SAFE_OUTPUT_CHUNK = int(LLM_MAX_TOKENS * LLM_CHARS_PER_TOKEN * LLM_OUTPUT_SAFETY_MARGIN)

_SCRIPT_DIR = Path(__file__).parent.resolve()

_llm_client = None

BASE_URL = os.environ.get("ABM_BASE_URL", "").rstrip("/")

# ---------------------------------------------------------------------------
# Module-level configured state (set via configure())
# ---------------------------------------------------------------------------

_jobs = None            # reference to jobs dict in audiobook_app
_upload_dir = None      # Path to data directory
_download_tokens = None # reference to token dict in audiobook_app
_save_tokens = None     # callable: persist tokens to disk
_log_activity = lambda *a, **kw: None   # callable: log activity (default: no-op)
_google_tts = None      # optional google_tts module
_invalidate_voices_cache = lambda: None  # callable (default: no-op)
_retention_sec = 64800  # job retention in seconds (configurable via ABM_JOB_RETENTION_SEC)
_gemini_retention_sec = 172800  # job retention per voci PREMIUM/Gemini (ABM_GEMINI_JOB_RETENTION_SEC)
_write_email_marker = None  # callable(work_dir, when): mark job dir as email-sent
_lookup_client_email = lambda cid: ""  # callable(cid) -> email or ""


def _is_gemini_voice(voice):
    """True per voice id Gemini (`gemini:<model>:<voice>`)."""
    return bool(voice) and isinstance(voice, str) and voice.startswith("gemini:")


def _retention_for_job(job):
    """Retention sec per il job (Gemini -> _gemini_retention_sec).
    Fallback su `opt_voice` per il flusso optimize-only/batch dove `voice`
    non e' ancora settato (lo /api/generate lo scrive, /api/optimize no)."""
    if not isinstance(job, dict):
        return _retention_sec
    v = job.get("voice", "") or job.get("opt_voice", "")
    return _gemini_retention_sec if _is_gemini_voice(v) else _retention_sec

CHAPTER_SILENCE_SEC = 3  # secondi di silenzio all'inizio di ogni capitolo


def _set_job_status(job, status):
    """Thread-safe job status update."""
    if _jobs_lock:
        with _jobs_lock:
            job["status"] = status
    else:
        job["status"] = status


def configure(jobs, upload_dir, download_tokens, save_tokens_fn, log_activity_fn,
              google_tts_module=None, invalidate_voices_cache_fn=None, jobs_lock=None,
              retention_sec=None, gemini_retention_sec=None, write_email_marker_fn=None,
              lookup_client_email_fn=None):
    """Inietta i riferimenti alle strutture dati condivise di audiobook_app.
    Chiamare una volta al startup, prima di avviare qualsiasi thread.
    """
    global _jobs, _upload_dir, _download_tokens, _save_tokens, _log_activity
    global _google_tts, _invalidate_voices_cache, _jobs_lock, _retention_sec
    global _gemini_retention_sec, _write_email_marker, _lookup_client_email
    _jobs = jobs
    _upload_dir = Path(upload_dir)
    _download_tokens = download_tokens
    _save_tokens = save_tokens_fn
    _log_activity = log_activity_fn
    _google_tts = google_tts_module
    if invalidate_voices_cache_fn is not None:
        _invalidate_voices_cache = invalidate_voices_cache_fn
    _jobs_lock = jobs_lock
    _retention_sec = retention_sec if retention_sec is not None else 64800
    _gemini_retention_sec = gemini_retention_sec if gemini_retention_sec is not None else 172800
    _write_email_marker = write_email_marker_fn
    if lookup_client_email_fn is not None:
        _lookup_client_email = lookup_client_email_fn
    
    # Inizializza client LLM (se API key presente)
    _init_llm()


# ---------------------------------------------------------------------------
# LLM client init (OpenAI-compatible)
# ---------------------------------------------------------------------------

def _init_llm():
    """Initialize LLM client and verify presence of essential prompts."""
    global _llm_client
    if not LLM_API_KEY:
        print("[startup] LLM text optimization disabled (ABM_LLM_API_KEY not set)")
        return
    try:
        from openai import OpenAI
        _llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_API_BASE)
        # Verifica almeno il prompt generico
        generic_path = _SCRIPT_DIR / "prompt_opt_AI" / "prompt_tts_generic.md"
        if not generic_path.exists():
            print(f"WARNING: {generic_path} not found \u2014 LLM optimization may fail.", flush=True)
        else:
            print(f"[startup] LLM text optimization enabled (Model: {LLM_MODEL}, MaxTokens: {LLM_MAX_TOKENS}, Reasoning: {LLM_REASONING_EFFORT}, Thinking: {LLM_THINKING})")
    except ImportError:
        print("WARNING: openai library not installed \u2014 LLM optimization disabled. Run: pip install openai", flush=True)
        _llm_client = None


def _llm_available():
    """True se l'ottimizzazione LLM è disponibile."""
    return _llm_client is not None


# ---------------------------------------------------------------------------
# Helper classes
# ---------------------------------------------------------------------------

class _CancelledError(Exception):
    """Raised when a generation job is cancelled."""
    pass


class _SimpleChapter:
    """Lightweight chapter object compatible with BookInfo.chapters interface."""
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text
        self.word_count = len(text.split())
        self.char_count = len(text)


class _SimpleBookInfo:
    """Lightweight book info for TXT files, duck-typed to match BookInfo."""
    def __init__(self, title, author, text):
        self.title = title
        self.author = author
        self.language = ""
        ch = _SimpleChapter(1, title, text)
        self.chapters = [ch]
        self.total_words = ch.word_count
        self.total_chars = ch.char_count
        self.estimated_duration_minutes = self.total_words / 150


# ---------------------------------------------------------------------------
# File parsers
# ---------------------------------------------------------------------------

def parse_txt(file_path):
    """Parse a plain text file into a _SimpleBookInfo."""
    path = Path(file_path)
    # Try UTF-8 first, fall back to latin-1
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        text = path.read_text(encoding="latin-1", errors="replace")

    text = text.strip()
    if not text:
        raise ValueError("Text file is empty")

    # Title = filename without extension
    title = path.stem.replace("_", " ").replace("-", " ").strip() or "Text"
    return _SimpleBookInfo(title=title, author="", text=text)


def parse_abm(file_path):
    """Parse an .abm project file (ZIP with manifest + chapter texts + optional cover).

    Returns (info, cover_info) where info is duck-typed BookInfo and
    cover_info is {"data": bytes, "filename": str} or None.
    """
    import zipfile

    path = Path(file_path)
    if not zipfile.is_zipfile(str(path)):
        raise ValueError("Invalid .abm file: not a valid ZIP archive")

    from secure_archive import safe_zip_path, check_zip_bomb, ZipSafetyError

    with zipfile.ZipFile(str(path), "r") as zf:
        # Zip-bomb / total-size guard PRIMA di leggere qualsiasi cosa
        try:
            check_zip_bomb(zf)
        except ZipSafetyError as e:
            raise ValueError(f"Invalid .abm file: {e}")
        # Read and validate manifest
        try:
            manifest_data = zf.read("manifest.json")
        except KeyError:
            raise ValueError("Invalid .abm file: manifest.json not found")

        try:
            manifest = json.loads(manifest_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid .abm file: malformed manifest.json ({e})")

        if manifest.get("format") != "audiobook-maker-project":
            raise ValueError("Invalid .abm file: unrecognized format in manifest.json")

        title = manifest.get("title", path.stem)
        author = manifest.get("author", "")
        language = manifest.get("language", "")

        # Read chapters in manifest order
        chapters_meta = manifest.get("chapters", [])
        if not chapters_meta:
            raise ValueError("Invalid .abm file: no chapters listed in manifest")

        chapters = []
        for cm in chapters_meta:
            fname = cm.get("filename", "")
            ch_title = cm.get("title", f"Chapter {cm.get('index', '?')}")
            ch_index = cm.get("index", len(chapters) + 1)

            raw_path = f"chapters/{fname}" if not fname.startswith("chapters/") else fname
            try:
                # Zip-slip: rifiuta path che escono dalla virtual root "chapters/"
                ch_path = safe_zip_path(raw_path, base="chapters")
            except ZipSafetyError as e:
                print(f"[abm] WARNING: skipping unsafe chapter path '{raw_path}': {e}")
                continue
            try:
                ch_text = zf.read(ch_path).decode("utf-8").strip()
            except KeyError:
                print(f"[abm] WARNING: chapter file '{ch_path}' not found in archive, skipping")
                continue
            except UnicodeDecodeError:
                ch_text = zf.read(ch_path).decode("latin-1", errors="replace").strip()

            if not ch_text:
                continue

            chapters.append(_SimpleChapter(index=ch_index, title=ch_title, text=ch_text))

        if not chapters:
            raise ValueError("Invalid .abm file: no readable chapter content found")

        # Build BookInfo-compatible object
        info = _SimpleBookInfo.__new__(_SimpleBookInfo)
        info.title = title
        info.author = author
        info.language = language
        info.chapters = chapters
        info.total_words = sum(ch.word_count for ch in chapters)
        info.total_chars = sum(ch.char_count for ch in chapters)
        info.estimated_duration_minutes = info.total_words / 150

        # Extract cover if present
        cover_info = None
        if manifest.get("has_cover") and manifest.get("cover_file"):
            cover_file_raw = manifest["cover_file"]
            try:
                cover_file = safe_zip_path(cover_file_raw)
            except ZipSafetyError as e:
                print(f"[abm] WARNING: skipping unsafe cover path '{cover_file_raw}': {e}")
                cover_file = None
            if cover_file:
                try:
                    cover_data = zf.read(cover_file)
                    if len(cover_data) > 100:  # sanity check
                        cover_info = {"data": cover_data, "filename": cover_file}
                except KeyError:
                    pass

    return info, cover_info


# ---------------------------------------------------------------------------
# LLM text optimization helpers
# ---------------------------------------------------------------------------

def _split_text_into_chunks(text, max_chars):
    """Split text into chunks respecting paragraph boundaries (LLM chunker)."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current_chunk = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)
        if para_size > max_chars:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            sentences = re.split(r'(?<=[.!?\u2026])\s+', para)
            sub_chunk = []
            sub_size = 0
            for sent in sentences:
                if sub_size + len(sent) > max_chars and sub_chunk:
                    chunks.append(" ".join(sub_chunk))
                    sub_chunk = []
                    sub_size = 0
                sub_chunk.append(sent)
                sub_size += len(sent)
            if sub_chunk:
                chunks.append(" ".join(sub_chunk))
            continue
        if current_size + para_size + 2 > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_size = 0
        current_chunk.append(para)
        current_size += para_size + 2
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return chunks


# Pattern di preamboli/postfazioni meta che il LLM a volte emette nonostante
# il prompt vieti commenti.
_LLM_PREAMBLE_PATTERNS = (
    # Inglese
    r"^(understood|sure|certainly|of\s+course|got\s+it|okay|ok|alright|"
    r"here(?:'s|\s+is)\s+(?:the\s+)?(?:optimized|cleaned|edited|revised)(?:\s+text|\s+version)?|"
    r"below\s+is\s+the|following\s+the\s+rules?|according\s+to\s+the\s+rules?|"
    r"as\s+requested|as\s+instructed|noted)\b",
    # Italiano
    r"^(capito|compreso|d[\u2019']accordo|ho\s+capito|perfetto|va\s+bene|certo|"
    r"ecco\s+(?:il|la|una)?\s*(?:testo|versione)(?:\s+ottimizzata?|\s+rivista|\s+pulita|\s+corretta)?|"
    r"seguendo\s+le\s+regole|secondo\s+le\s+regole|come\s+richiesto)\b",
    # Francese / spagnolo / tedesco (difese minori ma utili)
    r"^(compris|d[\u2019']accord|voici\s+le\s+texte|suivant\s+les\s+r[\u00e8e]gles|"
    r"entendido|de\s+acuerdo|aqu[\u00ed][\s\t]+est[\u00e1a]\s+el\s+texto|"
    r"verstanden|hier\s+ist\s+der\s+text)\b",
)
_LLM_PREAMBLE_RE = re.compile(
    "|".join(_LLM_PREAMBLE_PATTERNS), re.IGNORECASE | re.UNICODE
)


def _sanitize_llm_output(text: str) -> str:
    """Rimuove contaminazioni tipiche dell'output LLM prima di passarlo al TTS.

    1) Preamboli/postfazioni meta
    2) Paragrafi/righe duplicate consecutive
    """
    if not text:
        return text

    # 1) Strip preamble: rimuovi in testa le prime righe che iniziano con un marcatore meta
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    stripped_any = False
    while idx < len(lines):
        candidate = lines[idx].strip()
        if not candidate:
            if stripped_any:
                idx += 1
            break
        is_preamble = bool(_LLM_PREAMBLE_RE.match(candidate))
        is_meta_header = (
            len(candidate) <= 80 and candidate.endswith(":")
            and not candidate[0].islower()
        )
        if is_preamble or (stripped_any and is_meta_header):
            idx += 1
            stripped_any = True
            continue
        break

    # 2) Strip trailing meta: ultime righe tipo "Note: ..." o "[End of optimized text]"
    end = len(lines)
    while end > idx:
        tail = lines[end - 1].strip()
        if not tail:
            end -= 1
            continue
        if tail.startswith(("Note:", "Nota:", "[Note", "[End", "[Fine",
                            "\u2014 End", "- End")):
            end -= 1
            continue
        break

    cleaned = "\n".join(lines[idx:end]).strip("\n")

    # 3) Deduplica paragrafi consecutivi identici
    paragraphs = re.split(r"\n{2,}", cleaned)
    deduped = []
    for p in paragraphs:
        p_norm = p.strip()
        if not p_norm:
            continue
        if deduped and deduped[-1].strip() == p_norm:
            continue
        deduped.append(p)

    # 4) Deduplica righe consecutive identiche all'interno di un paragrafo
    final_paragraphs = []
    for p in deduped:
        plines = p.split("\n")
        out_lines = []
        for ln in plines:
            if out_lines and out_lines[-1].strip() and out_lines[-1].strip() == ln.strip():
                continue
            out_lines.append(ln)
        final_paragraphs.append("\n".join(out_lines))

    return "\n\n".join(final_paragraphs).strip()


class _PromptLeakError(Exception):
    """Sollevata quando l'output LLM contiene un echo del system prompt.

    Caso reale osservato: cap. 15 di Libretto_Es_Frat2026_optimized.abm
    conteneva il file prompt_tts_it.md letterale al posto del capitolo.
    """


_LEAK_PREFIX_LEN = 120      # char di "fingerprint" presi dal capo del prompt
_LEAK_PREFIX_MIN = 60       # soglia minima utile per evitare match casuali su prompt cortissimi
_LEAK_SEARCH_WINDOW = 400   # finestra iniziale dell'output in cui cercare il prefix (tollera heading saltati)
_LEAK_BLOCK_LEN = 200       # dimensione blocco contiguo per lo scan generale
_LEAK_BLOCK_STEP = 150      # passo dello scan: overlap di 50 char per non perdere match a cavallo del confine


def _is_prompt_leak(text, system_prompt):
    """True se `text` appare essere un echo del system prompt.

    Strategia (uno qualsiasi dei check basta → leak):
    - prefix match: i primi ~_LEAK_PREFIX_LEN char strippati del prompt
      appaiono nei primi _LEAK_SEARCH_WINDOW char dell'output
      (offset tollerato — il modello a volte salta il primo heading markdown);
    - block match: almeno un blocco contiguo di _LEAK_BLOCK_LEN char del
      system prompt compare letterale nell'output.

    Robusto cross-lingua: non dipende da marker hardcoded ma dal contenuto
    effettivo del prompt caricato.
    """
    if not text or not system_prompt:
        return False
    prompt_norm = system_prompt.strip()
    prompt_head = prompt_norm[:_LEAK_PREFIX_LEN].strip()
    if len(prompt_head) >= _LEAK_PREFIX_MIN and prompt_head in text[:_LEAK_SEARCH_WINDOW]:
        return True
    for offset in range(0, max(1, len(prompt_norm) - _LEAK_BLOCK_LEN), _LEAK_BLOCK_STEP):
        block = prompt_norm[offset:offset + _LEAK_BLOCK_LEN]
        if len(block) >= _LEAK_BLOCK_LEN and block in text:
            return True
    return False


def _write_llm_audit(*, job=None, job_id=None, chapter_num=None,
                    chapter_title="", chunk_index=None, outcome="",
                    chars_input=0, chars_output=0,
                    leaked_preview=""):
    """Append-only JSONL audit per eventi prompt-leak (best-effort, non-fatal).

    File: _upload_dir / "llm_leak_audit_YYYY-MM.jsonl"
    Schema: ts, job_id, chapter_num/title, chunk_index, outcome, model,
    lang, chars_input/output, leaked_preview (max 200 char).
    """
    try:
        if _upload_dir is None:
            return
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc)
        month = ts.strftime("%Y-%m")
        path = _upload_dir / f"llm_leak_audit_{month}.jsonl"
        # Risolvi lang/job_id da job se non passati esplicitamente
        resolved_job_id = job_id
        lang = ""
        if job is not None:
            if not resolved_job_id:
                resolved_job_id = job.get("job_id", "")
            lang = (job.get("opt_lang") or "").split("-")[0].lower()
        rec = {
            "ts": ts.isoformat(),
            "job_id": resolved_job_id or "",
            "chapter_num": chapter_num,
            "chapter_title": chapter_title or "",
            "chunk_index": chunk_index,
            "outcome": outcome,
            "model": LLM_MODEL,
            "lang": lang,
            "chars_input": int(chars_input or 0),
            "chars_output": int(chars_output or 0),
            "leaked_preview": (leaked_preview or "")[:200],
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        # Audit non deve mai bloccare il flusso utente
        print(f"[llm-audit] write failed: {e}")


_llm_prompts = {} # Cache per i prompt multilingua

def _get_llm_prompt(lang_code="it"):
    """
    Ritorna il prompt specifico per la lingua, o quello generico come fallback.
    lang_code può essere un codice ISO (it, en, fr...) o un locale (it-IT).
    """
    global _llm_prompts
    lang = (lang_code or "it").split("-")[0].lower()
    if lang in _llm_prompts:
        return _llm_prompts[lang]
    
    prompt_dir = _SCRIPT_DIR / "prompt_opt_AI"
    filename = f"prompt_tts_{lang}.md"
    path = prompt_dir / filename
    
    if not path.exists():
        path = prompt_dir / "prompt_tts_generic.md"
        
    if path.exists():
        try:
            print(f"[LLM] Using prompt file: {path.name}")
            content = path.read_text(encoding="utf-8").strip()
            _llm_prompts[lang] = content
            return content
        except Exception as e:
            print(f"Error reading prompt {path}: {e}")
            
    return ""

def _call_llm(user_content, job=None, max_retries=None):
    """Call LLM API with streaming. Returns optimized text.
    Retries on transient network errors with exponential backoff.
    """
    # Lingua del prompt LLM = lingua TTS selezionata dall'utente (non lingua
    # dell'input). Fonte primaria: opt_lang (settato da /api/optimize a partire
    # dal selector di lingua TTS). Fallback: estrazione dal voice id, che pero'
    # funziona solo per voci Edge/Google (es. "it-IT-X", "en-US-Chirp3-HD-X")
    # e fallisce per Gemini (es. "gemini:flash25:Zephyr" -> nessuna lingua
    # estraibile -> prompt generico).
    lang = "it"
    if job:
        opt_lang = (job.get("opt_lang") or "").strip()
        if opt_lang:
            lang = opt_lang.split("-")[0].lower()
        else:
            voice = job.get("voice") or job.get("opt_voice", "")
            if isinstance(voice, str) and voice and not voice.startswith("gemini:"):
                lang = voice.split("-")[0].lower()

    prompt = _get_llm_prompt(lang)

    if max_retries is None:
        max_retries = LLM_MAX_RETRIES

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    ]
    last_exc = None
    leak_attempts = 0
    attempt = 0
    # Loop con due budget indipendenti:
    # - `attempt` -> retry transient (network/5xx/429), consuma slot solo su Exception
    # - `leak_attempts` -> retry anti-leak, consuma slot solo su prompt-leak detectato
    # Il leak retry NON consuma il budget transient e viceversa.
    while attempt < max_retries:
        result_parts = []
        partial_streamed = 0
        try:
            # Configura i parametri per la chiamata (inclusi thinking e reasoning_effort).
            # Su retry anti-leak: temperature un filo piu' alta + reasoning off,
            # per ridurre la probabilita' che il modello "continui" il prompt.
            effective_temp = LLM_TEMPERATURE
            effective_reasoning = LLM_REASONING_EFFORT
            if leak_attempts > 0:
                effective_temp = min(LLM_TEMPERATURE + 0.1 * leak_attempts, 1.0)
                effective_reasoning = "none"

            kwargs = {
                "model": LLM_MODEL,
                "messages": messages,
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": effective_temp,
                "stream": True,
                "timeout": LLM_REQUEST_TIMEOUT_SEC,
            }
            if effective_reasoning != "none":
                kwargs["reasoning_effort"] = effective_reasoning
            if LLM_THINKING and leak_attempts == 0:
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

            stream = _llm_client.chat.completions.create(**kwargs)
            for event in stream:
                # Check cancellation during streaming to stop consuming tokens
                if job is not None and job.get("opt_cancelled"):
                    stream.close()
                    raise _CancelledError("Optimization cancelled during streaming")

                # Capture normal content
                if event.choices and event.choices[0].delta.content:
                    chunk = event.choices[0].delta.content
                    result_parts.append(chunk)
                    if job is not None:
                        job["opt_streamed_chars"] = job.get("opt_streamed_chars", 0) + len(chunk)
                        partial_streamed += len(chunk)

                # Count reasoning tokens toward progress (but not output)
                if hasattr(event.choices[0].delta, "reasoning_content") and event.choices[0].delta.reasoning_content:
                    if job is not None:
                        job["opt_streamed_chars"] = job.get("opt_streamed_chars", 0) + len(event.choices[0].delta.reasoning_content)

            raw = "".join(result_parts)
            cleaned = _sanitize_llm_output(raw)
            if cleaned != raw:
                removed = len(raw) - len(cleaned)
                if job is not None and removed > 0:
                    job["opt_streamed_chars"] = max(
                        0, job.get("opt_streamed_chars", 0) - removed
                    )
                print(f"  [LLM] sanitized output: removed {removed} chars of meta/duplicates")

            # Detection prompt-leak. Su match: scarica chars accumulati e ritenta
            # con parametri degradati. Esauriti i tentativi -> _PromptLeakError
            # che il chiamante traduce in fallback all'input originale.
            if _is_prompt_leak(cleaned, prompt):
                if job is not None and partial_streamed > 0:
                    job["opt_streamed_chars"] = max(0, job.get("opt_streamed_chars", 0) - partial_streamed)
                if leak_attempts < LLM_LEAK_MAX_RETRIES:
                    leak_attempts += 1
                    print(f"  [LLM] prompt-leak detected (attempt {leak_attempts}/{LLM_LEAK_MAX_RETRIES}), retrying with degraded params")
                    time.sleep(1.0)
                    continue
                print(f"  [LLM] prompt-leak persists after {LLM_LEAK_MAX_RETRIES} retries — giving up")
                if job is not None:
                    job["_last_leak_preview"] = cleaned[:200]
                    job["_last_leak_chars_output"] = len(cleaned)
                raise _PromptLeakError("LLM output contains system-prompt echo")

            return cleaned
        except _PromptLeakError:
            raise
        except _CancelledError:
            raise
        except Exception as e:
            last_exc = e
            if job is not None and partial_streamed > 0:
                job["opt_streamed_chars"] = max(0, job.get("opt_streamed_chars", 0) - partial_streamed)
            err_name = type(e).__name__
            # Errori di rete client-side (httpx/openai connection wrappers).
            transient = any(s in err_name for s in (
                "ReadError", "ConnectError", "ConnectTimeout", "ReadTimeout",
                "RemoteProtocolError", "APIConnectionError", "APITimeoutError",
            ))
            # Errori provider-side: 429/5xx → retry con backoff. Necessario perche'
            # openai.InternalServerError (503), RateLimitError (429), APIStatusError
            # non matchano la lista per-nome ma sono comunque transient.
            # status_code e' esposto sia da openai.APIStatusError sia (via response)
            # da alcune subclassi; usiamo getattr con fallback su response.status_code.
            if not transient:
                _sc = getattr(e, "status_code", None)
                if _sc is None:
                    _resp = getattr(e, "response", None)
                    if _resp is not None:
                        _sc = getattr(_resp, "status_code", None)
                if isinstance(_sc, int) and _sc in (429, 500, 502, 503, 504):
                    transient = True
            if not transient or attempt >= max_retries - 1:
                raise
            wait = 2 ** attempt  # 1, 2, 4, 8 seconds
            print(f"  [LLM] {err_name} (attempt {attempt+1}/{max_retries}), retry in {wait}s: {e}")
            time.sleep(wait)
            attempt += 1
    if last_exc:
        raise last_exc
    return "".join(result_parts)


def _is_trivial_input(text):
    """True se il testo è troppo banale per giustificare una chiamata LLM.

    Sono trivial:
    - Testo vuoto o solo whitespace.
    - Sotto LLM_TRIVIAL_INPUT_MIN_CHARS char (strippati).
    - Una sola riga di lunghezza < 2 * LLM_TRIVIAL_INPUT_MIN_CHARS senza
      punteggiatura terminale (titolo, nome proprio, intestazione). Il cap
      superiore evita di trattare come trivial prosa mal-estratta che ha
      perso la punteggiatura.

    Pass-through del testo originale elimina la causa principale di echo
    del system prompt (input povero di contesto).
    """
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) < LLM_TRIVIAL_INPUT_MIN_CHARS:
        return True
    nonblank_lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if (len(nonblank_lines) == 1
            and len(stripped) < 2 * LLM_TRIVIAL_INPUT_MIN_CHARS
            and not stripped.endswith((".", "!", "?", "…", '."'))):
        return True
    return False


def _optimize_chapter_text(text, chapter_num=None, total_chapters=None, job=None):
    """Optimize a single chapter's text, using chunking if needed."""
    label = f"[ch {chapter_num}/{total_chapters}]" if chapter_num else ""

    # Pre-filtro: input banale → pass-through, niente LLM.
    # Riduce drasticamente i casi di prompt echo (input povero di contesto
    # e' la causa principale del failure mode visto in produzione).
    if _is_trivial_input(text):
        print(f"  {label} LLM skipped: trivial input ({len(text)} chars)")
        return text

    chapter_title = ""
    if job is not None:
        chapter_title = job.get("opt_current_chapter", "") or ""

    def _record_leak(chunk_idx, chunk_text):
        leaked_preview = ""
        chars_output = 0
        if job is not None:
            job.setdefault("opt_leak_chapters", []).append({
                "chapter_num": chapter_num,
                "chunk_index": chunk_idx,
                "ts": time.time(),
            })
            leaked_preview = job.pop("_last_leak_preview", "")
            chars_output = job.pop("_last_leak_chars_output", 0)
        _write_llm_audit(
            job=job,
            job_id=(job.get("job_id") if job else None),
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            chunk_index=chunk_idx,
            outcome="prompt_leak_fallback",
            chars_input=len(chunk_text),
            chars_output=chars_output,
            leaked_preview=leaked_preview,
        )

    # Always chunk based on output-safe size so LLM response fits in MAX_TOKENS
    if len(text) <= LLM_SAFE_OUTPUT_CHUNK:
        print(f"  {label} LLM single call ({len(text):,} chars)")
        try:
            return _call_llm(text, job=job)
        except _PromptLeakError:
            print(f"  {label} prompt-leak fallback: returning original chapter text")
            _record_leak(None, text)
            return text

    chunks = _split_text_into_chunks(text, LLM_SAFE_OUTPUT_CHUNK)
    print(f"  {label} LLM chunked: {len(chunks)} chunks ({len(text):,} chars total)")
    results = []
    any_llm_output = False
    for i, chunk in enumerate(chunks):
        if job is not None and job.get("opt_cancelled"):
            raise _CancelledError("Optimization cancelled between chunks")
        if len(chunks) > 1:
            if i == 0:
                user_content = f"[Parte {i+1} di {len(chunks)} \u2014 inizio del testo]\n\n{chunk}"
            elif i == len(chunks) - 1:
                user_content = f"[Parte {i+1} di {len(chunks)} \u2014 fine del testo]\n\n{chunk}"
            else:
                user_content = f"[Parte {i+1} di {len(chunks)} \u2014 continuazione]\n\n{chunk}"
        else:
            user_content = chunk
        try:
            results.append(_call_llm(user_content, job=job))
            any_llm_output = True
        except _PromptLeakError:
            print(f"  {label} prompt-leak fallback on chunk {i+1}/{len(chunks)}: using original chunk")
            _record_leak(i, chunk)
            results.append(chunk)
        if i < len(chunks) - 1:
            time.sleep(LLM_INTER_CHUNK_SLEEP_SEC)  # rate limiting tra chunk
    joined = "\n\n".join(results)
    # Salta la sanitizzazione finale se tutto il contenuto e' fallback originale:
    # _sanitize_llm_output ha euristiche aggressive (preamble strip, dedup) che
    # sono pensate per output LLM, non per prosa originale dell'utente.
    if not any_llm_output:
        return joined
    return _sanitize_llm_output(joined)


# ---------------------------------------------------------------------------
# .abm snapshot generation
# ---------------------------------------------------------------------------

def _generate_optimized_abm(job_id):
    """Generate an .abm file with AI-optimized text for email download."""
    import zipfile
    import io
    from datetime import datetime, timezone

    job = _jobs[job_id]
    info = job.get("info")
    if not info:
        return None, None

    buf = io.BytesIO()
    safe_title = _safe_filename(info.title) or "project"

    # Use cumulative optimized_chapters if available; fall back to selected_chapters, then all chapters
    optimized = job.get("optimized_chapters")
    selected = job.get("selected_chapters")
    if optimized:
        chapter_set = set(optimized)
    elif selected:
        chapter_set = set(selected)
    else:
        chapter_set = None

    # Carica il system prompt della lingua del job per il check di sicurezza.
    # Best-effort: se manca lang, salta il check (graceful).
    safety_prompt = ""
    job_lang = (job.get("opt_lang") or "").split("-")[0].lower()
    if not job_lang and getattr(info, "language", ""):
        job_lang = info.language.split("-")[0].lower()
    if job_lang:
        try:
            safety_prompt = _get_llm_prompt(job_lang)
        except Exception:
            safety_prompt = ""

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        chapters_manifest = []
        for ch in info.chapters:
            if chapter_set and ch.index not in chapter_set:
                continue
            ch_safe = _safe_filename(ch.title)[:50] or f"ch_{ch.index}"
            ch_filename = f"{ch.index:03d}_{ch_safe}.txt"

            # Safety-net: se il testo del capitolo contiene un echo del system
            # prompt, sostituiscilo con un placeholder prima di scriverlo nel
            # .abm. Difesa di ultimo miglio per lo SNAPSHOT scaricabile: il TTS
            # gia' usa ch.text direttamente, ergo il leak nel TTS va prevenuto
            # a monte (Task 4/5 in _call_llm + _optimize_chapter_text).
            ch_text_safe = ch.text
            prompt_leak_flag = False
            if safety_prompt and _is_prompt_leak(ch_text_safe, safety_prompt):
                prompt_leak_flag = True
                print(f"[{job_id}] .abm safety-net: chapter {ch.index} contains "
                      f"prompt echo - replacing with placeholder")
                ch_text_safe = (f"[Capitolo non disponibile — anomalia di "
                                f"ottimizzazione rilevata in fase finale: "
                                f"{ch.title}]")
                _write_llm_audit(
                    job=job,
                    job_id=job_id,
                    chapter_num=ch.index,
                    chapter_title=ch.title,
                    chunk_index=None,
                    outcome="prompt_leak_safety_net",
                    chars_input=0,
                    chars_output=len(ch.text),
                    leaked_preview=ch.text[:200],
                )

            zf.writestr(f"chapters/{ch_filename}", ch_text_safe)
            entry = {
                "index": ch.index,
                "filename": ch_filename,
                "title": ch.title,
                "word_count": ch.word_count,
            }
            if prompt_leak_flag:
                entry["prompt_leak"] = True
            chapters_manifest.append(entry)

        # Cover
        has_cover = False
        cover_file = ""
        cover_path = job.get("cover_thumb")
        if cover_path and os.path.exists(cover_path):
            cover_ext = ".png" if cover_path.endswith(".png") else ".jpg"
            cover_file = f"cover{cover_ext}"
            with open(cover_path, "rb") as cf:
                zf.writestr(cover_file, cf.read())
            has_cover = True

        manifest = {
            "format": "audiobook-maker-project",
            "format_version": "1.0",
            "title": info.title,
            "author": getattr(info, "author", ""),
            "language": getattr(info, "language", ""),
            "has_cover": has_cover,
            "cover_file": cover_file,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "original_filename": job.get("original_filename", ""),
            "ai_optimized": True,
            "ai_optimized_at": datetime.now(timezone.utc).isoformat(),
            "chapters": chapters_manifest,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    # Save .abm to disk for email download.
    # Prefer the current epoch's output_{N}/ dir if set (so the ABM is
    # preserved per-generation alongside MP3/M4B). Fall back to work_dir
    # root when called during the optimization phase, before any audio
    # generation has run.
    work_dir = _upload_dir / job_id
    work_dir.mkdir(exist_ok=True)
    target_dir = work_dir
    out_dir_str = job.get("output_dir", "")
    if out_dir_str:
        out_dir = Path(out_dir_str)
        if out_dir.exists():
            target_dir = out_dir
    abm_name = f"{safe_title}_optimized.abm"
    abm_path = str(target_dir / abm_name)
    with open(abm_path, "wb") as f:
        f.write(buf.getvalue())
    # If we just wrote into output_dir, remove any stale copy left at
    # work_dir root from an earlier optimization-phase write.
    if target_dir != work_dir:
        legacy = work_dir / abm_name
        if legacy.exists() and str(legacy) != abm_path:
            try:
                legacy.unlink()
            except OSError:
                pass
    return abm_path, abm_name


# ---------------------------------------------------------------------------
# Completion emails
# ---------------------------------------------------------------------------

def _send_completion_email(job_id):
    """Send download link email when a job completes with email registered."""
    job = _jobs.get(job_id)
    if not job:
        print(f"[{job_id}] _send_completion_email: job missing from _jobs (cleanup race)", flush=True)
        try:
            _log_activity(job_id, "", "EMAIL_SKIPPED_NOJOB", "", "", "", "")
        except Exception:
            pass
        return
    if not job.get("notify_email"):
        # Fallback: cerca email precedentemente registrata per lo stesso client
        _cid = job.get("client_id", "")
        if _cid:
            _fallback = _lookup_client_email(_cid)
            if _fallback:
                job["notify_email"] = _fallback
                print(f"[{job_id}] _send_completion_email: using fallback email "
                      f"from client_id {_cid}", flush=True)
        if not job.get("notify_email"):
            print(f"[{job_id}] _send_completion_email: notify_email empty "
                  f"(email_registered={job.get('email_registered')})", flush=True)
            try:
                _log_activity(job_id, job.get("original_filename", ""), "EMAIL_SKIPPED_NOADDR",
                              job.get("client_id", ""), job.get("client_ip", ""),
                              job.get("voice", ""), job.get("browser_lang", ""))
            except Exception:
                pass
            return
    print(f"[{job_id}] _send_completion_email: preparing send to {job['notify_email']}", flush=True)
    _ret_sec_job = _retention_for_job(job)
    retention_h = _ret_sec_job // 3600
    email = job["notify_email"]
    info = job.get("info", None)
    book_title = info.title if info else "Audiobook"
    dl_type = job.get("notify_download_type", "audio")
    base_url = job.get("notify_base_url", "").rstrip("/")
    lang = job.get("notify_lang", "en")

    # Generate unique download token with job snapshot for restart survival
    token = str(uuid.uuid4())
    _download_tokens[token] = {
        "job_id": job_id,
        "created_at": time.time(),
        "download_type": dl_type,
        "base_url": base_url,
        # Snapshot: everything needed to serve download after restart
        "book_title": book_title,
        "output_zip": job.get("output_zip", ""),
        "output_name": job.get("output_name", ""),
        "output_file": job.get("output_files", [""])[0] if job.get("output_files") else "",
        "output_m4b": job.get("output_m4b", ""),
        "epub_path": job.get("epub_path", ""),
        "podcast_safe_name": job.get("podcast_safe_name", ""),
        "podcast_ready": job.get("podcast_ready", False),
        "podcast_mp3s": job.get("podcast_mp3s", []),
        "podcast_info_title": info.title if info else "",
        "podcast_info_author": info.author if info else "",
        "podcast_info_language": info.language if info else "",
        "original_filename": job.get("original_filename", ""),
        "lang": lang,
        "output_format": job.get("output_format", ""),
        "ai_optimized": job.get("ai_optimized", False),
        # Optional: optimized .abm snapshot (when auto_generate flow produced one)
        "optimized_abm_path": job.get("optimized_abm_path", ""),
        "optimized_abm_name": job.get("optimized_abm_name", ""),
        # Flag PREMIUM/Gemini: pilota retention 48h vs 18h nei /dl/* e nel cleanup.
        "is_gemini": _is_gemini_voice(job.get("voice", "") or job.get("opt_voice", "")),
    }
    _save_tokens()
    job["email_token"] = token
    _sent_at = time.time()
    job["email_sent_at"] = _sent_at
    # Marker su disco: protegge la job dir per tutta la finestra di retention
    # anche dal cleanup di altri worker Gunicorn che non vedono questo token.
    if _write_email_marker is not None:
        try:
            _write_email_marker(_upload_dir / job_id, _sent_at,
                                is_gemini=_is_gemini_voice(job.get("voice", "") or job.get("opt_voice", "")))
        except Exception as e:
            print(f"[{job_id}] email-marker write failed: {e}", flush=True)

    dl_url = f"{BASE_URL}/dl/{token}" if BASE_URL else f"/dl/{token}"

    # RSS XML filename for podcast
    safe_name = job.get("podcast_safe_name", _safe_filename(book_title) or "audiolibro")
    rss_filename = f"{safe_name}_podcast.xml"
    rss_url = f"{base_url}/{rss_filename}" if base_url else rss_filename

    # i18n email content
    _email_i18n = {
        "it": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" pronto per il download",
            "heading": "&#x1F3A7; Il tuo audiolibro &egrave; pronto!",
            "body": f"La generazione di <strong>{book_title}</strong> &egrave; stata completata con successo.",
            "btn": "&#x2B07;&#xFE0F; Scarica il tuo libro",
            "warn": f"&#x23F0; Attenzione: i file saranno disponibili per il download soltanto per {retention_h} ore a partire dalla ricezione di questa email. Dopo tale periodo verranno cancellati automaticamente.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Istruzioni per la pubblicazione del Podcast</strong>",
            "podcast_p1": f"Il file ZIP scaricato contiene tutti i file necessari per il tuo podcast. Per renderlo fruibile online, <strong>decomprimi il file ZIP</strong> e carica tutti i file contenuti sul tuo server web, in modo che siano raggiungibili all'indirizzo:",
            "podcast_p2": f"Il file XML del feed RSS del podcast sar&agrave;:",
            "podcast_p3": f"Per rendere il podcast disponibile su app come <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> o altri aggregatori, fornisci l'indirizzo del file XML come URL del feed.",
            "footer": "Questa email &egrave; stata generata automaticamente da Audiobook Maker.",
        },
        "en": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" ready for download",
            "heading": "&#x1F3A7; Your audiobook is ready!",
            "body": f"The generation of <strong>{book_title}</strong> has been completed successfully.",
            "btn": "&#x2B07;&#xFE0F; Download your book",
            "warn": f"&#x23F0; Please note: the files will be available for download for {retention_h} hours only from the time you receive this email. After that, they will be automatically deleted.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Podcast Publishing Instructions</strong>",
            "podcast_p1": f"The downloaded ZIP file contains all the files needed for your podcast. To make it available online, <strong>extract the ZIP file</strong> and upload all files to your web server so they are reachable at:",
            "podcast_p2": f"The podcast RSS feed XML file will be:",
            "podcast_p3": f"To make the podcast available on apps like <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> or other aggregators, provide the XML file URL as the feed URL.",
            "footer": "This email was automatically generated by Audiobook Maker.",
        },
        "fr": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" pr&ecirc;t au t&eacute;l&eacute;chargement",
            "heading": "&#x1F3A7; Votre livre audio est pr&ecirc;t !",
            "body": f"La g&eacute;n&eacute;ration de <strong>{book_title}</strong> a &eacute;t&eacute; compl&eacute;t&eacute;e avec succ&egrave;s.",
            "btn": "&#x2B07;&#xFE0F; T&eacute;l&eacute;charger votre livre",
            "warn": f"&#x23F0; Attention : les fichiers seront disponibles au t&eacute;l&eacute;chargement pendant {retention_h} heures seulement &agrave; compter de la r&eacute;ception de cet email. Pass&eacute; ce d&eacute;lai, ils seront automatiquement supprim&eacute;s.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Instructions de publication du podcast</strong>",
            "podcast_p1": f"Le fichier ZIP t&eacute;l&eacute;charg&eacute; contient tous les fichiers n&eacute;cessaires &agrave; votre podcast. Pour le rendre accessible en ligne, <strong>d&eacute;compressez le fichier ZIP</strong> et t&eacute;l&eacute;versez tous les fichiers sur votre serveur web, de sorte qu'ils soient accessibles &agrave; l'adresse :",
            "podcast_p2": f"Le fichier XML du flux RSS du podcast sera :",
            "podcast_p3": f"Pour rendre le podcast disponible sur des apps comme <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> ou d'autres agr&eacute;gateurs, fournissez l'URL du fichier XML comme URL du flux.",
            "footer": "Cet email a &eacute;t&eacute; g&eacute;n&eacute;r&eacute; automatiquement par Audiobook Maker.",
        },
        "es": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" listo para descargar",
            "heading": "&#x1F3A7; &iexcl;Tu audiolibro est&aacute; listo!",
            "body": f"La generaci&oacute;n de <strong>{book_title}</strong> se ha completado con &eacute;xito.",
            "btn": "&#x2B07;&#xFE0F; Descargar tu libro",
            "warn": f"&#x23F0; Atenci&oacute;n: los archivos estar&aacute;n disponibles para descargar solo durante {retention_h} horas desde la recepci&oacute;n de este email. Despu&eacute;s de ese periodo se eliminar&aacute;n autom&aacute;ticamente.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Instrucciones para publicar el podcast</strong>",
            "podcast_p1": f"El archivo ZIP descargado contiene todos los archivos necesarios para tu podcast. Para hacerlo accesible en l&iacute;nea, <strong>descomprime el archivo ZIP</strong> y sube todos los archivos a tu servidor web para que sean accesibles en:",
            "podcast_p2": f"El archivo XML del feed RSS del podcast ser&aacute;:",
            "podcast_p3": f"Para que el podcast est&eacute; disponible en apps como <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> u otros agregadores, proporciona la URL del archivo XML como URL del feed.",
            "footer": "Este email fue generado autom&aacute;ticamente por Audiobook Maker.",
        },
        "de": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" bereit zum Download",
            "heading": "&#x1F3A7; Dein H&ouml;rbuch ist fertig!",
            "body": f"Die Generierung von <strong>{book_title}</strong> wurde erfolgreich abgeschlossen.",
            "btn": "&#x2B07;&#xFE0F; Dein Buch herunterladen",
            "warn": f"&#x23F0; Hinweis: Die Dateien stehen nur {retention_h} Stunden ab Erhalt dieser E-Mail zum Download bereit. Danach werden sie automatisch gel&ouml;scht.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Anleitung zur Podcast-Ver&ouml;ffentlichung</strong>",
            "podcast_p1": f"Die heruntergeladene ZIP-Datei enth&auml;lt alle Dateien f&uuml;r deinen Podcast. Um ihn online verf&uuml;gbar zu machen, <strong>entpacke die ZIP-Datei</strong> und lade alle Dateien auf deinen Webserver hoch, sodass sie unter folgender Adresse erreichbar sind:",
            "podcast_p2": f"Die XML-Datei des Podcast-RSS-Feeds lautet:",
            "podcast_p3": f"Um den Podcast in Apps wie <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> oder anderen Aggregatoren verf&uuml;gbar zu machen, gib die URL der XML-Datei als Feed-URL an.",
            "footer": "Diese E-Mail wurde automatisch von Audiobook Maker generiert.",
        },
        "pt": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" pronto para o download",
            "heading": "&#x1F3A7; Seu audiolivro est&aacute; pronto!",
            "body": f"A gera&ccedil;&atilde;o de <strong>{book_title}</strong> foi conclu&iacute;da com sucesso.",
            "btn": "&#x2B07;&#xFE0F; Baixar seu livro",
            "warn": f"&#x23F0; Aten&ccedil;&atilde;o: os arquivos estar&atilde;o dispon&iacute;veis para download por apenas {retention_h} horas a partir do recebimento deste e-mail. Ap&oacute;s esse per&iacute;odo, eles ser&atilde;o exclu&iacute;dos automaticamente.",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>Instru&ccedil;&otilde;es de publica&ccedil;&atilde;o do Podcast</strong>",
            "podcast_p1": f"O arquivo ZIP baixato cont&eacute;m todos os arquivos necess&aacute;rios para o seu podcast. Para torn&aacute;-lo acess&iacute;vel online, <strong>descompacte o arquivo ZIP</strong> e envie todos os arquivos para o seu servidor web, para que sejam acess&iacute;veis em:",
            "podcast_p2": f"O arquivo XML do feed RSS do podcast ser&aacute;:",
            "podcast_p3": f"Para tornar o podcast dispon&iacute;vel em aplicativos como <strong>Pocket Casts</strong>, <strong>Apple Podcasts (iTunes)</strong> ou outros agregadores, forne&ccedil;a o URL do arquivo XML como o URL do feed.",
            "footer": "Este e-mail foi gerado automaticamente pelo Audiobook Maker.",
        },
        "zh": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" \u5df2\u51c6\u5907\u597d\u4e0b\u8f7d",
            "heading": "&#x1F3A7; \u60a8\u7684\u6709\u58f0\u8bfb\u7269\u5df2\u51c6\u5907\u597d\uff01",
            "body": f"<strong>{book_title}</strong> \u5df2\u6210\u529f\u751f\u6210\u3002",
            "btn": "&#x2B07;&#xFE0F; \u4e0b\u8f7d\u60a8\u7684\u4e66\u7c4d",
            "warn": f"&#x23F0; \u8bf7\u6ce8\u610f\uff1a\u6587\u4ef6\u4ec5\u5728\u6536\u5230\u6b64\u90ae\u4ef6\u540e{retention_h}\u5c0f\u65f6\u5185\u53ef\u4f9b\u4e0b\u8f7d\u3002\u4e4b\u540e\u5c06\u81ea\u52a8\u5220\u9664\u3002",
            "podcast_intro": "&#x1F399;&#xFE0F; <strong>\u64ad\u5ba2\u53d1\u5e03\u8bf4\u660e</strong>",
            "podcast_p1": f"\u4e0b\u8f7d\u7684ZIP\u6587\u4ef6\u5305\u542b\u64ad\u5ba2\u6240\u9700\u7684\u6240\u6709\u6587\u4ef6\u3002\u8981\u5728\u7ebf\u53d1\u5e03\uff0c\u8bf7<strong>\u89e3\u538bZIP\u6587\u4ef6</strong>\uff0c\u5e76\u5c06\u6240\u6709\u6587\u4ef6\u4e0a\u4f20\u5230\u60a8\u7684\u7f51\u7edc\u670d\u52a1\u5668\uff0c\u4f7f\u5176\u53ef\u901a\u8fc7\u4ee5\u4e0b\u5730\u5740\u8bbf\u95ee\uff1a",
            "podcast_p2": f"\u64ad\u5ba2RSS\u8ba2\u9605\u6e90\u7684XML\u6587\u4ef6\u5730\u5740\u4e3a\uff1a",
            "podcast_p3": f"\u8981\u5728<strong>Pocket Casts</strong>\u3001<strong>Apple Podcasts (iTunes)</strong>\u7b49\u5e94\u7528\u4e0a\u53d1\u5e03\u64ad\u5ba2\uff0c\u8bf7\u5c06XML\u6587\u4ef6\u7684URL\u4f5c\u4e3a\u8ba2\u9605\u6e90\u5730\u5740\u63d0\u4f9b\u3002",
            "footer": "\u6b64\u90ae\u4ef6\u7531 Audiobook Maker \u81ea\u52a8\u751f\u6210\u3002",
        },
    }

    t = dict(_email_i18n.get(lang, _email_i18n["en"]))

    # Podcast section (only for podcast downloads)
    podcast_section = ""
    if dl_type == "podcast" and base_url:
        podcast_section = f"""
      <div style="margin:20px 0;padding:16px 20px;background:#f0f7ff;border-left:4px solid #3b82f6;border-radius:4px">
        <p style="margin:0 0 10px">{t['podcast_intro']}</p>
        <p style="margin:0 0 8px">{t['podcast_p1']}</p>
        <p style="margin:0 0 12px;padding:8px 12px;background:#e2e8f0;border-radius:4px;font-family:monospace;word-break:break-all">
          &#x1F4C1; <a href="{base_url}" style="color:#3b82f6">{base_url}/</a>
        </p>
        <p style="margin:0 0 8px">{t['podcast_p2']}</p>
        <p style="margin:0 0 12px;padding:8px 12px;background:#e2e8f0;border-radius:4px;font-family:monospace;word-break:break-all">
          &#x1F4E1; <a href="{rss_url}" style="color:#3b82f6">{rss_url}</a>
        </p>
        <p style="margin:0">{t['podcast_p3']}</p>
      </div>"""

    subject = t["subject"]
    html_body = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#2c3e50">{t['heading']}</h2>
      <p>{t['body']}</p>
      <p style="margin:24px 0">
        <a href="{dl_url}" style="display:inline-block;padding:14px 28px;background:#3b82f6;color:white;
           text-decoration:none;border-radius:8px;font-weight:600;font-size:16px">
          {t['btn']}
        </a>
      </p>
      <p style="color:#e74c3c;font-weight:600">{t['warn']}</p>
      {podcast_section}
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#999;font-size:12px">
        {t['footer']}
        {('Visita ' + BASE_URL) if BASE_URL else ''}
      </p>
    </div>
    """
    success = email_service._send_email(email, subject, html_body)
    if success:
        _log_activity(job_id, job.get("original_filename", ""), "EMAIL_SENT",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))
    else:
        _log_activity(job_id, job.get("original_filename", ""), "EMAIL_FAILED",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))


def _send_optimization_email(job_id):
    """Send email with optimized .abm download link when LLM optimization completes."""
    job = _jobs.get(job_id)
    if not job or not job.get("notify_email"):
        return
    _ret_sec_job = _retention_for_job(job)
    retention_h = _ret_sec_job // 3600
    email = job["notify_email"]
    info = job.get("info")
    book_title = info.title if info else "Audiobook"
    lang = job.get("notify_lang", "en")

    token = str(uuid.uuid4())
    abm_path = job.get("optimized_abm_path", "")
    abm_name = job.get("optimized_abm_name", "optimized.abm")

    _download_tokens[token] = {
        "job_id": job_id,
        "created_at": time.time(),
        "download_type": "optimized_abm",
        "book_title": book_title,
        "optimized_abm_path": abm_path,
        "optimized_abm_name": abm_name,
        "original_filename": job.get("original_filename", ""),
        "lang": lang,
        "output_format": "",
        "ai_optimized": True,
        # Token .abm di sola ottimizzazione: la retention sarà comunque pilotata
        # dal flag voce se l'utente dopo procede a generazione PREMIUM.
        "is_gemini": _is_gemini_voice(job.get("voice", "") or job.get("opt_voice", "")),
    }
    _save_tokens()
    job["email_token"] = token
    _sent_at = time.time()
    job["email_sent_at"] = _sent_at
    if _write_email_marker is not None:
        try:
            _write_email_marker(_upload_dir / job_id, _sent_at,
                                is_gemini=_is_gemini_voice(job.get("voice", "") or job.get("opt_voice", "")))
        except Exception as e:
            print(f"[{job_id}] email-marker write failed: {e}", flush=True)

    dl_url = f"{BASE_URL}/dl/{token}" if BASE_URL else f"/dl/{token}"

    _opt_email_i18n = {
        "it": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" ottimizzazione testo completata",
            "heading": "&#x2728; Ottimizzazione testo completata!",
            "body": f"L'ottimizzazione AI del testo di <strong>{book_title}</strong> per la sintesi vocale &egrave; stata completata con successo.",
            "btn": "&#x2B07;&#xFE0F; Scarica il tuo libro",
            "warn": f"&#x23F0; Attenzione: il file sar&agrave; disponibile per il download soltanto per {retention_h} ore.",
            "footer": "Questa email &egrave; stata generata automaticamente da Audiobook Maker.",
        },
        "en": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" text optimization completed",
            "heading": "&#x2728; Text optimization completed!",
            "body": f"The AI text optimization of <strong>{book_title}</strong> for speech synthesis has been completed successfully.",
            "btn": "&#x2B07;&#xFE0F; Download your book",
            "warn": f"&#x23F0; Please note: the file will be available for download for {retention_h} hours only.",
            "footer": "This email was automatically generated by Audiobook Maker.",
        },
        "fr": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" optimisation du texte termin&eacute;e",
            "heading": "&#x2728; Optimisation du texte termin&eacute;e !",
            "body": f"L'optimisation AI du texte de <strong>{book_title}</strong> pour la synth&egrave;se vocale a &eacute;t&eacute; compl&eacute;t&eacute;e avec succ&egrave;s.",
            "btn": "&#x2B07;&#xFE0F; T&eacute;l&eacute;charger votre livre",
            "warn": f"&#x23F0; Attention : le fichier sera disponible au t&eacute;l&eacute;chargement pendant {retention_h} heures seulement.",
            "footer": "Cet email a &eacute;t&eacute; g&eacute;n&eacute;r&eacute; automatiquement par Audiobook Maker.",
        },
        "es": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" optimizaci&oacute;n de texto completada",
            "heading": "&#x2728; &iexcl;Optimizaci&oacute;n de texto completada!",
            "body": f"La optimizaci&oacute;n AI del texto de <strong>{book_title}</strong> para la s&iacute;ntesis de voz se ha completado con &eacute;xito.",
            "btn": "&#x2B07;&#xFE0F; Descargar tu libro",
            "warn": f"&#x23F0; Atenci&oacute;n: el archivo estar&aacute; disponible para descargar solo durante {retention_h} horas.",
            "footer": "Este email fue generado autom&aacute;ticamente por Audiobook Maker.",
        },
        "de": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" Textoptimierung abgeschlossen",
            "heading": "&#x2728; Textoptimierung abgeschlossen!",
            "body": f"Die KI-Textoptimierung von <strong>{book_title}</strong> f&uuml;r die Sprachsynthese wurde erfolgreich abgeschlossen.",
            "btn": "&#x2B07;&#xFE0F; Dein Buch herunterladen",
            "warn": f"&#x23F0; Hinweis: Die Datei steht nur {retention_h} Stunden zum Download bereit.",
            "footer": "Diese E-Mail wurde automatisch von Audiobook Maker generiert.",
        },
        "pt": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" otimiza&ccedil;&atilde;o de texto conclu&iacute;da",
            "heading": "&#x2728; Otimiza&ccedil;&atilde;o de texto conclu&iacute;da!",
            "body": f"A otimiza&ccedil;&atilde;o AI do texto de <strong>{book_title}</strong> para s&iacute;ntese de voz foi conclu&iacute;da com sucesso.",
            "btn": "&#x2B07;&#xFE0F; Baixar seu livro",
            "warn": f"&#x23F0; Aten&ccedil;&atilde;o: o arquivo estar&aacute; dispon&iacute;vel para download por apenas {retention_h} horas.",
            "footer": "Este e-mail foi gerado automaticamente pelo Audiobook Maker.",
        },
        "zh": {
            "subject": f"Audiobook Maker \u2014 \"{book_title}\" \u6587\u672c\u4f18\u5316\u5df2\u5b8c\u6210",
            "heading": "&#x2728; \u6587\u672c\u4f18\u5316\u5df2\u5b8c\u6210\uff01",
            "body": f"<strong>{book_title}</strong> \u7684AI\u6587\u672c\u4f18\u5316\u5df2\u6210\u529f\u5b8c\u6210\u3002",
            "btn": "&#x2B07;&#xFE0F; \u4e0b\u8f7d\u60a8\u7684\u4e66\u7c4d",
            "warn": f"&#x23F0; \u8bf7\u6ce8\u610f\uff1a\u6587\u4ef6\u4ec5\u5728{retention_h}\u5c0f\u65f6\u5185\u53ef\u4f9b\u4e0b\u8f7d\u3002",
            "footer": "\u6b64\u90ae\u4ef6\u7531 Audiobook Maker \u81ea\u52a8\u751f\u6210\u3002",
        },
    }

    t = _opt_email_i18n.get(lang, _opt_email_i18n["en"])
    subject = t["subject"]
    html_body = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#2c3e50">{t['heading']}</h2>
      <p>{t['body']}</p>
      <p style="margin:24px 0">
        <a href="{dl_url}" style="display:inline-block;padding:14px 28px;background:#3b82f6;color:white;
           text-decoration:none;border-radius:8px;font-weight:600;font-size:16px">
          {t['btn']}
        </a>
      </p>
      <p style="color:#e74c3c;font-weight:600">{t['warn']}</p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#999;font-size:12px">
        {t['footer']}
        {('Visita ' + BASE_URL) if BASE_URL else ''}
      </p>
    </div>
    """
    success = email_service._send_email(email, subject, html_body)
    if success:
        _log_activity(job_id, job.get("original_filename", ""), "OPT_EMAIL_SENT",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))
    else:
        _log_activity(job_id, job.get("original_filename", ""), "OPT_EMAIL_FAILED",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))


# ---------------------------------------------------------------------------
# Payment refund helper
# ---------------------------------------------------------------------------

def _write_forensic_marker(job_id, kind, outcome, reason_detail=""):
    """Scrive marker .forensic_retain.json nella work_dir del job per
    impedire al cleanup automatico di cancellarla. Sopravvive a restart
    e protegge contro TUTTI i branch di cleanup (status=error, orphan dir,
    token-orphan, orphan output). Retention configurabile via
    ABM_GEMINI_FORENSIC_RETENTION_DAYS (default 7 giorni; 0 = disabilita).

    Best-effort, non-fatal. Ritorna retain_until epoch o None.
    """
    import json as _json
    try:
        days = int(os.environ.get("ABM_GEMINI_FORENSIC_RETENTION_DAYS", "7"))
    except (TypeError, ValueError):
        days = 7
    days = max(0, days)
    if days <= 0:
        return None
    try:
        if _upload_dir is None:
            return None
        work_dir = _upload_dir / job_id
        if not work_dir.exists():
            return None
        now = time.time()
        retain_until = now + days * 86400
        marker_path = work_dir / ".forensic_retain.json"
        payload = {
            "retain_until": retain_until,
            "created_at": now,
            "kind": kind,
            "outcome": outcome,
            "reason": (reason_detail or "")[:500],
            "job_id": job_id,
            "days": days,
        }
        marker_path.write_text(
            _json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[{job_id}] Forensic marker written: retain_until="
              f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(retain_until))} "
              f"({days}d) outcome={outcome}")
        return retain_until
    except Exception as e:
        print(f"[{job_id}] Forensic marker write failed (non-fatal): {e}")
        return None


def _admin_alert_gemini_failure(job_id, job, kind, audit_outcome,
                                 reason_detail="",
                                 chunks_total=None, chunks_failed=None):
    """Notifica IMMEDIATA all'admin per ogni job Gemini fallito (con rimborso)
    o bloccato preventivamente. Best-effort, non-fatal.

    Scrive anche il marker forense sulla work_dir per consentire post-mortem
    (download ZIP dall'endpoint admin) prima del cleanup automatico.

    kind: "quota" | "budget" | "quality" | "preflight" | "generic"
    """
    forensic_until = _write_forensic_marker(job_id, kind, audit_outcome, reason_detail)
    try:
        payment_meta = job.get("payment") or {}
        amount_eur = float(payment_meta.get("total_eur", 0) or 0)
        method = payment_meta.get("method", "")
        voucher_code = job.get("refund_voucher_code") or None
        # Determina email destinataria
        email = ""
        try:
            tok = payment_meta.get("token")
            if method == "voucher" and tok:
                v = payment._vouchers.get(tok, {}) if hasattr(payment, "_vouchers") else {}
                email = v.get("email", "") or ""
            elif method == "paypal" and tok:
                pay = payment._payments.get(tok, {})
                email = pay.get("email", "") or ""
        except Exception:
            email = ""
        # Titolo libro
        book_title = ""
        try:
            info = job.get("info")
            if info is not None:
                book_title = getattr(info, "title", "") or job.get("original_filename", "")
            else:
                book_title = job.get("original_filename", "")
        except Exception:
            book_title = job.get("original_filename", "")
        chars_total = job.get("total_chars")
        if chunks_total is None:
            chunks_total = job.get("total_chunks")
        email_service._admin_notify_gemini_failure(
            job_id=job_id,
            kind=kind,
            amount_eur=amount_eur,
            email=email,
            book_title=book_title,
            audit_outcome=audit_outcome,
            reason_detail=reason_detail,
            voucher_code=voucher_code,
            chars_total=chars_total,
            chunks_total=chunks_total,
            chunks_failed=chunks_failed,
            forensic_until=forensic_until,
            work_dir_path=str(_upload_dir / job_id) if _upload_dir else "",
        )
    except Exception as e:
        print(f"[{job_id}] admin alert send failed (non-fatal): {e}")


def _progress_pct(job: dict) -> int:
    """Percentuale di completamento (0..100) di un job in corso.

    Robusta a campi mancanti o valori anomali: clamp 0..100, 0 se denominatore
    nullo/mancante.
    """
    try:
        total = float(job.get("progress_total", 0) or 0)
        if total <= 0:
            return 0
        current = float(job.get("progress_current", 0) or 0)
        pct = int(round(current / total * 100))
        return max(0, min(100, pct))
    except (TypeError, ValueError):
        return 0


def _refund_gemini_payment(job_id, job, reason, retained_eur: float = 0.0):
    """F3: Refund Gemini payment on cancel/error.

    For voucher tokens, refunds the amount on the original voucher.
    For PayPal tokens, emits a refund voucher to the buyer's email.

    `retained_eur` (default 0.0) e' l'importo trattenuto dalla piattaforma
    per coprire i costi gia' sostenuti (Google + fee PayPal). Solo i cancel
    volontari (reason == "cancelled") con costo provider > 0 lo usano;
    quota/budget/errori continuano a passare 0.0 -> rimborso integrale.

    apply_bonus al voucher PayPal emesso: True per failure piattaforma
    (default), False per cancel volontario (retained_eur > 0 oppure
    reason == "cancelled").

    Non-fatal: any failure is logged and swallowed.

    Returns a dict with refund details (or None if no refund applied):
        {"method": "voucher"|"paypal", "amount_eur": float,
         "email": str, "voucher_code": str|None}
    """
    payment_meta = job.get("payment") or {}
    tok = payment_meta.get("token")
    paid = float(payment_meta.get("total_eur", 0) or 0)
    method = payment_meta.get("method", "")
    if not tok or paid <= 0:
        return None
    refund_amt = round(max(0.0, paid - float(retained_eur or 0.0)), 2)
    apply_bonus = not (reason == "cancelled" or float(retained_eur or 0.0) > 0)
    result = {"method": method, "amount_eur": refund_amt, "email": "", "voucher_code": None}
    if refund_amt <= 0:
        try:
            if method == "voucher":
                v = payment._vouchers.get(tok, {}) if hasattr(payment, "_vouchers") else {}
                result["email"] = v.get("email", "") or ""
            elif method == "paypal":
                pay = payment._payments.get(tok, {})
                result["email"] = pay.get("email", "") or ""
        except Exception:
            pass
        return result
    try:
        if method == "voucher":
            payment._voucher_refund(tok, refund_amt, job_id=job_id, reason=reason)
            voucher = payment._vouchers.get(tok, {}) if hasattr(payment, "_vouchers") else {}
            result["email"] = voucher.get("email", "") or ""
        elif method == "paypal":
            pay = payment._payments.get(tok, {})
            email = pay.get("email", "") or ""
            result["email"] = email
            if email:
                code, _bonus = payment._create_voucher(
                    email, refund_amt, origin_order_id=tok, origin_job_id=job_id,
                    kind="refund", note=f"refund {reason} job {job_id}",
                    apply_bonus=apply_bonus,
                )
                result["voucher_code"] = code
                job["refund_voucher_code"] = code
            else:
                print(
                    f"[{job_id}] WARNING: cannot emit refund voucher — "
                    f"PayPal order {tok} has no buyer email "
                    f"(amount {refund_amt:.2f} EUR, reason {reason})"
                )
    except Exception as _ref_err:
        print(f"[{job_id}] refund failed ({reason}, non-fatal): {_ref_err}")
        return None
    return result


def _notify_user_gemini_job_failed(job_id, job, pause_reason, is_quota=True,
                                    failure_kind=None):
    """Invia email all'utente che ha pagato un job Gemini fallito.
    Deve essere chiamata DOPO _refund_gemini_payment.

    failure_kind: "quota" | "budget" | "quality". Se None, viene derivato da
    is_quota per retrocompatibilita'.

    Recupera l'email destinataria dal payment metadata (PayPal -> pay.email,
    voucher -> voucher.email). Non-fatal: errori vengono ingoiati.
    """
    payment_meta = job.get("payment") or {}
    tok = payment_meta.get("token")
    amt = float(payment_meta.get("total_eur", 0) or 0)
    method = payment_meta.get("method", "")
    if not tok or amt <= 0:
        return
    email = ""
    voucher_code = job.get("refund_voucher_code") or None
    try:
        if method == "voucher":
            v = payment._vouchers.get(tok, {}) if hasattr(payment, "_vouchers") else {}
            email = v.get("email", "") or ""
        elif method == "paypal":
            pay = payment._payments.get(tok, {})
            email = pay.get("email", "") or ""
    except Exception:
        email = ""
    if not email:
        print(f"[{job_id}] No email available for refund notification "
              f"(method={method}, token={tok}).")
        return
    if failure_kind is None:
        failure_kind = "quota" if is_quota else "budget"
    if failure_kind == "quota":
        reason_label = (
            "il provider del servizio voci ha esaurito la quota giornaliera "
            "di richieste sul nostro piano corrente"
        )
    elif failure_kind == "budget":
        reason_label = (
            "e' stato raggiunto il limite di spesa giornaliero del servizio"
        )
    else:  # quality
        reason_label = (
            "alcune porzioni del testo non sono state sintetizzate "
            "correttamente e l'audio risultante sarebbe stato incompleto"
        )
    book_title = ""
    try:
        info = job.get("info")
        if info is not None:
            book_title = getattr(info, "title", "") or job.get("original_filename", "")
        else:
            book_title = job.get("original_filename", "")
    except Exception:
        book_title = job.get("original_filename", "")
    try:
        email_service._send_gemini_failed_refund_email(
            email, amt, book_title, reason_label, voucher_code=voucher_code,
        )
        print(f"[{job_id}] Refund notification email sent to {email} "
              f"(amount={amt:.2f} EUR, reason={pause_reason}).")
    except Exception as e:
        print(f"[{job_id}] Failed to send refund notification email: {e}")


def _refund_job_payment(job_id, job, reason="error"):
    """Rimborsa il pagamento di un job di ottimizzazione fallito o annullato.
    - payment_type == "voucher": ri-accredita l'importo sul voucher originale.
    - payment_type == "paypal": emette un nuovo voucher di rimborso (con bonus).
    """
    if job.get("refund_done"):
        return  # gia rimborsato
    paid_amount = float(job.get("payment_amount_eur", 0) or 0)
    if paid_amount <= 0:
        return
    payment_type = job.get("payment_type", "")
    payment_email = job.get("payment_email", "")
    payment_token = job.get("payment_token", "")
    book_title = getattr(job.get("info"), "title", "") if job.get("info") else ""

    try:
        if payment_type == "voucher" and payment_token:
            # Ri-accredita direttamente sul voucher originale
            payment._voucher_refund(
                payment_token, paid_amount, job_id=job_id,
                reason=f"Rimborso automatico ottimizzazione {reason}",
            )
            job["refund_done"] = True
            _log_activity(job_id, job.get("original_filename", ""), "VOUCHER_REFUND",
                          job.get("client_id", ""), "", "", "")
            print(f"[{job_id}] Voucher {payment_token} refunded {paid_amount:.2f} EUR (reason={reason})")
        elif payment_type == "paypal" and payment_email:
            # Emetti nuovo voucher per pagamenti PayPal.
            # Bonus +10% riservato a failure piattaforma (reason != "cancel");
            # cancel volontari ottengono solo l'importo nominale (evita abuso
            # cancel-per-bonus).
            _apply_bonus = (reason != "cancel")
            code, bonus_amount = payment._create_voucher(
                payment_email, paid_amount,
                origin_order_id=payment_token,
                origin_job_id=job_id,
                kind="refund",
                created_by="auto_refund",
                note=f"Rimborso automatico ottimizzazione AI ({reason})",
                apply_bonus=_apply_bonus,
            )
            email_service._send_voucher_email(code, payment_email, bonus_amount, book_title)
            job["refund_voucher_code"] = code
            job["refund_done"] = True
            _log_activity(job_id, job.get("original_filename", ""), "VOUCHER_ISSUED",
                          job.get("client_id", ""), "", "", "")
            print(f"[{job_id}] Voucher issued: {code} ({bonus_amount:.2f} EUR) -> {payment_email} (reason={reason})")
    except Exception as ve:
        print(f"[{job_id}] Failed to refund payment: {ve}")


# ---------------------------------------------------------------------------
# Google TTS refund helper
# ---------------------------------------------------------------------------

def _google_tts_refund_unused(job_id, job):
    """Restituisce al budget i caratteri Google TTS prenotati ma non consumati,
    poi forza una riconciliazione con Cloud Monitoring."""
    if _google_tts is None:
        return
    reserved = job.get("google_tts_reserved", 0)
    consumed = job.get("processed_chars", 0)
    if reserved > consumed:
        unused = reserved - consumed
        _google_tts.refund_chars(unused)
        print(f"[{job_id}] Google TTS: refunded {unused:,} unused chars "
              f"(reserved {reserved:,}, consumed {consumed:,})")
        _invalidate_voices_cache()
    # Forza riconciliazione immediata in thread separato per non bloccare il cleanup
    def _do_reconcile():
        try:
            time.sleep(2)  # Piccolo delay per dare tempo all'API di registrare
            _google_tts.reconcile_with_cloud_monitoring()
        except Exception as e:
            print(f"[{job_id}] Post-cancel reconcile error: {e}")
    threading.Thread(target=_do_reconcile, daemon=True).start()


# ---------------------------------------------------------------------------
# run_optimization — background thread LLM
# ---------------------------------------------------------------------------

def run_optimization(job_id, selected_chapters=None):
    """Background thread: optimize text of all chapters via LLM.
    If selected_chapters is provided (list of indices), only those are optimized.
    """
    job = _jobs[job_id]
    _set_job_status(job, "optimizing")
    job["opt_cancelled"] = False
    job["last_poll"] = time.time()
    start_time = time.time()
    info = job["info"]

    print(f"[{job_id}] run_optimization selected_chapters param: {selected_chapters!r}")
    selected_set = set(selected_chapters) if selected_chapters else None
    job["selected_chapters"] = list(selected_set) if selected_set else None
    print(f"[{job_id}] run_optimization selected_set: {selected_set!r}")

    # Identify which chapters to optimize
    chapters_to_opt = info.chapters
    if selected_set:
        chapters_to_opt = [ch for ch in info.chapters if ch.index in selected_set]
        print(f"[{job_id}] run_optimization filtered chapters: {[ch.index for ch in chapters_to_opt]!r}")

    total_chapters = len(chapters_to_opt)
    total_chars = sum(ch.char_count for ch in chapters_to_opt)

    FINALIZATION_RATIO = 0.03
    MIN_FINALIZATION_CHARS = 3000
    finalization_weight = max(MIN_FINALIZATION_CHARS, int(total_chars * FINALIZATION_RATIO))
    total_chars_extended = total_chars + finalization_weight

    # Carica il prompt per la lingua TTS selezionata (non per la lingua
    # dell'input): l'ottimizzazione deve produrre testo adatto alla voce
    # che lo leggera`. Fallback finale: lingua del libro estratta in fase
    # di parsing (utile solo se per qualche motivo opt_lang non e` settato).
    lang = job.get("opt_lang") or job.get("lang") or "it"
    prompt = _get_llm_prompt(lang)
    if prompt:
        print(f"[{job_id}] Ottimizzazione AI avviata su {total_chapters} capitoli (prompt {lang} caricato: {len(prompt)} caratteri). "
              f"Model: {LLM_MODEL}, MaxTokens: {LLM_MAX_TOKENS}, Reasoning: {LLM_REASONING_EFFORT}, Thinking: {LLM_THINKING}")
    else:
        print(f"[{job_id}] Ottimizzazione AI avviata su {total_chapters} capitoli (prompt {lang} non trovato!). "
              f"Model: {LLM_MODEL}, MaxTokens: {LLM_MAX_TOKENS}, Reasoning: {LLM_REASONING_EFFORT}, Thinking: {LLM_THINKING}")

    job["opt_progress_current"] = 0
    job["opt_progress_total"] = total_chapters
    job["opt_total_chars"] = total_chars
    job["opt_total_chars_extended"] = total_chars_extended
    job["opt_finalization_weight"] = finalization_weight
    job["opt_processed_chars"] = 0
    job["opt_streamed_chars"] = 0
    job["opt_start_time"] = start_time
    job["opt_progress_message"] = "Starting optimization..."

    def _emit_finalization_progress(phase_name, fraction_done):
        """fraction_done: 0.0 -> 1.0 within finalization phase"""
        job["opt_processed_chars"] = total_chars + int(finalization_weight * fraction_done)
        job["opt_progress_message"] = phase_name
        job["opt_elapsed_seconds"] = round(time.time() - start_time)
        job["opt_progress_ts"] = time.time()

    try:
        for i, ch in enumerate(chapters_to_opt):
            if job.get("opt_cancelled"):
                raise _CancelledError("Optimization cancelled")
            # Heartbeat check (skip if email registered — batch mode)
            if not job.get("email_registered"):
                last_poll = job.get("last_poll", start_time)
                if time.time() - last_poll > LLM_HEARTBEAT_TIMEOUT_SEC:
                    raise _CancelledError("Optimization cancelled (heartbeat lost)")

            job["opt_progress_current"] = i
            job["opt_current_chapter"] = ch.title
            job["opt_current_chapter_num"] = i + 1
            job["opt_elapsed_seconds"] = round(time.time() - start_time)
            job["opt_progress_message"] = (
                f"Optimizing chapter {i+1}/{total_chapters}: "
                f"{ch.title[:40]}..."
            )
            print(f"[{job_id}] LLM optimizing chapter {i+1}/{total_chapters}: {ch.title}")

            ch_input_chars = ch.char_count
            job["opt_current_chapter_chars"] = ch_input_chars
            job["opt_streamed_chars"] = 0

            optimized_text = _optimize_chapter_text(
                ch.text, chapter_num=i+1, total_chapters=total_chapters, job=job
            )
            # Update chapter text with optimized version
            ch.text = optimized_text
            ch.word_count = len(optimized_text.split())
            ch.char_count = len(optimized_text)
            job["opt_processed_chars"] += ch_input_chars
            job["opt_streamed_chars"] = 0
            job["opt_current_chapter_chars"] = 0

        # Recalculate BookInfo totals
        info.total_words = sum(ch.word_count for ch in info.chapters)
        info.total_chars = sum(ch.char_count for ch in info.chapters)
        info.estimated_duration_minutes = info.total_words / 150

        total_elapsed = time.time() - start_time
        job["opt_progress_current"] = total_chapters
        job["opt_elapsed_seconds"] = round(total_elapsed)
        job["opt_completed_at"] = time.time()
        # Track per-chapter optimization status
        optimized = set(job.get("optimized_chapters", []))
        optimized.update(ch.index for ch in chapters_to_opt)
        job["optimized_chapters"] = list(optimized)
        job["ai_optimized"] = True
        # Segna il job come completato per il recovery voucher all'avvio
        if job.get("payment_type"):
            payment._mark_paid_opt_done(job_id)

        print(f"[{job_id}] LLM optimization completed in {total_elapsed:.1f}s")
        _log_activity(job_id, job.get("original_filename", ""), "OPT_COMPLETE",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))

        _emit_finalization_progress("Finalizing optimization...", 0.0)

        # Re-check auto_generate — may have been set via the unified optimization+generation flow
        auto_generate = job.get("opt_auto_generate", False)
        if auto_generate:
            _emit_finalization_progress("Generating optimized project archive...", 0.15)
            # Generate .abm snapshot first, then proceed to TTS generation
            try:
                abm_path, abm_name = _generate_optimized_abm(job_id)
                job["optimized_abm_path"] = abm_path
                job["optimized_abm_name"] = abm_name
                _emit_finalization_progress("Project archive created.", 0.30)
            except Exception as e:
                print(f"[{job_id}] Failed to generate .abm snapshot before auto-gen: {e}")
                _emit_finalization_progress("Project archive not available (non-critical).", 0.30)
            _emit_finalization_progress("Optimization complete! Preparing audio generation...", 1.0)
            # Go directly to generating — skip intermediate "optimized" status
            # to avoid race condition in SSE polling
            voice = job.get("opt_voice", "it-IT-IsabellaNeural")
            rate = job.get("opt_rate", "+0%")
            single_file = job.get("opt_single_file", True)
            output_format = job.get("opt_output_format", "m4b")
            podcast_base_url = job.get("opt_podcast_base_url", "")
            print(f"[{job_id}] Auto-generating after optimization (voice: {voice})")

            # Bump generation epoch so output lands in its own output_{epoch}/.
            # /api/generate normally does this; the auto-gen path bypasses it.
            job["gen_epoch"] = job.get("gen_epoch", 0) + 1

            # Filter info if only a subset was optimized
            if selected_chapters:
                selected_set = set(selected_chapters)
                filtered = [ch for ch in info.chapters if ch.index in selected_set]
                if filtered:
                    info = copy(info)
                    info.chapters = filtered
                    info.total_words = sum(ch.word_count for ch in filtered)
                    info.total_chars = sum(ch.char_count for ch in filtered)
                    info.estimated_duration_minutes = info.total_words / 150

            # Persisti la stima Gemini per l'audit (popola i campi *_est del
            # JSONL altrimenti sempre 0 in questo path: il flusso auto-gen
            # bypassa /api/generate dove la stima viene calcolata).
            # IMPORTANTE: se /api/optimize ha gia` salvato lo snapshot pre-LLM
            # (combined_optimize_autogen flow), NON sovrascrivere — il prezzo
            # lockato in payment["total_eur"] e` stato calcolato su quella
            # stima, e ricalcolarla qui su testo post-LLM disallinea cost_est
            # da charged nell'audit JSONL (artefatto delta_pct/margin).
            if (gemini_tts is not None and voice
                    and voice.startswith("gemini:")
                    and not job.get("gemini_estimate")):
                try:
                    _ui_lang_autogen = (job.get("opt_lang") or "").lower()
                    _lang_autogen = (_ui_lang_autogen
                                     or (getattr(info, "language", "") or "").split("-")[0].lower()
                                     or "it")
                    _est_autogen = gemini_tts.estimate_book_cost(
                        info.chapters, voice,
                        language=_lang_autogen, rate_pct=rate,
                    )
                    job["gemini_estimate"] = _est_autogen
                except Exception as _e_est_ag:
                    print(f"[{job_id}] auto-gen gemini_estimate persist failed (non-fatal): {_e_est_ag}")

            # Tracking nell'Activity Log: il flusso auto-gen bypassa
            # /api/generate (dove l'evento GENERATE viene scritto con voice),
            # quindi la voce non comparirebbe nella UI admin. Mirroriamo qui
            # il log per allineamento.
            try:
                _log_activity(job_id, job.get("original_filename", ""), "GENERATE",
                              job.get("client_id", ""), job.get("client_ip", ""),
                              voice, job.get("browser_lang", ""))
            except Exception:
                pass

            run_generation(job_id, info, voice, rate, single_file,
                           output_format=output_format,
                           podcast_base_url=podcast_base_url)
        elif job.get("email_registered"):
            # Batch mode, no auto-generate: create .abm and send email
            _emit_finalization_progress("Generating optimized project archive...", 0.15)
            try:
                abm_path, abm_name = _generate_optimized_abm(job_id)
                job["optimized_abm_path"] = abm_path
                job["optimized_abm_name"] = abm_name
                _emit_finalization_progress("Project archive created.", 0.30)
            except Exception as e:
                print(f"[{job_id}] Failed to generate .abm: {e}")
                _emit_finalization_progress("Project archive not available (non-critical).", 0.30)
            _emit_finalization_progress("Sending completion email...", 0.70)
            try:
                _send_optimization_email(job_id)
                _emit_finalization_progress("Completion email sent.", 1.0)
            except Exception as e:
                print(f"[{job_id}] Optimization email error: {e}")
                _emit_finalization_progress("Optimization complete (email error, retry manually).", 1.0)
            _set_job_status(job, "optimized")
        else:
            # Interactive mode: just mark as optimized
            _emit_finalization_progress("Optimization complete!", 1.0)
            _set_job_status(job, "optimized")
            job["last_poll"] = time.time()

    except _CancelledError:
        # Revert to analyzed so cleanup doesn't nuke the job — user can retry
        _set_job_status(job, "analyzed")
        job["opt_progress_message"] = "Optimization cancelled"
        print(f"[{job_id}] LLM optimization cancelled")
        _log_activity(job_id, job.get("original_filename", ""), "OPT_CANCEL",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      "", job.get("browser_lang", ""))
        _refund_job_payment(job_id, job, "cancel")
    except Exception as e:
        _set_job_status(job, "error")
        job["error"] = f"LLM optimization error: {e}"
        import traceback
        traceback.print_exc()
        _refund_job_payment(job_id, job, "error")


def _engine_for_voice(voice):
    """Sceglie il motore TTS dal voice ID.

    Prefissi:
      - "gemini:..."  -> Gemini TTS (PCM native)
      - "gcloud:..."  -> Google Cloud TTS Chirp3-HD (MP3)
      - altrimenti    -> Microsoft Edge TTS (MP3, default)
    """
    if not voice:
        return "edge"
    if voice.startswith("gemini:"):
        return "gemini"
    if _google_tts is not None and _google_tts.is_google_voice(voice):
        return "google"
    return "edge"


# ---------------------------------------------------------------------------
# run_generation — background thread TTS
# ---------------------------------------------------------------------------

def _audit_language(job, info):
    """Lingua da registrare nell'audit Gemini e in `record_rate_sample`.

    Per i job PREMIUM la lingua di interesse e' quella TTS scelta dall'utente
    (perche' determina la voce e il prompt), non la lingua metadata del libro:
    es. libro arabo letto da voce italiana -> audit deve mostrare "it", non
    "ar-sa". Preferenze in ordine:
      1. `job["opt_lang"]`  — settato da /api/optimize (body `lang`)
      2. `job["gen_lang"]`  — settato da /api/generate (body `lang`)
      3. `job["payment"]["gemini_est"].language` — lingua passata a
         `estimate_book_cost` al booking (riflette la stima lockata in
         `payment.total_eur`)
      4. `info.language` — fallback metadata libro (legacy / job senza
         pagamento, es. preview free sub-soglia)
    """
    for src in (job.get("opt_lang"), job.get("gen_lang")):
        if isinstance(src, str) and src.strip():
            return src.strip().split("-")[0].lower()
    try:
        _est_lang = (((job.get("payment") or {}).get("gemini_est") or {})
                     .get("language") or "")
        if isinstance(_est_lang, str) and _est_lang.strip():
            return _est_lang.strip().split("-")[0].lower()
    except Exception:
        pass
    fallback = getattr(info, "language", "") or ""
    return (fallback.split("-")[0].lower() if fallback else "")


def _write_gemini_audit(job_id, job, voice_id, language, outcome):
    """Append audit record at end of Gemini job. Best-effort, non-fatal."""
    try:
        if not voice_id or not voice_id.startswith("gemini:"):
            return
        actual = job.get("gemini_actual") or {}
        parts = voice_id.split(":")
        model_key = parts[1] if len(parts) >= 3 else "?"
        payment = job.get("payment") or {}
        charged = float(payment.get("total_eur", 0) or 0)
        payment_method = payment.get("method", "") or ""
        payment_source = payment.get("source", "") or ""
        payment_token_full = payment.get("token", "") or ""
        # Fallback: il flusso auto_generate post-optimize storicamente non
        # impostava job["payment"] (l'unico setter era /api/generate). Per
        # job legacy o path non ancora coperti, accettiamo come ripiego la
        # cifra registrata da /api/optimize (job["payment_amount_eur"]).
        # Nel JSONL marchiamo l'origine con payment_source="legacy_fallback"
        # cosi' un'eventuale doppia copertura e' rintracciabile.
        if charged <= 0:
            _legacy_amt = float(job.get("payment_amount_eur", 0) or 0)
            if _legacy_amt > 0:
                charged = _legacy_amt
                payment_method = job.get("payment_type", "") or payment_method
                payment_token_full = job.get("payment_token", "") or payment_token_full
                payment_source = payment_source or "legacy_fallback"
        # Token mascherato per audit (mai esporre il PayPal order_id completo).
        if payment_token_full:
            payment_token_short = (payment_token_full[:8] + "..."
                                   if len(payment_token_full) > 12
                                   else payment_token_full)
        else:
            payment_token_short = ""
        google_cost_actual = float(actual.get("google_cost_eur", 0.0) or 0.0)
        try:
            if gemini_tts is not None:
                should = gemini_tts.compute_user_price_eur(google_cost_actual, model_key)
                should_have_been = float(should.get("user_price_eur", 0.0))
            else:
                should_have_been = 0.0
        except Exception:
            should_have_been = 0.0
        delta_eur = round(should_have_been - charged, 4)
        # DELTA % = scostamento di ricarico in punti percentuali rispetto al
        # costo Google. Ricarico effettivo = (charged - cost)/cost; ricarico
        # atteso = (should - cost)/cost; il delta tra i due = delta_eur/cost.
        # NB: non si divide piu` per `charged` (era ambiguo: scostamento di
        # prezzo, non di margine).
        delta_pct = round((delta_eur / google_cost_actual * 100), 2) if google_cost_actual > 0 else 0.0
        est = job.get("gemini_estimate") or {}
        # Rate scelto dall'utente: il prezzo proposto scala col fattore di
        # velocità, quindi va tracciato per consentire calibrazione per
        # rate_step (vedi recalc-params, raggruppato anche su rate_step).
        rate_raw = job.get("rate", "+0%")
        try:
            if isinstance(rate_raw, str):
                rate_pct_val = int(rate_raw.replace("%", "").replace("+", "").strip() or 0)
            else:
                rate_pct_val = int(rate_raw or 0)
        except Exception:
            rate_pct_val = 0
        try:
            if gemini_tts is not None and hasattr(gemini_tts, "_rate_pct_to_step"):
                rate_step_val = int(gemini_tts._rate_pct_to_step(rate_pct_val))
            else:
                rate_step_val = max(-3, min(3, round(rate_pct_val / 10.0)))
        except Exception:
            rate_step_val = 0
        rec = {
            "job_id": job_id,
            "model_key": model_key,
            "language": language or "",
            "rate_pct": rate_pct_val,
            "rate_step": rate_step_val,
            "chars_total": int(actual.get("chars", 0) or 0),
            "input_tokens_est": int(est.get("input_tokens_est", 0) or 0),
            "input_tokens_actual": int(actual.get("input_tokens", 0) or 0),
            "output_tokens_est": int(est.get("output_tokens_est", 0) or 0),
            "output_tokens_actual": int(actual.get("output_tokens", 0) or 0),
            "audio_seconds_est": float(est.get("audio_seconds_est", 0) or 0),
            "audio_seconds_actual": round(float(actual.get("audio_seconds", 0) or 0), 2),
            "google_cost_eur_est": float(est.get("google_cost_eur", 0) or 0),
            "google_cost_eur_actual": round(google_cost_actual, 4),
            "user_price_eur_charged": charged,
            "user_price_eur_should_have_been": round(should_have_been, 2),
            "delta_eur": delta_eur,
            "delta_pct": delta_pct,
            "margin_eur_actual": round(charged - google_cost_actual, 4),
            "outcome": outcome,
            "payment_method": payment_method,
            "payment_token_short": payment_token_short,
            "payment_source": payment_source,
        }
        _cancel_meta = job.get("cancel_meta")
        if isinstance(_cancel_meta, dict):
            rec["cancel_paid_eur"] = round(float(_cancel_meta.get("paid_eur", 0) or 0), 2)
            rec["cancel_retained_eur"] = round(float(_cancel_meta.get("retained_eur", 0) or 0), 2)
            rec["cancel_refund_eur"] = round(float(_cancel_meta.get("refund_eur", 0) or 0), 2)
            rec["cancel_progress_pct"] = int(_cancel_meta.get("progress_pct", 0) or 0)
            rec["cancel_partial_audio_delivered"] = bool(
                _cancel_meta.get("partial_audio_delivered", False))
        gemini_cost_audit.append_record(rec)
        # Release atomic budget reservation (cost ora persistito nel JSONL,
        # quindi futuri preflight lo conteranno in `spent` direttamente).
        try:
            import gemini_tts as _gtts
            _gtts.release_reservation(job_id)
        except Exception:
            pass
        # Diagnostica: job completato sopra soglia gratuita senza pagamento
        # registrato e' sintomo di bug (token consumato in un branch che non
        # stasha job["payment"], oppure stima divergente fra frontend/server
        # che salta il branch payment). Stampa WARNING esplicito cosi' la
        # prossima occorrenza emerge nei log senza dover scavare nel JSONL.
        try:
            _free_thr = float(os.environ.get("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50"))
        except (TypeError, ValueError):
            _free_thr = 0.50
        if (outcome == "completed"
                and charged <= 0.0
                and should_have_been > _free_thr):
            print(f"[{job_id}] AUDIT WARNING: completed job sopra soglia "
                  f"({should_have_been:.2f}€) senza pagamento registrato "
                  f"(payment_method={payment_method or 'NONE'}, "
                  f"payment_token_in_job={'YES' if job.get('payment_token') else 'NO'}). "
                  f"Possibile bug: token consumato in un path che non stasha "
                  f"job['payment']. Vedi md_files/ttsgemini.md sezione audit.")
        # Reconciliation a livello mensile (gemini_tts_usage.json): registra
        # il delta stima/reale per consentire calibrazione del modello di costo.
        # Solo job davvero completati - per i cancel partiali la stima ex-ante
        # non sarebbe confrontabile con un costo reale "tronco".
        try:
            if (gemini_tts is not None and outcome == "completed"
                    and model_key in ("flash25", "flash31")):
                gemini_tts.record_job_completion(
                    model_key,
                    estimated_eur=float(est.get("google_cost_eur", 0) or 0),
                    actual_eur=google_cost_actual,
                    user_price_eur=charged,
                )
        except Exception as e:
            print(f"[{job_id}] record_job_completion failed (non-fatal): {e}")
    except Exception as e:
        print(f"[{job_id}] audit write failed (non-fatal): {e}")


def _offload_to_cloud(job_id, output_dir, when):
    """Carica i file di output offloadable su cold storage e scrive il marker.
    No-op se il backend S3 non è configurato. Verifica l'esistenza remota
    prima di marcare: la finestra calda evacuerà il locale solo se il marker
    c'è, quindi un upload fallito NON porta mai a perdita di file."""
    if not storage_backend.is_enabled():
        return
    from pathlib import Path
    od = Path(output_dir)
    if not od.exists():
        return
    all_ok = True
    uploaded_any = False
    for f in od.rglob("*"):
        if not f.is_file() or not storage_tiering.is_offloadable(f.name):
            continue
        key = storage_tiering.key_for_path(str(f))
        if not key:
            continue
        try:
            storage_backend.upload_file(str(f), key)
            if not storage_backend.object_exists(key):
                all_ok = False
            else:
                uploaded_any = True
        except Exception as e:
            print(f"[{job_id}] cloud offload error for {f.name}: {e}", flush=True)
            all_ok = False
    if all_ok and uploaded_any:
        storage_tiering.mark_cloud_uploaded(od, when)
        print(f"[{job_id}] cloud offload complete: {output_dir}", flush=True)


def _spawn_cloud_offload(job_id, output_dir):
    """Avvia l'upload su cold storage in un thread daemon: non blocca l'email
    di completamento né il ritorno di run_generation. La finestra calda serve
    nel frattempo i file da locale."""
    if not storage_backend.is_enabled():
        return
    import threading, time as _t
    threading.Thread(
        target=_offload_to_cloud,
        args=(job_id, output_dir, _t.time()),
        daemon=True,
    ).start()


def run_generation(job_id, info, voice, rate, single_file, output_format='m4b', podcast_base_url='', gemini_style_instruction=None):
    job = _jobs[job_id]
    _set_job_status(job, "generating")
    job["cancelled"] = False
    my_epoch = job.get("gen_epoch", 0)
    job["last_poll"] = time.time()
    # Conserva il rate scelto sul job: serve all'audit Gemini (calibrazione
    # per rate_step) e a eventuali ri-letture diagnostiche del job state.
    job["rate"] = rate
    work_dir = _upload_dir / job_id
    work_dir.mkdir(exist_ok=True)
    # Per-epoch output directory: each /api/generate call creates its own
    # output_{epoch}/ folder. This isolates concurrent generations and keeps
    # earlier outputs intact for active email-download tokens, so
    # /api/reset_to_chapters never has to delete or rename anything.
    output_dir = work_dir / f"output_{my_epoch}"
    output_dir.mkdir(exist_ok=True)
    job["output_dir"] = str(output_dir)
    # Clear stale output paths from previous generations on this same job_id.
    # Without this, if the current run produces a different format (e.g. mp3
    # only) the old M4B/ZIP/ABM paths from the previous epoch would persist
    # in the job dict and be served by /api/download, leaking files across
    # generations. Active email tokens hold their own snapshot copies, so
    # this clear is safe for them too.
    for _stale_key in ("output_files", "output_name", "output_zip", "output_file",
                       "output_m4b", "optimized_abm_path", "optimized_abm_name",
                       "podcast_ready", "podcast_safe_name", "podcast_mp3s",
                       "podcast_info", "podcast_rss_included",
                       "m4b_failed"):
        job.pop(_stale_key, None)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    start_time = time.time()

    # Determina il motore TTS (3-way: edge / google / gemini)
    engine = _engine_for_voice(voice)
    use_google = (engine == "google")
    use_gemini = (engine == "gemini")

    try:
        job["progress_message"] = "Preparing..."
        print(f"[{job_id}] Generation started: voice={voice}, rate={rate}, "
              f"chapters={len(info.chapters)}, single_file={single_file}, "
              f"output_format={output_format}, engine={engine}")
        max_chars = _pick_chunk_max_chars(voice, getattr(info, "language", None) or "")
        max_bytes = _pick_chunk_max_bytes(voice)
        plan = _plan_chunks(info, max_chars=max_chars, max_bytes=max_bytes)
        gemini_usage = {"input_tokens": 0, "output_tokens": 0, "model_key": None}
        job["gemini_actual"] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "chars": 0,
            "audio_seconds": 0.0,
            "google_cost_eur": 0.0,
            "model_key": None,
        }
        total_chunks = len(plan)
        total_chars = sum(b["chars"] for b in plan)
        print(f"[{job_id}] Plan ready: {total_chunks} chunks, {total_chars:,} chars total")
        job["total_chars"] = total_chars
        job["total_chunks"] = total_chunks

        # Pre-flight RPD check: per job Gemini, se i chunk previsti superano
        # la quota giornaliera residua (cap - used - reserve), abortire ANTE
        # di sintetizzare alcunche': rimborso integrale, notifica utente
        # generica "voci PREMIUM sovraccarico", admin alert.
        if use_gemini and gemini_tts is not None:
            try:
                _parts_v = (voice or "").split(":")
                _model_key = _parts_v[1] if len(_parts_v) >= 3 else "flash25"
                _pf = gemini_tts.preflight_can_run(_model_key, total_chunks)
                # Log RPD status sempre (anche quando ok) per visibilita' operativa.
                # cap=0 = nessun cap locale configurato (l'API Google fa da unica barriera).
                _cap_v = _pf.get("cap", 0)
                if _cap_v and _cap_v > 0:
                    print(f"[{job_id}] RPD status [{_model_key}]: "
                          f"used={_pf.get('used', 0)}/{_cap_v}, "
                          f"reserve={_pf.get('reserve', 0)}, "
                          f"available={_pf.get('available', 0)}, "
                          f"needed={_pf.get('needed', 0)} "
                          f"-> {'OK' if _pf.get('ok') else 'BLOCK (shortfall=' + str(_pf.get('shortfall', 0)) + ')'}")
                else:
                    print(f"[{job_id}] RPD status [{_model_key}]: no local cap "
                          f"(ABM_GEMINI_RPD_{_model_key.upper()}=0), needed={_pf.get('needed', 0)}")
            except Exception as _pf_err:
                print(f"[{job_id}] Preflight check error (non-fatal, proceeding): {_pf_err}")
                _pf = {"ok": True}
            if not _pf.get("ok"):
                _reason = (f"preflight_block: model={_model_key} "
                           f"needed={_pf.get('needed')} "
                           f"available={_pf.get('available')} "
                           f"shortfall={_pf.get('shortfall')} "
                           f"cap={_pf.get('cap')} used={_pf.get('used')} "
                           f"reserve={_pf.get('reserve')}")
                print(f"[{job_id}] PREFLIGHT BLOCK -> {_reason}")
                _user_msg = ("Generazione non avviata: il motore voci PREMIUM "
                             "e' temporaneamente sovraccarico. Hai diritto al "
                             "rimborso integrale, gia' emesso automaticamente. "
                             "Riprova tra qualche ora.")
                # IMPORTANTE: settare i marker del preflight block PRIMA di
                # cambiare status a "error". Lo stream SSE in /api/progress
                # polla ogni secondo e si chiude al primo tick con status=error;
                # se gemini_preflight_block non e' ancora settato a quel tick,
                # il frontend non riceve error_kind=gemini_overload e cade nel
                # branch errore generico (e nel popup non viene mostrato).
                job["error"] = _user_msg
                job["user_facing_error"] = _user_msg
                job["gemini_preflight_block"] = {
                    "model_key": _model_key,
                    "needed": _pf.get("needed"),
                    "available": _pf.get("available"),
                    "retry_after_sec": _pf.get("retry_after_sec"),
                }
                _set_job_status(job, "error")
                # Audit
                try:
                    _write_gemini_audit(job_id, job, voice,
                                        _audit_language(job, info),
                                        "preflight_blocked_refunded")
                except Exception:
                    pass
                # Refund
                _refund_info = None
                try:
                    _refund_info = _refund_gemini_payment(
                        job_id, job, f"preflight_block: {_reason}",
                    )
                except Exception as _ref_err:
                    print(f"[{job_id}] Preflight refund failed (non-fatal): {_ref_err}")
                # Notifica utente (overload copy)
                try:
                    payment_meta = job.get("payment") or {}
                    amt = float(payment_meta.get("total_eur", 0) or 0)
                    method = payment_meta.get("method", "")
                    tok = payment_meta.get("token")
                    _email_to = ""
                    try:
                        if method == "voucher" and tok:
                            v = payment._vouchers.get(tok, {}) if hasattr(payment, "_vouchers") else {}
                            _email_to = v.get("email", "") or ""
                        elif method == "paypal" and tok:
                            pay = payment._payments.get(tok, {})
                            _email_to = pay.get("email", "") or ""
                    except Exception:
                        _email_to = ""
                    _book_title = ""
                    try:
                        _book_title = getattr(info, "title", "") or job.get("original_filename", "")
                    except Exception:
                        _book_title = job.get("original_filename", "")
                    if _email_to and amt > 0:
                        email_service._send_gemini_overload_email(
                            _email_to, amt, _book_title,
                            voucher_code=job.get("refund_voucher_code"),
                            retry_after_sec=_pf.get("retry_after_sec", 0),
                        )
                except Exception as _notif_err:
                    print(f"[{job_id}] Preflight user notification failed (non-fatal): {_notif_err}")
                # Admin alert
                _admin_alert_gemini_failure(
                    job_id, job, kind="preflight",
                    audit_outcome="preflight_blocked_refunded",
                    reason_detail=_reason,
                    chunks_total=total_chunks,
                )
                return

        job["progress_current"] = 1
        job["progress_message"] = "Analisi testo..."

        # Genera file di silenzio da preporre a ogni capitolo (PCM se Gemini, MP3 altrimenti)
        if use_gemini:
            silence_path = str(work_dir / "_silence.pcm")
            _generate_silence_pcm(silence_path, CHAPTER_SILENCE_SEC)
            silence_ok = os.path.exists(silence_path)
        else:
            silence_path = str(work_dir / "_silence.mp3")
            silence_ok = _generate_silence_mp3(silence_path, CHAPTER_SILENCE_SEC)
        print(f"[{job_id}] Silence file: {silence_path}, ok={silence_ok}")
        job["progress_current"] = 2
        job["progress_message"] = "Preparazione audio..."

        job["progress_total"] = total_chunks + 2
        job["total_chars"] = total_chars
        job["processed_chars"] = 0
        job["bytes_generated"] = 0
        job["start_time"] = start_time
        job["current_chapter"] = ""
        job["current_chapter_num"] = 0
        job["total_chapters"] = len(info.chapters)

        def _check_cancelled():
            """Controlla se il job e stato cancellato o il client disconnesso."""
            if job.get("gen_epoch", 0) != my_epoch:
                print(f"[{job_id}] _check_cancelled: epoch mismatch "
                      f"(job={job.get('gen_epoch')}, my={my_epoch})")
                return True
            if job.get("cancelled"):
                print(f"[{job_id}] _check_cancelled: explicit cancel flag")
                return True
            if job.get("email_registered"):
                return False
            # Heartbeat: se nessun client ha chiesto il progresso da 60+ sec
            last_poll = job.get("last_poll", start_time)
            idle = time.time() - last_poll
            if idle > 60:
                print(f"[{job_id}] _check_cancelled: heartbeat timeout "
                      f"({idle:.0f}s idle > 60s)")
                return True
            return False

        def _update_progress(i, block):
            elapsed = time.time() - start_time
            job["progress_current"] = 2 + i
            job["progress_message"] = (
                f"Cap. {block['chapter_index']}/{len(info.chapters)}: "
                f"{block['chapter_title'][:35]}... \u2014 "
                f"chunk {block['chunk_index']+1}/{block['chunks_in_chapter']}"
            )
            job["current_chapter"] = block["chapter_title"]
            job["current_chapter_num"] = block["chapter_index"]
            job["elapsed_seconds"] = round(elapsed)

        # Gap inter-chunk Gemini (Premium quality). Calcolato qui per essere
        # disponibile sia nel ramo single-file sia nel ramo multi-file.
        gap_ms_inter = (gemini_tts.inter_chunk_gap_ms()
                        if (use_gemini and gemini_tts is not None) else 0)

        if single_file:
            all_parts = []
            m4b_chapters = []
            current_ms = 0
            if use_gemini and os.path.exists(silence_path):
                silence_ms = int(pcm_size_to_seconds(os.path.getsize(silence_path)) * 1000)
            else:
                silence_ms = _get_audio_duration_ms(silence_path) if os.path.exists(silence_path) else 0
            prev_chapter_idx = -1
            failed_chunks = 0
            # Gap inter-chunk (Premium quality Gemini): pcm_concat inserira` un
            # silenzio di gap_ms_inter ms PRIMA di ogni elemento di all_parts
            # tranne il primo. Per mantenere allineati i marker M4B aggiorniamo
            # current_ms e l'end del capitolo corrente PRIMA di ogni append a
            # all_parts (escluso il primo). Il gap viene quindi attribuito al
            # capitolo "uscente" se inserito prima del silence_path, e al
            # capitolo "entrante" se inserito prima di un chunk audio (sia
            # all'interno di un capitolo, sia come primo chunk di un capitolo
            # nuovo senza silence_path: in questo caso l'ascoltatore sente
            # ~gap_ms di silenzio in testa al cap, che e` esteticamente OK).
            for i, block in enumerate(plan):
                if _check_cancelled():
                    raise _CancelledError("Job cancelled")
                _update_progress(i, block)

                # Periodic progress logging ogni 10 chunk
                if i > 0 and (i % 10 == 0 or i == total_chunks - 1):
                    pct = (i + 1) / total_chunks * 100
                    print(f"[{job_id}] Progress: chunk {i+1}/{total_chunks} "
                          f"({pct:.0f}%), failed_chunks={failed_chunks}, "
                          f"elapsed={time.time()-start_time:.0f}s")

                ch_idx = block["chapter_index"]
                ch_title = block["chapter_title"]

                # Silenzio all'inizio di ogni capitolo
                if ch_idx != prev_chapter_idx:
                    if os.path.exists(silence_path):
                        # Bump per il gap che verra` inserito PRIMA del silence:
                        # appartiene alla coda del capitolo precedente.
                        if gap_ms_inter and all_parts:
                            current_ms += gap_ms_inter
                            if m4b_chapters:
                                m4b_chapters[-1]["end"] += gap_ms_inter
                        all_parts.append(silence_path)
                        if m4b_chapters:
                            m4b_chapters[-1]["end"] = current_ms
                        m4b_chapters.append({"title": ch_title, "start": current_ms, "end": current_ms + silence_ms})
                        current_ms += silence_ms
                    else:
                        if m4b_chapters:
                            m4b_chapters[-1]["end"] = current_ms
                        m4b_chapters.append({"title": ch_title, "start": current_ms, "end": current_ms})
                    prev_chapter_idx = ch_idx

                if use_gemini:
                    part_path = str(work_dir / f"chunk_{i:06d}.pcm")
                    debug_prompt_path = str(work_dir / f"prompt{i+1}.txt")
                    # Applichiamo lo stile a TUTTI i chunk: limitarlo al primo
                    # chunk del capitolo (vecchio design cost-saving) faceva
                    # percepire all'utente uno stile diverso tra preview (1 chunk,
                    # sempre con stile) e job finale (1 chunk su N con stile).
                    # Il costo dei token aggiuntivi e` trascurabile (~315 char di
                    # prefix x N chunk: pochi millicent per libro tipico).
                    style_for_chunk = gemini_style_instruction
                    try:
                        result = generate_chunk_pcm_gemini(block["text"], voice, part_path,
                                                           style_instruction=style_for_chunk,
                                                           rate=rate,
                                                           debug_prompt_path=debug_prompt_path)
                    except Exception as _quota_or_budget_err:
                        # GeminiQuotaExhausted / GeminiBudgetExceeded: meglio
                        # marcare il job come paused/error che silenziare il resto
                        # del libro. Salviamo lo stato e usciamo dal loop chunk.
                        if gemini_tts is not None and isinstance(_quota_or_budget_err,
                                                                  (gemini_tts.GeminiQuotaExhausted,
                                                                   gemini_tts.GeminiBudgetExceeded)):
                            retry_after = getattr(_quota_or_budget_err, "retry_after_sec", None)
                            reason = getattr(_quota_or_budget_err, "reason",
                                             getattr(_quota_or_budget_err, "scope", "quota"))
                            job["gemini_paused"] = True
                            job["gemini_pause_reason"] = reason
                            job["gemini_pause_retry_after_sec"] = retry_after
                            job["gemini_pause_message"] = str(_quota_or_budget_err)
                            print(f"[{job_id}] Gemini paused at chunk {i}/{total_chunks}: "
                                  f"reason={reason} retry_after={retry_after}s. "
                                  f"Err: {str(_quota_or_budget_err)[:200]}")
                            raise
                        # Errore generico non quota-related: rilancia
                        raise
                    if result is False:
                        failed_chunks += 1
                    else:
                        gemini_usage["input_tokens"] += result.get("input_tokens", 0)
                        gemini_usage["output_tokens"] += result.get("output_tokens", 0)
                        if not gemini_usage["model_key"]:
                            gemini_usage["model_key"] = result.get("model_key")
                        ga = job["gemini_actual"]
                        ga["input_tokens"] += result.get("input_tokens", 0)
                        ga["output_tokens"] += result.get("output_tokens", 0)
                        ga["chars"] += len(block["text"])
                        bw = result.get("bytes_written", 0)
                        ga["audio_seconds"] += bw / (24000.0 * 2)
                        model_key = result.get("model_key", "flash25")
                        if not ga["model_key"]:
                            ga["model_key"] = model_key
                        # Costo Google REALE del chunk (token reali da usage_metadata
                        # x rate per MTok). Calcolato una sola volta, riusato sia per
                        # l'aggregato job (gemini_actual) sia per record_usage().
                        chunk_google_cost_eur = 0.0
                        if gemini_tts is not None:
                            try:
                                bd = gemini_tts.google_cost_breakdown(
                                    result.get("input_tokens", 0),
                                    result.get("output_tokens", 0),
                                    model_key,
                                )
                                chunk_google_cost_eur = float(bd.get("total_eur", 0.0) or 0.0)
                                ga["google_cost_eur"] += chunk_google_cost_eur
                            except Exception as e:
                                print(f"[{job_id}] google_cost_breakdown failed (non-fatal): {e}")
                        result["_google_cost_eur"] = chunk_google_cost_eur
                else:
                    part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                    if use_google:
                        result = generate_chunk_mp3_google(block["text"], voice, rate, part_path)
                    else:
                        try:
                            result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                        except Exception as _edge_err:
                            print(f"[{job_id}] edge-tts chunk {i} crashed: {_edge_err}")
                            import traceback
                            traceback.print_exc()
                            _generate_silence_mp3(part_path, duration_sec=1)
                            result = False
                    if result is False:
                        failed_chunks += 1
                # Bump per il gap che verra` inserito PRIMA di questo part_path
                # (Premium Gemini): aggiorna i timing M4B per il capitolo corrente.
                if gap_ms_inter and all_parts:
                    current_ms += gap_ms_inter
                    if m4b_chapters:
                        m4b_chapters[-1]["end"] += gap_ms_inter
                all_parts.append(part_path)
                # Record Gemini usage per chunk (so partial completions on cancel still book it)
                if use_gemini and result is not False and gemini_tts is not None:
                    try:
                        gemini_tts.record_usage(
                            result.get("model_key", "flash25"),
                            len(block["text"]),
                            result.get("input_tokens", 0),
                            result.get("output_tokens", 0),
                            float(result.get("_google_cost_eur", 0.0) or 0.0),
                            0.0,
                        )
                    except Exception as e:
                        print(f"[{job_id}] gemini_tts.record_usage failed (non-fatal): {e}")
                    # Empirical rate sample (chars normalizzati -> audio_seconds reali).
                    # Lingua = TTS scelta (opt_lang/gen_lang), NON metadata libro:
                    # cosi' i campioni rate sono raggruppati per lingua REALE della
                    # voce, non per lingua dell'input (es. libro arabo -> voce IT
                    # registra sample "it", utili per calibrazione voce italiana).
                    try:
                        _lang = (_audit_language(job, info) or "it")[:2]
                        _norm_chars = len(gemini_tts._normalize_text(block["text"]))
                        _audio_secs = result.get("audio_seconds_real")
                        if _audio_secs is None:
                            _audio_secs = result.get("bytes_written", 0) / (24000.0 * 2)
                        gemini_tts.record_rate_sample(
                            _norm_chars, _audio_secs, _lang,
                            result.get("model_key", "flash25"),
                            rate_pct=rate,
                        )
                    except Exception as e:
                        print(f"[{job_id}] gemini_tts.record_rate_sample failed (non-fatal): {e}")

                    # Trim trailing silence dal PCM chunk Gemini per ridurre le
                    # pause percepibili tra chunk consecutivi. Cap a trim_tail_ms()
                    # per evitare di tagliare l'attacco/coda di parola. NON applicato
                    # se result is False (sotto e` silenzio puro segnaposto).
                    if gemini_tts is not None:
                        try:
                            _trim_cap = gemini_tts.trim_tail_ms()
                            _trim_thr = gemini_tts.trim_tail_threshold()
                            if _trim_cap > 0:
                                trim_pcm_trailing_silence(
                                    part_path, threshold=_trim_thr, max_trim_ms=_trim_cap,
                                )
                        except Exception as _e_trim:
                            print(f"[{job_id}] trim_pcm_trailing_silence failed (non-fatal): {_e_trim}")

                # Log sul primo chunk per confermare che il TTS sta procedendo
                if i == 0:
                    print(f"[{job_id}] First chunk done: {part_path}, "
                          f"size={os.path.getsize(part_path) if os.path.exists(part_path) else 0}, "
                          f"failed={failed_chunks}")

                # Aggiorna timing per capitolo M4B
                if use_gemini and os.path.exists(part_path):
                    size_bytes = os.path.getsize(part_path)
                    duration = int(pcm_size_to_seconds(size_bytes) * 1000)
                else:
                    duration = _get_audio_duration_ms(part_path)
                if m4b_chapters:
                    m4b_chapters[-1]["end"] += duration
                current_ms += duration

                job["processed_chars"] += block["chars"]
                if os.path.exists(part_path):
                    job["bytes_generated"] += os.path.getsize(part_path)

            if m4b_chapters:
                m4b_chapters[-1]["end"] = current_ms

            print(f"[{job_id}] All chunks processed: {total_chunks} total, {failed_chunks} failed")
            job["progress_message"] = "Merging audio..."
            safe_name = _safe_filename(info.title) or "audiolibro"

            if use_gemini:
                # Gemini: tutto PCM. Assembly diretto in base a output_format.
                final_mp3 = str(output_dir / f"{safe_name}.mp3")
                final_m4b = str(output_dir / f"{safe_name}.m4b")
                valid_m4b_ch = [c for c in m4b_chapters if c.get("end", 0) > c.get("start", 0)]
                cover_path = _prepare_m4b_cover_path(job, info.title, info.author, work_dir)

                if output_format in ('mp3', 'zip', 'zip_rss'):
                    # Solo MP3 finale richiesto
                    pcm_to_mp3(all_parts, final_mp3, gap_ms=gap_ms_inter)
                    print(f"[{job_id}] PCM->MP3 merged: {final_mp3}, "
                          f"size={os.path.getsize(final_mp3) if os.path.exists(final_mp3) else 0}, "
                          f"gap_ms={gap_ms_inter}")
                else:
                    # M4B richiesto: percorso PCM->AAC diretto (niente MP3 intermedio)
                    job["progress_message"] = "Converting to M4B..."
                    print(f"[{job_id}] Starting PCM->M4B direct conversion: {final_m4b} (gap_ms={gap_ms_inter})")
                    m4b_ok = False
                    for attempt in range(1, 3):
                        if attempt > 1:
                            print(f"[{job_id}] Retrying PCM->M4B (attempt {attempt})...")
                        if pcm_to_aac_m4b(
                            all_parts, final_m4b,
                            chapters=valid_m4b_ch or None,
                            title=info.title, author=info.author or None,
                            cover_path=cover_path,
                            date=getattr(info, "date", None),
                            language=getattr(info, "language", None),
                            description=getattr(info, "description", None),
                            gap_ms=gap_ms_inter,
                        ):
                            job["output_m4b"] = final_m4b
                            job["m4b_failed"] = False
                            m4b_ok = True
                            break
                    if not m4b_ok:
                        job["m4b_failed"] = True
                        # Fallback: produci MP3 cosi' l'utente ha qualcosa
                        pcm_to_mp3(all_parts, final_mp3, gap_ms=gap_ms_inter)
                        print(f"[{job_id}] M4B failed, fallback MP3 produced: {final_mp3}")
            else:
                # Edge/Google: percorso storico (chunk MP3 -> concat MP3 -> eventuale M4B)
                final_mp3 = str(output_dir / f"{safe_name}.mp3")
                _concatenate_mp3(all_parts, final_mp3)
                print(f"[{job_id}] MP3 merged: {final_mp3}, "
                      f"size={os.path.getsize(final_mp3) if os.path.exists(final_mp3) else 0}")

            # Generate M4B too (skip for mp3-only format and for Gemini, which already handled it)
            if not use_gemini and output_format != 'mp3':
                final_m4b = str(output_dir / f"{safe_name}.m4b")
                job["progress_message"] = "Converting to M4B..."
                print(f"[{job_id}] Starting M4B conversion: {final_m4b}")
                # Cover hi-res: EPUB 1400x1400 → thumb esistente → branded fallback (PDF/TXT)
                cover_path = _prepare_m4b_cover_path(job, info.title, info.author, work_dir)
                valid_m4b_ch = [c for c in m4b_chapters if c.get("end", 0) > c.get("start", 0)]

                # Retry logic: max 2 attempts
                for attempt in range(1, 3):
                    try:
                        if attempt > 1:
                            print(f"[{job_id}] Retrying M4B generation (attempt {attempt})...")

                        if _convert_mp3_to_m4b(final_mp3, final_m4b,
                                               chapters=valid_m4b_ch or None,
                                               title=info.title, author=info.author or None,
                                               cover_path=cover_path,
                                               date=getattr(info, "date", None),
                                               language=getattr(info, "language", None),
                                               description=getattr(info, "description", None)):
                            job["output_m4b"] = final_m4b
                            job["m4b_failed"] = False
                            break # Success!
                        else:
                            raise Exception("Conversion returned False")
                    except Exception as e:
                        print(f"[{job_id}] M4B conversion attempt {attempt} failed: {e}")
                        if attempt == 2:
                            job["m4b_failed"] = True
                            if os.path.exists(final_m4b):
                                try: os.remove(final_m4b)
                                except OSError: pass

            for p in all_parts:
                if os.path.exists(p) and p != silence_path:
                    os.remove(p)

            if output_format == 'm4b' and job.get("output_m4b"):
                # When the user requested M4B and conversion succeeded, the intermediate
                # MP3 is no longer needed: drop it to reclaim disk (a 500MB book stores
                # MP3 + M4B = ~1GB otherwise). For Gemini there is no intermediate MP3.
                if not use_gemini and os.path.exists(final_mp3):
                    try:
                        mp3_size = os.path.getsize(final_mp3)
                        os.remove(final_mp3)
                        print(f"[{job_id}] Removed intermediate MP3 ({mp3_size} bytes) — M4B is the served format")
                    except OSError as e:
                        print(f"[{job_id}] Could not remove intermediate MP3: {e}")
                job["output_files"] = [job["output_m4b"]]
                job["output_name"] = f"{safe_name}.m4b"
                if os.path.exists(job["output_m4b"]):
                    job["bytes_generated"] = os.path.getsize(job["output_m4b"])
            else:
                # Per Gemini in modalita' m4b senza output_m4b (fallback dopo failure) usa MP3.
                # Per Edge/Google segue il percorso storico.
                if os.path.exists(final_mp3):
                    job["output_files"] = [final_mp3]
                    job["bytes_generated"] = os.path.getsize(final_mp3)
                else:
                    job["output_files"] = []
                if job.get("output_m4b"):
                    job["output_name"] = f"{safe_name}.m4b"
                else:
                    job["output_name"] = f"{safe_name}.mp3"

            # Log roll-up Gemini usage (record_usage gia' chiamato per chunk)
            if use_gemini:
                print(f"[{job_id}] Gemini usage total: model={gemini_usage['model_key']} "
                      f"input_tok={gemini_usage['input_tokens']} "
                      f"output_tok={gemini_usage['output_tokens']}")
        else:
            mp3_files = []
            m4b_chapters = []
            current_ms = 0
            current_chapter_parts = []
            current_chapter_idx = -1
            failed_chunks = 0
            chapter_by_idx = {ch.index: ch for ch in info.chapters}
            output_num_by_idx = {ch.index: pos + 1 for pos, ch in enumerate(info.chapters)}
            for i, block in enumerate(plan):
                if _check_cancelled():
                    raise _CancelledError("Job cancelled")
                _update_progress(i, block)
                # Periodic progress logging ogni 10 chunk (multi-file)
                if i > 0 and (i % 10 == 0 or i == total_chunks - 1):
                    pct = (i + 1) / total_chunks * 100
                    print(f"[{job_id}] Progress: chunk {i+1}/{total_chunks} "
                          f"({pct:.0f}%), failed_chunks={failed_chunks}, "
                          f"elapsed={time.time()-start_time:.0f}s")
                if block["chapter_index"] != current_chapter_idx:
                    if current_chapter_parts and current_chapter_idx >= 0:
                        ch = chapter_by_idx[current_chapter_idx]
                        safe_title = _safe_filename(ch.title)[:50] or f"ch_{current_chapter_idx}"
                        out_num = output_num_by_idx.get(current_chapter_idx, current_chapter_idx)
                        mp3_path = str(output_dir / f"{out_num:03d}_{safe_title}.mp3")
                        if use_gemini:
                            pcm_to_mp3(current_chapter_parts, mp3_path, gap_ms=gap_ms_inter)
                        else:
                            _concatenate_mp3(current_chapter_parts, mp3_path)
                        mp3_files.append(mp3_path)

                        duration = _get_audio_duration_ms(mp3_path)
                        m4b_chapters.append({
                            "title": ch.title,
                            "start": current_ms,
                            "end": current_ms + duration
                        })
                        current_ms += duration

                        for p in current_chapter_parts:
                            if os.path.exists(p) and p != silence_path:
                                os.remove(p)
                    current_chapter_parts = []
                    current_chapter_idx = block["chapter_index"]
                    # Silenzio all'inizio del capitolo
                    if os.path.exists(silence_path):
                        current_chapter_parts.append(silence_path)

                if use_gemini:
                    part_path = str(work_dir / f"chunk_{i:06d}.pcm")
                    debug_prompt_path = str(work_dir / f"prompt{i+1}.txt")
                    # Applichiamo lo stile a TUTTI i chunk: limitarlo al primo
                    # chunk del capitolo (vecchio design cost-saving) faceva
                    # percepire all'utente uno stile diverso tra preview (1 chunk,
                    # sempre con stile) e job finale (1 chunk su N con stile).
                    # Il costo dei token aggiuntivi e` trascurabile (~315 char di
                    # prefix x N chunk: pochi millicent per libro tipico).
                    style_for_chunk = gemini_style_instruction
                    try:
                        result = generate_chunk_pcm_gemini(block["text"], voice, part_path,
                                                           style_instruction=style_for_chunk,
                                                           rate=rate,
                                                           debug_prompt_path=debug_prompt_path)
                    except Exception as _quota_or_budget_err:
                        # GeminiQuotaExhausted / GeminiBudgetExceeded: meglio
                        # marcare il job come paused/error che silenziare il resto
                        # del libro. Salviamo lo stato e usciamo dal loop chunk.
                        if gemini_tts is not None and isinstance(_quota_or_budget_err,
                                                                  (gemini_tts.GeminiQuotaExhausted,
                                                                   gemini_tts.GeminiBudgetExceeded)):
                            retry_after = getattr(_quota_or_budget_err, "retry_after_sec", None)
                            reason = getattr(_quota_or_budget_err, "reason",
                                             getattr(_quota_or_budget_err, "scope", "quota"))
                            job["gemini_paused"] = True
                            job["gemini_pause_reason"] = reason
                            job["gemini_pause_retry_after_sec"] = retry_after
                            job["gemini_pause_message"] = str(_quota_or_budget_err)
                            print(f"[{job_id}] Gemini paused at chunk {i}/{total_chunks}: "
                                  f"reason={reason} retry_after={retry_after}s. "
                                  f"Err: {str(_quota_or_budget_err)[:200]}")
                            raise
                        # Errore generico non quota-related: rilancia
                        raise
                    if result is False:
                        failed_chunks += 1
                    else:
                        gemini_usage["input_tokens"] += result.get("input_tokens", 0)
                        gemini_usage["output_tokens"] += result.get("output_tokens", 0)
                        if not gemini_usage["model_key"]:
                            gemini_usage["model_key"] = result.get("model_key")
                        ga = job["gemini_actual"]
                        ga["input_tokens"] += result.get("input_tokens", 0)
                        ga["output_tokens"] += result.get("output_tokens", 0)
                        ga["chars"] += len(block["text"])
                        bw = result.get("bytes_written", 0)
                        ga["audio_seconds"] += bw / (24000.0 * 2)
                        model_key_local = result.get("model_key", "flash25")
                        if not ga["model_key"]:
                            ga["model_key"] = model_key_local
                        chunk_google_cost_eur = 0.0
                        if gemini_tts is not None:
                            try:
                                bd = gemini_tts.google_cost_breakdown(
                                    result.get("input_tokens", 0),
                                    result.get("output_tokens", 0),
                                    model_key_local,
                                )
                                chunk_google_cost_eur = float(bd.get("total_eur", 0.0) or 0.0)
                                ga["google_cost_eur"] += chunk_google_cost_eur
                            except Exception as e:
                                print(f"[{job_id}] google_cost_breakdown failed (non-fatal): {e}")
                        if gemini_tts is not None:
                            try:
                                gemini_tts.record_usage(
                                    result.get("model_key", "flash25"),
                                    len(block["text"]),
                                    result.get("input_tokens", 0),
                                    result.get("output_tokens", 0),
                                    chunk_google_cost_eur,
                                    0.0,
                                )
                            except Exception as e:
                                print(f"[{job_id}] gemini_tts.record_usage failed (non-fatal): {e}")
                            # Empirical rate sample — vedi commento branch single-file
                            # sopra per la motivazione del fallback _audit_language.
                            try:
                                _lang = (_audit_language(job, info) or "it")[:2]
                                _norm_chars = len(gemini_tts._normalize_text(block["text"]))
                                _audio_secs = result.get("audio_seconds_real")
                                if _audio_secs is None:
                                    _audio_secs = result.get("bytes_written", 0) / (24000.0 * 2)
                                gemini_tts.record_rate_sample(
                                    _norm_chars, _audio_secs, _lang,
                                    result.get("model_key", "flash25"),
                                    rate_pct=rate,
                                )
                            except Exception as e:
                                print(f"[{job_id}] gemini_tts.record_rate_sample failed (non-fatal): {e}")

                        # Trim trailing silence dal PCM Gemini (idem single-file branch).
                        if gemini_tts is not None:
                            try:
                                _trim_cap = gemini_tts.trim_tail_ms()
                                _trim_thr = gemini_tts.trim_tail_threshold()
                                if _trim_cap > 0:
                                    trim_pcm_trailing_silence(
                                        part_path, threshold=_trim_thr, max_trim_ms=_trim_cap,
                                    )
                            except Exception as _e_trim:
                                print(f"[{job_id}] trim_pcm_trailing_silence failed (non-fatal): {_e_trim}")
                else:
                    part_path = str(work_dir / f"chunk_{i:06d}.mp3")
                    if use_google:
                        result = generate_chunk_mp3_google(block["text"], voice, rate, part_path)
                    else:
                        try:
                            result = loop.run_until_complete(generate_chunk_mp3(block["text"], voice, rate, part_path))
                        except Exception as _edge_err:
                            print(f"[{job_id}] edge-tts chunk {i} crashed (multi-file): {_edge_err}")
                            import traceback
                            traceback.print_exc()
                            _generate_silence_mp3(part_path, duration_sec=1)
                            result = False
                    if result is False:
                        failed_chunks += 1
                current_chapter_parts.append(part_path)

                # Log sul primo chunk per confermare che il TTS sta procedendo
                if i == 0:
                    print(f"[{job_id}] First chunk done (multi-file): {part_path}, "
                          f"size={os.path.getsize(part_path) if os.path.exists(part_path) else 0}, "
                          f"failed={failed_chunks}")

                job["processed_chars"] += block["chars"]
                if os.path.exists(part_path):
                    job["bytes_generated"] += os.path.getsize(part_path)

            print(f"[{job_id}] All chunks processed (multi-file): {total_chunks} total, {failed_chunks} failed, {len(mp3_files)} chapters assembled")

            if current_chapter_parts and current_chapter_idx >= 0:
                ch = chapter_by_idx[current_chapter_idx]
                safe_title = _safe_filename(ch.title)[:50] or f"ch_{current_chapter_idx}"
                out_num = output_num_by_idx.get(current_chapter_idx, current_chapter_idx)
                mp3_path = str(output_dir / f"{out_num:03d}_{safe_title}.mp3")
                if use_gemini:
                    pcm_to_mp3(current_chapter_parts, mp3_path, gap_ms=gap_ms_inter)
                else:
                    _concatenate_mp3(current_chapter_parts, mp3_path)
                mp3_files.append(mp3_path)

                duration = _get_audio_duration_ms(mp3_path)
                m4b_chapters.append({
                    "title": ch.title,
                    "start": current_ms,
                    "end": current_ms + duration
                })
                current_ms += duration

                for p in current_chapter_parts:
                    if os.path.exists(p) and p != silence_path:
                        os.remove(p)

            job["progress_message"] = "Creating ZIP..."
            safe_name = _safe_filename(info.title) or "audiolibro"

            # Include book cover in ZIP if available
            _include_cover_in_dir(job, output_dir)

            # Generate RSS XML for zip_rss format (before ZIP so it gets included)
            if output_format == 'zip_rss':
                try:
                    rss_fname = "podcast.xml"
                    rss_path = str(output_dir / rss_fname)
                    cover_file = ""
                    for _ext in ("jpg", "jpeg", "png"):
                        _candidate = output_dir / f"cover.{_ext}"
                        if _candidate.exists():
                            cover_file = _candidate.name
                            break
                    _generate_podcast_rss(info, mp3_files, rss_path,
                                          base_url=podcast_base_url,
                                          cover_filename=cover_file,
                                          rss_filename=rss_fname)
                    print(f"[{job_id}] RSS XML embedded in ZIP ({rss_fname})")
                    job["podcast_rss_included"] = True
                except Exception as e:
                    print(f"[{job_id}] RSS generation failed (non-fatal): {e}")

            # Build ZIP outside output_dir (make_archive can't write inside its
            # source), then move it inside so cleanup per-epoch handles it.
            _zip_tmp = shutil.make_archive(str(work_dir / f"_zip_{my_epoch}"), "zip", str(output_dir))
            zip_path = str(output_dir / f"{safe_name}.zip")
            shutil.move(_zip_tmp, zip_path)
            job["output_files"] = mp3_files
            job["output_name"] = f"{safe_name}.zip"
            job["output_zip"] = zip_path

            # Storage cleanup: per output_format zip / zip_rss i singoli MP3 sono
            # gia' contenuti nello ZIP (duplicazione completa su disco). Verifichiamo
            # integrita' dello ZIP, poi rimuoviamo i sorgenti per liberare spazio.
            # Per zip_rss richiediamo anche l'embed RSS riuscito: senza, il fallback
            # in /api/download_podcast ricostruisce lo ZIP dai singoli MP3.
            if output_format in ('zip', 'zip_rss'):
                _purge_ok = False
                try:
                    import zipfile as _zf_check
                    _purge_ok = (os.path.exists(zip_path)
                                 and os.path.getsize(zip_path) > 0
                                 and _zf_check.is_zipfile(zip_path))
                except Exception as _e_zfchk:
                    print(f"[{job_id}] ZIP integrity check failed: {_e_zfchk}")
                if output_format == 'zip_rss' and not job.get("podcast_rss_included"):
                    _purge_ok = False
                if _purge_ok:
                    _freed_bytes = 0
                    _purged_count = 0
                    for _mp3 in mp3_files:
                        try:
                            if os.path.exists(_mp3):
                                _freed_bytes += os.path.getsize(_mp3)
                                os.remove(_mp3)
                                _purged_count += 1
                        except OSError as _e_rm:
                            print(f"[{job_id}] Cleanup MP3 skip {_mp3}: {_e_rm}")
                    print(f"[{job_id}] ZIP cleanup: rimossi {_purged_count}/{len(mp3_files)} "
                          f"MP3 individuali ({_freed_bytes} byte liberati) — "
                          f"contenuto preservato in {os.path.basename(zip_path)}")

            # background M4B generation even in ZIP mode (skip for mp3, zip and zip_rss formats)
            if output_format not in ('mp3', 'zip', 'zip_rss'):
                try:
                    # Concatenate all MP3s into one for M4B conversion
                    temp_full_mp3 = str(work_dir / f"_full_temp_{my_epoch}.mp3")
                    _concatenate_mp3(mp3_files, temp_full_mp3)
                    final_m4b = str(output_dir / f"{safe_name}.m4b")
                    cover_path = _prepare_m4b_cover_path(job, info.title, info.author, work_dir)

                    for attempt in range(1, 3):
                        if _convert_mp3_to_m4b(temp_full_mp3, final_m4b,
                                               chapters=m4b_chapters or None,
                                               title=info.title, author=info.author or None,
                                               cover_path=cover_path):
                            job["output_m4b"] = final_m4b
                            job["m4b_failed"] = False
                            break
                        else:
                            if attempt == 2: job["m4b_failed"] = True

                    if os.path.exists(temp_full_mp3):
                        os.remove(temp_full_mp3)
                except Exception as e:
                    print(f"[{job_id}] Background M4B generation failed: {e}")
                    job["m4b_failed"] = True

            # Flag: podcast available (RSS included in ZIP for zip_rss; downloadable separately)
            job["podcast_ready"] = (output_format == 'zip_rss')
            job["podcast_info"] = info
            job["podcast_mp3s"] = mp3_files
            job["podcast_safe_name"] = safe_name

        # Cleanup silence file
        if os.path.exists(silence_path):
            os.remove(silence_path)

        # Sweep intermedi per-chunk rimasti in work_dir dopo l'assembly.
        # Il loop su all_parts (single-file) e su current_chapter_parts (multi-file)
        # rimuove i chunk audio, ma NON i file di debug per-chunk (prompt{i}.txt di
        # Gemini, .part*.txt/.pcm di tts_split) ne' eventuali chunk residui di un
        # branch interrotto. I file di output finali vivono in output_dir (subdir),
        # quindi una glob non-ricorsiva sul livello di work_dir non li tocca.
        try:
            for _pattern in ("chunk_*", "prompt*.txt", "*.filelist.txt"):
                for _leftover in work_dir.glob(_pattern):
                    if _leftover.is_file():
                        try:
                            os.remove(_leftover)
                        except OSError as _e_rm:
                            print(f"[{job_id}] sweep leftover skip {_leftover.name}: {_e_rm}")
        except Exception as _e_sweep:
            print(f"[{job_id}] work_dir leftover sweep failed (non-fatal): {_e_sweep}")

        # Caratteri Google TTS: sistema delta tra prenotato e consumato
        if use_google:
            reserved = job.get("google_tts_reserved", 0)
            consumed = job.get("processed_chars", 0)
            if reserved > consumed:
                _google_tts.refund_chars(reserved - consumed)
                print(f"[{job_id}] Google TTS: refunded {reserved - consumed} chars "
                      f"(reserved {reserved}, consumed {consumed})")
            elif consumed > reserved:
                _google_tts.deduct_chars(consumed - reserved)
                print(f"[{job_id}] Google TTS: extra deduction {consumed - reserved} chars")
            _invalidate_voices_cache()

        total_elapsed = time.time() - start_time
        job["progress_current"] = job["progress_total"]
        job["elapsed_seconds"] = round(total_elapsed)
        job["completed_at"] = time.time()
        job["last_poll"] = time.time()
        job["failed_chunks"] = failed_chunks
        # Calcolo ratio chunk falliti per decidere se il job e' "done" oppure "partial".
        # Soglia configurabile via ABM_GEMINI_MAX_FAILED_RATIO (default 5%).
        try:
            _max_failed_ratio = float(os.environ.get("ABM_GEMINI_MAX_FAILED_RATIO", "0.05"))
        except (TypeError, ValueError):
            _max_failed_ratio = 0.05
        # Soglia per refund automatico su engine Gemini: se la frazione di
        # chunk silenziati supera questo valore, il job e' considerato fallito
        # (refund + notifica) invece di consegnato parziale. Default 0.0 =
        # qualsiasi chunk silenziato innesca il refund. Disabilita con un valore
        # > 1 (es. 2.0).
        try:
            _refund_failed_ratio = float(os.environ.get("ABM_GEMINI_REFUND_FAILED_RATIO", "0.0"))
        except (TypeError, ValueError):
            _refund_failed_ratio = 0.0
        _tot_chunks_safe = max(1, int(total_chunks))
        _fail_ratio = failed_chunks / _tot_chunks_safe
        job["failed_chunks_ratio"] = round(_fail_ratio, 4)
        job["total_chunks"] = _tot_chunks_safe
        # Auto-refund su qualita' insufficiente (chunk silenziati sopra soglia).
        # Applicato solo su engine Gemini, dove il fallback a silenzio non
        # rappresenta l'output che l'utente ha pagato.
        if use_gemini and failed_chunks > 0 and _fail_ratio > _refund_failed_ratio:
            _set_job_status(job, "error")
            _user_msg = (
                f"Generazione interrotta: {failed_chunks}/{_tot_chunks_safe} segmenti "
                f"({_fail_ratio:.1%}) non sintetizzati correttamente. L'audio risultante "
                f"sarebbe stato incompleto: rimborso integrale gia' emesso."
            )
            job["error"] = _user_msg
            job["user_facing_error"] = _user_msg
            job["failed_chunks_ratio"] = round(_fail_ratio, 4)
            print(f"[{job_id}] Gemini job FAILED for quality "
                  f"({failed_chunks}/{_tot_chunks_safe}={_fail_ratio:.1%}) "
                  f"-> full refund triggered.")
            try:
                _write_gemini_audit(job_id, job, voice,
                                    _audit_language(job, info),
                                    "failed_quality_refunded")
            except Exception:
                pass
            try:
                _refund_gemini_payment(job_id, job, f"quality_failed: {failed_chunks}/{_tot_chunks_safe}")
            except Exception as _ref_err:
                print(f"[{job_id}] Refund failed (non-fatal): {_ref_err}")
            try:
                _notify_user_gemini_job_failed(job_id, job, "quality_failed",
                                               failure_kind="quality")
            except Exception as _notif_err:
                print(f"[{job_id}] User notification failed (non-fatal): {_notif_err}")
            _admin_alert_gemini_failure(
                job_id, job, kind="quality",
                audit_outcome="failed_quality_refunded",
                reason_detail=f"{failed_chunks}/{_tot_chunks_safe} chunk silenziati ({_fail_ratio:.1%})",
                chunks_total=_tot_chunks_safe, chunks_failed=failed_chunks,
            )
            return

        # Guardia output: un assembly fallito (es. ENOSPC / disco pieno, errore
        # ffmpeg) puo' lasciare il job SENZA alcun file pur con failed_chunks=0
        # (i chunk TTS sono andati, ma il merge finale PCM->M4B/MP3 no). Senza
        # questo check il job verrebbe marcato "done" con output vuoto, con
        # conseguenze a cascata: email con link rotti, snapshot token vuoto,
        # /api/download in 500, e cleanup aggressivo che cancella la cartella.
        # Lo trattiamo come fallimento: status error + rimborso integrale.
        def _job_has_output():
            if job.get("output_m4b") and os.path.exists(job["output_m4b"]):
                return True
            for _f in (job.get("output_files") or []):
                if _f and os.path.exists(_f):
                    return True
            if job.get("output_zip") and os.path.exists(job["output_zip"]):
                return True
            return False

        if not _job_has_output():
            _set_job_status(job, "error")
            _user_msg = (
                "Generazione interrotta: impossibile salvare il file audio finale "
                "(spazio su disco insufficiente o errore di conversione). "
                "Nessun file e' stato prodotto: rimborso integrale gia' emesso."
            )
            job["error"] = _user_msg
            job["user_facing_error"] = _user_msg
            print(f"[{job_id}] EMPTY OUTPUT after assembly "
                  f"(failed_chunks={failed_chunks}, output_format={output_format}, "
                  f"m4b_failed={job.get('m4b_failed')}) -> error + refund.")
            if use_gemini:
                try:
                    _write_gemini_audit(job_id, job, voice,
                                        _audit_language(job, info),
                                        "failed_no_output_refunded")
                except Exception:
                    pass
                try:
                    _refund_gemini_payment(job_id, job, "no_output: assembly failed")
                except Exception as _ref_err:
                    print(f"[{job_id}] Refund failed (non-fatal): {_ref_err}")
                try:
                    _notify_user_gemini_job_failed(job_id, job, "no_output",
                                                   failure_kind="generic")
                except Exception as _notif_err:
                    print(f"[{job_id}] User notification failed (non-fatal): {_notif_err}")
                try:
                    _admin_alert_gemini_failure(
                        job_id, job, kind="generic",
                        audit_outcome="failed_no_output_refunded",
                        reason_detail="empty output after assembly (disk full / ffmpeg error)",
                        chunks_total=_tot_chunks_safe, chunks_failed=failed_chunks,
                    )
                except Exception:
                    pass
            else:
                try:
                    _refund_job_payment(job_id, job, "no_output")
                except Exception as _ref_err:
                    print(f"[{job_id}] Refund failed (non-fatal): {_ref_err}")
            return

        _is_partial = _fail_ratio > _max_failed_ratio
        if _is_partial:
            job["status_partial_reason"] = (
                f"failed_chunks_ratio={_fail_ratio:.1%} exceeds threshold "
                f"{_max_failed_ratio:.1%}"
            )
            job["progress_message"] = (
                f"Completato parzialmente: {failed_chunks}/{_tot_chunks_safe} chunk falliti "
                f"({_fail_ratio:.1%})"
            )
            print(f"[{job_id}] PARTIAL: {job['status_partial_reason']}")
        elif failed_chunks > 0:
            job["progress_message"] = f"Done! ({failed_chunks} chunk(s) skipped due to TTS errors)"
            print(f"[{job_id}] Completed with {failed_chunks} failed chunk(s) "
                  f"(ratio {_fail_ratio:.1%} <= {_max_failed_ratio:.1%})")
        else:
            job["progress_message"] = "Done!"

        # Snapshot the .abm into this epoch's output_dir so it is preserved
        # alongside the audio files. Always regenerate (even if a previous
        # optimization-phase ABM exists at work_dir root) so the snapshot
        # reflects the current optimized_chapters state and ends up inside
        # the per-epoch folder.
        if job.get("ai_optimized"):
            try:
                abm_path, abm_name = _generate_optimized_abm(job_id)
                job["optimized_abm_path"] = abm_path
                job["optimized_abm_name"] = abm_name
                print(f"[{job_id}] .abm snapshot in {abm_path}")
            except Exception as e:
                print(f"[{job_id}] Failed to write .abm: {e}")
                job["abm_generation_error"] = str(e)

        _set_job_status(job, "partial" if _is_partial else "done")
        _log_activity(job_id, job.get("original_filename", ""), "COMPLETE",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))

        # Offload asincrono su cold storage (se configurato). I file restano
        # serviti da locale per tutta la finestra calda; l'upload gira intanto.
        try:
            _spawn_cloud_offload(job_id, job.get("output_dir", ""))
        except Exception as e:
            print(f"[{job_id}] cloud offload spawn error: {e}", flush=True)

        if use_gemini:
            _write_gemini_audit(job_id, job, voice, _audit_language(job, info), "completed")

        # Send email notification if user registered
        notify_email = job.get("notify_email")
        if not notify_email:
            # Fallback: cerca email precedentemente registrata per lo stesso client
            _cid = job.get("client_id", "")
            if _cid:
                notify_email = _lookup_client_email(_cid)
                if notify_email:
                    job["notify_email"] = notify_email
                    print(f"[{job_id}] post-COMPLETE: using fallback email "
                          f"from client_id {_cid}", flush=True)
        if notify_email:
            print(f"[{job_id}] post-COMPLETE: triggering email to {notify_email}", flush=True)
            try:
                _send_completion_email(job_id)
            except Exception as e:
                import traceback
                print(f"[{job_id}] Email notification error: {e}", flush=True)
                traceback.print_exc()
                try:
                    _log_activity(job_id, job.get("original_filename", ""), "EMAIL_FAILED",
                                  job.get("client_id", ""), job.get("client_ip", ""),
                                  job.get("voice", ""), job.get("browser_lang", ""))
                except Exception:
                    pass
        else:
            print(f"[{job_id}] post-COMPLETE: no notify_email "
                  f"(email_registered={job.get('email_registered')})", flush=True)
            try:
                _log_activity(job_id, job.get("original_filename", ""), "EMAIL_SKIPPED_BRANCH",
                              job.get("client_id", ""), job.get("client_ip", ""),
                              job.get("voice", ""), job.get("browser_lang", ""))
            except Exception:
                pass

    except _CancelledError:
        still_current = job.get("gen_epoch", 0) == my_epoch
        partial_audio_delivered = False
        partial_download_url = None

        if still_current and use_gemini:
            try:
                actual = job.get("gemini_actual") or {}
                google_cost = float(actual.get("google_cost_eur", 0.0) or 0.0)
                payment_meta = job.get("payment") or {}
                paid = float(payment_meta.get("total_eur", 0) or 0)
                method = payment_meta.get("method", "")

                # Margin (ricarico) del modello: il trattenuto corrisponde al
                # PREZZO che l'utente avrebbe pagato per la quota di lavoro
                # eseguita, non al solo costo Google. Mantiene la stessa
                # marginalita' commerciale del job completato.
                margin_pct = 0.0
                try:
                    if voice and gemini_tts is not None and voice.startswith("gemini:"):
                        _mk, _, _ = gemini_tts.parse_voice_id(voice)
                        margin_pct = float(gemini_tts.get_margin_percent(_mk) or 0.0)
                except Exception as _mp_err:
                    print(f"[{job_id}] margin lookup failed (using 0%): {_mp_err}")

                cr = cancel_policy.compute_cancel_retention(
                    google_cost, method, paid, margin_percent=margin_pct)
                retained = cr["retained_eur"]
                refund = cr["refund_eur"]

                # Encoding MP3 parziale (best-effort)
                try:
                    pcm_files = []
                    if work_dir.exists():
                        pcm_files = sorted(work_dir.glob("chunk_*.pcm"))
                        pcm_files = [str(p) for p in pcm_files if p.stat().st_size > 0]
                    if pcm_files:
                        partial_mp3 = output_dir / f"{job_id}_partial.mp3"
                        output_dir.mkdir(parents=True, exist_ok=True)
                        gap = gemini_tts.inter_chunk_gap_ms() if gemini_tts is not None else 100
                        ok = pcm_to_mp3(pcm_files, str(partial_mp3), gap_ms=gap)
                        if ok and partial_mp3.exists() and partial_mp3.stat().st_size > 0:
                            partial_audio_delivered = True
                            token = str(uuid.uuid4())
                            _download_tokens[token] = {
                                "job_id": job_id,
                                "created_at": time.time(),
                                "download_type": "audio",
                                "output_file": str(partial_mp3),
                                "output_format": "mp3",
                                "book_title": (getattr(info, "title", "") or
                                               job.get("original_filename", "")),
                                "original_filename": job.get("original_filename", ""),
                                "lang": job.get("browser_lang", "en"),
                                "is_gemini": True,
                                "partial_cancel": True,
                            }
                            _save_tokens()
                            partial_download_url = (f"{BASE_URL}/dl/{token}/download"
                                                     if BASE_URL else f"/dl/{token}/download")
                            job["partial_download_url"] = partial_download_url
                            job["partial_download_token"] = token
                except Exception as enc_err:
                    print(f"[{job_id}] Cancel partial encoding failed (non-fatal): {enc_err}")

                progress_pct = _progress_pct(job)
                job["cancel_meta"] = {
                    "paid_eur": round(paid, 2),
                    "retained_eur": retained,
                    "refund_eur": refund,
                    "progress_pct": progress_pct,
                    "partial_audio_delivered": partial_audio_delivered,
                }

                outcome = "cancelled_partial" if retained > 0 else "cancelled_refunded"
                _write_gemini_audit(job_id, job, voice,
                                    _audit_language(job, info), outcome)

                refund_result = _refund_gemini_payment(
                    job_id, job, "cancelled", retained_eur=retained)

                if (refund_result and refund_result.get("email")
                        and partial_audio_delivered
                        and hasattr(email_service, "_send_gemini_cancelled_partial_email")):
                    try:
                        email_service._send_gemini_cancelled_partial_email(
                            email=refund_result["email"],
                            paid_eur=round(paid, 2),
                            retained_eur=retained,
                            refund_eur=refund,
                            voucher_code=refund_result.get("voucher_code"),
                            book_title=(getattr(info, "title", "") or
                                        job.get("original_filename", "")),
                            download_url=partial_download_url,
                            lang=job.get("browser_lang", "it"),
                        )
                    except Exception as e:
                        print(f"[{job_id}] cancel partial email failed: {e}")
            except Exception as cancel_err:
                print(f"[{job_id}] Cancel partial flow error (fallback to legacy): {cancel_err}")
                try:
                    _write_gemini_audit(job_id, job, voice,
                                        _audit_language(job, info),
                                        "cancelled_refunded")
                except Exception:
                    pass
                try:
                    _refund_gemini_payment(job_id, job, "cancelled", retained_eur=0.0)
                except Exception:
                    pass
        elif use_gemini and not still_current:
            print(f"[{job_id}] Gemini cancel STALE - no refund/audit")

        if use_google:
            _google_tts_refund_unused(job_id, job)

        if still_current:
            _set_job_status(job, "analyzed")
            job["progress_message"] = "Cancelled"
            try:
                if work_dir.exists():
                    # Conserva l'MP3 parziale finche' il token download e' vivo:
                    # rimuoviamo solo i PCM/sub-dir intermedi, non output_dir.
                    for p in work_dir.glob("chunk_*.pcm"):
                        try: p.unlink()
                        except OSError: pass
                    for p in work_dir.glob("prompt*.txt"):
                        try: p.unlink()
                        except OSError: pass
                    sil = work_dir / "_silence.pcm"
                    if sil.exists():
                        try: sil.unlink()
                        except OSError: pass
                    # Se NON e' stato consegnato audio parziale, rimuovi tutta la work_dir.
                    if not partial_audio_delivered:
                        shutil.rmtree(str(work_dir), ignore_errors=True)
            except Exception:
                pass

        print(f"[{job_id}] Generation cancelled, resources freed"
              f"{' (stale)' if not still_current else ''}.")
        _log_activity(job_id, job.get("original_filename", ""), "CANCEL",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))

    except BaseException as e:
        # SystemExit/KeyboardInterrupt devono propagare — non sopprimerli.
        if isinstance(e, (SystemExit, KeyboardInterrupt)):
            raise

        # Marker forense: preserva la work_dir per analisi post-mortem
        # anche se il codice di cleanup successivo dovesse fallire.
        _write_forensic_marker(
            job_id,
            kind="silent_death",
            outcome="error",
            reason_detail=f"{type(e).__name__}: {str(e)[:300]}",
        )
        print(f"[{job_id}] FORENSIC: silent thread death — "
              f"{type(e).__name__}: {e}")

        # Quota Gemini (RPD/daily) e budget guard interno: il job e' interrotto
        # a meta'. L'audio parziale non viene consegnato, quindi l'operazione e'
        # da considerare FALLITA per l'utente -> refund integrale + notifica.
        _is_quota = False
        _is_budget = False
        if use_gemini and gemini_tts is not None:
            try:
                _is_quota = isinstance(e, gemini_tts.GeminiQuotaExhausted)
                _is_budget = isinstance(e, gemini_tts.GeminiBudgetExceeded)
            except Exception:
                _is_quota = False
                _is_budget = False
        if _is_quota or _is_budget:
            pause_reason = getattr(e, "reason",
                                   getattr(e, "scope",
                                           "budget" if _is_budget else "quota"))
            retry_after = getattr(e, "retry_after_sec", None)
            # Salviamo i campi pause_* per diagnostica (UI/log) ma marchiamo
            # il job come ERROR: l'utente vede l'operazione fallita e riceve
            # rimborso completo (i chunk prodotti non sono consegnabili).
            job["gemini_paused"] = True
            job["gemini_pause_reason"] = pause_reason
            job["gemini_pause_retry_after_sec"] = retry_after
            job["gemini_pause_message"] = str(e)
            _set_job_status(job, "error")
            if _is_quota:
                _user_msg = ("Generazione interrotta: quota giornaliera del "
                             "servizio voci PREMIUM esaurita. Hai diritto al "
                             "rimborso integrale, gia' emesso automaticamente.")
            else:
                _user_msg = ("Generazione interrotta: limite di spesa "
                             "raggiunto. Hai diritto al rimborso integrale, "
                             "gia' emesso automaticamente.")
            job["error"] = _user_msg
            job["user_facing_error"] = _user_msg
            try:
                _write_gemini_audit(job_id, job, voice,
                                    _audit_language(job, info),
                                    "failed_quota_refunded" if _is_quota
                                    else "failed_budget_refunded")
            except Exception:
                pass
            print(f"[{job_id}] Gemini job FAILED for {pause_reason} "
                  f"(retry_after={retry_after}s) -> full refund triggered.")
            try:
                _refund_gemini_payment(job_id, job,
                                       f"quota_exhausted: {pause_reason}"
                                       if _is_quota
                                       else f"budget_exceeded: {pause_reason}")
            except Exception as _ref_err:
                print(f"[{job_id}] Refund failed (non-fatal): {_ref_err}")
            # Notifica esplicita all'utente che ha pagato il job (oltre al
            # voucher gia' inviato per PayPal da _refund_gemini_payment).
            try:
                _notify_user_gemini_job_failed(job_id, job, pause_reason,
                                               is_quota=_is_quota)
            except Exception as _notif_err:
                print(f"[{job_id}] User notification failed (non-fatal): {_notif_err}")
            _admin_alert_gemini_failure(
                job_id, job,
                kind="quota" if _is_quota else "budget",
                audit_outcome="failed_quota_refunded" if _is_quota
                              else "failed_budget_refunded",
                reason_detail=f"{pause_reason} | retry_after={retry_after}s | {str(e)[:200]}",
            )
            import traceback
            traceback.print_exc()
            return
        _set_job_status(job, "error")
        job["error"] = str(e)
        if use_gemini:
            _write_gemini_audit(job_id, job, voice, _audit_language(job, info), "failed_refunded")
            # F3: Refund the user payment (voucher or paypal) for failed Gemini job
            _refund_gemini_payment(job_id, job, f"failed: {e}")
            # Notifica utente con copy "qualita'" (errore generico, parziale non consegnabile)
            try:
                _notify_user_gemini_job_failed(job_id, job, f"generic_error: {e}",
                                               failure_kind="quality")
            except Exception as _notif_err:
                print(f"[{job_id}] User notification failed (non-fatal): {_notif_err}")
            _admin_alert_gemini_failure(
                job_id, job, kind="generic",
                audit_outcome="failed_refunded",
                reason_detail=f"{type(e).__name__}: {str(e)[:300]}",
            )
        # Refund caratteri Google TTS non consumati anche in caso di errore
        if use_google:
            try:
                _google_tts_refund_unused(job_id, job)
            except Exception as ref_err:
                print(f"[{job_id}] Refund error: {ref_err}")
        import traceback
        traceback.print_exc()
    finally:
        loop.close()
