"""tts_engines — registro dei motori TTS premium (E1d, 2026-10-09).

Un posto solo per cio' che prima ogni modulo chiedeva con una scala if/elif
sul prefisso della voce: cap caratteri/byte per chunk, normalizzazione
pre-split, sforamento di frase, sample rate del PCM, stima del costo,
writer di audit, eccezione "motore non disponibile", chiave della stima sul
job. `tts_split._pick_*`, `generation_engine._engine_for_voice` /
`_pcm_sample_rate` / `_PREMIUM_AUDIT` e i dispatch `estimate_book_cost` di
`audiobook_app` passano da qui.

Non e' una foglia: importa i moduli motore, ma in ritardo (`importlib`)
e a ogni chiamata, cosi' i test che sostituiscono `gemini_tts.X` & co. sono
visti anche da qui, e un motore senza credenziali non blocca l'import.
Edge non e' nel registro: `engine_for_voice` risponde "edge" e i chiamanti
tengono i loro default (MP3, 2000 caratteri, 24 kHz).
"""
import importlib
from dataclasses import dataclass

from voice_utils import engine_for_voice, is_gemini_voice, is_speechify_voice, is_voxcpm_voice


@dataclass(frozen=True)
class Engine:
    name: str
    module: str
    is_voice: object                 # voice_id -> bool
    estimate_key: str                # chiave della stima sul job
    audit_writer: str                # nome del writer in generation_engine
    unavailable_exc: str             # classe "motore non disponibile" nel modulo
    chunk_fallback: int              # cap caratteri se il modulo non risponde
    sample_rate_default: int
    sample_rate_job_key: str = ""    # Speechify: valore vero dal primo chunk
    sentence_slack: float = 0.0      # frazione di sforamento di una frase intera
    only_language: str = ""          # Speechify: solo inglese

    def mod(self):
        return importlib.import_module(self.module)

    def chunk_max_chars(self, language=None):
        """Cap caratteri per chunk (Gemini per lingua, gli altri globali)."""
        try:
            if self.name == "gemini":
                return self.mod().get_max_chunk_chars((language or "").lower().split("-")[0])
            return self.mod().chunk_max_chars()
        except Exception:
            return self.chunk_fallback

    def chunk_max_bytes(self):
        """Cap byte UTF-8 sul solo testo (Gemini), None per gli altri."""
        if self.name != "gemini":
            return None
        try:
            return int(self.mod().MAX_BYTES_PER_CALL)
        except Exception:
            return 700

    def pre_split(self):
        """Normalizzazione del testo intero prima del taglio (solo VoxCPM)."""
        if self.name != "voxcpm":
            return None
        try:
            return self.mod().prepara_capitolo
        except Exception:
            return None

    def sample_rate(self, job=None):
        """Sample rate del PCM in corso: Speechify lo rilegge dal job."""
        if self.sample_rate_job_key and isinstance(job, dict):
            return job.get(self.sample_rate_job_key, self.sample_rate_default)
        return self.sample_rate_default

    def is_available(self):
        try:
            return bool(self.mod().is_available())
        except Exception:
            return False

    def unavailable(self):
        """La classe di eccezione "motore non disponibile" del modulo."""
        return getattr(self.mod(), self.unavailable_exc)

    def estimate(self, chapters, voice=None, language=None, rate_pct=0):
        """`estimate_book_cost` del motore con la sua firma: Gemini vuole la
        voce e il rate, Speechify legge solo inglese, VoxCPM la lingua."""
        m = self.mod()
        if self.name == "gemini":
            return m.estimate_book_cost(chapters, voice, language=language or "it", rate_pct=rate_pct)
        if self.only_language:
            return m.estimate_book_cost(chapters, language=self.only_language)
        return m.estimate_book_cost(chapters, language=language or "it")


ENGINES = {
    "gemini": Engine("gemini", "gemini_tts", is_gemini_voice, "gemini_estimate", "_write_gemini_audit",
                     "GeminiUnavailable", chunk_fallback=700, sample_rate_default=24000),
    "speechify": Engine("speechify", "speechify_tts", is_speechify_voice, "speechify_estimate",
                        "_write_speechify_audit", "SpeechifyUnavailable", chunk_fallback=1800,
                        sample_rate_default=48000, sample_rate_job_key="speechify_sample_rate",
                        only_language="en"),
    # Il cap VoxCPM e' di qualita' (il timbro deriva sui chunk lunghi) e il
    # tetto vero e' allargato dallo sforamento di frase (280 x 1,15 = 322):
    # vedi il commento in tts_split._pick_sentence_slack.
    "voxcpm": Engine("voxcpm", "voxcpm_tts", is_voxcpm_voice, "voxcpm_estimate", "_write_voxcpm_audit",
                     "VoxcpmUnavailable", chunk_fallback=300, sample_rate_default=48000,
                     sentence_slack=0.15),
}
PREMIUM = tuple(ENGINES)


# `engine_for_voice(voice)` -> "gemini" / "speechify" / "voxcpm" / "edge" e'
# quello di voice_utils (B3), riesportato: il registro non ne tiene una copia.


def premium_for_voice(voice):
    """L'`Engine` premium della voce, None per Edge."""
    return ENGINES.get(engine_for_voice(voice))


def estimate(engine, chapters, voice=None, language=None, rate_pct=0):
    """Stima del costo per nome motore (comodo nei dispatch di audiobook_app)."""
    return ENGINES[engine].estimate(chapters, voice, language=language, rate_pct=rate_pct)


def unavailable_exceptions():
    """Le classi "motore non disponibile" dei motori importabili, per un
    `isinstance` unico nel path di errore di `run_generation`."""
    out = []
    for eng in ENGINES.values():
        try:
            out.append(eng.unavailable())
        except Exception:
            continue
    return tuple(out)
