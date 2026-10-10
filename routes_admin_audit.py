"""routes_admin_audit — pagine e API dell'audit dei servizi premium
(E3, seam admin, parte 1, 2026-10-10).

Blueprint `admin_audit`: `/admin/audit-premium` (+ i due redirect storici),
`/admin/api/gemini_cost_audit[/languages|/recalc-params]`,
`/admin/api/gemini_kill_switch`, `/admin/api/tts_backend`,
`/admin/api/gemini_model_availability`, `/admin/api/translation_cost_audit
[/languages]`, `/admin/api/optimization_cost_audit[/languages]`,
`/admin/api/voice_clone_audit`, `/admin/api/accounts_audit`, con i record
sintetici dei job in corso, la trattenuta effettiva dei cancel, la sonda
manuale del backend Cloudflare. Spostato pari pari da `audiobook_app`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app): la guardia `admin_required`, il
token admin, l'autenticazione e la pagina di gate, `_log_activity`,
`client_ip`, l'invalidazione della cache voci, la nota di rifiuto delle
voci campionate; e, come oggetti condivisi mutati in place, `jobs`,
`_jobs_lock` e il modulo `generation_engine` (che un modulo di route non
importa). Non importa `audiobook_app`.
"""
import functools
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, redirect, request

import accounts
import gemini_tts
import i18n as _i18n
import payment
import speechify_tts
import tts_backend_state
import voice_clone
import voxcpm_tts
from env_utils import env_str
from page_brand import page_template as _page_template
from voice_utils import (is_gemini_voice as _is_gemini_voice, is_speechify_voice as _is_speechify_voice,
                         is_voxcpm_voice as _is_voxcpm_voice, parse_rate_pct as _parse_rate_pct)

bp = Blueprint("admin_audit", __name__)

_cfg = {}
_jobs_lock = None
generation_engine = None


def configure(*, admin_required, admin_token, admin_auth_ok, admin_auth_from_request,
              render_admin_gate, log_activity, client_ip, invalidate_voices_cache,
              vc_translate_reject_note, jobs, jobs_lock, engine):
    """Funzioni (risolte a ogni chiamata) e oggetti condivisi dalla app."""
    global generation_engine
    _cfg.update(admin_required=admin_required, admin_token=admin_token, admin_auth_ok=admin_auth_ok,
                admin_auth_from_request=admin_auth_from_request, render_admin_gate=render_admin_gate,
                log_activity=log_activity, client_ip=client_ip,
                invalidate_voices_cache=invalidate_voices_cache,
                vc_translate_reject_note=vc_translate_reject_note)
    _cfg["jobs"] = jobs
    globals()["_jobs_lock"] = jobs_lock
    generation_engine = engine


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _admin_token():
    return _cfg["admin_token"]()


def _jobs():
    # `jobs` come funzione: i test ribindano `audiobook_app.jobs`.
    return _cfg["jobs"]()


def _admin_auth_ok(provided):
    return _cfg["admin_auth_ok"](provided)


def _admin_auth_from_request():
    return _cfg["admin_auth_from_request"]()


def _render_admin_gate(title, target_url):
    return _cfg["render_admin_gate"](title, target_url)


def _log_activity(*a, **k):
    return _cfg["log_activity"](*a, **k)


def client_ip():
    return _cfg["client_ip"]()


def _invalidate_voices_cache():
    return _cfg["invalidate_voices_cache"]()


def _vc_translate_reject_note(clone_id):
    return _cfg["vc_translate_reject_note"](clone_id)


def admin_required(fn=None, *, as_json=True):
    """La guardia admin della app, applicata a ogni richiesta (le route del
    blueprint si decorano all'import, prima di `configure`)."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            return _cfg["admin_required"](as_json=as_json)(f)(*args, **kwargs)
        return wrapper
    return deco(fn) if fn is not None else deco


@bp.route("/admin/audit-premium", methods=["GET"])
def admin_audit_premium_page():
    """Admin dashboard unificata dei servizi premium: 4 tab (Audit TTS,
    Audit Traduzioni, Audit AI Optimization, Voci campionate). Sostituisce
    /admin/audit-tts e /admin/audit-translations."""
    if not _admin_token():
        return ("Admin audit premium UI disabled.", 404,
                {"Content-Type": "text/plain; charset=utf-8"})
    token = _admin_auth_from_request()
    if not _admin_auth_ok(token):
        return (_render_admin_gate("Audit Premium Services", "/admin/audit-premium"),
                200, {"Content-Type": "text/html; charset=utf-8"})
    html = _page_template("admin_audit_premium")
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.route("/admin/audit-tts", methods=["GET"])
def admin_logs_page():
    """Deprecato: unificato in /admin/audit-premium. Redirect."""
    return redirect("/admin/audit-premium#tab-tts", code=302)


@bp.route("/admin/audit-translations", methods=["GET"])
def admin_audit_translations_page():
    """Deprecato: unificato in /admin/audit-premium. Redirect."""
    return redirect("/admin/audit-premium#tab-translations", code=302)


_ACTIVE_JOB_STATUSES = ("queued", "running", "generating", "paused", "starting")


def _synth_running_gemini_audit_records():
    """Snapshot dei job PREMIUM attivi (Gemini + Speechify/Simba + VoxCPM) in
    forma audit-shaped.

    Permette a /admin/audit-tts di mostrare una riga immediatamente all'avvio
    di una generazione Premium, aggiornata ad ogni refresh con i dati di costo
    accumulati in `job["gemini_actual"]` (Gemini), `job["speechify_actual"]`
    (Simba) o `job["voxcpm_actual"]` (VoxCPM). Quando il job termina, la riga
    "running" sparisce e viene rimpiazzata dal record persistito nel JSONL.
    """
    out = []
    now_iso = datetime.now(timezone.utc).isoformat()
    with _jobs_lock:
        snapshot = list(_jobs().items())
    for job_id, job in snapshot:
        try:
            if not isinstance(job, dict):
                continue
            status = job.get("status", "")
            if status not in _ACTIVE_JOB_STATUSES:
                continue
            voice = job.get("voice") or job.get("opt_voice") or ""
            is_gem = _is_gemini_voice(voice)
            is_spe = _is_speechify_voice(voice)
            is_vox = _is_voxcpm_voice(voice)
            if not (is_gem or is_spe or is_vox):
                continue
            parts = voice.split(":")
            model_key = parts[1] if len(parts) >= 3 else "?"
            info = job.get("info")
            # Lingua della GENERAZIONE TTS (voce scelta dall'utente), non quella
            # dei metadata del libro: stessa fonte del record persistito
            # (`generation_engine._audit_language`), altrimenti la riga "running"
            # mostrava la lingua del libro e cambiava valore a job concluso
            # (es. libro con dc:language sporco -> "c").
            try:
                language = generation_engine._audit_language(job, info) or ""
            except Exception:
                language = _i18n.norm_lang(getattr(info, "language", "")) if info else ""
            payment = job.get("payment") or {}
            charged = float(payment.get("total_eur", 0) or 0)
            if charged <= 0:
                charged = generation_engine._tts_share_eur(
                    job.get("payment_amount_eur", 0), payment.get("llm_eur"))
            rate_raw = job.get("rate", "+0%")
            rate_pct = int(_parse_rate_pct(rate_raw))
            if is_gem:
                if gemini_tts is None:
                    continue
                ga = job.get("gemini_actual") or {}
                if model_key == "?":
                    model_key = ga.get("model_key") or "?"
                provider_cost_actual = float(ga.get("google_cost_eur", 0.0) or 0.0)
                # Mirror di _write_gemini_audit (generation_engine.py): la riga
                # "running" deve confrontare l'incasso col LISTINO (D1), non
                # col costo reale accumulato finora, altrimenti su Cloudflare
                # questa riga live urlerebbe una deriva prezzo falsa per
                # l'intera durata del job.
                pricing_cost_actual = float(
                    ga.get("pricing_cost_eur", provider_cost_actual) or provider_cost_actual)
                try:
                    should = gemini_tts.compute_user_price_eur(pricing_cost_actual, model_key)
                    should_have_been = float(should.get("user_price_eur", 0.0))
                except Exception:
                    should_have_been = 0.0
                chars_total = int(ga.get("chars", 0) or 0)
                audio_seconds = float(ga.get("audio_seconds", 0) or 0)
                pricing_cost_field = pricing_cost_actual
                vat_actual = float(ga.get("vat_eur", 0) or 0)
            elif is_vox:
                # Mirror di _write_voxcpm_audit: costo = tempo di GPU stimato
                # dai caratteri col tariffario VoxCPM, mai quello di Speechify
                # (altrimenti la riga live mostra costo 0 e delta_eur negativo
                # quanto l'incasso, e sballa l'aggregato della pagina).
                va = job.get("voxcpm_actual") or {}
                chars_metered = int(va.get("chars", 0) or 0)
                try:
                    price = voxcpm_tts.compute_user_price_eur(chars_metered, language)
                    provider_cost_actual = float(price.get("cost_usd", 0.0) or 0.0) * float(
                        speechify_tts.usd_eur_rate())
                    should_have_been = float(price.get("user_price_eur", 0.0) or 0.0)
                except Exception:
                    provider_cost_actual = 0.0
                    should_have_been = 0.0
                # Chiave fissa come in _write_voxcpm_audit: per le voci
                # campionate (voxcpm:mine:<token>) parts[1] e' "mine", non il
                # modello, e la riga live mostrava "mine" invece di "v2".
                model_key = "v2"
                chars_total = chars_metered
                audio_seconds = float(va.get("audio_seconds", 0) or 0)
                pricing_cost_field = provider_cost_actual
                vat_actual = 0.0
            else:  # Speechify / Simba
                sa = job.get("speechify_actual") or {}
                metered = int(sa.get("billable_chars", 0) or 0) or int(sa.get("chars", 0) or 0)
                try:
                    price = speechify_tts.compute_user_price_eur(metered)
                    provider_cost_actual = float(price.get("cost_usd", 0.0) or 0.0) * float(
                        speechify_tts.usd_eur_rate())
                    should_have_been = float(price.get("user_price_eur", 0.0) or 0.0)
                except Exception:
                    provider_cost_actual = 0.0
                    should_have_been = 0.0
                chars_total = int(sa.get("chars", 0) or 0)
                audio_seconds = float(sa.get("audio_seconds", 0) or 0)
                # Speechify non ha una separazione listino/costo reale (un
                # solo backend): coincide col costo, come nel record persistito.
                pricing_cost_field = provider_cost_actual
                vat_actual = 0.0
            delta_eur = round(should_have_been - charged, 4)
            _llm_quota = (job.get("payment") or {}).get("llm_eur")
            combined_total = (round(charged + float(_llm_quota or 0), 4)
                              if _llm_quota is not None else round(charged, 4))
            rec = {
                "ts": job.get("started_at") or now_iso,
                "job_id": job_id,
                "model_key": model_key,
                "language": language,
                "rate_pct": rate_pct,
                "chars_total": chars_total,
                "audio_seconds_actual": round(audio_seconds, 2),
                "google_cost_eur_actual": round(provider_cost_actual, 4),
                "vat_eur_actual": round(vat_actual, 4),
                "pricing_cost_eur_actual": round(pricing_cost_field, 4),
                "user_price_eur_charged": round(charged, 4),
                "user_price_eur_should_have_been": round(should_have_been, 2),
                "delta_eur": delta_eur,
                "margin_eur_actual": round(charged - provider_cost_actual, 4),
                "combined_total_eur": combined_total,
                "outcome": "running",
                "_live": True,
            }
            out.append(rec)
        except Exception:
            continue
    return out


def _synth_running_translation_audit_records():
    """Snapshot dei job di traduzione attivi (status "translating") in forma
    audit-shaped, per mostrare una riga live in /admin/audit-translations.

    Il costo parziale usa i token accumulati in `job["tr_usage"]` (aggiornato
    a fine di ogni capitolo da run_translation). Quando il job termina la riga
    "running" sparisce e viene rimpiazzata dal record persistito nel JSONL.
    """
    out = []
    now_iso = datetime.now(timezone.utc).isoformat()
    with _jobs_lock:
        snapshot = list(_jobs().items())
    for job_id, job in snapshot:
        try:
            if not isinstance(job, dict):
                continue
            if job.get("status", "") != "translating":
                continue
            p = job.get("tr_params") or {}
            source_lang = (p.get("source_lang") or "").lower()
            target_lang = (p.get("target_lang") or "").lower()
            optimize = bool(p.get("optimize"))
            chars_total = int(job.get("tr_total_chars", 0) or 0)
            ur = job.get("tr_usage") or {}
            prompt_tokens = int(ur.get("prompt_tokens", 0) or 0)
            completion_tokens = int(ur.get("completion_tokens", 0) or 0)
            cost_eur = payment._translation_provider_cost_eur(
                prompt_tokens, completion_tokens)
            pay = job.get("payment") or {}
            charged = float(pay.get("total_eur", 0) or 0)
            if charged <= 0:
                charged = float(job.get("payment_amount_eur", 0) or 0)
            est = payment._estimate_translation_cost_eur(chars_total, optimize=optimize)
            should_have_been = float(est.get("due_eur", 0.0) or 0.0)
            _llm_quota = (job.get("payment") or {}).get("llm_eur")
            combined_total = (round(charged + float(_llm_quota or 0), 4)
                              if _llm_quota is not None else round(charged, 4))
            rec = {
                "ts": job.get("started_at") or now_iso,
                "job_id": job_id,
                "backend": job.get("tr_backend", "") or "",
                "model_key": job.get("tr_model", "") or "",
                "source_lang": source_lang,
                "target_lang": target_lang,
                "optimize": optimize,
                "chars_total": chars_total,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "tokens_estimated": bool(ur.get("estimated", False)),
                "google_cost_eur_actual": round(cost_eur, 6),
                "user_price_eur_charged": round(charged, 4),
                "user_price_eur_should_have_been": round(should_have_been, 2),
                "delta_eur": round(should_have_been - charged, 4),
                "margin_eur_actual": round(charged - cost_eur, 4),
                "combined_total_eur": combined_total,
                "payment_method": pay.get("method", "") or "",
                "outcome": "running",
                "_live": True,
            }
            out.append(rec)
        except Exception:
            continue
    return out


def _synth_running_optimization_audit_records():
    """Snapshot dei job in ottimizzazione (status "optimizing") in forma
    audit-shaped, per la riga live nella tab AI Optimization.

    Costo parziale dai token accumulati in job["opt_usage"]. Revenue = quota
    LLM (payment.llm_eur se combinato, altrimenti total_eur). Quando il job
    termina la riga "running" sparisce, rimpiazzata dal record JSONL.
    """
    out = []
    now_iso = datetime.now(timezone.utc).isoformat()
    with _jobs_lock:
        snapshot = list(_jobs().items())
    for job_id, job in snapshot:
        try:
            if not isinstance(job, dict):
                continue
            if job.get("status", "") != "optimizing":
                continue
            ur = job.get("opt_usage") or {}
            prompt_tokens = int(ur.get("prompt_tokens", 0) or 0)
            completion_tokens = int(ur.get("completion_tokens", 0) or 0)
            cost_eur = payment._optimization_provider_cost_eur(
                prompt_tokens, completion_tokens)
            chars_total = int(job.get("opt_total_chars", 0) or 0)
            pay = job.get("payment") or {}
            total_eur = float(pay.get("total_eur", 0) or 0)
            llm_eur = pay.get("llm_eur")
            if llm_eur is not None:
                charged = float(llm_eur or 0)
                combined_total = round(total_eur + charged, 4)
            else:
                charged = total_eur
                if charged <= 0:
                    charged = float(job.get("payment_amount_eur", 0) or 0)
                combined_total = round(charged, 4)
            _lp_shb = payment.llm_price_eur(chars_total,
                                            is_combined=(llm_eur is not None))
            # Standalone (llm_eur is None): il floor minimo alza il prezzo atteso
            # cosi' il delta rispetto all'incassato e' coerente. Combinato: la
            # quota LLM non ha floor, resta la stima grezza. Fonte unica:
            # payment.llm_price_eur.
            should_have_been = _lp_shb["due_eur"]
            rec = {
                "ts": job.get("started_at") or now_iso,
                "job_id": job_id,
                "model_key": getattr(generation_engine, "LLM_MODEL", "") or "",
                "language": (job.get("opt_lang") or "").lower(),
                "chars_total": chars_total,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "tokens_estimated": bool(ur.get("estimated", False)),
                "google_cost_eur_actual": round(cost_eur, 6),
                "user_price_eur_charged": round(charged, 4),
                "user_price_eur_should_have_been": round(should_have_been, 2),
                "delta_eur": round(should_have_been - charged, 4),
                "margin_eur_actual": round(charged - cost_eur, 4),
                "combined_total_eur": combined_total,
                "payment_method": pay.get("method", "") or "",
                "outcome": "running",
                "_live": True,
            }
            out.append(rec)
        except Exception:
            continue
    return out


# Outcome che rappresentano un rimborso TOTALE all'utente: il ricavo
# effettivo e' 0 a prescindere da `user_price_eur_charged` originario.
# I `cancelled_partial` sono trattati a parte tramite `cancel_retained_eur`.
_FULL_REFUND_OUTCOMES = frozenset({
    "failed_refunded",
    "failed_quota_refunded",
    "failed_budget_refunded",
    "failed_quality_refunded",
    "failed_no_output_refunded",
    "failed_all_chunks_refunded",
    "preflight_blocked_refunded",
    "cancelled_refunded",
})


def _compute_paypal_fee_eur(revenue_eur, payment_method, combined_total_eur=None):
    """Stima fee PayPal addebitata sul ricavo PER QUESTO record.

    Applica la formula PayPal standard (`% gross + fissa`) solo se il record
    è stato pagato via PayPal e ha ricavo > 0; altrimenti ritorna 0:
    - `voucher`: PayPal non e' coinvolto (lo era stato all'origine del voucher,
      ma la fee era gia` stata pagata in quella transazione → non si addebita
      due volte qui).
    - rimborso totale (revenue_eur = 0): la fee viene quasi sempre trattenuta
      da PayPal anche sui rimborsi, ma per l'audit del margine sul singolo job
      consideriamo 0 (non c'e' ricavo da decurtare).
    - free (nessun pagamento): 0.
    - record legacy senza `payment_method`: 0 (conservativo: non assumiamo
      paypal in assenza di dato).
    """
    try:
        rev = float(revenue_eur or 0)
    except (TypeError, ValueError):
        return 0.0
    if rev <= 0:
        return 0.0
    if (payment_method or "").lower() != "paypal":
        return 0.0
    if gemini_tts is None:
        return 0.0
    try:
        pct = float(gemini_tts.PAYPAL_PERCENT_FEE)
        fixed = float(gemini_tts.PAYPAL_FIXED_FEE_EUR)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    # Fee fissa ripartita in proporzione al prezzo quando il pagamento copre
    # piu' servizi premium in un'unica transazione PayPal (combined_total_eur =
    # somma delle quote). Per servizio singolo/legacy (combined assente o <= rev)
    # la fissa resta piena. La percentuale e' sempre sul revenue del servizio
    # (naturalmente additiva, nessun doppio conteggio).
    try:
        combined = float(combined_total_eur) if combined_total_eur is not None else rev
    except (TypeError, ValueError):
        combined = rev
    if combined <= 0:
        combined = rev
    fixed_share = fixed * rev / combined if combined > 0 else fixed
    return round(rev * pct / 100.0 + fixed_share, 4)


def _apply_cancel_effective(rec):
    """Augmenta il record con `_eff_*` che riflettono i rimborsi reali.

    - `cancelled_partial`: ricavo = quota trattenuta (`cancel_retained_eur`),
      a copertura del consumato; eventuale eccedenza restituita.
    - `*_refunded` (rimborso totale: qualita`/quota/budget/preflight/cancel
      pre-attivita`/failure generico): ricavo = 0, quindi margine = -costo.
    - altri (completed, running, ...): ricavo = `user_price_eur_charged`.

    Aggiunge inoltre `_paypal_fee_eur` e `_net_margin_eur` (margine al netto
    delle fee PayPal: zero per voucher/free).
    """
    if not isinstance(rec, dict):
        return rec
    charged = float(rec.get("user_price_eur_charged", 0) or 0)
    cost = float(rec.get("google_cost_eur_actual", 0) or 0)
    # Base per la % di deriva: LISTINO quando il record la porta (Gemini,
    # dopo la separazione prezzo/costo reale), altrimenti il costo (unica
    # nozione di costo per Speechify/traduzione/ottimizzazione). Coincide con
    # `cost` quando Cloudflare non e' configurato o il record non e' Gemini:
    # nessun cambio di comportamento in quei casi.
    drift_base = float(rec.get("pricing_cost_eur_actual", cost) or cost)
    should = float(rec.get("user_price_eur_should_have_been", 0) or 0)
    cancel_retained = rec.get("cancel_retained_eur")
    outcome = rec.get("outcome") or ""
    if outcome in _FULL_REFUND_OUTCOMES:
        revenue = 0.0
    elif rec.get("llm_refunded_eur"):
        # Ottimizzazione consegnata ma restituita col job premium fallito:
        # il costo resta, il ricavo no (marker `llm_refunded`).
        revenue = 0.0
    elif cancel_retained is not None:
        revenue = float(cancel_retained or 0)
    else:
        revenue = charged
    rec["_eff_revenue_eur"] = round(revenue, 4)
    rec["_eff_margin_eur"] = round(revenue - cost, 4)
    rec["_eff_delta_eur"] = round(should - revenue, 4)
    rec["_eff_delta_pct"] = round((rec["_eff_delta_eur"] / drift_base * 100), 2) if drift_base > 0 else 0.0
    fee = _compute_paypal_fee_eur(revenue, rec.get("payment_method", ""),
                                  combined_total_eur=rec.get("combined_total_eur"))
    rec["_paypal_fee_eur"] = round(fee, 4)
    rec["_net_margin_eur"] = round(revenue - cost - fee, 4)
    return rec


# Soglia di "importo zero": mezzo centesimo. Sotto, la riga non e' una
# transazione ma un uso gratuito (voce standard, ottimizzazione sotto la
# soglia free, voce campionata omaggio).
_AUDIT_ZERO_EUR = 0.005


def _audit_has_amount(rec):
    """Vero se la riga porta un importo addebitato all'utente.

    Criterio: l'ADDEBITO (`user_price_eur_charged`), non il ricavo effettivo.
    Un job rimborsato resta una transazione (addebito > 0, ricavo 0) e deve
    restare visibile; un job gratuito no.
    """
    if not isinstance(rec, dict):
        return True
    try:
        charged = float(rec.get("user_price_eur_charged", 0) or 0)
    except (TypeError, ValueError):
        charged = 0.0
    return charged >= _AUDIT_ZERO_EUR


def _audit_hide_zero(args):
    """Il filtro "nascondi transazioni a importo zero" della UI audit."""
    return str(args.get("hide_zero", "")).strip().lower() in ("1", "true", "yes", "on")


@bp.route("/admin/api/gemini_cost_audit", methods=["GET"])
@admin_required
def admin_api_gemini_cost_audit():
    """List Gemini TTS audit records with filters + aggregates. Admin-only.

    Restituisce, in aggiunta ai record persistiti su JSONL, righe sintetiche
    `outcome="running"` per i job Gemini attualmente in corso (snapshot live).
    Ogni record viene arricchito con campi `_eff_*` che applicano i rimborsi
    da cancellazione anticipata su ricavo/margine/delta.
    """

    import gemini_cost_audit
    model = request.args.get("model")
    language = request.args.get("language")
    outcome = request.args.get("outcome")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid limit/offset"}), 400

    def _norm(v):
        return v if v and v != "all" else None

    persisted = list(gemini_cost_audit.iter_records(
        model=_norm(model), language=_norm(language), outcome=_norm(outcome),
        date_from=date_from, date_to=date_to,
    ))
    persisted_ids = {r.get("job_id") for r in persisted}

    # Inietta i job in corso: rispetta i filtri model/lang; outcome="running"
    # e' visibile solo quando outcome=all o esattamente "running".
    # NB: la riga live NON viene piu' soppressa quando esiste gia' un record
    # persistito per lo stesso job_id (vecchio comportamento): un job
    # ri-lanciato dal recovery dopo un esito terminale (es.
    # failed_quality_refunded) era ATTIVO ma invisibile nell'audit
    # (incidente jgIehwtzU2D6jog1S8f5vw, 2026-06). Ora la riga live viene
    # mostrata sempre e marcata `_rerun` se il job_id ha gia' storia
    # persistita, cosi' l'admin vede sia il run corrente sia gli esiti
    # precedenti.
    live = []
    out_filter = _norm(outcome)
    if out_filter in (None, "running"):
        for r in _synth_running_gemini_audit_records():
            if _norm(model) and r.get("model_key") != _norm(model):
                continue
            if _norm(language) and r.get("language") != _norm(language):
                continue
            if r.get("job_id") in persisted_ids:
                r["_rerun"] = True
            live.append(r)

    # I JSONL di audit sono append-only in ordine cronologico CRESCENTE: senza
    # questo sort la paginazione (limit=200) taglierebbe i record piu' RECENTI
    # invece dei piu' vecchi, e i job di oggi sparirebbero dalla tabella.
    persisted.sort(key=lambda r: r.get("ts") or "", reverse=True)

    recs = live + persisted
    for r in recs:
        _apply_cancel_effective(r)
    # `hide_zero`: via le righe senza addebito. Filtra PRIMA degli aggregati,
    # come gli altri filtri, cosi' i totali descrivono sempre la tabella.
    if _audit_hide_zero(request.args):
        recs = [r for r in recs if _audit_has_amount(r)]
    total = len(recs)
    page = recs[offset:offset + limit]

    # Aggregati ricomputati sui record arricchiti (solo "completed" + i live
    # in corso, esclusi rimborsi totali). Ricavo/margine usano _eff_* per
    # tener conto dei rimborsi da cancel.
    agg_n = 0
    agg_rev = 0.0
    agg_cost = 0.0
    agg_pricing_cost = 0.0
    agg_delta = 0.0
    agg_fee = 0.0
    for r in recs:
        oc = r.get("outcome") or ""
        if oc not in ("completed", "running", "cancelled_partial"):
            continue
        agg_n += 1
        agg_rev += float(r.get("_eff_revenue_eur", 0) or 0)
        google_cost_actual = float(r.get("google_cost_eur_actual", 0) or 0)
        agg_cost += google_cost_actual
        # Base del delta_pct_avg: LISTINO (D1), non costo reale (vedi
        # gemini_cost_audit.aggregate() per lo stesso pattern). Il costo
        # reale (agg_cost) resta usato per margin_eur/net_margin_eur, che
        # riguardano la marginalita' effettiva, non il confronto di prezzo.
        agg_pricing_cost += float(
            r.get("pricing_cost_eur_actual", google_cost_actual) or google_cost_actual)
        agg_delta += float(r.get("_eff_delta_eur", 0) or 0)
        agg_fee += float(r.get("_paypal_fee_eur", 0) or 0)
    agg = {
        "count": agg_n,
        "revenue_eur": round(agg_rev, 4),
        "google_cost_eur": round(agg_cost, 4),
        "margin_eur": round(agg_rev - agg_cost, 4),
        "paypal_fees_eur": round(agg_fee, 4),
        "net_margin_eur": round(agg_rev - agg_cost - agg_fee, 4),
        "delta_pct_avg": round((agg_delta / agg_pricing_cost * 100), 2) if agg_pricing_cost > 0 else 0.0,
        "filters": {"model": _norm(model), "language": _norm(language),
                    "date_from": date_from, "date_to": date_to},
    }
    return jsonify({"records": page, "count": total, "aggregates": agg})


@bp.route("/admin/api/gemini_kill_switch", methods=["GET", "POST"])
@admin_required
def admin_api_gemini_kill_switch():
    """Kill-switch admin per disattivare runtime le voci PREMIUM.

    GET  -> stato corrente {disabled, reason, updated_at, capability_ok}.
    POST -> attiva/disattiva. Body JSON: {"disabled": bool, "reason": str?}.

    Quando disabled=True, gemini_tts.is_available() ritorna False e il
    pannello Voci PREMIUM scompare dalla UI utente (incluse stime e flusso
    di pagamento Premium, che gia` gateano su is_available()).
    """

    if gemini_tts is None:
        return jsonify({"error": "Gemini TTS module not loaded"}), 503

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        disabled = bool(data.get("disabled", False))
        reason = str(data.get("reason", "") or "")
        state = gemini_tts.set_admin_disabled(disabled, reason)
        # Invalida la cache voci cosi` la prossima /api/voices riflette subito
        # il cambio (rimozione/aggiunta dell'optgroup PREMIUM).
        _invalidate_voices_cache()
        _log_activity("", "", "ADMIN_GEMINI_KILLSWITCH", "", client_ip(),
                      "disabled" if disabled else "enabled", reason[:80])
        print(f"[admin] Gemini PREMIUM kill-switch: "
              f"{'DISABLED' if disabled else 'ENABLED'} reason={reason!r}")
        return jsonify({**state, "capability_ok": _gemini_capability_ok()})

    return jsonify({
        **gemini_tts.admin_disabled_state(),
        "capability_ok": _gemini_capability_ok(),
    })


# Sonde manuali in corso, una per model_key. La sonda vera dura fino al
# timeout di produzione (65s in prod), percio' NON viene eseguita dentro la
# richiesta HTTP dell'admin: un reverse proxy con `proxy_read_timeout` a 60s
# taglierebbe la connessione e la console mostrerebbe un 504 su una sonda
# perfettamente viva, che intanto rientra o fallisce senza che nessuno lo
# veda. Parte quindi in un thread e la console rilegge lo stato persistito,
# che e' gia' la fonte di verita' per la sonda automatica.
_manual_probe_running = set()
_MANUAL_PROBE_LOCK = threading.Lock()


def _manual_probe_start(model_key):
    """Avvia una sonda manuale in background. False se ce n'e' gia' una.

    Il guard non e' cosmetico: `probe_cloudflare` scrive sullo stato
    persistito (contatore dei tentativi, ultimo errore) e due sonde
    sovrapposte sullo stesso modello produrrebbero due misure che si
    sovrascrivono a vicenda, con l'admin che legge l'esito della prima
    credendolo quello della seconda. Un click ripetuto sul pulsante e' il
    caso normale, non quello patologico.
    """
    with _MANUAL_PROBE_LOCK:
        if model_key in _manual_probe_running:
            return False
        _manual_probe_running.add(model_key)

    def _run():
        try:
            esito = gemini_tts.probe_cloudflare(model_key, manual=True)
            print(f"[admin] sonda manuale {model_key}: {esito}", flush=True)
        except Exception as e:
            # probe_cloudflare non solleva mai, ma questo thread non deve
            # poter morire lasciando `_manual_probe_running` sporco: da li'
            # in poi il pulsante resterebbe bloccato fino al riavvio.
            print(f"[admin] sonda manuale {model_key} esplosa "
                  f"({type(e).__name__}: {e})", flush=True)
        finally:
            with _MANUAL_PROBE_LOCK:
                _manual_probe_running.discard(model_key)

    threading.Thread(target=_run, daemon=True,
                     name=f"cf-probe-manual-{model_key}").start()
    return True


def _probe_payload(model_key):
    """Vista JSON dell'appuntamento della sonda di rientro.

    Non solleva mai: il pannello «Backend TTS» deve continuare a mostrare lo
    stato del breaker anche se la sonda non e' disponibile (modulo TTS non
    caricato, stato senza campi di sonda perche' scritto da una versione
    precedente). In quel caso i campi ci sono comunque, a None: il contratto
    non cambia forma fra installazioni, cosi' il client non deve gestirne due.
    """
    with _MANUAL_PROBE_LOCK:
        in_corso = model_key in _manual_probe_running
    vuoto = {"probe_enabled": False, "probe_next_at": None,
             "probe_in_sec": None, "probe_attempts": 0,
             "probe_last_error": None, "probe_delay_sec": 0,
             "probe_running": in_corso}
    try:
        info = tts_backend_state.probe_info(model_key)
        nxt = info.get("next_at")
        return {
            "probe_enabled": bool(gemini_tts is not None
                                  and gemini_tts._cf_probe_enabled()),
            "probe_next_at": nxt,
            "probe_in_sec": None if not nxt else max(0, int(nxt - time.time())),
            "probe_attempts": info.get("attempts", 0),
            "probe_last_error": info.get("last_error"),
            "probe_delay_sec": info.get("delay_sec", 0),
            # Riguarda la sola sonda MANUALE: quella automatica gira dentro
            # il sorvegliante e la console non la vede mai in corso, la vede
            # solo nei suoi effetti.
            "probe_running": in_corso,
        }
    except Exception:
        return vuoto


def _tts_backend_payload(model_key, configured_backend):
    """Vista JSON completa dello stato del backend TTS.

    Estratta perche' ogni risposta dell'endpoint - GET, reset,
    topup e sonda manuale - deve avere la STESSA forma. Una
    risposta parziale (per esempio il solo blocco `probe_*` della
    sonda) arriva al pannello come uno stato in cui
    `configured_backend` manca, e `tbApply` la leggerebbe come
    «Cloudflare non configurato»: il pulsante appena premuto
    spegnerebbe il pannello che doveva aggiornare.
    """
    s = tts_backend_state.state(model_key)
    return {
        "model_key": model_key,
        # Ripiego sulla configurazione dichiarata, mai sulla stringa
        # "cloudflare": su un'installazione pulita `state()` ritorna {} e un
        # default fisso faceva scrivere al pannello «Cloudflare non
        # configurato · il TTS gira su cloudflare», che si contraddice da
        # solo nella prima riga che un admin legge dopo il deploy.
        "active": s.get("active") or configured_backend,
        "tripped_at": s.get("tripped_at"),
        "trip_reason": s.get("trip_reason"),
        "trip_detail": s.get("trip_detail"),
        "trip_job_id": s.get("trip_job_id"),
        "consecutive_failures": s.get("consecutive_failures", 0),
        # Stato della sonda di rientro. `probe_next_at` viaggia come epoch
        # (float), la stessa forma in cui e' persistito: e' l'unico campo
        # dello stato che sia un istante confrontabile invece di una marca
        # ISO, e convertirlo qui obbligherebbe il pannello a ri-parsarlo per
        # calcolare «fra quanto». `probe_in_sec` e' il comodo derivato, gia'
        # clampato a zero per un appuntamento scaduto che il sorvegliante non
        # ha ancora raccolto.
        **_probe_payload(model_key),
        # USD e' l'importo autorevole (il credito Cloudflare e' denominato
        # in dollari); l'equivalente in euro viaggia accanto solo perche' il
        # pannello lo mostri a chi ragiona in euro, convertito con la stessa
        # ABM_GEMINI_USD_EUR_RATE usata dal resto dell'app.
        "credit_left_usd": round(tts_backend_state.credit_left_usd(), 2),
        "credit_left_eur": round(
            tts_backend_state.to_eur(tts_backend_state.credit_left_usd()), 2),
        # Il residuo viaggia SEMPRE, anche a controllo spento: il campo non
        # sparisce mai dal contratto, cosi' nessun client deve gestire due
        # forme di payload. E' il pannello a decidere cosa mostrarne.
        "credit_check_enabled": tts_backend_state.credit_check_enabled(),
        "credit_spent_usd": round(tts_backend_state.credit_spent_usd(), 2),
        "credit_spent_eur": round(
            tts_backend_state.to_eur(tts_backend_state.credit_spent_usd()), 2),
        "configured_backend": configured_backend,
    }


@bp.route("/admin/api/tts_backend", methods=["GET", "POST"])
@admin_required
def admin_api_tts_backend():
    """Stato del backend TTS (Cloudflare/Vertex), rientro manuale su
    Cloudflare e azzeramento del ledger di spesa dopo una ricarica.

    GET  -> stato corrente del modello (default flash31).
    POST -> {"action": "reset"}: riattiva Cloudflare (breaker + cache).
    POST -> {"action": "topup"}: azzera il ledger della spesa dopo una
            ricarica del credito, e NON tocca il breaker.
    POST -> {"action": "probe"}: esegue SUBITO una sonda di rientro, senza
            aspettare l'appuntamento automatico. E' la sola azione che
            misura il backend invece di dichiararlo sano: sintetizza una
            parola, butta l'audio e, se Cloudflare risponde, rientra da
            sola. Un fallimento non allunga l'appuntamento automatico (vedi
            `gemini_tts.probe_cloudflare(manual=True)`), altrimenti
            guardare piu' spesso farebbe ricontrollare piu' di rado.
            Risponde 202 con la sonda avviata in background: dura quanto il
            timeout di produzione e non puo' stare dentro la richiesta HTTP.

    Perche' il topup e' un'azione a se' e non piu' un campo del rientro:
    `tts_backend_state.reset_spend()` e' l'unica cosa che riarma il
    pre-allarme sul credito, e il ciclo normale del credito non passa mai da
    un trip (residuo sotto soglia -> email di pre-allarme -> ricarica ->
    topup, con Cloudflare ancora sano). Finche' l'unico innesco era la
    casella accanto al pulsante di rientro — abilitato solo DOPO un trip —
    l'allarme partiva una volta sola nella vita dell'installazione e il
    residuo mostrato in console restava sbagliato per sempre, perche' il
    saldo dichiarato veniva rialzato mentre `spent_usd` continuava ad
    accumulare dal ciclo precedente. Il campo `topup` dentro `action="reset"`
    e' stato quindi rimosso; per non perdere in silenzio l'intenzione di un
    chiamante che usasse ancora la forma vecchia, un `topup` VERO in un
    `action="reset"` e' rifiutato con 400 invece di essere ignorato.

    Questo endpoint non e' piu' l'unica via di rientro, ma resta l'unica
    IMMEDIATA. L'altra e' la sonda di rientro (`gemini_tts.probe_cloudflare`,
    innescata dal sorvegliante `_cf_probe_supervisor`): poche parole di
    sintesi in background, senza alcun utente collegato, a intervalli che
    raddoppiano a ogni fallimento. L'obiezione storica al ripristino
    automatico - «un backend caduto per credito esaurito tornerebbe a cadere
    subito, e ogni caduta costa un job» - vale per un rientro tentato con un
    JOB VERO, non per una sonda che costa una richiesta rifiutata. I job non
    riprovano mai Cloudflare da soli: il rientro avviene sempre fra un job e
    l'altro.

    La risposta espone percio' anche l'appuntamento della sonda
    (`probe_*`), perche' l'admin sappia se aspettare o premere il pulsante.

    Punto delicato: il breaker vive in due posti, lo stato persistito su
    disco (tts_backend_state) e la cache in-process gemini_tts._BACKEND,
    consultata a ogni sintesi. Un reset che tocca solo il disco risponde OK
    ma non cambia nulla fino al riavvio del processo (gemini_tts._resolve_backend
    congela il backend risolto in _BACKEND fino al prossimo cache-miss).
    Il reset qui sotto invalida percio' anche la cache per TUTTI i model_key
    noti (gemini_tts.GEMINI_MODELS), non solo quello passato: ogni modello,
    target compreso, si ririsolve da solo rispettando il proprio stato reale
    (pop, mai un valore forzato). Un `_set_backend(model_key, "cloudflare")`
    forzato qui sarebbe un bug: scavalcherebbe `_resolve_backend`, cioe' la
    configurazione dichiarata e la presenza di `id_cloudflare`, inchiodando
    su Cloudflare anche un modello che Cloudflare non ospita - da li' in poi
    ogni job PREMIUM su quel modello finirebbe in errore con rimborso
    integrale, fino al riavvio del processo.

    Due guardie sull'ingresso, valide per ENTRAMBE le azioni ed entrambe
    indispensabili perche' quelle lato client (i bottoni disabilitati in
    `tbApply`) sono scavalcabili da una chiamata diretta all'API:

    - `model_key` deve essere una chiave nota: `reset()` materializza la voce
      su disco, quindi una chiave inventata sporcherebbe per sempre lo stato
      persistito con un modello inesistente. Il topup non materializza nulla,
      ma la chiave finisce comunque nella risposta e nell'activity log: una
      forense sul credito deve leggere un modello vero, non quello che
      qualcuno ha digitato per sbaglio;
    - l'azione ha senso solo se l'ambiente seleziona davvero Cloudflare
      (`ABM_GEMINI_BACKEND == "cloudflare"`). Altrimenti la console direbbe
      all'admin di aver riacceso un backend che nessuna sintesi usera' mai,
      o di aver riarmato un allarme su una spesa che nessuno accumulera'.

    `model_key` e' coerciuto a stringa PRIMA di qualunque confronto: arriva
    anche dal corpo JSON, dove una lista o un dict e' sintatticamente
    legittima e renderebbe `model_key not in GEMINI_MODELS` un
    `TypeError: unhashable` (500 su un input malformato, invece del 400 gia'
    previsto per una chiave sconosciuta).

    Sicurezza: `trip_detail` e' persistito e loggato senza redazione (vedi
    tts_backend_state) - puo' contenere solo testo diagnostico (mai
    token/credenziali, responsabilita' del chiamante che invoca trip()).
    Qui viaggia cosi' com'e' nel JSON di risposta; il rendering HTML lato
    client deve trattarlo come testo non fidato (escape), mai come markup.
    """
    if gemini_tts is None:
        return jsonify({"error": "Gemini TTS module not loaded"}), 503

    # str() prima di ogni uso: `model_key` puo' arrivare dal corpo JSON come
    # lista/dict, e un valore unhashable farebbe esplodere in TypeError sia il
    # confronto con GEMINI_MODELS sia `tts_backend_state.state()` (500 invece
    # del 400 previsto per una chiave sconosciuta).
    model_key = str(request.args.get("model_key")
                    or (request.get_json(silent=True) or {}).get("model_key")
                    or "flash31")
    configured_backend = (env_str("ABM_GEMINI_BACKEND", "auto")
                          or "auto").strip().lower()

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        action = str(data.get("action", "") or "").strip().lower()
        if action not in ("reset", "topup", "probe"):
            return jsonify({"error": f"Azione non riconosciuta: {action!r}"}), 400
        if action == "reset" and data.get("topup"):
            # Forma vecchia dell'API (il topup come campo del rientro): non
            # viene ignorata in silenzio, perche' ignorarla lascerebbe il
            # ledger intatto facendo credere il contrario a chi ha appena
            # ricaricato - cioe' proprio il residuo sbagliato che l'azione
            # dedicata esiste per evitare.
            return jsonify({
                "error": ("Il campo 'topup' non e' piu' accettato da "
                          "action='reset': l'azzeramento del contatore di "
                          "spesa e' ora l'azione dedicata "
                          "action='topup', raggiungibile anche senza alcun "
                          "failover in corso."),
            }), 400
        if model_key not in gemini_tts.GEMINI_MODELS:
            # Il perche' del rifiuto dipende dall'azione: solo il reset
            # materializzerebbe una voce di stato. Motivare il topup con il
            # testo del reset descriverebbe un effetto che quell'azione non
            # ha, e manderebbe l'admin a cercare una voce di stato inesistente.
            if action == "reset":
                why = ("Il reset creerebbe una voce di stato per un modello "
                       "che non esiste.")
            elif action == "probe":
                why = ("La sonda chiede a Cloudflare l'id di un modello che "
                       "non conosciamo: non c'e' nulla da sintetizzare.")
            else:
                why = ("Il ledger della spesa Cloudflare e' unico per "
                       "l'account, ma il model_key resta tracciato nel log "
                       "dell'operazione.")
            return jsonify({
                "error": f"model_key sconosciuto: {model_key!r}. {why}",
                "known_model_keys": sorted(gemini_tts.GEMINI_MODELS),
            }), 400
        if configured_backend != "cloudflare":
            what = {"reset": "Rientro",
                    "probe": "Sonda di rientro"}.get(
                        action, "Azzeramento del contatore di spesa")
            why = {"reset": "riarmare il breaker",
                   "probe": "misurare Cloudflare"}.get(
                       action, "azzerare il ledger della spesa Cloudflare")
            return jsonify({
                "error": (f"{what} non applicabile: ABM_GEMINI_BACKEND vale "
                          f"{configured_backend!r}, non 'cloudflare'. Con "
                          f"questa configurazione la sintesi non usa "
                          f"Cloudflare in nessun caso, quindi {why} "
                          f"non cambierebbe nulla. Per riaccendere "
                          f"Cloudflare: impostare ABM_GEMINI_BACKEND="
                          f"cloudflare nell'unit systemd e riavviare il "
                          f"servizio."),
                "configured_backend": configured_backend,
            }), 409

        if action == "probe":
            # Nessun `reset()` e nessuna invalidazione di cache qui: la sonda
            # rientra DA SOLA se Cloudflare risponde (`_finish_cf_return`), e
            # fa gia' tutto il lavoro con la stessa disciplina del rientro
            # manuale. Un reset preventivo qui sarebbe il rientro alla cieca
            # che la sonda esiste proprio per evitare.
            avviata = _manual_probe_start(model_key)
            _log_activity("", "", "ADMIN_TTS_PROBE", "",
                          client_ip(), model_key,
                          f"avviata={avviata}")
            print(f"[admin] Sonda di rientro manuale richiesta per "
                  f"{model_key} (avviata: {avviata})")
            return jsonify({
                **_tts_backend_payload(model_key, configured_backend),
                "probe_started": avviata,
                "message": ("Sonda avviata: l'esito compare qui sotto entro "
                            "il timeout di produzione."
                            if avviata else
                            "Sonda gia' in corso su questo modello: "
                            "l'esito della prima vale anche per questo click."),
            }), (202 if avviata else 409)

        if action == "topup":
            # Solo il ledger: nessun `reset()`, nessuna invalidazione della
            # cache `gemini_tts._BACKEND`. Un modello scattato DEVE restare
            # scattato - aver ricaricato il credito non dimostra che la causa
            # del guasto sia stata risolta, e il rientro ha una sua conferma
            # separata.
            # Senza saldo dichiarato il "residuo" e' solo la spesa cambiata di
            # segno: un numero negativo che non significa nulla, e che il
            # pre-allarme stesso ignora (con saldo <= 0 non scatta mai). Meglio
            # dirlo che stamparlo come se fosse una misura.
            if tts_backend_state.declared_balance_usd() > 0:
                before = (f"residuo stimato prima: "
                          f"{tts_backend_state.credit_left_usd():.2f} USD")
            else:
                before = ("residuo non calcolabile: ABM_CF_CREDIT_BALANCE_USD "
                          "non dichiarato")
            tts_backend_state.reset_spend()
            _log_activity("", "", "ADMIN_TTS_CREDIT_TOPUP", "",
                          client_ip(), model_key,
                          f"ledger azzerato ({before})")
            print(f"[admin] Ledger spesa Cloudflare azzerato ({before}) - "
                  f"pre-allarme credito riarmato")
        else:
            had_trip = tts_backend_state.reset(model_key)
            # Invalida la cache in-process per ogni modello noto (pop, non
            # overwrite): un reset che lasciasse la cache degli altri modelli
            # intonsa sarebbe innocuo, ma lasciare quella del modello appena
            # resettato e' esattamente il difetto silenzioso descritto sopra.
            # Nessun valore forzato nemmeno per il target: il backend torna a
            # essere deciso da _resolve_backend alla prossima sintesi.
            with gemini_tts._BACKEND_LOCK:
                for known_key in gemini_tts.GEMINI_MODELS:
                    gemini_tts._BACKEND.pop(known_key, None)
            _log_activity("", "", "ADMIN_TTS_BACKEND_RESET", "",
                          client_ip(), model_key, f"had_trip={had_trip}")
            print(f"[admin] Backend TTS {model_key} riportato su Cloudflare "
                  f"(aveva trip: {had_trip})")

    return jsonify(_tts_backend_payload(model_key, configured_backend))


@bp.route("/admin/api/gemini_model_availability", methods=["GET", "POST"])
@admin_required
def admin_api_gemini_model_availability():
    """Stato "non disponibile" dei modelli Gemini senza failover e reset manuale."""
    if gemini_tts is None:
        return jsonify({"error": "Gemini TTS module not loaded"}), 503
    import gemini_availability
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        mk = str(data.get("model_key", "") or "")
        if data.get("action") != "reset" or mk not in gemini_tts.GEMINI_MODELS:
            return jsonify({"error": "bad request"}), 400
        gemini_availability.clear(mk)
        _invalidate_voices_cache()
        _log_activity("", "", "ADMIN_TTS_MODEL_RESET", "", client_ip(), mk, "")
    return jsonify({"models": gemini_availability.snapshot(),
                    "cooldown_sec": gemini_availability.cooldown_sec()})


def _gemini_capability_ok():
    """True se Gemini TTS e' tecnicamente configurato (a prescindere dal
    kill-switch). Usato dal pannello admin per distinguere 'spento per scelta'
    da 'non configurato'.
    """
    if gemini_tts is None:
        return False
    try:
        return bool(gemini_tts.is_capability_available())
    except Exception:
        return False


@bp.route("/admin/api/gemini_cost_audit/languages", methods=["GET"])
@admin_required
def admin_api_gemini_cost_audit_languages():
    """Restituisce le lingue distinte realmente presenti nei record audit Gemini.

    Usato dalla pagina /admin/audit-tts per popolare dinamicamente il filtro
    lingua con i codici effettivamente generati, evitando di confondere
    "lingue UI" con "lingue di generazione TTS".
    """

    import gemini_cost_audit
    seen = set()
    for rec in gemini_cost_audit.iter_records():
        lang = (rec.get("language") or "").strip().lower()
        if lang:
            seen.add(lang)
    return jsonify({"languages": sorted(seen)})


@bp.route("/admin/api/translation_cost_audit", methods=["GET"])
@admin_required
def admin_api_translation_cost_audit():
    """List record audit traduzioni con filtri + aggregati. Admin-only.

    Include righe sintetiche outcome="running" per i job di traduzione in
    corso. Ogni record e' arricchito con `_eff_*` (ricavo/margine effettivi
    dopo refund) da _apply_cancel_effective.
    """

    import translation_cost_audit
    model = request.args.get("model")
    source_lang = request.args.get("source_lang")
    target_lang = request.args.get("target_lang")
    outcome = request.args.get("outcome")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid limit/offset"}), 400

    def _norm(v):
        return v if v and v != "all" else None

    persisted = list(translation_cost_audit.iter_records(
        model=_norm(model), source_lang=_norm(source_lang),
        target_lang=_norm(target_lang), outcome=_norm(outcome),
        date_from=date_from, date_to=date_to,
    ))
    persisted_ids = {r.get("job_id") for r in persisted}

    live = []
    out_filter = _norm(outcome)
    if out_filter in (None, "running"):
        for r in _synth_running_translation_audit_records():
            if _norm(model) and r.get("model_key") != _norm(model):
                continue
            if _norm(source_lang) and r.get("source_lang") != _norm(source_lang):
                continue
            if _norm(target_lang) and r.get("target_lang") != _norm(target_lang):
                continue
            if r.get("job_id") in persisted_ids:
                r["_rerun"] = True
            live.append(r)

    # Ordine cronologico decrescente prima della paginazione: i JSONL sono
    # append-only (piu' vecchi in testa) e il taglio a `limit` scarterebbe
    # altrimenti i record piu' recenti. Vedi audit TTS.
    persisted.sort(key=lambda r: r.get("ts") or "", reverse=True)

    recs = live + persisted
    for r in recs:
        _apply_cancel_effective(r)
    if _audit_hide_zero(request.args):
        recs = [r for r in recs if _audit_has_amount(r)]
    total = len(recs)
    page = recs[offset:offset + limit]

    agg_n = 0
    agg_rev = 0.0
    agg_cost = 0.0
    agg_delta = 0.0
    agg_fee = 0.0
    for r in recs:
        oc = r.get("outcome") or ""
        if oc not in ("completed", "running"):
            continue
        agg_n += 1
        agg_rev += float(r.get("_eff_revenue_eur", 0) or 0)
        agg_cost += float(r.get("google_cost_eur_actual", 0) or 0)
        agg_delta += float(r.get("_eff_delta_eur", 0) or 0)
        agg_fee += float(r.get("_paypal_fee_eur", 0) or 0)
    agg = {
        "count": agg_n,
        "revenue_eur": round(agg_rev, 4),
        "google_cost_eur": round(agg_cost, 4),
        "margin_eur": round(agg_rev - agg_cost, 4),
        "paypal_fees_eur": round(agg_fee, 4),
        "net_margin_eur": round(agg_rev - agg_cost - agg_fee, 4),
        "delta_pct_avg": round((agg_delta / agg_cost * 100), 2) if agg_cost > 0 else 0.0,
        "filters": {"model": _norm(model), "source_lang": _norm(source_lang),
                    "target_lang": _norm(target_lang),
                    "date_from": date_from, "date_to": date_to},
    }
    return jsonify({"records": page, "count": total, "aggregates": agg})


@bp.route("/admin/api/translation_cost_audit/languages", methods=["GET"])
@admin_required
def admin_api_translation_cost_audit_languages():
    """Codici lingua origine/destinazione e modelli distinti nei record audit
    traduzioni. Popola i filtri di /admin/audit-translations."""

    import translation_cost_audit
    src, dst, models = set(), set(), set()
    for rec in translation_cost_audit.iter_records():
        s = (rec.get("source_lang") or "").strip().lower()
        t = (rec.get("target_lang") or "").strip().lower()
        mk = (rec.get("model_key") or "").strip()
        if s:
            src.add(s)
        if t:
            dst.add(t)
        if mk:
            models.add(mk)
    return jsonify({"source_langs": sorted(src),
                    "target_langs": sorted(dst),
                    "models": sorted(models)})


@bp.route("/admin/api/optimization_cost_audit", methods=["GET"])
@admin_required
def admin_api_optimization_cost_audit():
    """List record audit ottimizzazione AI con filtri + aggregati. Admin-only.

    Include righe sintetiche outcome="running" per i job in ottimizzazione.
    Ogni record e' arricchito con `_eff_*` da _apply_cancel_effective (la fee
    fissa PayPal e' ripartita proporzionalmente via combined_total_eur).
    """

    import optimization_cost_audit
    language = request.args.get("language")
    outcome = request.args.get("outcome")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid limit/offset"}), 400

    def _norm(v):
        return v if v and v != "all" else None

    persisted = list(optimization_cost_audit.iter_records(
        language=_norm(language), outcome=_norm(outcome),
        date_from=date_from, date_to=date_to,
    ))
    # Marker `llm_refunded` (quota AI restituita col job premium fallito):
    # non sono righe, si applicano al record del job. Letti senza filtri di
    # data, perche' il rimborso puo' cadere dopo la fine dell'intervallo.
    _llm_refunds = {
        m.get("job_id"): float(m.get("refund_eur", 0) or 0)
        for m in optimization_cost_audit.iter_records(outcome="llm_refunded")
        if m.get("outcome") == "llm_refunded"
    }
    persisted = [r for r in persisted if r.get("outcome") != "llm_refunded"]
    for r in persisted:
        if r.get("job_id") in _llm_refunds:
            r["llm_refunded_eur"] = _llm_refunds[r.get("job_id")]
    persisted_ids = {r.get("job_id") for r in persisted}

    live = []
    out_filter = _norm(outcome)
    if out_filter in (None, "running"):
        for r in _synth_running_optimization_audit_records():
            if _norm(language) and r.get("language") != _norm(language):
                continue
            if r.get("job_id") in persisted_ids:
                r["_rerun"] = True
            live.append(r)

    # Ordine cronologico decrescente prima della paginazione: i JSONL sono
    # append-only (piu' vecchi in testa) e il taglio a `limit` scarterebbe
    # altrimenti i record piu' recenti. Vedi audit TTS.
    persisted.sort(key=lambda r: r.get("ts") or "", reverse=True)

    recs = live + persisted
    for r in recs:
        _apply_cancel_effective(r)
    if _audit_hide_zero(request.args):
        recs = [r for r in recs if _audit_has_amount(r)]
    total = len(recs)
    page = recs[offset:offset + limit]

    agg_n = 0
    agg_rev = 0.0
    agg_cost = 0.0
    agg_fee = 0.0
    for r in recs:
        oc = r.get("outcome") or ""
        if oc not in ("completed", "running"):
            continue
        agg_n += 1
        agg_rev += float(r.get("_eff_revenue_eur", 0) or 0)
        agg_cost += float(r.get("google_cost_eur_actual", 0) or 0)
        agg_fee += float(r.get("_paypal_fee_eur", 0) or 0)
    net = agg_rev - agg_cost - agg_fee
    agg = {
        "count": agg_n,
        "revenue_eur": round(agg_rev, 4),
        "provider_cost_eur": round(agg_cost, 4),
        "margin_eur": round(agg_rev - agg_cost, 4),
        "paypal_fees_eur": round(agg_fee, 4),
        "net_margin_eur": round(net, 4),
        "margin_pct_avg": round((net / agg_cost * 100), 2) if agg_cost > 0 else 0.0,
        "filters": {"language": _norm(language),
                    "date_from": date_from, "date_to": date_to},
    }
    return jsonify({"records": page, "count": total, "aggregates": agg})


@bp.route("/admin/api/voice_clone_audit", methods=["GET"])
@admin_required
def admin_api_voice_clone_audit():
    """Una riga per voce campionata: incassi, costo GPU delle demo, margini,
    dispositivi, attivazione/scadenza, libri generati. Admin-only.

    `state`: paid (default: tutte le voci con un pagamento) | drafts | all |
    ready | demos | refunded | expired | deleted. `date_from`/`date_to`
    (YYYY-MM-DD, UTC) sulla data di pagamento; per le bozze la creazione.
    Mai il token della voce: solo l'id `vc_...`.
    """

    import voice_clone_audit
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid limit/offset"}), 400
    language = request.args.get("language")
    try:
        recs = voice_clone._all()
    except Exception as e:
        return jsonify({"error": f"voice store unavailable: {e}"}), 503
    try:
        usd_eur = float(speechify_tts.usd_eur_rate())
    except Exception:
        usd_eur = 1.0
    # Motivi di rifiuto ancora senza traduzione italiana: si ritentano qui.
    for r in recs:
        note = r.get("reject_note") if isinstance(r, dict) else None
        if isinstance(note, dict) and note.get("text") and not note.get("it"):
            _vc_translate_reject_note(r.get("id"))
    out = voice_clone_audit.report(
        recs,
        state=request.args.get("state") or "paid",
        language=language if language and language != "all" else None,
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
        usd_eur=usd_eur,
        fee_fn=lambda rev, method: _compute_paypal_fee_eur(rev, method),
        limit=limit, offset=offset,
        hide_zero=_audit_hide_zero(request.args),
    )
    return jsonify(out)


@bp.route("/admin/api/accounts_audit", methods=["GET"])
@admin_required
def admin_api_accounts_audit():
    """Anagrafica degli account dell'area personale: data di registrazione,
    ultimo accesso, sessioni attive, storico e cancellazione. Admin-only.

    `state`: all (default) | active | dormant | never | deleted.
    `q` cerca nell'email (gli account cancellati hanno gia' un segnaposto al
    posto dell'indirizzo: li trova solo per id). `date_from`/`date_to`
    (YYYY-MM-DD, UTC) sulla data di registrazione.
    """
    if not accounts.enabled():
        return jsonify({"error": "accounts disabled"}), 503
    try:
        limit = max(1, min(int(request.args.get("limit", 500)), 2000))
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid limit/offset"}), 400


    def _epoch(name, end=False):
        raw = (request.args.get(name) or "").strip()
        if not raw:
            return None
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        if end:
            d += timedelta(days=1)
        return int(d.timestamp())

    try:
        out = accounts.admin_list(
            state=(request.args.get("state") or "all").strip().lower(),
            q=(request.args.get("q") or "").strip(),
            date_from=_epoch("date_from"),
            date_to=_epoch("date_to", end=True),
            limit=limit, offset=offset,
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"accounts unavailable: {e}"}), 503
    return jsonify(out)


@bp.route("/admin/api/optimization_cost_audit/languages", methods=["GET"])
@admin_required
def admin_api_optimization_cost_audit_languages():
    """Codici lingua distinti nei record audit ottimizzazione. Popola i filtri
    della tab AI Optimization."""

    import optimization_cost_audit
    langs = set()
    for rec in optimization_cost_audit.iter_records():
        code = (rec.get("language") or "").strip().lower()
        if code:
            langs.add(code)
    return jsonify({"languages": sorted(langs)})


@bp.route("/admin/api/gemini_cost_audit/recalc-params", methods=["GET"])
@admin_required
def admin_api_gemini_recalc_params():
    """Aggrega audit records completed per (model, lang) e suggerisce tuning."""

    import gemini_cost_audit
    # Doppio raggruppamento:
    #   - groups_global: (model, lang)              — vista aggregata storica
    #   - groups_rate:   (model, lang, rate_step)   — calibrazione per velocità
    # La velocità incide direttamente sul prezzo proposto (estimate_audio_seconds
    # scala con rate_pct), quindi i delta vanno monitorati anche per rate.
    groups_global = {}
    groups_rate = {}
    for rec in gemini_cost_audit.iter_records(outcome="completed"):
        model = rec.get("model_key") or "?"
        lang = rec.get("language") or "?"
        # I record precedenti l'introduzione di rate_step potrebbero non averlo:
        # li trattiamo come rate_step=0 (velocità "normale").
        try:
            rstep = int(rec.get("rate_step") if rec.get("rate_step") is not None else 0)
        except Exception:
            rstep = 0
        groups_global.setdefault((model, lang), []).append(rec)
        groups_rate.setdefault((model, lang, rstep), []).append(rec)

    def _label_for(avg_delta_pct):
        if avg_delta_pct > 5:
            return "margine alto, valuta riduzione tariffa utente"
        if avg_delta_pct < -5:
            return "margine in perdita, valuta aumento tariffa utente o sec_per_kchars"
        return "parametri OK"

    def _rate_label(step):
        # Mappa step -> etichetta UI (cfr. SPEED_KEYS in app.js)
        return {-3: "vs", -2: "s", -1: "ss", 0: "n", 1: "sf", 2: "f", 3: "vf"}.get(int(step), str(step))

    # DELTA% = delta_eur / listino (pricing_cost_eur_actual), sempre sulla
    # base di LISTINO (D1), mai sul costo reale sostenuto dal backend che ha
    # eseguito il job: coerente con gemini_cost_audit.aggregate() e con
    # l'aggregato di admin_api_gemini_cost_audit(). Calcolato sui totali del
    # gruppo: piu` robusto della media semplice di percentuali (outlier su
    # record con costo molto piccolo). Fallback su google_cost_eur_actual per
    # record storici pre-esistenti alla separazione listino/reale (dove i due
    # numeri coincidevano comunque).
    def _avg_delta_pct(recs):
        d_sum = sum(float(r.get("delta_eur") or 0) for r in recs)
        c_sum = 0.0
        for r in recs:
            google_cost_actual = float(r.get("google_cost_eur_actual", 0) or 0)
            c_sum += float(r.get("pricing_cost_eur_actual", google_cost_actual) or google_cost_actual)
        return (d_sum / c_sum * 100.0) if c_sum > 0 else 0.0

    suggestions = []
    suggestions.append("=== Aggregato globale (model / lang) ===")
    if not groups_global:
        suggestions.append("  (nessun record disponibile)")
    for (model, lang), recs in sorted(groups_global.items()):
        if len(recs) < 3:
            suggestions.append(f"  [{model} / {lang}] (n={len(recs)}) campioni insufficienti (servono >=3)")
            continue
        avg = _avg_delta_pct(recs)
        suggestions.append(f"  [{model} / {lang}] (n={len(recs)}) avg delta {avg:+.2f}% — {_label_for(avg)}")

    suggestions.append("")
    suggestions.append("=== Per velocità (model / lang / rate_step) ===")
    if not groups_rate:
        suggestions.append("  (nessun record disponibile)")
    for (model, lang, rstep), recs in sorted(groups_rate.items()):
        n = len(recs)
        avg = _avg_delta_pct(recs)
        rate_pcts = [int(r.get("rate_pct") or 0) for r in recs]
        rp_min, rp_max = (min(rate_pcts), max(rate_pcts)) if rate_pcts else (0, 0)
        rp_str = f"{rp_min:+d}%" if rp_min == rp_max else f"{rp_min:+d}%..{rp_max:+d}%"
        head = f"  [{model} / {lang} / step={rstep:+d} ({_rate_label(rstep)}) {rp_str}] (n={n})"
        if n < 3:
            suggestions.append(f"{head} campioni insufficienti")
        else:
            suggestions.append(f"{head} avg delta {avg:+.2f}% — {_label_for(avg)}")
    return jsonify({
        "suggestions": suggestions,
        "groups_total": len(groups_global),
        "groups_evaluated": sum(1 for g in groups_global.values() if len(g) >= 3),
        "groups_by_rate_total": len(groups_rate),
        "groups_by_rate_evaluated": sum(1 for g in groups_rate.values() if len(g) >= 3),
    })
