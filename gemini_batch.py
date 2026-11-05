"""gemini_batch — Gemini TTS in batch sull'API Gemini, per il catalogo gratuito.

Con `ABM_GEMINI_TRANSPORT=batch` (mai in produzione: `env_utils.batch_transport`)
i chunk del libro vanno alla Batch API prima del giro sincrono: un file JSONL
caricato per lotto di `lot_chunks()` chunk, al massimo `in_flight()` lotti in
volo (Google limita i token in coda), risposte in un file JSONL da scaricare.
Costa meta' listino (`gemini_tts.BATCH_BACKEND`) e resta in coda da minuti a
ore: il libro di un cliente non deve aspettarlo.

Riusa il percorso sincrono di `gemini_tts`: stesso prompt (`build_final_text`),
stessa richiesta (`speech_request_json`), stesso client API key (`_get_client`),
stessa estrazione e stessi controlli dell'audio (`_extract_audio_pcm`,
`mostly_silent_reason`). Un chunk che il batch non consegna (rifiuto del
modello, audio muto, lotto fallito o scaduto) non compare negli esiti: lo
rifa' il giro sincrono con la sua catena di ripiego.
"""
import json
import os
import time

import gemini_tts
import retry_util as _retry
from audio_utils import pcm_size_to_seconds
from env_utils import batch_transport, env_float, env_int

# Tentativi per ogni chiamata all'API (upload, creazione, stato, download).
_TENTATIVI = 5
# Cadenza del controllo di annullamento durante l'attesa fra due letture.
_TICK_S = 5.0
_RIUSCITO = "JOB_STATE_SUCCEEDED"


class GeminiBatchAnnullato(RuntimeError):
    """Il job e' stato annullato mentre i batch erano in coda."""


def enabled(voice_id):
    """True se il libro di questa voce va in batch: env accesa fuori
    produzione e API key configurata (il batch gira solo li')."""
    if not batch_transport("ABM_GEMINI_TRANSPORT"):
        return False
    try:
        model_key = gemini_tts.parse_voice_id(voice_id)[0]
    except ValueError:
        return False
    return gemini_tts._backend_ready("apikey", model_key)


def lot_chunks():
    """Chunk per batch. ~1,6 MB di risposta per chunk da 380 caratteri: il file
    di un lotto da 50 si scarica e si legge in memoria senza pensieri."""
    return env_int("ABM_GEMINI_BATCH_CHUNKS", 50, floor=1)


def in_flight():
    """Batch in volo insieme: oltre, Google risponde 429 (token in coda)."""
    return env_int("ABM_GEMINI_BATCH_IN_FLIGHT", 4, floor=1)


def poll_seconds():
    """Secondi fra due letture dello stato dei batch. Floor a 5."""
    return env_float("ABM_GEMINI_BATCH_POLL_S", 30.0, floor=5.0)


def timeout_s():
    """Tetto all'attesa: oltre si cancellano i batch in volo e il resto va in
    sincrono. Google fa scadere un batch dopo 48 h; il default resta sotto."""
    return env_float("ABM_GEMINI_BATCH_TIMEOUT_S", 46 * 3600.0, floor=60.0)


def _ritentabile(retry_429=True):
    def _ok(e):
        code = getattr(e, "code", None)
        if code is None:
            # Rete caduta (nessuno status); i difetti di programma no.
            return not isinstance(e, (ValueError, TypeError, KeyError, AttributeError))
        if code == 429 and not retry_429:
            return False
        return _retry.is_transient_http(code)
    return _ok


def _chiama(fn, sleep, *, retry_429=True):
    return _retry.retry_call(lambda _a: fn(), attempts=_TENTATIVI,
                             is_retryable=_ritentabile(retry_429), wait=2.0, sleep=sleep)


def _senza_errori(fn):
    """Pulizia best-effort (cancel, delete): non deve mai far fallire il libro."""
    try:
        fn()
    except Exception as e:      # noqa: BLE001
        print(f"[gemini-batch] pulizia non riuscita: {e}")


def _riga(item, voice_name, model_key, style, rate, accent, temperature):
    """Riga JSONL del chunk, o None se il prompt supera il cap dell'API (lo
    gestisce il percorso sincrono, che solleva)."""
    final_text = gemini_tts.build_final_text(item["text"], style, rate, accent)
    if len(final_text.encode("utf-8")) > gemini_tts.API_HARD_BYTES_CAP:
        return None
    gemini_tts.write_debug_prompt(item.get("prompt_path"), final_text)
    return {"key": str(item["key"]),
            "request": gemini_tts.speech_request_json(final_text, voice_name, model_key,
                                                      temperature)}


def _invia(client, model_id, righe, work_dir, etichetta, sleep):
    """Carica il JSONL del lotto e crea il batch. Ritorna (nome batch, nome file).

    Un 429 alla creazione (token in coda) esce subito: il chiamante riprova
    al giro successivo invece di martellare con i ritentativi."""
    path = os.path.join(work_dir, f"gemini_batch_{etichetta}.jsonl")
    try:
        with open(path, "w", encoding="utf-8") as f:
            for r in righe:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        up = _chiama(lambda: client.files.upload(
            file=path, config={"mime_type": "jsonl", "display_name": f"abm-{etichetta}"}),
            sleep)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        job = _chiama(lambda: client.batches.create(
            model=model_id, src=up.name, config={"display_name": f"abm-{etichetta}"}),
            sleep, retry_429=False)
    except Exception:
        _senza_errori(lambda: client.files.delete(name=up.name))
        raise
    return job.name, up.name


def _audio(risposta, item, model_key, voice_name):
    """Esito del chunk da una riga di risposta, o None se non e' audio buono.
    La riga si legge come una risposta sincrona: stessa estrazione, stessi
    controlli di `synthesize`."""
    from google.genai import types as genai_types
    try:
        response = genai_types.GenerateContentResponse.model_validate_json(
            json.dumps(risposta))
        pcm = gemini_tts._extract_audio_pcm(response, model_key)
    except (gemini_tts.GeminiEmptyResponse, gemini_tts.GeminiAudioFormatError,
            ValueError) as e:
        print(f"[gemini-batch] chunk {item['key']} non consegnato: {e}")
        return None
    muto = gemini_tts.mostly_silent_reason(pcm)
    if muto is not None:
        print(f"[gemini-batch] chunk {item['key']} non consegnato: audio muto ({muto})")
        return None
    os.makedirs(os.path.dirname(item["dest"]) or ".", exist_ok=True)
    with open(item["dest"], "wb") as f:
        f.write(pcm)
    um = response.usage_metadata
    return {
        "success": True,
        "bytes_written": len(pcm),
        "audio_seconds_real": pcm_size_to_seconds(len(pcm)),
        "input_tokens": (um.prompt_token_count or 0) if um else 0,
        "output_tokens": (um.candidates_token_count or 0) if um else 0,
        "model_key": model_key,
        "voice_name": voice_name,
        "attempts_used": 1,
        "backend": gemini_tts.BATCH_BACKEND,
        "tokens_measured": um is not None,
    }


def _consegna(client, job, attesi, model_key, voice_name, sleep):
    """{key: esito} dal file delle risposte di un batch riuscito."""
    nome = getattr(job.dest, "file_name", None) if job.dest is not None else None
    if not nome:
        print(f"[gemini-batch] {job.name}: riuscito ma senza file di risposte")
        return {}
    data = _chiama(lambda: client.files.download(file=nome), sleep)
    esiti = {}
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            riga = json.loads(line)
        except ValueError:
            continue
        item = attesi.get(str(riga.get("key")))
        if item is None:
            continue
        if riga.get("error") or not riga.get("response"):
            print(f"[gemini-batch] chunk {item['key']} non consegnato: "
                  f"{str(riga.get('error'))[:200]}")
            continue
        esito = _audio(riga["response"], item, model_key, voice_name)
        if esito is not None:
            esiti[item["key"]] = esito
    _senza_errori(lambda: client.files.delete(name=nome))
    return esiti


def _attendi(secondi, cancelled, sleep):
    resto = float(secondi)
    while resto > 0:
        if cancelled is not None and cancelled():
            return
        passo = min(_TICK_S, resto)
        sleep(passo)
        resto -= passo


def synthesize_batch(items, voice_id, *, work_dir, style_instruction=None, rate="+0%",
                     accent_directive=None, in_corso=None, on_in_corso=None,
                     cancelled=None, on_counts=None, client=None,
                     sleep=time.sleep, clock=time.monotonic):
    """Sintetizza `items` in batch. Ritorna {key: esito} dei chunk consegnati.

    items: [{"key": indice chunk, "text": testo pulito da una sola chiamata
    (`premium_chunk.gemini_single_call_text`), "dest": file PCM, "prompt_path":
    file del prompt o None}]. L'esito ha la forma di quello di
    `gemini_tts.synthesize`, con `backend=BATCH_BACKEND`.

    in_corso: batch creati da un run precedente (`[{"name", "file", "keys"}]`),
    da riprendere invece di ripagarli; on_in_corso(lista) riceve l'elenco a
    ogni cambiamento, da persistere nel job. on_counts(finiti, totali) conta i
    chunk dei batch chiusi. Solleva GeminiBatchAnnullato se `cancelled()`.
    """
    model_key, _, voice_name = gemini_tts.parse_voice_id(voice_id)
    model_id = gemini_tts._resolve_model_id(model_key, backend="apikey")
    client = client or gemini_tts._get_client(model_key, backend="apikey")
    temperature = gemini_tts._temperature()
    per_chiave = {str(it["key"]): it for it in items}

    attivi = []
    for b in in_corso or []:
        keys = [k for k in (b.get("keys") or []) if str(k) in per_chiave]
        if b.get("name") and keys:
            attivi.append({"name": b["name"], "file": b.get("file"), "keys": keys})
    coperti = {str(k) for b in attivi for k in b["keys"]}
    resto = [it for it in items if str(it["key"]) not in coperti]
    n = lot_chunks()
    lotti = [resto[i:i + n] for i in range(0, len(resto), n)]

    esiti = {}
    finiti = 0

    def _pubblica():
        if on_in_corso is not None:
            on_in_corso([dict(b) for b in attivi])

    def _annulla_attivi():
        for b in attivi:
            _senza_errori(lambda name=b["name"]: client.batches.cancel(name=name))
            if b.get("file"):
                _senza_errori(lambda name=b["file"]: client.files.delete(name=name))
        attivi.clear()
        _pubblica()

    _pubblica()
    scadenza = clock() + timeout_s()
    while lotti or attivi:
        if cancelled is not None and cancelled():
            _annulla_attivi()
            raise GeminiBatchAnnullato("job annullato con i batch in coda")
        cambiato = False

        while lotti and len(attivi) < in_flight():
            lotto = lotti[0]
            righe, keys = [], []
            for it in lotto:
                r = _riga(it, voice_name, model_key, style_instruction, rate,
                          accent_directive, temperature)
                if r is not None:
                    righe.append(r)
                    keys.append(it["key"])
            if not righe:
                lotti.pop(0)
                continue
            try:
                nome, file_nome = _invia(client, model_id, righe, work_dir,
                                         f"{keys[0]:06d}", sleep)
            except Exception as e:      # noqa: BLE001 - deciso sotto
                if getattr(e, "code", None) == 429 and attivi:
                    print(f"[gemini-batch] coda piena, il lotto da {keys[0]} "
                          f"riparte al prossimo giro")
                    break
                # 429 senza batch nostri in volo (la coda e' piena d'altro o
                # il credito e' finito) o errore non ritentabile: il resto del
                # libro va in sincrono, che sa classificare l'errore.
                print(f"[gemini-batch] batch non creato ({str(e)[:200]}): "
                      f"{sum(len(x) for x in lotti)} chunk in sincrono")
                lotti.clear()
                break
            lotti.pop(0)
            attivi.append({"name": nome, "file": file_nome, "keys": keys})
            cambiato = True

        for b in list(attivi):
            try:
                job = _chiama(lambda name=b["name"]: client.batches.get(name=name), sleep)
            except Exception as e:      # noqa: BLE001 - si riprova al prossimo giro
                print(f"[gemini-batch] stato di {b['name']} non letto: {str(e)[:200]}")
                continue
            if not job.done:
                continue
            stato = getattr(job.state, "name", str(job.state))
            if stato == _RIUSCITO:
                attesi = {str(k): per_chiave[str(k)] for k in b["keys"]}
                try:
                    esiti.update(_consegna(client, job, attesi, model_key, voice_name, sleep))
                except Exception as e:      # noqa: BLE001 - il lotto va in sincrono
                    print(f"[gemini-batch] risposte di {b['name']} non lette: {str(e)[:200]}")
            else:
                print(f"[gemini-batch] {b['name']} chiuso in {stato}: "
                      f"{str(getattr(job, 'error', None))[:200]}")
            if b.get("file"):
                _senza_errori(lambda name=b["file"]: client.files.delete(name=name))
            finiti += len(b["keys"])
            attivi.remove(b)
            cambiato = True

        if cambiato:
            _pubblica()
        if on_counts is not None:
            on_counts(finiti, len(items))
        if not (lotti or attivi):
            break
        if clock() >= scadenza:
            print(f"[gemini-batch] tetto di attesa superato: {len(attivi)} batch "
                  f"cancellati, il resto in sincrono")
            _annulla_attivi()
            break
        _attendi(poll_seconds(), cancelled, sleep)
    return esiti
