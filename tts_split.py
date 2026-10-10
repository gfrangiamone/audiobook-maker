"""
tts_split.py — Splitting del testo e piano dei chunk per Audiobook Maker.

Funzioni:
  - split_text_into_chunks: divide testo in chunk senza spezzare frasi (TTS)
  - _split_sentences_for_tts: tokenizza in frasi, accorpando quelle troppo corte
  - _is_multilingual_voice: rileva voci Azure Multilingual soggette a lingua-drift
  - _pick_chunk_max_chars / _pick_chunk_max_bytes / _pick_pre_split / _pick_sentence_slack:
    parametri di chunking per motore (da tts_engines.ENGINES)
  - _plan_chunks: costruisce il piano di chunk per un intero BookInfo

Le regole di testo pre-TTS (prepare_tts_text, _sanitize_tts_text, spoken_title_prefix, ...)
vivono in text_reflow e sono riesportate qui (F1c). La sintesi dei chunk sta in
edge_engine (edge-tts, MP3) e premium_chunk (Gemini/Speechify, PCM) dal F1d
(2026-10-10): questo modulo non importa nessun motore.
"""

import re


# Predicato voce PREMIUM Gemini: definizione unica in voice_utils (modulo foglia).
import tts_engines as _engines


# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

CHUNK_MAX_CHARS = _engines.CHUNK_MAX_CHARS   # 2000, definito in tts_engines (F1c)

def _pick_chunk_max_chars(voice_id, language):
    """Limite caratteri/chunk per motore e lingua, dal registro `tts_engines`.

    Gemini: `gemini_tts.get_max_chunk_chars(lang)` (default 700 per stabilita'
    acustica; override `ABM_GEMINI_CHUNK_CHARS` o per lingua). Speechify:
    `speechify_tts.chunk_max_chars()` (default 1800: l'endpoint rifiuta un
    SSML > 2000 caratteri, tag compresi). VoxCPM: `voxcpm_tts.chunk_max_chars()`
    (default 280, limite di qualita': il timbro deriva sui chunk lunghi; il
    tetto vero e' allargato da `_pick_sentence_slack`). Edge: `CHUNK_MAX_CHARS`.
    """
    eng = _engines.premium_for_voice(voice_id)
    return eng.chunk_max_chars(language) if eng else CHUNK_MAX_CHARS


def _pick_chunk_max_bytes(voice_id):
    """Cap byte UTF-8 per chunk per voci Gemini (`MAX_BYTES_PER_CALL`, sul solo
    testo da sintetizzare: i prefissi style/rate di synthesize() non contano),
    None per gli altri motori."""
    eng = _engines.premium_for_voice(voice_id)
    return eng.chunk_max_bytes() if eng else None


def _pick_pre_split(voice_id):
    """Normalizzazione del testo INTERO prima del taglio, dal registro.

    Serve alle regole di punteggiatura che guardano cosa viene DOPO il segno:
    applicate ai chunk gia' tagliati vedono un confine artificiale e decidono
    il verdetto sbagliato. Solo VoxCPM (`voxcpm_tts.prepara_capitolo`: puntini
    di sospensione -> virgola o punto, punto in fondo al capitolo); gli altri
    motori leggono «...» come pausa lunga e non vanno toccati: None.
    """
    eng = _engines.premium_for_voice(voice_id)
    return eng.pre_split() if eng else None


# Quanto una frase puo' sforare il cap pur di NON essere spezzata sulle
# virgole. Vale solo per VoxCPM (`tts_engines.ENGINES["voxcpm"].sentence_slack`)
# ed e' il rimedio a un difetto suo: il worker sintetizza ogni chunk come
# enunciato a se' e li concatena campione su campione, quindi un taglio a
# meta' frase si sente due volte: la virgola finale, sospesa, il modello la
# puo' pronunciare («punto»), e fra i due enunciati restano in fila la coda
# di silenzio del primo e l'attacco del secondo. Collaudo del 9/9/2026: «il
# paragone e', il piu' delle volte,» / «a favore dell'affare umano».
# La frase tenuta intera allunga il chunk, e chunk lunghi fanno derivare il
# timbro: per questo il cap base e' sceso a 280 (voxcpm_tts.CHUNK_MAX_CHARS),
# cosi' il tetto con lo sforamento resta intorno ai 300 misurati sul worker.
_VOXCPM_SENTENCE_SLACK = _engines.ENGINES["voxcpm"].sentence_slack


def _pick_sentence_slack(voice_id):
    """Frazione di sforamento concessa a una frase intera, 0 = nessuna.

    Solo VoxCPM: gli altri motori hanno cap che sono limiti veri (byte
    dell'API per Gemini, lunghezza SSML per Speechify) o non hanno il
    problema, e allargarli non si fa.
    """
    eng = _engines.premium_for_voice(voice_id)
    return eng.sentence_slack if eng else 0.0


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


# Segni deboli, ma meno deboli di una virgola: un punto e virgola o due punti
# reggono un taglio molto meglio, perche' li' la voce chiude comunque il
# periodo. Fra due tagli possibili si sceglie questo.
_SEGNI_FORTI = ";:；："


def _hard_split_oversized(s, max_chars, max_bytes):
    """Spezza una singola frase oltre i limiti in pezzi <= (max_chars, max_bytes).

    1) prova i breakpoint deboli (virgole CJK/latine), preferendo i segni forti
       e senza lasciare un moncone in fondo;
    2) per i residui ancora oversize (es. lunghe sequenze CJK senza punteggiatura)
       taglio duro carattere-per-carattere rispettando SEMPRE il cap byte —
       garantisce che nessun pezzo superi mai il limite dell'API.

    Ogni pezzo e' una sintesi a se' e ogni giunzione fra due pezzi va cucita:
    il numero di pezzi resta quindi il minimo che sta nei limiti. Quel che si
    puo' scegliere e' *dove* tagliare — su un punto e virgola meglio che su una
    virgola — e che l'ultimo pezzo non sia di tre parole: un frammento corto
    il modello lo legge senza contesto, con la cadenza sbagliata.
    """
    parts = [p for p in _SOFT_BREAK_RE.split(s) if p]

    def unisci(ps):
        # Il breakpoint latino si porta via lo spazio che seguiva la virgola
        # (`(?<=[,;:])\s+` lo consuma): rimettendo insieme due pezzi va
        # restituito, o al TTS arriva «tra cui,pubblicati da Garzanti,Danny»
        # dove il testo diceva «tra cui, pubblicati da Garzanti, Danny». Il
        # breakpoint CJK e' a larghezza zero, non aveva spazi da consumare:
        # li' i pezzi si riattaccano come stavano.
        out = ""
        for p in ps:
            out += (" " if out and out[-1] in ",;:" else "") + p
        return out

    gruppi = []
    cur = []
    for p in parts:
        if not cur:
            cur = [p]
            continue
        testo = unisci(cur)
        if not _within(unisci(cur + [p]), max_chars, max_bytes):
            gruppi.append(cur)
            cur = [p]
        elif (testo[-1] in _SEGNI_FORTI
                and len(testo) >= _TTS_MIN_SENT_CHARS):
            # Ci sta ancora, ma questo e' un segno forte e il pezzo ha gia'
            # una misura sua: meglio tagliare qui che su una virgola piu' in
            # la' per riempire il cap.
            gruppi.append(cur)
            cur = [p]
        else:
            cur.append(p)
    if cur:
        gruppi.append(cur)
    # Il moncone finale si evita arretrando il taglio precedente, non
    # aggiungendo pezzi: il conto resta quello. Si arretra solo finche' chi
    # cede resta a sua volta di misura, altrimenti il moncone cambia solo di
    # posto.
    while (len(gruppi) >= 2 and len(gruppi[-2]) > 1
            and len(unisci(gruppi[-1])) < _TTS_MIN_SENT_CHARS):
        p = gruppi[-2][-1]
        if (not _within(unisci([p] + gruppi[-1]), max_chars, max_bytes)
                or len(unisci(gruppi[-2][:-1])) < _TTS_MIN_SENT_CHARS):
            break
        gruppi[-2].pop()
        gruppi[-1].insert(0, p)
    merged = [unisci(g) for g in gruppi]
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


def split_text_into_chunks(text, max_chars=CHUNK_MAX_CHARS, max_bytes=None,
                           sentence_slack=0.0):
    """Spezza il testo in chunk <= max_chars (e <= max_bytes UTF-8).

    Strategia: tokenizza in frasi (terminatori latini E CJK), pre-spezza ogni
    frase che da sola supera i limiti (caso tipico CJK: testo senza spazi ->
    frasi enormi), poi accumula le frasi adiacenti finche' uno dei due cap viene
    raggiunto. Invariante: nessun chunk supera mai max_bytes — elimina i rifiuti
    "Payload exceeds API hard cap" su giapponese/cinese.

    max_bytes: cap byte UTF-8 opzionale (necessario per Gemini, che limita a
        byte; per il giapponese ogni carattere pesa ~3 byte). Se None, solo chars.
    sentence_slack: frazione di sforamento concessa a una frase pur di tenerla
        intera invece di spezzarla sulle virgole (vedi _pick_sentence_slack).
        Riguarda SOLO il cap caratteri: max_bytes resta un limite invalicabile.
        L'accumulo di frasi adiacenti continua a fermarsi a max_chars — la
        deroga serve alla frase che da sola sfora di poco, non a gonfiare i
        chunk.
    """
    if not text or not text.strip():
        return [text] if text else [""]
    raw_sentences = _SENT_SPLIT_RE.split(text.strip())
    sentences = [s.strip() for s in raw_sentences if s and s.strip()]
    if not sentences:
        sentences = [text.strip()]
    # Pre-bound: ogni frase oversize viene spezzata sotto i cap. La frase che
    # sfora di poco resta intera se il motore lo concede: meglio un chunk un
    # po' lungo che un taglio a meta' frase (vedi _pick_sentence_slack).
    tetto_frase = max(max_chars, int(max_chars * (1.0 + max(0.0, sentence_slack))))
    bounded = []
    for s in sentences:
        if _within(s, tetto_frase, max_bytes):
            bounded.append(s)
        else:
            # Il tetto e' quello della frase, non il cap secco: lo slack e'
            # gia' la misura che il motore regge, e concederlo anche ai pezzi
            # significa un pezzo in meno, cioe' una giunzione in meno.
            bounded.extend(_hard_split_oversized(s, tetto_frase, max_bytes))
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


# Terminatore + eventuali virgolette/chiuse + whitespace obbligatorio
# (precompilata: prima veniva ricompilata a ogni chiamata).
_TTS_SENT_SPLIT_RE = re.compile(r'(?<=[.?!\u2026])[\'"»\u201c\u201d\)\]]*\s+')


def _split_sentences_for_tts(text: str):
    """Split un chunk in frasi, accorpando quelle troppo corte per dare contesto
    sufficiente al motore TTS Multilingual.

    Ritorna una lista di stringhe pronte per TTS (nessuna sarà vuota).
    """
    if not text:
        return []
    raw = _TTS_SENT_SPLIT_RE.split(text)
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
# Text preprocessing: in text_reflow (F1c, 2026-10-10); qui i nomi storici
# ---------------------------------------------------------------------------

from text_reflow import (  # noqa: F401 - nomi storici, F1c: le regole vivono in text_reflow
    _flatten_ws, _strip_parenthetical, _ROMAN_RE, _NUMBERING_WORDS, _SENT_END_CHARS, _word_core, _is_roman_numeral, _is_shouted_word, _line_is_shouted, _recapitalize, _sentence_case_shouted_line, _is_caps_filler, _lower_inline_shouted_runs, _normalize_shouting, _CHIUSA_RE, _ensure_heading_pause, prepare_tts_text, _normalize_for_title_match, _title_already_in_text, _sanitize_tts_text, spoken_title_prefix,
)


def _plan_chunks(info, max_chars=CHUNK_MAX_CHARS, max_bytes=None,
                 strip_round=True, strip_square=True, pre_split=None,
                 sentence_slack=0.0):
    """Costruisce la lista di chunk da generare per tutti i capitoli di un BookInfo.

    max_chars: limite caratteri/chunk (default CHUNK_MAX_CHARS=2000).
               Per voci Gemini su lingue CJK/Hindi/Arabo passare 1500.
    max_bytes: cap byte UTF-8 opzionale (None per Edge, MAX_BYTES_PER_CALL
               meno margine di sicurezza per Gemini).
    strip_round/strip_square: se False, il testo tra parentesi tonde/quadre viene
               letto dal TTS invece di essere rimosso (default: rimuove entrambe).
    pre_split: callable opzionale applicato al testo INTERO del capitolo appena
               prima della spezzatura (vedi _pick_pre_split). None = nessuna.
    sentence_slack: sforamento concesso a una frase intera pur di non spezzarla
               sulle virgole (vedi _pick_sentence_slack). 0 = nessuno.
    """
    plan = []
    for ch in info.chapters:
        clean_text = prepare_tts_text(ch.text, strip_round=strip_round,
                                      strip_square=strip_square)
        # Solo il testo letto dal TTS viene normalizzato: ch.title resta intatto
        # nel piano, e` il titolo che finisce nei metadati/capitoli del file.
        full_text = spoken_title_prefix(ch, clean_text) + clean_text
        # Ultimo ritocco a testo ancora intero: dopo la spezzatura la fine del
        # chunk e` un confine finto e le regole di punteggiatura che guardano
        # il seguito sbaglierebbero verdetto (vedi _pick_pre_split).
        if pre_split is not None:
            full_text = pre_split(full_text)
        chunks = split_text_into_chunks(full_text, max_chars=max_chars,
                                        max_bytes=max_bytes,
                                        sentence_slack=sentence_slack)
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
