"""recovery — recupero al boot dei job interrotti da un riavvio (E3, seam
recovery orfani, 2026-10-10).

Spostato pari pari da `audiobook_app`: il gate che decide se un job premium
orfano puo' ripartire (modello ritirato, cap caratteri, quota gratuita,
pagamento), la ri-accodatura (`_reenqueue_orphan`), la consegna gia'
avvenuta, il ripiego con rimborso ed email «interrotto»
(`_orphan_fallback`) e il giro `_recover_orphan_jobs` chiamato
all'avvio. I descrittori vivono in `pending_jobs`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app), gli helper in FUNCS (parsing del
libro, quota gratuita, prezzo, rimborso, log, `run_generation`/
`run_optimization` del motore, che un modulo di servizio non importa) e
`jobs`; per riferimento il lock dei job. Non importa `audiobook_app`.
"""
from copy import copy
import os
import threading
import time

import activity_log
import email_service
import free_quota
import gemini_tts
import i18n as _i18n
import pending_jobs
import tts_engines
import voice_clone
import voxcpm_tts
from env_utils import env_bool, env_int
from voice_utils import (is_gemini_voice as _is_gemini_voice, is_speechify_voice as _is_speechify_voice,
                         is_voxcpm_voice as _is_voxcpm_voice)

_cfg = {}
_jobs_lock = None

FUNCS = ['_abuse_reset_recovery_markers', '_assert_priced_on_real_text', '_effective_max_text_chars', '_free_quota_book_chars', '_free_quota_log', '_log_activity', '_parse_book', '_premium_quota_decision', '_refund_payment_on_orphan', '_smtp_available', '_voice_for_log', '_voice_model_key', 'run_generation', 'run_optimization']
VALUES = ('jobs',)


def configure(*, _jobs_lock, **fns):
    """`fns`: una funzione per ogni nome in FUNCS e VALUES (la app passa
    lambda che risolvono i suoi globali a ogni chiamata)."""
    missing = [n for n in FUNCS + list(VALUES) if n not in fns]
    assert not missing, f"recovery.configure: mancano {missing}"
    _cfg.update(fns)
    globals()["_jobs_lock"] = _jobs_lock


# Valori della app usati dal codice spostato: risolti a ogni chiamata.
def _jobs():
    return _cfg["jobs"]()


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _abuse_reset_recovery_markers(*a, **k):
    return _cfg["_abuse_reset_recovery_markers"](*a, **k)

def _assert_priced_on_real_text(*a, **k):
    return _cfg["_assert_priced_on_real_text"](*a, **k)

def _effective_max_text_chars(*a, **k):
    return _cfg["_effective_max_text_chars"](*a, **k)

def _free_quota_book_chars(*a, **k):
    return _cfg["_free_quota_book_chars"](*a, **k)

def _free_quota_log(*a, **k):
    return _cfg["_free_quota_log"](*a, **k)

def _log_activity(*a, **k):
    return _cfg["_log_activity"](*a, **k)

def _parse_book(*a, **k):
    return _cfg["_parse_book"](*a, **k)

def _premium_quota_decision(*a, **k):
    return _cfg["_premium_quota_decision"](*a, **k)

def _refund_payment_on_orphan(*a, **k):
    return _cfg["_refund_payment_on_orphan"](*a, **k)

def _smtp_available(*a, **k):
    return _cfg["_smtp_available"](*a, **k)

def _voice_for_log(*a, **k):
    return _cfg["_voice_for_log"](*a, **k)

def _voice_model_key(*a, **k):
    return _cfg["_voice_model_key"](*a, **k)

def run_generation(*a, **k):
    return _cfg["run_generation"](*a, **k)

def run_optimization(*a, **k):
    return _cfg["run_optimization"](*a, **k)


class _RecoveryRejected(Exception):
    """Il descrittore NON va rilanciato: motivo nel messaggio."""


def _orphan_reject(job_id, rec, reason):
    """Chiude un descrittore che non va rilanciato e per cui NON c'e' nulla da
    rimborsare (nessun pagamento agganciato): niente email "interrotto" — il
    job non e' mai partito o non e' piu' eseguibile alle condizioni originali —
    solo mark failed, cosi' il boot successivo non ci riprova."""
    print(f"[recover] {job_id}: NON rilanciato -> {reason}; descrittore chiuso "
          f"(nessun pagamento da rimborsare)", flush=True)
    try:
        pending_jobs.mark_failed(job_id)
    except Exception as e:
        print(f"[recover] mark_failed {job_id} failed: {e}")


def _recovery_reject_retired_model(voice):
    """Solleva _RecoveryRejected se la voce e' di un modello Gemini ritirato.

    Rigenerare con un altro modello cambierebbe la voce a meta' libro. Il
    reject porta il job pagato al rimborso standard (_orphan_fallback), quello
    non pagato a _orphan_reject. Vale anche per il ramo optimize senza .abm,
    che non passa da _recovery_generate_gate.
    """
    voice = (voice or "").strip()
    if _is_gemini_voice(voice) and gemini_tts is not None:
        _mk = _voice_model_key(voice)
        if _mk not in gemini_tts.GEMINI_MODELS:
            raise _RecoveryRejected(f"modello ritirato: {_mk}")


def _recovery_generate_gate(job_id, rec, info):
    """Gate PREZZO/QUOTA/CAP per un job che il recovery sta per mandare a
    run_generation. Replica i controlli di /api/generate che il recovery
    bypassa (incidente 1rDPmro8ROjYKcGLo8Outw, 31/08/2026: descrittore
    'generate' con voce PREMIUM per un job mai partito -> al boot il libro
    INTERO, 1,6M caratteri, sintetizzato gratis senza stima ne' quota).

    Ritorna {"info", "estimate_key", "estimate", "quota_charge"}; solleva
    _RecoveryRejected se il job non deve partire.

    - selezione capitoli del descrittore applicata su una COPIA di `info`,
      fail-closed (nessuna corrispondenza -> reject, non "tutto il libro");
    - voce premium: cap caratteri, stima ex-ante (persistita dal chiamante
      sul job per l'audit), e se il descrittore NON ha un pagamento la
      generazione parte solo se la quota gratuita la copre (`quota_charge`
      da consumare alla partenza).
    """
    voice = (rec.get("voice") or "").strip()
    all_chs = list(getattr(info, "chapters", []) or [])
    sel = list(rec.get("selected_chapters") or [])
    if sel:
        _by_idx = {ch.index: ch for ch in all_chs}
        chs = [_by_idx[i] for i in sel if i in _by_idx]
        if not chs:
            raise _RecoveryRejected(
                f"selezione capitoli {sel} senza corrispondenza nel libro "
                f"ri-parsato ({len(all_chs)} capitoli)")
        if len(chs) != len(all_chs):
            info = copy(info)
            info.chapters = chs
    else:
        chs = all_chs
    out = {"info": info, "estimate_key": None, "estimate": None, "quota_charge": None}
    is_gem = _is_gemini_voice(voice)
    is_spx = _is_speechify_voice(voice)
    is_vox = _is_voxcpm_voice(voice)
    _recovery_reject_retired_model(voice)
    if not (is_gem or is_spx or is_vox):
        return out
    total_chars = sum(getattr(ch, "char_count", 0) or 0 for ch in chs)
    max_chars = _effective_max_text_chars(voice, None)
    if total_chars > max_chars:
        raise _RecoveryRejected(
            f"{total_chars:,} caratteri oltre il cap {max_chars:,} della voce premium")
    lang = (_i18n.norm_lang((rec.get("gen_lang") or rec.get("lang")
             or getattr(info, "language", "") or "it")) or "it")
    if is_gem:
        if gemini_tts is None:
            raise _RecoveryRejected("modulo gemini_tts non disponibile")
        est = tts_engines.estimate("gemini", chs, voice, language=lang,
                                            rate_pct=rec.get("rate", "+0%"))
        key = "gemini_estimate"
    elif is_spx:
        est = tts_engines.estimate("speechify", chs, language="en")
        key = "speechify_estimate"
    else:
        if voxcpm_tts is None:
            raise _RecoveryRejected("modulo voxcpm_tts non disponibile")
        if voice.startswith(voice_clone.VOICE_ID_PREFIX):
            # Stesso ruling di /api/generate: locale del DESCRITTORE (non
            # della voce, altrimenti il confronto sarebbe tautologico) - ''
            # se il descrittore non lo porta, resta il solo confronto lingua.
            _vc_locale = (rec.get("locale") or "").strip()
            _err = voice_clone.check_use(voice, (rec.get("client_id") or "").strip(), lang, _vc_locale)
            if _err:
                raise _RecoveryRejected(f"voce campione non usabile: {_err}")
        est = tts_engines.estimate("voxcpm", chs, language=lang)
        key = "voxcpm_estimate"
    if not _assert_priced_on_real_text(job_id, chs, est.get("chars_total", 0)):
        raise _RecoveryRejected("stima ex-ante su testo vuoto")
    out["estimate_key"] = key
    out["estimate"] = est
    list_total = round(float(est.get("list_price_eur", 0.0) or 0.0), 2)
    payment = rec.get("payment") or {}
    if isinstance(payment, dict) and (payment.get("token") or payment.get("total_eur")):
        print(f"[recover] {job_id}: voce premium pagata "
              f"({float(payment.get('total_eur') or 0):.2f}EUR), listino ricalcolato "
              f"{list_total:.2f}EUR su {total_chars:,} caratteri", flush=True)
        return out
    _fq_key = (rec.get("free_quota_key") or "").strip() or job_id
    dec = _premium_quota_decision((rec.get("client_id") or "").strip(),
                                  voice, list_total, _fq_key,
                                  book_chars=_free_quota_book_chars(info, all_chs),
                                  language=lang)
    _free_quota_log(job_id, dec)
    if not dec["is_free"]:
        raise _RecoveryRejected(
            f"voce premium SENZA pagamento: listino {list_total:.2f}EUR non coperto "
            f"dalla quota gratuita (dovuto {float(dec['due_eur']):.2f}EUR)")
    out["quota_charge"] = list_total
    out["quota_key"] = _fq_key
    return out


def _reenqueue_orphan(job_id, rec):
    """Ricostruisce il job dal descrittore e rilancia il thread appropriato.
    Riusa l'.abm ottimizzato se presente (salta l'LLM)."""
    # F2 — Guardia voce vuota: un descrittore non-optimize senza voce produrrebbe
    # un audiolibro completamente muto (edge-tts solleva "Invalid voice ''" su
    # ogni chunk -> fallback silenzio). Capita con descrittori 'generate'
    # mis-registrati (es. job di traduzione orfano) o snapshot salvati prima che
    # /api/generate impostasse job["voice"]. NON avviare una generazione muta:
    # tratta il job come non recuperabile (refund secondo policy + email
    # interrotto + mark failed), come per il superamento del cap tentativi.
    _voice_rec = (rec.get("voice") or "").strip()
    if rec.get("phase") != "optimize" and not _voice_rec:
        print(f"[recover] {job_id}: descrittore '{rec.get('phase')}' SENZA voce "
              f"-> skip generazione muta, fallback interrotto.")
        _orphan_fallback(job_id, rec)
        return False
    abm_path = rec.get("abm_path") or ""
    use_abm = bool(abm_path) and os.path.exists(abm_path)
    # Traduzione adottata: il libro del job e' quello tradotto, non il file
    # caricato. Se lo snapshot manca, ri-parsare l'originale farebbe leggere
    # il testo sorgente alla voce della lingua tradotta: meglio non ripartire.
    adopted_path = rec.get("adopted_abm_path") or ""
    if not use_abm and adopted_path:
        if not os.path.exists(adopted_path):
            raise FileNotFoundError(
                f"traduzione adottata mancante per {job_id}: {adopted_path!r}")
        src = adopted_path
    else:
        src = abm_path if use_abm else rec.get("input_path", "")
    if not src or not os.path.exists(src):
        raise FileNotFoundError(f"input mancante per {job_id}: {src!r}")
    info = _parse_book(src)
    # Tutto cio' che va a run_generation passa dal gate (selezione capitoli,
    # cap, stima, quota): il ramo optimize senza .abm ha i suoi controlli in
    # run_optimization e nell'auto-generazione post-LLM.
    _gate = None
    try:
        if rec.get("phase") == "optimize" and not use_abm:
            # Niente gate completo qui, ma un modello ritirato va fermato
            # ora: l'auto-generazione post-LLM lo leggerebbe con un'altra voce.
            _recovery_reject_retired_model(rec.get("voice"))
        else:
            _gate = _recovery_generate_gate(job_id, rec, info)
    except _RecoveryRejected as e:
        _pay = rec.get("payment") or {}
        if isinstance(_pay, dict) and (_pay.get("token") or _pay.get("total_eur")):
            # Pagato ma non eseguibile alle condizioni originali: policy
            # "non recuperabile" (rimborso + email interrotto + failed).
            print(f"[recover] {job_id}: {e} -> job pagato, fallback interrotto.")
            _orphan_fallback(job_id, rec)
        else:
            _orphan_reject(job_id, rec, str(e))
        return False
    if _gate is not None:
        info = _gate["info"]
    job = {
        "status": "queued",
        "epub_path": rec.get("input_path", ""),
        "original_filename": rec.get("original_filename", ""),
        "info": info,
        "voice": rec.get("voice", ""),
        "rate": rec.get("rate", "+0%"),
        "single_file": rec.get("single_file", True),
        "output_format": rec.get("output_format", "m4b"),
        "gemini_style_instruction": rec.get("gemini_style_instruction"),
        "notify_email": rec.get("notify_email", ""),
        "notify_download_type": rec.get("notify_download_type", "audio"),
        "notify_base_url": rec.get("notify_base_url", ""),
        "notify_lang": rec.get("notify_lang", "en"),
        # Ripristina la lingua di lettura: run_optimization (prompt LLM) e
        # _audit_language (accento/rate-sample Gemini) leggono opt_lang/gen_lang/
        # lang. Senza, il recovery ricadeva sul default "it" degradando prompt e
        # calibrazione per libri non italiani.
        "lang": rec.get("lang", ""),
        "opt_lang": rec.get("opt_lang", ""),
        "gen_lang": rec.get("gen_lang", ""),
        "browser_lang": rec.get("browser_lang", ""),
        "platform": rec.get("platform", ""),
        "gemini_accent": rec.get("gemini_accent"),
        # Senza questa riga un job Speechify recuperato ripartiva in tono neutro.
        "speechify_emotion": rec.get("speechify_emotion", ""),
        "voxcpm_voice_pace": rec.get("voxcpm_voice_pace"),
        "email_registered": True,
        "client_id": rec.get("client_id", ""),
        # Slot imputato al client originale: il recovery NON e' soggetto al
        # tetto (ripartire e' un obbligo verso un lavoro gia' avviato, spesso
        # pagato), ma deve comunque occupare il posto giusto nel conteggio.
        "gen_owner_cid": rec.get("client_id", ""),
        "client_ip": rec.get("client_ip", ""),
        "payment": rec.get("payment"),
        "ai_optimized": bool(rec.get("ai_optimized")) or use_abm,
        "adopted_abm_path": adopted_path,
        "recovered": True,
        "gen_epoch": 1,
        # Parametri opt_* per il ramo optimize: run_optimization legge questi
        # (non i corrispettivi senza prefisso) per l'auto-generazione TTS dopo
        # la ri-ottimizzazione. Senza, un recovery in fase optimize si
        # fermerebbe a .abm+email invece di produrre l'audio atteso.
        "opt_voice": rec.get("voice", ""),
        "opt_rate": rec.get("rate", "+0%"),
        "opt_single_file": rec.get("single_file", True),
        "opt_output_format": rec.get("output_format", "m4b"),
        "opt_podcast_base_url": rec.get("podcast_base_url", ""),
        "opt_auto_generate": bool(rec.get("opt_auto_generate")),
        "opt_selected_chapters": rec.get("selected_chapters"),
        # Ripristina la scelta lettura parentesi: run_generation la legge da job.
        "read_round_parens": bool(rec.get("read_round_parens", False)),
        "read_square_brackets": bool(rec.get("read_square_brackets", False)),
        # Copie admin agganciate prima del restart: da materializzare al COMPLETE.
        "admin_copy_cids": list(rec.get("admin_copy_cids", []) or []),
    }
    if _gate and _gate.get("estimate_key"):
        # Stima ex-ante per l'audit premium: senza, il record riporta costo
        # stimato 0 e l'alert di margine attribuisce il job a "sotto soglia".
        job[_gate["estimate_key"]] = _gate["estimate"]
    _abuse_reset_recovery_markers(job)
    with _jobs_lock:
        _jobs()[job_id] = job
    if _gate and _gate.get("quota_charge") is not None and free_quota.limit_eur() > 0:
        try:
            _fq_total = free_quota.consume(job.get("client_id", ""),
                                           _gate["quota_charge"],
                                           _gate.get("quota_key") or job_id)
            job["free_quota_key"] = _gate.get("quota_key") or job_id
            print(f"[recover] {job_id}: free quota consumed: "
                  f"+{_gate['quota_charge']:.2f}€ -> {_fq_total:.2f}€/"
                  f"{free_quota.limit_eur():.2f}€", flush=True)
        except Exception as _fq_err:
            print(f"[recover] {job_id}: free_quota consume failed (non-fatal): {_fq_err}")
    if rec.get("phase") == "optimize" and not use_abm:
        t = threading.Thread(
            target=run_optimization,
            args=(job_id, rec.get("selected_chapters")),
            daemon=True,
        )
    else:
        # Tracking nell'Activity Log: il recovery bypassa /api/generate (dove
        # l'evento GENERATE viene scritto con voice), quindi senza questo mirror
        # il job recuperato non verrebbe marcato come PREMIUM/Gemini nella UI
        # admin (gemini_started + data-gemini richiedono "GENERATE" in events).
        try:
            _log_activity(job_id, job.get("original_filename", ""), "GENERATE",
                          job.get("client_id", ""), job.get("client_ip", ""),
                          _voice_for_log(job["voice"]), job.get("browser_lang", ""),
                          epoch=job.get("gen_epoch"),
                          platform=job.get("platform", ""))
        except Exception:
            pass
        t = threading.Thread(
            target=run_generation,
            args=(job_id, info, job["voice"], job["rate"], job["single_file"]),
            kwargs={"output_format": job["output_format"],
                    "podcast_base_url": rec.get("podcast_base_url", ""),
                    "gemini_style_instruction": job["gemini_style_instruction"],
                    "speechify_emotion": job.get("speechify_emotion") or None},
            daemon=True,
        )
    t.start()
    return True


def _send_interrupted_email(rec, refund_code=None):
    """Notifica all'utente che l'elaborazione è stata interrotta e non recuperabile.
    Riusa il template di rimborso job fallito esistente."""
    email = rec.get("notify_email", "")
    if not email or not _smtp_available():
        return
    _pay = rec.get("payment") or {}
    amt = round(float(_pay.get("total_eur", 0) or 0)
                + float(_pay.get("llm_eur", 0) or 0), 2)
    title = rec.get("original_filename", "") or "Audiobook"
    try:
        email_service._send_gemini_failed_refund_email(
            email, amt, title, "interrupted_restart", voucher_code=refund_code,
            lang=rec.get("browser_lang") or rec.get("notify_lang") or "it",
        )
    except Exception as e:
        print(f"[{rec.get('id')}] interrupted email failed (non-fatal): {e}")


def _orphan_job_delivered(job_id, rec):
    """True se l'activity log dimostra che questo job è stato portato a termine.
    Per la fase 'optimize' basta OPT_COMPLETE; per 'generate' serve COMPLETE
    (un OPT_COMPLETE senza COMPLETE significa audio mai prodotto)."""
    try:
        idx = activity_log.delivered_ids()
    except Exception as e:
        print(f"[recover] {job_id}: check consegna fallito, procedo col rimborso: {e}")
        return False
    if job_id in idx["complete"]:
        return True
    return rec.get("phase") == "optimize" and job_id in idx["opt_complete"]


def _orphan_fallback(job_id, rec):
    """Dopo il cap tentativi: rimborso secondo policy + mail interrotto + mark failed.

    Se però l'activity log dice che il job era già stato consegnato, il
    descrittore è rimasto aperto per un buco di finalize (job senza
    notify_email, o SMTP fallito), non per un'elaborazione andata persa:
    niente rimborso e niente email "interrotto", si chiude e basta."""
    if _orphan_job_delivered(job_id, rec):
        print(f"[recover] {job_id}: job già consegnato (COMPLETE nell'activity log) "
              f"→ nessun rimborso, chiudo il descrittore")
        try:
            pending_jobs.finalize(job_id)
        except Exception as e:
            print(f"[recover] finalize {job_id} failed: {e}")
            try:
                pending_jobs.mark_failed(job_id)
            except Exception:
                pass
        return
    job_like = {"payment": rec.get("payment"),
                "client_id": rec.get("client_id", ""),
                "client_ip": rec.get("client_ip", "")}
    refund_code = _refund_payment_on_orphan(job_id, job_like, "recover_failed")
    _send_interrupted_email(rec, refund_code=refund_code)
    try:
        pending_jobs.mark_failed(job_id)
    except Exception as e:
        print(f"[recover] mark_failed {job_id} failed: {e}")


def _recover_orphan_jobs():
    """Eseguito UNA volta al boot: il dict jobs è vuoto, ogni descrittore non
    finalizzato è orfano. Incrementa attempts su disco PRIMA di rilanciare."""
    if not env_bool("ABM_RECOVER_ENABLED", True):
        return
    try:
        orphans = pending_jobs.orphans()
    except Exception as e:
        print(f"[recover] impossibile leggere pending _jobs(): {e}")
        return
    if not orphans:
        return
    max_attempts = env_int("ABM_RECOVER_MAX_ATTEMPTS", 2)
    print(f"[recover] {len(orphans)} job batch orfani da recuperare (cap={max_attempts})")
    for rec in orphans:
        job_id = rec.get("id")
        # Idempotenza: se il job e' gia' vivo in memoria (thread in esecuzione,
        # o gia' re-enqueued da un pass precedente), NON ri-accodarlo: un
        # secondo run_generation sullo stesso job_id crea thread duplicati che
        # corrono sulla stessa entry _jobs e sugli stessi file di output.
        with _jobs_lock:
            already_live = job_id in _jobs()
        if already_live:
            print(f"[recover] {job_id}: gia' vivo in memoria — skip (no duplicato)")
            continue
        try:
            attempts = pending_jobs.mark_running_bump(job_id)  # persiste PRIMA del run
        except Exception as e:
            print(f"[recover] bump fallito {job_id}: {e}")
            continue
        if attempts > max_attempts:
            print(f"[recover] {job_id}: superato cap ({attempts}>{max_attempts}) → fallback")
            _orphan_fallback(job_id, rec)
            continue
        try:
            # Il log va emesso solo se il job e' stato davvero riavviato: la
            # guardia anti-audio-muto puo' dirottare su _orphan_fallback e un
            # "re-enqueued" incondizionato faceva credere in fase forense che il
            # job stesse ripartendo mentre era gia' stato rimborsato e chiuso.
            if _reenqueue_orphan(job_id, rec):
                print(f"[recover] {job_id}: re-enqueued (tentativo {attempts})")
        except Exception as e:
            print(f"[recover] {job_id}: re-enqueue fallito (tentativo {attempts}): {e}")
        time.sleep(2)  # throttle anti-spike se molti orfani
