"""Demo della voce campione sul worker VoxCPM, approvazione, rigenerazione,
rifiuto con rimborso (spec §3.5, §5.5, §7.4, §10).

Modulo foglia: `voice_clone`, `voxcpm_tts`, `payment`, stdlib. Mai
`audiobook_app`. Le notifiche (email, log, digest) arrivano da un notifier
iniettato con `configure()`.

Deviazione dichiarata dalla spec §10/§11: le due demo sono due job
successivi da un chunk con audio inline; `demo.runpod_job_id` resta None e
il recovery al riavvio rilancia la generazione saltando i file gia'
presenti. Motivo: `voxcpm_tts` non espone la ripresa di un job in volo e
ripetere un chunk da dieci secondi costa meno di aggiungerla.
"""
import os
import shutil
import subprocess
import threading
import time
import traceback

import payment
import voice_clone as vc
import voxcpm_tts

_notifier = None
_threads = {}                 # clone_id -> Thread
_threads_lock = threading.Lock()
_UNUSABLE_MARKERS = ("sample", "campione", "prompt")


class RegenExhausted(ValueError):
    """Rigenerazioni esaurite (§3.5, `ABM_VOICE_CLONE_REGEN_MAX`)."""


def configure(notifier=None):
    global _notifier
    _notifier = notifier


def _notify(event, rec, **extra):
    if _notifier is None:
        return
    try:
        _notifier(event, rec, **extra)
    except Exception as e:      # noqa: BLE001 - il notifier non blocca mai il flusso
        print(f"[voice_clone_demo] notifier {event} fallito per {rec.get('id')}: {type(e).__name__}", flush=True)


# ---------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------
def pcm_to_wav48(pcm_path, wav_path):
    """PCM s16le mono 48 kHz del worker -> wav (§5.5). Cancella il PCM."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "48000",
           "-ac", "1", "-i", pcm_path, wav_path]
    subprocess.run(cmd, check=True, timeout=120, capture_output=True)
    try:
        os.remove(pcm_path)
    except OSError:
        pass


def _is_unusable(exc):
    msg = str(exc).lower()
    return any(k in msg for k in _UNUSABLE_MARKERS)


def _demo_texts(rec):
    demo = rec.get("demo") or {}
    return ((vc.DEMO_NAMES[0], demo.get("common_text") or ""),
            (vc.DEMO_NAMES[1], demo.get("extra_text") or ""))


def generate_demos(clone_id, *, sleep=time.sleep):
    """Sincrona. Una demo per volta, ognuna un job da un chunk con audio
    inline (`key=""`). Ritenta `demo_retries()` volte per demo con pausa
    2**n s (tetto 30). Ritorna ("ok", "") | ("failed", ultimo errore) |
    ("unusable", errore) quando il worker rifiuta il campione (§10)."""
    rec = vc.get(clone_id)
    if rec is None:
        return "failed", "record assente"
    d = vc.voice_dir(rec["token"])
    os.makedirs(d, exist_ok=True)
    voice_id = vc.voice_id_of(rec)
    ultimo = ""
    for name, text in _demo_texts(rec):
        wav = os.path.join(d, name)
        if os.path.exists(wav):
            continue
        pcm = wav[:-4] + ".pcm"
        ok = False
        for tentativo in range(vc.demo_retries()):
            try:
                voxcpm_tts.synthesize_chapter([text], voice_id, pcm, key="")
                pcm_to_wav48(pcm, wav)
                ok = True
                break
            except voxcpm_tts.VoxcpmJobError as e:
                ultimo = f"{type(e).__name__}: {e}"[:300]
                if _is_unusable(e):
                    return "unusable", ultimo
            except Exception as e:      # noqa: BLE001 - ffmpeg, disco, rete
                ultimo = f"{type(e).__name__}: {e}"[:300]
            try:
                os.remove(pcm)
            except OSError:
                pass
            if tentativo + 1 < vc.demo_retries():
                sleep(min(30, 2 ** tentativo))
        if not ok:
            return "failed", ultimo
    return "ok", ""


# ---------------------------------------------------------------------------
# ciclo di generazione
# ---------------------------------------------------------------------------
def _run(clone_id):
    try:
        esito, dettaglio = generate_demos(clone_id)
    except Exception as e:      # noqa: BLE001
        traceback.print_exc()
        esito, dettaglio = "failed", f"{type(e).__name__}: {e}"[:300]
    t = time.time()
    last_seen = vc.get(clone_id)
    try:
        rec = last_seen
        if rec is None or rec.get("state") != "demos_generating":
            return
        demo = dict(rec.get("demo") or {})
        if esito == "ok":
            demo.update({"failed_at": None, "last_error": ""})
            out = vc.transition(clone_id, "demos_ready", {"demo": demo}, now=t)
            _notify("demos_ready", out)
        elif esito == "unusable":
            refund(clone_id, "sample_unusable", bonus=True)
        else:
            demo.update({"failed_at": t, "fail_count": int(demo.get("fail_count") or 0) + 1,
                         "first_failed_at": demo.get("first_failed_at") or t,
                         "last_error": dettaglio})
            out = vc.transition(clone_id, "demo_failed", {"demo": demo}, now=t)
            _notify("demo_failed", out, error=dettaglio)
    except Exception as e:      # noqa: BLE001 - I1: mai lasciare il record bloccato in
        # demos_generating per un'eccezione qui (scrittura record, notify, ecc.):
        # tentativo di miglior sforzo per portarlo comunque a demo_failed, cosi'
        # il ciclo relaunch/refund dello sweep lo riprende invece di restare
        # ostaggio per sempre.
        traceback.print_exc()
        try:
            rec2 = vc.get(clone_id)
            if rec2 is not None and rec2.get("state") == "demos_generating":
                demo2 = dict(rec2.get("demo") or {})
                demo2.update({"failed_at": t, "fail_count": int(demo2.get("fail_count") or 0) + 1,
                             "first_failed_at": demo2.get("first_failed_at") or t,
                             "last_error": type(e).__name__})
                out2 = vc.transition(clone_id, "demo_failed", {"demo": demo2}, now=t)
                _notify("demo_failed", out2, error=type(e).__name__)
        except Exception as e2:      # noqa: BLE001 - ultima rete: solo log
            print(f"[voice_clone_demo] _run fallback demo_failed fallito per {clone_id}: "
                 f"{type(e2).__name__}", flush=True)
    finally:
        # I2: nel frattempo un altro attore (utente, sweep) puo' avere
        # rimborsato/cancellato la voce mentre questo thread generava: se il
        # record e' sparito o e' ormai terminale, i file appena scritti da
        # questo giro non servono piu' a nessuno. Fuori da qualunque lock.
        cur = vc.get(clone_id)
        if cur is not None:
            if cur.get("state") in vc._TERMINAL:
                vc.remove_files(cur)
        elif last_seen is not None:
            vc.remove_files(last_seen)


def _run_and_forget(clone_id):
    try:
        _run(clone_id)
    finally:
        with _threads_lock:
            _threads.pop(clone_id, None)


def start_demos(clone_id, *, background=True):
    """`paid`/`demos_ready`/`demo_failed` -> `demos_generating`, poi il
    thread. Un secondo avvio mentre il primo lavora e' un no-op."""
    with vc._lock:
        rec = vc.get(clone_id)
        if rec is None:
            raise vc.VoiceGone(clone_id)
        if rec.get("state") != "demos_generating":
            rec = vc.transition(clone_id, "demos_generating")
        with _threads_lock:
            th = _threads.get(clone_id)
            if th is not None and th.is_alive():
                return rec
            if background:
                th = threading.Thread(target=_run_and_forget, args=(clone_id,),
                                      name=f"vc-demo-{clone_id}", daemon=True)
                _threads[clone_id] = th
                th.start()
    if not background:
        _run(clone_id)
        return vc.get(clone_id)
    return rec


def _require(clone_id, cid, states):
    rec = vc.get(clone_id)
    if rec is None or rec.get("state") in vc._TERMINAL:
        raise vc.VoiceGone(clone_id)
    if not vc._has_cid(rec, cid):
        raise PermissionError("cid non autorizzato")
    if rec.get("state") not in states:
        raise vc.BadTransition(f"{rec.get('state')} -> azione non ammessa")
    return rec


def _delete_tries(rec):
    d = vc.voice_dir(rec["token"])
    for f in os.listdir(d) if os.path.isdir(d) else []:
        if f.startswith("demo_try_"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass


def approve(clone_id, cid, now=None):
    """`demos_ready` -> `ready` (§3.5): upload su R2 di campione, originale e
    demo; via i tentativi; retention piena da adesso."""
    t = vc._now(now)
    with vc._lock:
        rec = _require(clone_id, cid, ("demos_ready",))
        out = vc.transition(clone_id, "ready",
                            {"last_used_at": t, "expires_at": t + vc.retention_sec(),
                             "expiry_warned_at": None}, now=t)
    _delete_tries(out)
    ext = (out.get("sample") or {}).get("original_ext") or "wav"
    for name in ("sample.wav", f"original.{ext}") + vc.DEMO_NAMES:
        if os.path.exists(os.path.join(vc.voice_dir(out["token"]), name)):
            vc.upload_to_r2(out, name)
    return out


def regenerate(clone_id, cid, *, extra_id, extra_text, background=True):
    """Nuova coppia di demo con la seconda frase scelta (§3.5). Le demo
    correnti diventano `demo_try_<n>_*`."""
    with vc._lock:
        rec = _require(clone_id, cid, ("demos_ready",))
        demo = dict(rec.get("demo") or {})
        used = int(demo.get("regen_used") or 0)
        if used >= int(demo.get("regen_max") if demo.get("regen_max") is not None else vc.regen_max()):
            raise RegenExhausted("rigenerazioni esaurite")
        d = vc.voice_dir(rec["token"])
        for name in vc.DEMO_NAMES:
            src = os.path.join(d, name)
            if os.path.exists(src):
                shutil.move(src, os.path.join(d, f"demo_try_{used}_{name[len('demo_'):]}"))
        demo.update({"regen_used": used + 1, "extra_id": extra_id, "extra_text": extra_text})
        vc.store().update(clone_id, {"demo": demo})
    return start_demos(clone_id, background=background)


def retry(clone_id, cid, background=True):
    """`demo_failed` -> riprova, senza consumare rigenerazioni (§3.5)."""
    with vc._lock:
        _require(clone_id, cid, ("demo_failed",))
    return start_demos(clone_id, background=background)


def reject(clone_id, cid):
    """Rifiuto esplicito dell'utente (§3.5, §7.4): rimborso senza bonus."""
    with vc._lock:
        _require(clone_id, cid, ("demos_ready", "demo_failed"))
    return refund(clone_id, "user_rejected", bonus=False)


def refund(clone_id, reason, *, bonus=False):
    """Rimborso idempotente (§7.4). Voucher -> riaccredito silenzioso;
    PayPal -> buono al proprietario (codice consegnato al notifier, che
    manda l'email); gratis -> nulla. Poi `refunded` e file rimossi."""
    job_id = "vc:" + clone_id
    extra = {"reason": reason, "method": "free", "amount_eur": 0.0,
             "voucher_code": None, "bonus_amount": 0.0}
    with vc._lock:
        rec = vc.get(clone_id)
        if rec is None:
            raise vc.VoiceGone(clone_id)
        if rec.get("state") == "refunded":
            return rec
        if rec.get("state") in vc._TERMINAL:
            raise vc.BadTransition(f"{rec.get('state')} -> refunded")
        pay = rec.get("payment") or {}
        method = pay.get("type") or "free"
        amount = round(float(pay.get("amount_eur") or 0.0), 2)
        extra.update({"method": method, "amount_eur": amount})
        gia = payment.has_refund_for_job(job_id, pay.get("token") or "")
        if amount > 0 and not gia:
            if method == "voucher":
                payment._voucher_refund(pay["token"], amount, job_id=job_id,
                                        reason="voice clone " + reason)
            elif method == "paypal":
                code, bonus_amt = payment._create_voucher(
                    rec.get("owner_email") or pay.get("email") or "", amount,
                    origin_order_id=pay.get("token"), origin_job_id=job_id,
                    kind="refund", note="voice clone " + reason,
                    created_by="auto_refund", apply_bonus=bool(bonus))
                extra.update({"voucher_code": code, "bonus_amount": bonus_amt})
        out = vc.transition(clone_id, "refunded",
                            {"refund": {"reason": reason, "method": method,
                                        "amount_eur": amount, "at": time.time()}})
    vc.remove_files(out)
    _notify("refunded", out, **extra)
    return out


def recover():
    """Al riavvio: ogni voce ferma in `paid` (crash fra commit e avvio) o in
    `demos_generating` (thread perso) riparte. Ritorna quante.

    C1 item 4: anche un giro di riconciliazione delle capture orfane, per lo
    stesso motivo del riavvio del crash-loop (`recover` gira una sola volta
    all'avvio, prima che lo `sweep` periodico riprenda a girare)."""
    n = 0
    for rec in vc._all():
        if rec.get("state") in ("paid", "demos_generating"):
            try:
                start_demos(rec["id"])
                n += 1
            except Exception as e:      # noqa: BLE001
                print(f"[voice_clone_demo] recover {rec.get('id')}: {type(e).__name__}", flush=True)
    try:
        vc.reconcile_orphan_captures()
    except Exception as e:      # noqa: BLE001
        print(f"[voice_clone_demo] recover reconcile_orphan_captures fallita: "
             f"{type(e).__name__}", flush=True)
    return n
