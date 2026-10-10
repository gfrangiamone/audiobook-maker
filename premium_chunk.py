"""premium_chunk — sintesi di un chunk con i motori premium in PCM (F1d, 2026-10-10; prima in tts_split).

- `generate_chunk_pcm_gemini`: pre-split per frase, retry, modello e voce di
  ripiego, errori fatali di quota/budget (`_gemini_fatal`), ripiego su Edge in
  PCM (`_edge_fallback_to_pcm`, voce scelta per lingua/genere/accento);
- `generate_chunk_pcm_speechify`;
- `_generate_silence_pcm`, `_mp3_to_pcm_24k` (via `ffmpeg_tools`).

I moduli motore (`gemini_tts`, `speechify_tts`) restano importati tardi, come
prima. `tts_split` e `edge_engine` sono chiamati qualificati: i test che
sostituiscono `tts_split._pick_chunk_max_bytes` o `edge_engine.generate_chunk_mp3`
continuano a essere visti da qui.
"""
import asyncio
import os

import edge_engine
import ffmpeg_tools
import retry_util as _retry
import tts_split
from i18n import norm_lang as _norm_lang
from text_reflow import _sanitize_tts_text


def _gemini_fatal(mod):
    """Eccezioni di `mod` (gemini_tts, importato tardi dal chiamante) che non
    si ritentano e non si silenziano: il chiamante decide se sospendere il
    job."""
    return (mod.GeminiQuotaExhausted, mod.GeminiBudgetExceeded, mod.GeminiUnavailable)



_PCM_SAMPLE_RATE = ffmpeg_tools.PCM_SAMPLE_RATE      # 24000, i chunk Gemini
_PCM_CHANNELS = ffmpeg_tools.PCM_CHANNELS
_PCM_SAMPLE_WIDTH = ffmpeg_tools.PCM_SAMPLE_WIDTH    # 2 byte per campione (16-bit)


def _generate_silence_pcm(output_path, duration_sec=1, sample_rate=None):
    """Scrive N secondi di silenzio PCM mono 16-bit (zero bytes).

    sample_rate=None usa il default Gemini (24kHz). I chiamanti PCM a rate
    diverso (es. Speechify Simba-3.2, 48kHz nativo) passano il rate reale.
    """
    ffmpeg_tools.write_pcm_silence(output_path, duration_sec, sample_rate or _PCM_SAMPLE_RATE,
                                   _PCM_CHANNELS, _PCM_SAMPLE_WIDTH)


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
    lang2 = _norm_lang(lang2)
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
    Ritorna True se il PCM prodotto e' non vuoto. Best-effort: log su errore
    (timeout 300 s: il ripiego Edge lavora su un chunk, non su un libro)."""
    return ffmpeg_tools.pcm_transcode(mp3_path, pcm_path, out_rate=_PCM_SAMPLE_RATE,
                                      channels=_PCM_CHANNELS, timeout=300, tag="gemini-tts edge-fallback")


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
    lang2 = _norm_lang(fallback_lang)
    voice = _pick_edge_fallback_voice(lang2, gender=gender, accent_code=accent_code)
    tmp_mp3 = output_path + ".edgefallback.mp3"
    # Loop asyncio dedicato e isolato: generate_chunk_mp3 e' async ma qui siamo
    # in contesto sincrono, fuori dal loop del thread di generazione. Un loop
    # nuovo evita di interferire con quello usato dai chunk edge nativi.
    _loop = None
    try:
        _loop = asyncio.new_event_loop()
        _loop.run_until_complete(
            edge_engine.generate_chunk_mp3(text, voice, rate or "+0%", tmp_mp3, max_retries=3)
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
                try:
                    result = _retry.retry_call(
                        lambda _a: _gemini.synthesize(
                            piece_text, voice_id, output_path=tmp_path,
                            style_instruction=style_instruction,
                            rate=rate,
                            debug_prompt_path=piece_debug_path,
                            accent_directive=accent_directive,
                            job_id=job_id,
                        ),
                        attempts=max_retries, wait=1.0,
                        is_retryable=lambda e: not isinstance(e, _gemini_fatal(_gemini)))
                except _gemini_fatal(_gemini):
                    raise
                except Exception as e:      # noqa: BLE001 - esauriti i tentativi
                    last_error = e
                else:
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


def _gemini_fallback_voice(_gemini, voice_id):
    """Voce sostitutiva per un chunk con i retry esauriti, o None.

    Stessa voce sul `chunk_fallback_model` del catalogo (flash38 -> flash31),
    solo se quel modello ha un canale risolto e non e' marcato non
    disponibile. Il ripiego e' per singolo chunk: il chunk successivo torna
    sul modello scelto dall'utente.
    """
    try:
        _, mk, vname = str(voice_id).split(":")
        fb = (_gemini.GEMINI_MODELS.get(mk) or {}).get("chunk_fallback_model")
        if not fb or fb not in _gemini.GEMINI_MODELS:
            return None
        if _gemini._resolve_backend(fb) is None or _gemini.model_unavailable(fb):
            return None
        return f"gemini:{fb}:{vname}"
    except Exception:
        return None


def _synthesize_with_fallback_model(_gemini, text, voice_id, output_path, **kwargs):
    """Tenta il chunk sul modello di ripiego. Ritorna il dict di synthesize()
    (marcato `fallback_model`) o None se non c'e' ripiego o fallisce anche lui.

    Qualunque errore del ripiego, quota e budget compresi, lascia il posto a
    edge-tts: il modello di ripiego non deve mai sospendere o fermare un job
    che non l'ha scelto.
    """
    fb_voice = _gemini_fallback_voice(_gemini, voice_id)
    if not fb_voice:
        return None
    dbg = kwargs.pop("debug_prompt_path", None)
    if dbg:
        base, ext = os.path.splitext(dbg)
        dbg = f"{base}.fallback{ext or '.txt'}"
    try:
        result = _gemini.synthesize(text, fb_voice, output_path=output_path,
                                    debug_prompt_path=dbg, **kwargs)
    except Exception as e:
        print(f"[gemini-tts] Fallback {fb_voice} failed too: {e}")
        return None
    result["fallback_model"] = fb_voice.split(":")[1]
    print(f"[gemini-tts] Chunk recovered via fallback model {fb_voice}")
    return result


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
        voice_id: 'gemini:<model_key>:<voice_name>' (es. 'gemini:flash31:Zephyr').
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
    effective_cap = tts_split._pick_chunk_max_bytes(voice_id)
    clean_bytes = len(clean.encode("utf-8"))
    if effective_cap is not None and clean_bytes > effective_cap:
        max_chars_for_split = max(1000, effective_cap // 2)
        pieces = tts_split.split_text_into_chunks(clean, max_chars=max_chars_for_split, max_bytes=effective_cap)
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
            # Modello con ripiego (flash38 -> flash31): l'intero chunk
            # rifatto sul ripiego, cosi' i token restano di un modello solo.
            fb_voice = _gemini_fallback_voice(_gemini, voice_id)
            if fb_voice:
                try:
                    agg = _synthesize_pcm_pieces_and_concat(
                        pieces, fb_voice, output_path, style_instruction, max_retries,
                        rate=rate, accent_directive=accent_directive, job_id=job_id,
                    )
                except Exception as e:
                    print(f"[gemini-tts] Fallback {fb_voice} byte-split failed too: {e}")
                    agg = False
                if agg is not False:
                    agg["fallback_model"] = fb_voice.split(":")[1]
                    if isinstance(failure_info, dict):
                        failure_info["fallback_engine"] = f"gemini:{agg['fallback_model']}"
                        failure_info["reason"] = "gemini_failed_model_fallback"
                    return agg
            # Fall-through: se lo split fallisce, scriviamo silenzio sotto.
            _generate_silence_pcm(output_path, duration_sec=1)
            return _fail("byte_split_failed", f"{len(pieces)} sub-chunk")

    last_error = None
    snippet = clean[:60].replace('\n', ' ')

    def _log(attempt, e, _wait):
        print(f"[gemini-tts] Attempt {attempt+1}/{max_retries} failed for chunk "
              f"({len(clean)} chars: \"{snippet}...\"): {e}")

    try:
        return _retry.retry_call(
            lambda _a: _gemini.synthesize(
                clean, voice_id, output_path=output_path,
                style_instruction=style_instruction,
                rate=rate,
                debug_prompt_path=debug_prompt_path,
                accent_directive=accent_directive,
                job_id=job_id,
            ),
            attempts=max_retries, wait=1.0, on_retry=_log,
            is_retryable=lambda e: not isinstance(e, _gemini_fatal(_gemini)))
    except _gemini_fatal(_gemini):
        # Non silenziare: il caller decide se sospendere il job.
        # GeminiUnavailable (kill-switch/capability) e' istantaneo e
        # permanente per il processo: silenziarlo significherebbe
        # silenziare l'INTERO libro (incidente 2026-06).
        raise
    except Exception as e:      # noqa: BLE001 - esauriti i tentativi
        last_error = e
        _log(max_retries - 1, e, 0)

    print(f"[gemini-tts] WARNING: All {max_retries} attempts failed, "
          f"generating silence ({len(clean)} chars). Last error: {last_error}")
    # Modello con ripiego nel catalogo (flash38 -> flash31): stessa voce sul
    # modello di ripiego, prima di edge-tts. Solo questo chunk; il successivo
    # torna sul modello scelto.
    fb = _synthesize_with_fallback_model(
        _gemini, clean, voice_id, output_path,
        style_instruction=style_instruction, rate=rate,
        debug_prompt_path=debug_prompt_path,
        accent_directive=accent_directive, job_id=job_id)
    if fb is not None:
        if isinstance(failure_info, dict):
            failure_info["fallback_engine"] = f"gemini:{fb['fallback_model']}"
            failure_info["reason"] = "gemini_failed_model_fallback"
            failure_info["detail"] = str(last_error)[:300] if last_error else ""
        return fb
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
    snippet = clean[:60].replace('\n', ' ')

    def _log(attempt, e, _wait):
        print(f"[speechify] Attempt {attempt+1}/{max_retries} failed "
              f"({len(clean)} chars: \"{snippet}...\"): {e}")

    try:
        # I ritentativi (rete, 429, 5xx, Retry-After) vivono tutti dentro
        # `speechify_tts.synthesize`: qui un solo giro (D2 passo 5, prima 3 x 3
        # = 9 chiamate HTTP per chunk). `max_retries` resta per i test.
        return _retry.retry_call(
            lambda _a: _spx.synthesize(clean, voice_id, output_path,
                                       emotion=emotion, rate=rate),
            attempts=max_retries, wait=1.0, on_retry=_log,
            is_retryable=lambda e: not isinstance(
                e, (_spx.SpeechifyUnavailable, _spx.SpeechifyFatalError)))
    except _spx.SpeechifyUnavailable:
        raise  # non silenziare: il caller decide
    except _spx.SpeechifyFatalError as e:
        # 4xx non ritentabile (es. SSML invalido): ritentare costa
        # chiamate a vuoto con esito identico.
        last_error = e
        print(f"[speechify] Fatal error, no retry "
              f"({len(clean)} chars: \"{snippet}...\"): {e}")
    except Exception as e:      # noqa: BLE001 - esauriti i tentativi
        last_error = e
        _log(max_retries - 1, e, 0)

    print(f"[speechify] WARNING: synthesis failed, silence "
          f"({len(clean)} chars). Last error: {last_error}")
    _generate_silence_pcm(output_path, duration_sec=1, sample_rate=48000)
    return _fail("synthesize_failed", str(last_error) if last_error else "")
