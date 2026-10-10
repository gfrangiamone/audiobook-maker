"""routes_voice_clone — API e pagine della voce campionata (E3, seam voice
clone, 2026-10-10).

Blueprint `vc`: `/api/voice_clone/*` (config, prompt, campione, demo,
email, commit e pagamento, avanzamento SSE, approva/riprova/rifiuta,
le mie voci, claim/conferma, scarta/dimentica/rinomina/velocita', reinvio
email, audio campione e demo), `/api/paypal_create_order_voice_clone`,
`/vc/<token>/*` (pagina di gestione: ripresa, dispositivi, velocita',
demo, cancellazione). Spostato pari pari da `audiobook_app`; lo stato
delle voci vive in `voice_clone`, l'audio in `voice_clone_audio`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app), gli helper in FUNCS (identita' del
client, no-cache, rate limit per IP, lingua, account, activity log,
manutenzione, PayPal, SSE) e i valori `UPLOAD_DIR` e `BASE_URL`; per
riferimento i testi delle pagine e il nome del cookie lingua. Non importa
`audiobook_app`.
"""
import hashlib
import html as html_mod
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone

from flask import Blueprint, Response, abort, jsonify, redirect, request, send_file

import community_translator
import email_service
import i18n as _i18n
import page_brand
import payment
import transcript_judge
import voice_clone
import voice_clone_audio
import voice_clone_demo
import voice_clone_prompts
import voxcpm_catalog
import voxcpm_tts

bp = Blueprint("vc", __name__)

_cfg = {}
_VC_PAGES_I18N = {}
_LANG_COOKIE = "lang"

FUNCS = ['_get_client_id', '_apply_no_cache', '_ip_rl_check', 'client_ip', '_get_browser_lang', '_current_account', '_log_activity', '_maintenance_gate', '_paypal_available', '_paypal_create_order', '_sse_event', '_sse_response']
VALUES = ("upload_dir", "base_url")


def configure(*, vc_pages_i18n, lang_cookie, **fns):
    """`fns`: una funzione per ogni nome in FUNCS e VALUES (la app passa
    lambda che risolvono i suoi globali a ogni chiamata)."""
    missing = [n for n in FUNCS + list(VALUES) if n not in fns]
    assert not missing, f"routes_voice_clone.configure: mancano {missing}"
    _cfg.update(fns)
    globals()["_VC_PAGES_I18N"] = vc_pages_i18n
    globals()["_LANG_COOKIE"] = lang_cookie


# Valori della app usati dal codice spostato: risolti a ogni chiamata.
def _upload_dir():
    return _cfg["upload_dir"]()


def _base_url():
    return _cfg["base_url"]()


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _get_client_id(*a, **k):
    return _cfg["_get_client_id"](*a, **k)

def _apply_no_cache(*a, **k):
    return _cfg["_apply_no_cache"](*a, **k)

def _ip_rl_check(*a, **k):
    return _cfg["_ip_rl_check"](*a, **k)

def client_ip(*a, **k):
    return _cfg["client_ip"](*a, **k)

def _get_browser_lang(*a, **k):
    return _cfg["_get_browser_lang"](*a, **k)

def _current_account(*a, **k):
    return _cfg["_current_account"](*a, **k)

def _log_activity(*a, **k):
    return _cfg["_log_activity"](*a, **k)

def _maintenance_gate(*a, **k):
    return _cfg["_maintenance_gate"](*a, **k)

def _paypal_available(*a, **k):
    return _cfg["_paypal_available"](*a, **k)

def _paypal_create_order(*a, **k):
    return _cfg["_paypal_create_order"](*a, **k)

def _sse_event(*a, **k):
    return _cfg["_sse_event"](*a, **k)

def _sse_response(*a, **k):
    return _cfg["_sse_response"](*a, **k)


# ---------------------------------------------------------------------------
# Voci campionate (spec 2026-09-09, piano 2)
# ---------------------------------------------------------------------------
_VC_ID_RE = re.compile(r"^vc_[A-Za-z0-9_\-]{4,64}$")
# I4: quanti dispositivi diversi possono autorizzarsi tramite il link di
# resume della stessa voce, prima che il link vada considerato compromesso/
# condiviso oltre l'uso personale previsto.
RESUME_DEVICES_MAX = 10


def _vc_err(code, msg, status, **extra):
    body = {"error": msg, "error_code": code}
    body.update(extra)
    return jsonify(body), status


def _vc_gate():
    """None se la feature e' attiva, altrimenti la risposta 404."""
    if voxcpm_tts is None or not voice_clone.enabled():
        return _vc_err("voice_clone_disabled", "Voice samples are not available", 404)
    return None


def _vc_rec_or_404(clone_id):
    if not _VC_ID_RE.match(clone_id or ""):
        return None
    return voice_clone.get(clone_id)


def _vc_urls(rec):
    base = _base_url() or ""
    return {"resume_url": f"{base}/vc/{rec['resume_token']['value']}/resume",
            "manage_url": f"{base}/vc/{rec['manage_token']}/devices",
            "delete_url": f"{base}/vc/{rec['manage_token']}/delete"}


def _vc_view(rec):
    """Vista pubblica per progress/approve/retry/reject/claim/confirm.

    `voice_code` va restituito solo da `commit` (il pagante, che costruisce la
    propria risposta a parte) e da `mine()` (solo al proprietario): qui va
    tolto sempre, anche a chi e' gia' autorizzato, perche' questa vista e'
    condivisa da tutti i dispositivi con accesso (es. dopo un resume/confirm).
    """
    pub = voice_clone.public_view(rec)
    pub.pop("voice_code", None)
    demo = rec.get("demo") or {}
    if demo:
        pub["extra_id"] = demo.get("extra_id")
    if rec.get("state") in ("demos_ready", "ready"):
        pub["demo_urls"] = {"common": f"/api/voice_clone/{rec['id']}/demo/common",
                            "extra": f"/api/voice_clone/{rec['id']}/demo/extra"}
    return pub


def _vc_log(rec_or_id, op, extra=""):
    cid_pub = rec_or_id["id"] if isinstance(rec_or_id, dict) else rec_or_id
    try:
        _log_activity(cid_pub, extra, op, client_id=_get_client_id(), client_ip=client_ip())
    except Exception:
        pass


def _vc_demo_texts(locale):
    """Frase comune + frasi extra dedup per testo, dal catalogo (§3.4)."""
    if voxcpm_catalog is None:
        return None
    comune, extra, visti = None, [], set()
    for rec in voxcpm_catalog.voices():
        if rec.get("locale") != locale:
            continue
        for d in rec.get("demos") or []:
            if d.get("common"):
                if comune is None:
                    comune = {"id": d["id"], "text": d.get("text") or ""}
                    visti.add(comune["text"])
                continue
            testo = d.get("text") or ""
            if testo and testo not in visti:
                visti.add(testo)
                extra.append({"id": d["id"], "text": testo})
    if comune is None:
        return None
    extra.sort(key=lambda e: e["id"])
    return {"common": comune, "extra": extra}


def _voice_clone_notify(event, rec, **extra):
    """Eventi da voice_clone_demo / voice_clone.sweep -> email + log."""
    email = rec.get("owner_email") or ""
    lang = rec.get("ui_lang") or "en"
    urls = _vc_urls(rec)
    if event == "demos_ready":
        _vc_log(rec, "VOICE_CLONE_DEMOS_READY")
    elif event == "demo_failed":
        # m3: solo il nome del tipo (prima dei ':'), mai il testo dell'eccezione.
        err_kind = str(extra.get("error") or "").split(":", 1)[0].strip()[:60]
        _vc_log(rec, "VOICE_CLONE_DEMO_FAILED", err_kind)
        print(f"[voice_clone] demo fallita per {rec['id']}: {err_kind}", flush=True)
    elif event == "refunded":
        _vc_log(rec, "VOICE_CLONE_REFUNDED", extra.get("reason") or "")
        if email:
            try:
                email_service.send_voice_clone_refunded(
                    email, lang, amount_eur=extra.get("amount_eur") or 0.0,
                    method=extra.get("method") or "free", reason=extra.get("reason") or "user_rejected",
                    voucher_code=extra.get("voucher_code"),
                    voucher_amount=extra.get("bonus_amount") or extra.get("amount_eur"))
            except Exception as e:      # noqa: BLE001 - m3: mai loggare str(e), puo' contenere l'email
                print(f"[voice_clone] notify refunded fallita: {type(e).__name__}", flush=True)
    elif event == "expiring":
        _vc_log(rec, "VOICE_CLONE_EXPIRING")
        if email:
            try:
                email_service.send_voice_clone_expiring(email, lang, days=extra.get("days", 30),
                                                         manage_url=urls["manage_url"])
            except Exception as e:      # noqa: BLE001
                print(f"[voice_clone] notify expiring fallita: {type(e).__name__}", flush=True)
    elif event == "expired":
        _vc_log(rec, "VOICE_CLONE_EXPIRED")
    elif event == "approval_reminder":
        _vc_log(rec, "VOICE_CLONE_REMINDER", str(extra.get("stage")))
        if email:
            try:
                email_service.send_voice_clone_reminder(email, lang, resume_url=urls["resume_url"],
                                                         stage=extra.get("stage", 1))
            except Exception as e:      # noqa: BLE001
                print(f"[voice_clone] notify reminder fallita: {type(e).__name__}", flush=True)


@bp.route("/api/voice_clone/config")
def api_vc_config():
    gate = _vc_gate()
    if gate:
        return gate
    g = voice_clone_audio.gate_from_env()
    price = payment.voice_clone_price_eur()
    return jsonify({"enabled": True, "price_eur": price, "free": price <= 0,
                    "max_upload_mb": voice_clone.max_upload_mb(),
                    "languages": voice_clone.offered_languages(),
                    "min_sec": g.min_sec, "max_sec": g.max_sec,
                    "asr": voice_clone_audio.asr_enabled(),
                    "device_name_guess": _vc_device_name_guess()})


@bp.route("/api/voice_clone/prompt")
def api_vc_prompt():
    gate = _vc_gate()
    if gate:
        return gate
    lang = (request.args.get("lang") or "").strip().lower()
    gender = (request.args.get("gender") or "").strip().lower()
    if lang not in voice_clone.offered_languages() or gender not in ("m", "f"):
        return _vc_err("bad_request", "Unknown language or gender", 400)
    text = voice_clone_prompts.prompt_for(lang, gender)
    return jsonify({"text": text, "version": voice_clone_prompts.prompt_version(text),
                    "lang": lang, "gender": gender})


@bp.route("/api/voice_clone/sample", methods=["POST"])
def api_vc_sample():
    gate = _vc_gate()
    if gate:
        return gate
    from werkzeug.utils import secure_filename
    cid = _get_client_id()
    ip = client_ip()
    ok, retry = _ip_rl_check("vc_sample", ip, 10, 30)
    if ok:
        ok, retry = _ip_rl_check("vc_sample_cid", cid or ip, 10, 10)
    if not ok:
        return _vc_err("rate_limited", "Too many samples, try later", 429, retry_after=retry)
    f = request.files.get("file")
    lang = (request.form.get("lang") or "").strip().lower()
    locale = (request.form.get("locale") or "").strip()
    gender = (request.form.get("gender") or "").strip().lower()
    offerte = voice_clone.offered_languages()
    if f is None or lang not in offerte or locale not in offerte[lang] or gender not in ("m", "f"):
        return _vc_err("bad_request", "Missing file, language, locale or gender", 400)
    ext = (secure_filename(f.filename or "").rsplit(".", 1)[-1].lower() or "webm")[:5]
    if ext not in voice_clone.accepted_ext():
        ext = "webm"
    tmp_id = uuid.uuid4().hex
    src = os.path.join(str(_upload_dir()), f"vc_{tmp_id}.{ext}")
    # Il suffisso `_norm` non e' cosmesi: con un caricamento gia' in .wav i due
    # percorsi coincidevano, prepare_sample scriveva il campione normalizzato
    # SOPRA l'originale e create_draft, dopo aver spostato sample.wav, non
    # trovava piu' niente da spostare in original.wav (500 sull'endpoint).
    wav = os.path.join(str(_upload_dir()), f"vc_{tmp_id}_norm.wav")
    prompt_text = voice_clone_prompts.prompt_for(lang, gender)
    max_bytes = voice_clone.max_upload_mb() * 1024 * 1024
    try:
        f.save(src)
        if os.path.getsize(src) > max_bytes:
            return _vc_err("too_large", f"Sample over {voice_clone.max_upload_mb()} MB", 413)
        try:
            mt = voice_clone_audio.prepare_sample(src, wav)
        except voice_clone_audio.SampleRejected as e:
            # Il dettaglio elenca TUTTI i motivi di scarto (il campo `reason`
            # ne porta uno solo): in log e in console servono le misure, o
            # dell'ennesimo scarto resta solo la parola «scartato».
            _vc_log("", "VOICE_CLONE_SAMPLE_REJECTED", str(e))
            metrics = getattr(e, "metrics", None)
            print(f"[voice_clone] campione scartato: {e} "
                  f"{metrics.as_dict() if metrics is not None else ''}", flush=True)
            return _vc_err("sample_rejected", str(e), 400, reason=e.reason,
                           metrics=(metrics.as_dict() if metrics is not None else {}))
        cer = None
        if voice_clone_audio.asr_enabled():
            try:
                asr = voice_clone_audio.check_transcript(wav, lang, prompt_text)
            except voice_clone_audio.AsrUnavailable as e:
                # Senza questa riga il motivo finiva solo nella risposta al browser.
                print(f"[voice_clone] verifica trascrizione non disponibile: {e}", flush=True)
                return _vc_err("asr_unavailable", f"Transcript check unavailable: {e}", 503)
            cer = asr["cer"]
            if cer > voice_clone_audio.max_cer():
                # Sopra soglia stanno due casi diversi: chi legge un altro
                # testo (da fermare: la frase guidata e' la prova del
                # consenso) e chi legge la frase giusta con un accento che
                # whisper non sa trascrivere. Il CER non li distingue, e il
                # secondo non ha modo di capire cosa ha sbagliato. La domanda
                # semantica puo' solo recuperare: nel dubbio resta il rifiuto.
                if transcript_judge.rescues(prompt_text, asr.get("heard", ""), cer,
                                            lang=lang, client_id=cid):
                    _vc_log("", "VOICE_CLONE_TRANSCRIPT_RESCUED", f"cer={cer:.2f}")
                else:
                    _vc_log("", "VOICE_CLONE_SAMPLE_REJECTED", "vc_gate_transcript")
                    return _vc_err("sample_rejected", "Transcript does not match", 400,
                                   reason="vc_gate_transcript", cer=cer, heard=asr.get("heard", ""))
        rec = voice_clone.create_draft(cid, lang=lang, locale=locale, gender=gender,
                                       prompt_text=prompt_text, sample_wav=wav, original_path=src,
                                       original_ext=ext, metrics=mt.as_dict(),
                                       ui_lang=_get_browser_lang() or "en",
                                       name=request.form.get("name") or "",
                                       device_name=_vc_device_name(request.form.get("device_name")))
        _vc_log(rec, "VOICE_CLONE_SAMPLE_OK")
        return jsonify({"clone_id": rec["id"], "state": rec["state"], "expires_at": rec["expires_at"],
                        "metrics": rec.get("metrics") or {}, "cer": cer})
    finally:
        for p in (src, wav):
            try:
                os.remove(p)
            except OSError:
                pass


@bp.route("/api/voice_clone/demo_texts")
def api_vc_demo_texts():
    gate = _vc_gate()
    if gate:
        return gate
    d = _vc_demo_texts((request.args.get("locale") or "").strip())
    if d is None:
        return _vc_err("bad_request", "No voices for this locale", 400)
    return jsonify(d)


@bp.route("/api/voice_clone/check_email", methods=["POST"])
def api_vc_check_email():
    """Dice subito se l'email ha gia' una voce viva.

    Senza questa rotta il conflitto si scopriva solo dentro `commit`, cioe'
    DOPO aver pagato: il pagamento viene rilasciato, ma l'utente si vede
    l'errore a cose fatte. Serve la bozza del proprio dispositivo, altrimenti
    la rotta diventerebbe un modo per sondare gli indirizzi altrui.
    """
    gate = _vc_gate()
    if gate:
        return gate
    data = request.get_json(silent=True) or {}
    rec = _vc_rec_or_404(str(data.get("clone_id") or ""))
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not voice_clone.is_owner(rec, _get_client_id()):
        return _vc_err("not_authorized", "Not authorized", 403)
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return _vc_err("bad_request", "Invalid email", 400)
    return jsonify({"ok": True,
                    "taken": bool(voice_clone.email_has_active_voice(email, exclude_id=rec["id"]))})


@bp.route("/api/voice_clone/commit", methods=["POST"])
def api_vc_commit():
    gate = _vc_gate()
    if gate:
        return gate
    data = request.get_json(silent=True) or {}
    cid = _get_client_id()
    rec = _vc_rec_or_404(str(data.get("clone_id") or ""))
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    e1 = (data.get("email") or "").strip().lower()
    e2 = (data.get("email2") or "").strip().lower()
    if not e1 or "@" not in e1 or e1 != e2:
        return _vc_err("email_mismatch", "The two email addresses differ", 400)
    testi = _vc_demo_texts(rec.get("locale") or "") or {"common": None, "extra": []}
    # Il secondo brano non si sceglie piu': una combo in piu' da leggere prima
    # di pagare non aggiungeva nulla, e uno a sorte fra i candidati vale
    # esattamente quanto uno scelto a mano.
    if not testi["extra"] or testi["common"] is None:
        return _vc_err("bad_request", "No demo phrases for this locale", 400)
    extra = secrets.choice(testi["extra"])
    price = payment.voice_clone_price_eur()
    try:
        out, created = voice_clone.commit(
            rec["id"], cid, email=e1, extra_id=extra["id"], extra_text=extra["text"],
            common_text=testi["common"]["text"], payment_token=(data.get("payment_token") or "").strip(),
            price_eur=price)
    except voice_clone.EmailHasVoice:
        return _vc_err("email_has_voice", "This email already has a voice sample", 409)
    except voice_clone.VoiceGone:
        # C1 item 1: una capture vc:<clone_id> gia' incassata (payment_token
        # consumato in un tentativo precedente) su una voce ormai sparita/
        # terminale non deve restare orfana: nessun altro punto la rimborsera'.
        payment.refund_unused_captures_for_job("vc:" + rec["id"], reason="voice_clone_gone")
        return _vc_err("voice_gone", "Voice no longer available", 410)
    except PermissionError:
        return _vc_err("not_authorized", "Not authorized", 403)
    except voice_clone.PaymentInvalid as e:
        return _vc_err("payment_invalid", f"Payment not valid: {e}", 402)
    if created:
        _vc_log(out, "VOICE_CLONE_PAID", (out.get("payment") or {}).get("type") or "")
        try:
            voice_clone_demo.start_demos(out["id"])
        except Exception as e:      # noqa: BLE001 - lo sweeper/recover riprendera'
            print(f"[voice_clone] start_demos {out['id']}: {e}", flush=True)

        def _send_paid_email():
            try:
                email_service.send_voice_clone_paid(
                    out["owner_email"], out.get("ui_lang") or "en", voice_code=out["voice_code"],
                    amount_eur=(out.get("payment") or {}).get("amount_eur") or 0.0, **_vc_urls(out))
            except Exception as e:      # noqa: BLE001 - m3: mai loggare str(e)
                print(f"[voice_clone] send_voice_clone_paid {out['id']}: {type(e).__name__}", flush=True)

        try:
            threading.Thread(target=_send_paid_email, daemon=True,
                             name=f"vc-paid-email-{out['id']}").start()
        except Exception:
            _send_paid_email()
    return jsonify({"clone_id": out["id"], "voice_code": out["voice_code"],
                    "state": out["state"], "created": created})


@bp.route("/api/paypal_create_order_voice_clone", methods=["POST"])
def api_paypal_create_order_voice_clone():
    gate = _vc_gate()
    if gate:
        return gate
    gate = _maintenance_gate()
    if gate:
        return gate
    if not _paypal_available():
        return jsonify({"error": "PayPal not configured"}), 503
    data = request.get_json(silent=True) or {}
    rec = _vc_rec_or_404(str(data.get("clone_id") or ""))
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not voice_clone._has_cid(rec, _get_client_id()):
        return _vc_err("not_authorized", "Not authorized", 403)
    if rec.get("state") != "sample_ok":
        return _vc_err("bad_state", "Voice already paid", 409)
    amount_eur = payment.voice_clone_price_eur()
    if amount_eur <= 0:
        return jsonify({"error": "No payment required"}), 400
    try:
        order = _paypal_create_order(amount_eur, "Voice sample - Audiobook Maker",
                                     custom_id="vc:" + rec["id"])
    except Exception as e:
        print(f"[paypal] voice clone create_order failed: {e}")
        return jsonify({"error": f"PayPal error: {e}"}), 500
    return jsonify({"order_id": order.get("id"), "amount_eur": amount_eur,
                    "status": order.get("status")})


_VC_SSE_END = ("demos_ready", "demo_failed", "ready", "refunded", "expired", "deleted")


@bp.route("/api/voice_clone/progress/<clone_id>")
def api_vc_progress(clone_id):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not voice_clone._has_cid(rec, _get_client_id()):
        return _vc_err("not_authorized", "Not authorized", 403)

    def stream():
        fine = time.time() + 1800
        while True:
            cur = voice_clone.get(clone_id) or rec
            yield _sse_event(_vc_view(cur))
            if cur.get("state") in _VC_SSE_END or time.time() > fine:
                return
            time.sleep(2)
    return _sse_response(stream())


def _vc_action(clone_id, fn):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    try:
        out = fn(rec, _get_client_id())
    except voice_clone.BadTransition:
        return _vc_err("bad_state", "Action not allowed in this state", 409)
    except voice_clone.VoiceGone:
        return _vc_err("voice_gone", "Voice no longer available", 410)
    except PermissionError:
        return _vc_err("not_authorized", "Not authorized", 403)
    return jsonify(_vc_view(out))


class _VcBadRequest(ValueError):
    pass


@bp.route("/api/voice_clone/<clone_id>/approve", methods=["POST"])
def api_vc_approve(clone_id):
    def go(rec, cid):
        out = voice_clone_demo.approve(rec["id"], cid)
        _vc_log(out, "VOICE_CLONE_READY")
        if out.get("owner_email"):
            email_service.send_voice_clone_ready(
                out["owner_email"], out.get("ui_lang") or "en", voice_code=out["voice_code"],
                manage_url=_vc_urls(out)["manage_url"], delete_url=_vc_urls(out)["delete_url"],
                retention_days=int(voice_clone.retention_sec() // 86400))
        return out
    return _vc_action(clone_id, go)


@bp.route("/api/voice_clone/<clone_id>/retry", methods=["POST"])
def api_vc_retry(clone_id):
    return _vc_action(clone_id, lambda rec, cid: voice_clone_demo.retry(rec["id"], cid))


_vc_reject_translating = set()
_vc_reject_translating_lock = threading.Lock()


def _vc_translate_reject_note(clone_id):
    """Traduce in italiano, in background, il motivo del rifiuto (tab admin
    «Voci campionate»). Una sola traduzione per voce alla volta; se fallisce
    la ritenta la prossima apertura della tab."""
    with _vc_reject_translating_lock:
        if clone_id in _vc_reject_translating:
            return
        _vc_reject_translating.add(clone_id)

    def run():
        try:
            note = (voice_clone.get(clone_id) or {}).get("reject_note") or {}
            text = note.get("text") if isinstance(note, dict) else ""
            if not text or note.get("it"):
                return
            out = community_translator.translate_to_italian(text)
            if out:
                voice_clone.set_reject_translation(clone_id, out["it"], out.get("source_lang"))
        except Exception as e:      # noqa: BLE001 - la traduzione non e' critica
            print(f"[voice_clone] reject note translation failed for {clone_id}: {type(e).__name__}")
        finally:
            with _vc_reject_translating_lock:
                _vc_reject_translating.discard(clone_id)

    threading.Thread(target=run, daemon=True, name=f"vc-reject-it-{clone_id}").start()


@bp.route("/api/voice_clone/<clone_id>/reject", methods=["POST"])
def api_vc_reject(clone_id):
    data = request.get_json(silent=True) or {}
    note = voice_clone.normalize_reject_note(data.get("reason") if isinstance(data, dict) else "")
    rec0 = _vc_rec_or_404(clone_id)
    # Chi rifiuta le demo pronte deve dire perche'; se le demo sono fallite
    # il motivo e' gia' noto e non si chiede. Solo per chi ne ha diritto: agli
    # altri risponde _vc_action (403/410), senza rivelare lo stato.
    if (rec0 and rec0.get("state") == "demos_ready"
            and voice_clone._has_cid(rec0, _get_client_id())
            and len(note) < voice_clone.REJECT_NOTE_MIN):
        return _vc_err("reject_reason_required", "Please tell us why", 400,
                       min_chars=voice_clone.REJECT_NOTE_MIN)

    def go(rec, cid):
        if rec.get("state") == "refunded":
            return rec
        out = voice_clone_demo.reject(rec["id"], cid, note=note)
        _vc_log(out, "VOICE_CLONE_REJECTED")
        if note:
            _vc_translate_reject_note(rec["id"])
        return out
    return _vc_action(clone_id, go)


@bp.route("/api/voice_clone/mine")
def api_vc_mine():
    gate = _vc_gate()
    if gate:
        return gate
    return jsonify({"voices": voice_clone.mine(_get_client_id())})


@bp.route("/api/voice_clone/claim", methods=["POST"])
def api_vc_claim():
    gate = _vc_gate()
    if gate:
        return gate
    cid = _get_client_id()
    ok, retry = _ip_rl_check("vc_claim_cid", cid or client_ip(), 5, 5)
    if not ok:
        return _vc_err("rate_limited", "Too many attempts, try later", 429, retry_after=retry)
    data = request.get_json(silent=True) or {}
    code = voice_clone.normalize_voice_code(str(data.get("voice_code") or ""))
    try:
        esito = voice_clone.claim(code, cid, device_name=str(data.get("device_name") or ""),
                                  identity=str(data.get("identity") or ""))
    except voice_clone.VoiceGone:
        # VoiceGone e ClaimIncomplete sono ValueError: vanno intercettate
        # prima del ValueError generico sotto (l'unico altro ValueError di
        # claim() e' il lock, niente sniffing sul messaggio).
        return _vc_err("code_unknown", "Unknown voice code", 404)
    except voice_clone.ClaimIncomplete as e:
        return _vc_err(f"{e.field}_required", f"Missing {e.field}", 400,
                       min_chars=voice_clone.IDENTITY_MIN)
    except voice_clone.TooManyPending:
        return _vc_err("claim_busy", "Too many pending requests for this voice", 429)
    except ValueError:
        return _vc_err("code_locked", "Too many wrong codes, try later", 423)
    status, rec, confirm_code = esito
    _vc_log(rec, "VOICE_CLONE_CLAIM", status if confirm_code or status == "ok" else "pending_again")
    if status == "ok":
        return jsonify({"status": "ok", "voice": _vc_view(rec)})
    if confirm_code is None:
        # Richiesta gia' aperta da questo dispositivo: il proprietario ha gia'
        # l'email con il codice, non gliene arriva un'altra.
        return jsonify({"status": "pending", "already_sent": True})
    if rec.get("owner_email"):
        pc = voice_clone.pending_of(rec, cid) or {}
        email_service.send_voice_clone_confirm(rec["owner_email"], rec.get("ui_lang") or "en",
                                                confirm_code=confirm_code,
                                                device_name=pc.get("device_name") or "",
                                                identity=pc.get("identity") or "",
                                                hours=voice_clone.CONFIRM_TTL_SEC // 3600)
    return jsonify({"status": "pending"})


@bp.route("/api/voice_clone/confirm", methods=["POST"])
def api_vc_confirm():
    gate = _vc_gate()
    if gate:
        return gate
    cid = _get_client_id()
    data = request.get_json(silent=True) or {}
    code = voice_clone.normalize_voice_code(str(data.get("voice_code") or ""))
    try:
        nome = _vc_device_name(data.get("device_name"))
        esito = voice_clone.confirm(code, cid, str(data.get("confirm_code") or "").strip(),
                                    device_name=nome)
    except voice_clone.VoiceGone:
        return _vc_err("code_unknown", "Unknown voice code", 404)
    if esito == "ok":
        rec = voice_clone.by_voice_code(code)
        _vc_log(rec, "VOICE_CLONE_DEVICE_ADDED")
        nome = (voice_clone.device_of(rec, cid) or {}).get("name") or nome
        if rec.get("owner_email"):
            email_service.send_voice_clone_device_added(rec["owner_email"], rec.get("ui_lang") or "en",
                                                         devices_url=_vc_urls(rec)["manage_url"],
                                                         device_name=nome or _vc_device_key(cid))
        return jsonify({"status": "ok", "voice": _vc_view(rec)})
    mappa = {"wrong": ("confirm_wrong", 400), "expired": ("confirm_expired", 410),
             "none": ("confirm_none", 404), "locked": ("code_locked", 423)}
    ec, sc = mappa.get(esito, ("confirm_none", 404))
    return _vc_err(ec, f"Confirmation {esito}", sc)


@bp.route("/api/voice_clone/<clone_id>/discard", methods=["POST"])
def api_vc_discard(clone_id):
    """Butta via una bozza mai pagata: e' l'unica via d'uscita prima del
    pagamento, visto che il link di gestione arriva solo dopo."""
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    out = voice_clone.discard_draft(clone_id, _get_client_id())
    if out is None:
        return _vc_err("bad_state", "Only an unpaid draft of this device can be discarded", 409)
    _vc_log(out, "VOICE_CLONE_DRAFT_DISCARDED")
    return jsonify({"ok": True})


@bp.route("/api/voice_clone/<clone_id>/forget", methods=["POST"])
def api_vc_forget(clone_id):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    try:
        ok = voice_clone.forget(clone_id, _get_client_id())
    except voice_clone.BadTransition:
        # m1: il creatore si toglie solo da voce pronta con email (voice_clone.can_forget).
        return _vc_err("bad_state", "The owner device cannot be forgotten; delete the voice instead", 409)
    if not ok:
        return _vc_err("voice_not_found", "Voice not found", 404)
    return jsonify({"ok": True})


@bp.route("/api/voice_clone/<clone_id>/rename", methods=["POST"])
def api_vc_rename(clone_id):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    data = request.get_json(silent=True) or {}
    out = voice_clone.rename(clone_id, _get_client_id(), data.get("name"))
    if out is None:
        return _vc_err("bad_state", "Only the owner device can rename a live voice", 409)
    return jsonify({"ok": True, "name": out.get("name") or ""})


@bp.route("/api/voice_clone/<clone_id>/speed", methods=["POST"])
def api_vc_speed(clone_id):
    """Velocita' della voce, per tutti i dispositivi che la usano. Solo dal
    dispositivo creatore; l'altra via e' il link di gestione dell'email."""
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    data = request.get_json(silent=True) or {}
    try:
        out = voice_clone.set_speed(clone_id, _get_client_id(), data.get("speed"))
    except ValueError:
        return _vc_err("bad_speed",
                       f"Speed must be between {voice_clone.SPEED_MIN} and {voice_clone.SPEED_MAX}", 400)
    if out is None:
        return _vc_err("bad_state", "Only the owner device can change the speed of a live voice", 409)
    _vc_log(out, "VOICE_CLONE_SPEED", str(voice_clone.speed_of(out)))
    return jsonify({"ok": True, "speed": voice_clone.speed_of(out)})


def _vc_is_owner(rec, cid):
    return voice_clone.is_owner(rec, cid)


@bp.route("/api/voice_clone/<clone_id>/resend", methods=["POST"])
def api_vc_resend(clone_id):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not _vc_is_owner(rec, _get_client_id()) or rec.get("state") in voice_clone._TERMINAL:
        return _vc_err("not_authorized", "Only the owner can resend the email", 403)
    try:
        ok, retry = voice_clone.check_and_record_resend(rec["id"])
    except voice_clone.VoiceGone:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not ok:
        return _vc_err("rate_limited", "Limit of 3 emails per day reached", 429, retry_after=retry)
    sent = _vc_send_manage_email(rec)
    _vc_log(rec, "VOICE_CLONE_RESEND")
    return jsonify({"ok": bool(sent)})


def _vc_send_manage_email(rec):
    """Rimanda a chi possiede la voce il codice e i link di gestione.

    Prima del «pronto» la voce non ha ancora le prove approvate: l'email da
    rimandare e' quella del pagamento, che porta gli stessi link.
    """
    urls = _vc_urls(rec)
    lang = rec.get("ui_lang") or "en"
    if rec.get("state") == "ready":
        return email_service.send_voice_clone_ready(
            rec["owner_email"], lang, voice_code=rec["voice_code"],
            manage_url=urls["manage_url"], delete_url=urls["delete_url"],
            retention_days=int(voice_clone.retention_sec() // 86400))
    return email_service.send_voice_clone_paid(
        rec["owner_email"], lang, voice_code=rec["voice_code"],
        amount_eur=(rec.get("payment") or {}).get("amount_eur") or 0.0, **urls)


@bp.route("/api/voice_clone/resend_manage", methods=["POST"])
def api_vc_resend_manage():
    """Rimanda il link di gestione all'indirizzo che risulta gia' occupato.

    Chi si vede rifiutare l'email deve cancellare la vecchia voce dal link
    ricevuto a suo tempo: se quell'email e' andata persa non ha nessuna via
    d'uscita. Il link parte SOLO verso quell'indirizzo, quindi lo legge solo
    chi possiede quella casella; a chi lo chiede non torna niente oltre
    all'esito. Il limite di invii e' quello della voce che li subisce
    (RESEND_MAX al giorno), condiviso col resend del proprietario: nessuno
    puo' usare questa rotta per bersagliare un indirizzo.
    """
    gate = _vc_gate()
    if gate:
        return gate
    data = request.get_json(silent=True) or {}
    rec = _vc_rec_or_404(str(data.get("clone_id") or ""))
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not voice_clone.is_owner(rec, _get_client_id()):
        return _vc_err("not_authorized", "Not authorized", 403)
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return _vc_err("bad_request", "Invalid email", 400)
    occupante = voice_clone.active_voice_for_email(email, exclude_id=rec["id"])
    if occupante is None or not occupante.get("owner_email"):
        # niente conflitto: l'indirizzo e' libero, non c'e' nessun link da
        # rimandare (e nessun modo di scoprirlo da qui, la risposta e' uguale).
        return _vc_err("voice_not_found", "No voice for that address", 404)
    try:
        ok, retry = voice_clone.check_and_record_resend(occupante["id"])
    except voice_clone.VoiceGone:
        return _vc_err("voice_not_found", "No voice for that address", 404)
    if not ok:
        return _vc_err("rate_limited", "Limit of 3 emails per day reached", 429, retry_after=retry)
    sent = _vc_send_manage_email(occupante)
    _vc_log(occupante, "VOICE_CLONE_RESEND_CONFLICT")
    return jsonify({"ok": bool(sent)})


def _vc_send_audio(clone_id, name):
    gate = _vc_gate()
    if gate:
        return gate
    rec = _vc_rec_or_404(clone_id)
    if rec is None:
        return _vc_err("voice_not_found", "Voice not found", 404)
    if not voice_clone._has_cid(rec, _get_client_id()):
        return _vc_err("not_authorized", "Not authorized", 403)
    try:
        path = voice_clone._ensure_local(rec, name)
    except Exception:
        path = None
    if not path or not os.path.exists(path):
        return _vc_err("voice_not_found", "File not available", 404)
    return send_file(path, mimetype="audio/wav", conditional=True)


@bp.route("/api/voice_clone/<clone_id>/sample.wav")
def api_vc_sample_file(clone_id):
    return _vc_send_audio(clone_id, "sample.wav")


@bp.route("/api/voice_clone/<clone_id>/demo/<which>")
def api_vc_demo_file(clone_id, which):
    if which not in ("common", "extra"):
        return _vc_err("voice_not_found", "File not available", 404)
    return _vc_send_audio(clone_id, f"demo_{which}.wav")


# Lo stesso marchio dell'intestazione del sito: chi arriva qui da un link
# dell'email deve riconoscere subito di chi e' la pagina che gli chiede di
# cancellare o autorizzare qualcosa.
_VC_LOGO_SVG = page_brand.LOGO_SVG

# Se il file i18n non si carica le pagine devono restare in piedi lo stesso:
# sono l'unica via per revocare un dispositivo o cancellare una voce.
_VC_PAGES_FALLBACK = {
    "brand": "Audiobook Maker",
    "resume_title": "Resume your voice sample",
    "resume_q": "Resume the voice sample procedure on this device?",
    "resume_btn": "Resume",
    "toomany_title": "Too many devices",
    "toomany_body": "Too many devices have used this link. Revoke one from the "
                    "management link in your email, then try again.",
    "devices_title": "Your voice sample: devices",
    "devices_intro": "Devices allowed to use your voice sample.",
    "th_device": "Device", "th_via": "Added via", "th_date": "Date",
    "revoke_btn": "Revoke", "delete_link": "Delete this voice",
    "via_creator": "Creation", "via_resume": "Email link", "via_code": "Voice code",
    "identity_lbl": "Introduction",
    "device_name_lbl": "Name of this device",
    "device_name_hint": "It lets you recognise this device later in the list of authorised devices.",
    "this_device": "this device", "device_unnamed": "Unnamed device", "rename_btn": "Rename",
    "speed_title": "Voice speed",
    "speed_intro": "The reading speed of audiobooks made with this voice, on every device that uses it. "
                   "Whoever generates a book can still make it faster or slower from there.",
    "speed_btn": "Save", "speed_saved": "saved",
    "speed_demo_lbl": "Listen to the voice at the chosen speed",
    "cancel_btn": "Cancel", "edit_name_btn": "Edit name",
    "revoke_owner_title": "Revoke the device that created the voice?",
    "revoke_owner_body": "This is the device the voice was created on. Once revoked, the voice stays on "
                         "our server and on the other devices, but it can be renamed or deleted only from "
                         "the management link in your email. You can add the device back at any time with "
                         "the voice code you received by email.",
    "revoke_owner_btn": "Revoke this device", "cancel_link": "Cancel",
    "delete_cancel_btn": "Cancel deletion",
    "delete_title": "Delete your voice sample",
    "delete_p1": "This removes your voice sample and every file derived from it. "
                 "Audiobooks already generated are not affected.",
    "delete_p2": "If you have not approved the voice yet and want a refund, "
                 "reject it from the app instead.",
    "delete_btn": "Delete my voice",
    "deleted_title": "Voice deleted",
    "deleted_body": "Your voice sample and its files have been deleted.",
    "gone_title": "This voice is no longer available",
    "gone_deleted": "The voice sample this link points to has been deleted, "
                    "together with every file derived from it.",
    "gone_expired": "The voice sample this link points to has expired and has "
                    "been removed, together with every file derived from it.",
    "gone_refunded": "The voice sample this link points to was rejected and "
                     "refunded, and its files have been removed.",
    "gone_generic": "This link no longer opens anything: the voice it pointed "
                    "to does not exist any more, or the address is incomplete.",
    "gone_refund": "If you had paid for it, you received a voucher for the "
                   "amount spent by email.",
    "gone_books": "Audiobooks already generated with that voice are not "
                  "affected: they stay yours.",
    "gone_home": "Back to Audiobook Maker",
}


def _vc_page_lang():
    """Lingua della pagina: quella scelta nell'app (cookie `abm_lang`, posato
    dalla SPA: dal tab «Voci» dell'area personale si arriva qui e la lingua
    non deve cambiare), poi quella del browser, e inglese se non e' fra
    quelle tradotte. Nessun `?lang=`: chi apre il link dell'email deve
    ritrovare la stessa lingua su tutte le pagine del giro."""
    return _i18n.choose_lang([request.cookies.get(_LANG_COOKIE), _get_browser_lang()],
                             _VC_PAGES_I18N)


def _vc_txt(lang):
    """Stringhe della lingua sopra l'inglese: una chiave non ancora tradotta
    esce in inglese invece che vuota."""
    return _i18n.pick(_VC_PAGES_I18N, lang, base=_VC_PAGES_FALLBACK)


_VC_PENCIL_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                  '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>')

# Rinomina a scomparsa: la matita nasconde l'etichetta e mostra il campo,
# «Annulla» o Esc tornano indietro senza salvare. Senza JavaScript i campi
# restano sempre visibili (noscript).
_VC_RENAME_JS = (
    "<noscript><style>.devs form.dev-rename[hidden]{display:flex!important}"
    "[data-edit]{display:none!important}</style></noscript>"
    "<script>(function(){var U=document.querySelector('.devs');if(!U)return;"
    "function apri(l,on){var v=l.querySelector('[data-view]'),f=l.querySelector('.dev-rename');"
    "if(!v||!f)return;var i=f.querySelector('input[name=name]');v.hidden=on;f.hidden=!on;"
    "if(on){i.dataset.orig=i.value;i.focus();i.select();}"
    "else if(i.dataset.orig!==undefined){i.value=i.dataset.orig;}}"
    "U.addEventListener('click',function(e){var b=e.target.closest('[data-edit],[data-cancel]');"
    "if(!b)return;apri(b.closest('li'),b.hasAttribute('data-edit'));});"
    "U.addEventListener('keydown',function(e){if(e.key==='Escape'&&e.target.name==='name')"
    "apri(e.target.closest('li'),false);});})();</script>")


def _vc_page(title, body_html, status=200, lang="en", tools_html=""):
    """`tools_html`: strumenti a destra del marchio, allineati al logo (es.
    il ritorno all'area personale); vuoto = solo il marchio."""
    t = _vc_txt(lang)
    marchio = html_mod.escape(t["brand"])
    html_doc = (f"<!doctype html><html lang=\"{html_mod.escape(lang)}\"><head><meta charset=\"utf-8\">"
                f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                f"<meta name=\"robots\" content=\"noindex,nofollow\">"
                f"<title>{marchio} - {html_mod.escape(title)}</title>"
                # Tavolozza, bottoni e tema della SPA (page_brand): stessa
                # resa dell'area personale; qui solo le regole della pagina.
                f"{page_brand.THEME_SCRIPT}<style>{page_brand.BASE_CSS}"
                f"body{{max-width:560px}}"
                f"input,select{{padding:.5em .7em;font:inherit;max-width:100%;box-sizing:border-box;"
                f"border:1px solid var(--brd);border-radius:var(--rs);background:var(--srf);color:var(--tx)}}"
                f"input:focus,select:focus{{outline:2px solid var(--ac);outline-offset:1px}}"
                f".speed-row{{display:flex;align-items:center;gap:.6em;flex-wrap:wrap}}"
                f".speed-row select{{min-width:7em;cursor:pointer}}"
                f".speed-demo{{margin-top:1em;border-top:1px solid var(--brd);padding-top:.9em}}"
                f".speed-demo .meta{{margin:0 0 .4em}}.speed-demo audio{{width:100%;display:block}}"
                f".ok{{font-size:.85em;background:var(--oks);color:var(--ok);border-radius:1em;padding:.15em .7em}}"
                f".devs{{list-style:none;padding:0}}.devs li{{border-top:1px solid var(--brd);padding:.9em 0}}"
                f".devs form{{display:inline-flex;gap:.4em;margin:.5em .6em 0 0;flex-wrap:wrap}}"
                f".dev-head{{display:flex;align-items:center;flex-wrap:wrap;gap:.2em}}"
                f".dev-head form.dev-revoke{{margin:0 0 0 auto}}"
                f".devs form.dev-rename{{display:flex;align-items:center;margin:0 0 .3em}}"
                f".dev-rename input{{flex:1 1 12em}}"
                f".icon-btn{{padding:.3em .4em;border:none;background:transparent;color:var(--txd);"
                f"line-height:0;margin-left:.2em}}.icon-btn:hover{{background:var(--srf2);color:var(--tx);border-color:transparent}}"
                f".icon-btn svg{{width:16px;height:16px}}"
                f".meta{{margin-top:.2em}}</style>"
                f"</head><body>{page_brand.brand_bar(_VC_LOGO_SVG, marchio, tools_html=tools_html)}"
                f"<h1>{html_mod.escape(title)}</h1>{body_html}</body></html>")
    # I5: pagine di gestione voce (link email) mai in cache: contengono stato
    # per-dispositivo che cambia dopo ogni azione (revoke, delete, resume).
    resp = _apply_no_cache(Response(html_doc, status=status, mimetype="text/html"))
    # La lingua dipende dall'header: senza Vary una cache intermedia servirebbe
    # a tutti la prima lingua capitata.
    vary = resp.headers.get("Vary")
    resp.headers["Vary"] = f"{vary}, Accept-Language" if vary else "Accept-Language"
    return resp


def _vc_rec_by_manage(token):
    rec = voice_clone.by_manage_token(token or "")
    if rec is None or rec.get("state") in voice_clone._TERMINAL:
        return None
    return rec


def _vc_gone(stato=""):
    """Pagina di cortesia per i link dell'email che non aprono piu' nulla.

    Quei link restano nella casella di posta per sempre, ma la voce a cui
    puntano puo' essere stata cancellata (o scaduta, o rifiutata col
    rimborso): un «Not Found» nudo del server sembra un guasto nostro e
    lascia l'utente senza sapere ne' perche' ne' che fine hanno fatto i suoi
    soldi. `stato` e' lo stato terminale del record quando lo conosciamo:
    410 Gone con la spiegazione precisa; se il token e' ignoto resta 404 con
    il testo generico (potrebbe essere anche un indirizzo copiato a meta').
    """
    lang = _vc_page_lang()
    t = _vc_txt(lang)
    motivo = t.get("gone_" + stato) if stato else None
    righe = [motivo or t["gone_generic"]]
    if motivo:
        righe += [t["gone_refund"], t["gone_books"]]
    body = "".join(f"<p>{html_mod.escape(p)}</p>" for p in righe)
    body += f"<p><a href=\"/\">{html_mod.escape(t['gone_home'])}</a></p>"
    return _vc_page(t["gone_title"], body, status=410 if motivo else 404, lang=lang)


def _vc_manage_gone(token):
    """`_vc_gone` per un link di gestione: rilegge il record ignorando il
    filtro sugli stati terminali, cosi' la pagina puo' dire *perche'* quel
    link non apre piu' nulla invece di un generico «non trovato»."""
    rec = voice_clone.by_manage_token(token or "")
    stato = str((rec or {}).get("state") or "")
    return _vc_gone(stato if stato in voice_clone._TERMINAL else "")


@bp.route("/vc/<token>/resume", methods=["GET", "POST"])
def vc_resume(token):
    # I4: GET non deve mutare nulla (link cliccato da un client mail/preview
    # che pre-carica gli URL delle pagine) - solo una pagina di conferma con
    # un form POST. Solo la POST autorizza il dispositivo.
    if _vc_gate():
        abort(404)
    rec = voice_clone.by_resume_token(token)
    if rec is None or rec.get("state") in voice_clone._TERMINAL:
        return _vc_gone(str((rec or {}).get("state") or ""))
    lang = _vc_page_lang()
    t = _vc_txt(lang)
    if request.method == "GET":
        body = (f"<p>{html_mod.escape(t['resume_q'])}</p>"
                f"<form method=\"post\">"
                f"<p><label>{html_mod.escape(t['device_name_lbl'])}<br>"
                f"<input name=\"device_name\" maxlength=\"{voice_clone.DEVICE_NAME_MAX}\" "
                f"value=\"{html_mod.escape(_vc_device_name_guess())}\"></label><br>"
                f"<small>{html_mod.escape(t['device_name_hint'])}</small></p>"
                f"<button>{html_mod.escape(t['resume_btn'])}</button></form>")
        return _vc_page(t["resume_title"], body, lang=lang)
    cid = _get_client_id()
    if cid and not voice_clone._has_cid(rec, cid):
        resume_devices = [d for d in (rec.get("devices") or []) if d.get("via") == "resume"]
        if len(resume_devices) >= RESUME_DEVICES_MAX:
            body = f"<p>{html_mod.escape(t['toomany_body'])}</p>"
            return _vc_page(t["toomany_title"], body, status=409, lang=lang)
        voice_clone.add_resume_device(rec["id"], cid, _vc_device_name(request.form.get("device_name")))
        _vc_log(rec, "VOICE_CLONE_RESUME")
    return _apply_no_cache(redirect(f"/?vc={rec['id']}", code=302))


def _vc_device_key(cid):
    return hashlib.sha256((cid or "").encode("utf-8")).hexdigest()[:8]


def _vc_device_name_guess():
    return voice_clone.device_name_from_ua(request.headers.get("User-Agent"))


def _vc_device_name(nome):
    """Il nome scritto dall'utente o, se l'ha lasciato vuoto, quello proposto
    dal browser: un dispositivo senza nome non si riconosce piu' dopo."""
    return voice_clone.normalize_device_name(nome) or _vc_device_name_guess()


def _vc_device_by_key(rec, key):
    return next((d for d in rec.get("devices") or []
                 if key and (d.get("cid") == key or _vc_device_key(d.get("cid")) == key)), None)


@bp.route("/vc/<token>/devices")
def vc_devices(token):
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None:
        return _vc_manage_gone(token)
    lang = _vc_page_lang()
    t = _vc_txt(lang)
    tok = html_mod.escape(token)
    coda = ""
    mio = _get_client_id()
    righe = ""
    for d in rec.get("devices") or []:
        when = datetime.fromtimestamp(float(d.get("added_at") or 0), timezone.utc).strftime("%Y-%m-%d")
        chiave = _vc_device_key(d.get("cid"))
        nome = str(d.get("name") or "")
        # «creator», «resume» e «code» sono nomi interni: a chi legge si dice
        # da dove e' entrato quel dispositivo, nella sua lingua.
        via = str(d.get("via") or "")
        questo = (f" <span class=\"me\">{html_mod.escape(t['this_device'])}</span>"
                  if mio and d.get("cid") == mio else "")
        # Chi e' entrato con il codice-voce si e' presentato: il proprietario
        # deve poterlo rileggere anche dopo, non solo nell'email.
        chi = str(d.get("identity") or "")
        presentazione = (f"<div class=\"meta\">{html_mod.escape(t['identity_lbl'])}: "
                         f"«{html_mod.escape(chi)}»</div>" if chi else "")
        # Il nome e' un'etichetta: la matita apre il campo al suo posto, e
        # dopo il salvataggio la pagina si ricarica e torna etichetta.
        righe += (f"<li><div class=\"dev-head\" data-view><b>{html_mod.escape(nome or t['device_unnamed'])}</b>"
                  f"<button type=\"button\" class=\"icon-btn\" data-edit "
                  f"title=\"{html_mod.escape(t['edit_name_btn'])}\" "
                  f"aria-label=\"{html_mod.escape(t['edit_name_btn'])}\">{_VC_PENCIL_SVG}</button>{questo}"
                  f"<form class=\"dev-revoke\" method=\"post\" action=\"/vc/{tok}/devices/revoke{coda}\">"
                  f"<input type=\"hidden\" name=\"key\" value=\"{chiave}\">"
                  f"<button class=\"danger\">{html_mod.escape(t['revoke_btn'])}</button></form></div>"
                  f"<form class=\"dev-rename\" method=\"post\" action=\"/vc/{tok}/devices/rename{coda}\" hidden>"
                  f"<input type=\"hidden\" name=\"key\" value=\"{chiave}\">"
                  f"<input name=\"name\" maxlength=\"{voice_clone.DEVICE_NAME_MAX}\" "
                  f"value=\"{html_mod.escape(nome)}\" aria-label=\"{html_mod.escape(t['th_device'])}\">"
                  f"<button class=\"primary\">{html_mod.escape(t['speed_btn'])}</button>"
                  f"<button type=\"button\" data-cancel>{html_mod.escape(t['cancel_btn'])}</button></form>"
                  f"{presentazione}"
                  f"<div class=\"meta\">{html_mod.escape(t.get('via_' + via, via))} · {when} · {chiave}</div></li>")
    body = (_vc_speed_section(rec, tok, coda, t) +
            f"<p>{html_mod.escape(t['devices_intro'])}</p>"
            f"<ul class=\"devs\">{righe}</ul>{_VC_RENAME_JS}"
            f"<div class=\"actions\"><a class=\"btn danger end\" href=\"/vc/{tok}/delete\">"
            f"{html_mod.escape(t['delete_link'])}</a></div>")
    return _vc_page(t["devices_title"], body, lang=lang, tools_html=_vc_back_to_account(rec, t))


def _vc_back_to_account(rec, t):
    """«X» in testata che riporta all'area personale, solo se chi guarda e'
    connesso con l'account proprietario della voce: chi arriva dal link
    dell'email senza sessione non ha un'area a cui tornare."""
    acct = _current_account()
    if not acct or rec.get("owner_email_hash") != voice_clone.email_hash(acct.get("email") or ""):
        return ""
    lbl = html_mod.escape(t["back_account"])
    return (f"<a class=\"btn icon-x\" href=\"/account?tab=voices\" title=\"{lbl}\" aria-label=\"{lbl}\">"
            f"{page_brand.CLOSE_SVG}</a>")


def _vc_speed_section(rec, tok, coda, t):
    """Velocita' della voce sulla pagina di gestione: un menu, un «Salva» e
    la prova della voce riprodotta alla velocita' scelta (playbackRate), cosi'
    il proprietario la sente prima di salvare senza rigenerare nulla. Le prove
    escono dal worker al passo nativo, lo stesso della base delle voci
    campionate: il moltiplicatore del menu e' esattamente quello da applicare."""
    attuale = voice_clone.speed_of(rec)
    opzioni = "".join(
        f"<option value=\"{v:.2f}\"{' selected' if abs(v - attuale) < 1e-9 else ''}>"
        f"{v:.2f}×</option>" for v in voice_clone.speed_choices())
    salvata = (f"<span class=\"ok\">{html_mod.escape(t['speed_saved'])}</span>"
               if request.args.get("saved") == "speed" else "")
    prova = ""
    if rec.get("state") == "ready":
        prova = (f"<div class=\"speed-demo\"><div class=\"meta\">{html_mod.escape(t['speed_demo_lbl'])}</div>"
                 f"<audio id=\"vcSpeedDemo\" controls preload=\"none\" "
                 f"src=\"/vc/{tok}/demo.wav\"></audio></div>"
                 "<script>(function(){var s=document.getElementById('vcSpeed'),"
                 "a=document.getElementById('vcSpeedDemo');if(!s||!a)return;"
                 "var f=function(){var v=parseFloat(s.value)||1;a.defaultPlaybackRate=v;a.playbackRate=v;};"
                 "s.addEventListener('change',f);a.addEventListener('play',f);f();})();</script>")
    return (f"<section class=\"card\"><h2>{html_mod.escape(t['speed_title'])}</h2>"
            f"<p>{html_mod.escape(t['speed_intro'])}</p>"
            f"<form class=\"speed-row\" method=\"post\" action=\"/vc/{tok}/speed{coda}\">"
            f"<select id=\"vcSpeed\" name=\"speed\" aria-label=\"{html_mod.escape(t['speed_title'])}\">"
            f"{opzioni}</select><button class=\"primary\">{html_mod.escape(t['speed_btn'])}</button>{salvata}</form>"
            f"{prova}</section>")


@bp.route("/vc/<token>/speed", methods=["POST"])
def vc_speed(token):
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None:
        return _vc_manage_gone(token)
    try:
        out = voice_clone.set_speed_by_manage(token, request.form.get("speed"))
    except ValueError:
        out = None
    coda = ""
    if out is not None:
        _vc_log(out, "VOICE_CLONE_SPEED", str(voice_clone.speed_of(out)))
        coda = "?saved=speed"
    return _apply_no_cache(redirect(f"/vc/{token}/devices{coda}", code=302))


@bp.route("/vc/<token>/demo.wav")
def vc_speed_demo(token):
    """La prova comune della voce per la pagina di gestione: chi apre il link
    dell'email puo' non essere un dispositivo autorizzato, quindi l'accesso
    passa dal token di gestione e non dal cookie."""
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None or rec.get("state") != "ready":
        abort(404)
    try:
        path = voice_clone._ensure_local(rec, "demo_common.wav")
    except Exception:
        path = None
    if not path or not os.path.exists(path):
        abort(404)
    return _apply_no_cache(send_file(path, mimetype="audio/wav", conditional=True))


@bp.route("/vc/<token>/devices/rename", methods=["POST"])
def vc_devices_rename(token):
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None:
        return _vc_manage_gone(token)
    d = _vc_device_by_key(rec, (request.form.get("key") or "").strip())
    if d is not None:
        voice_clone.rename_device(token, d.get("cid"), request.form.get("name") or "")
    return _apply_no_cache(redirect(f"/vc/{token}/devices", code=302))


@bp.route("/vc/<token>/devices/revoke", methods=["POST"])
def vc_devices_revoke(token):
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None:
        return _vc_manage_gone(token)
    key = (request.form.get("key") or request.form.get("cid") or "").strip()
    d = _vc_device_by_key(rec, key)
    coda = ""
    if d is not None and d.get("via") == "creator" and request.form.get("confirm") != "1":
        # Il creatore e' l'unico dispositivo che rinomina e cancella la voce
        # dall'app: prima di toglierlo si dice che dopo restera' solo il link
        # dell'email. Il codice-voce non si perde, e' nell'email di consegna.
        lang = _vc_page_lang()
        t = _vc_txt(lang)
        tok = html_mod.escape(token)
        nome = str(d.get("name") or "") or t["device_unnamed"]
        body = (f"<p><b>{html_mod.escape(nome)}</b></p>"
                f"<p>{html_mod.escape(t['revoke_owner_body'])}</p>"
                f"<form method=\"post\" action=\"/vc/{tok}/devices/revoke{coda}\">"
                f"<input type=\"hidden\" name=\"key\" value=\"{html_mod.escape(key)}\">"
                f"<input type=\"hidden\" name=\"confirm\" value=\"1\">"
                f"<button>{html_mod.escape(t['revoke_owner_btn'])}</button></form>"
                f"<p><a href=\"/vc/{tok}/devices{coda}\">{html_mod.escape(t['cancel_link'])}</a></p>")
        return _vc_page(t["revoke_owner_title"], body, lang=lang)
    if d is not None:
        voice_clone.revoke_device(token, d.get("cid"))
        _vc_log(rec, "VOICE_CLONE_DEVICE_REVOKED")
    return _apply_no_cache(redirect(f"/vc/{token}/devices{coda}", code=302))


@bp.route("/vc/<token>/delete", methods=["GET", "POST"])
def vc_delete(token):
    if _vc_gate():
        abort(404)
    rec = _vc_rec_by_manage(token)
    if rec is None:
        return _vc_manage_gone(token)
    lang = _vc_page_lang()
    t = _vc_txt(lang)
    if request.method == "GET":
        # «Annulla» e' la scelta predefinita (primaria, con il fuoco: Invio
        # non cancella nulla) e riporta alla gestione della voce.
        tok = html_mod.escape(token)
        body = (f"<p>{html_mod.escape(t['delete_p1'])}</p>"
                f"<p>{html_mod.escape(t['delete_p2'])}</p>"
                f"<div class=\"actions\">"
                f"<form method=\"get\" action=\"/vc/{tok}/devices\">"
                f"<button class=\"primary\" autofocus>{html_mod.escape(t['delete_cancel_btn'])}</button></form>"
                f"<form method=\"post\"><button class=\"danger\">{html_mod.escape(t['delete_btn'])}</button></form>"
                f"</div>")
        return _vc_page(t["delete_title"], body, lang=lang)
    out = voice_clone.delete_by_owner(token)
    if out is None:
        return _vc_manage_gone(token)
    _vc_log(out, "VOICE_CLONE_DELETED")
    return _vc_page(t["deleted_title"], f"<p>{html_mod.escape(t['deleted_body'])}</p>", lang=lang)
