# Incidente assembly obsoleto — agosto 2026

Redatto il 2026-08-24. Fonti: `/var/log/syslog*`, `/opt/audiobook-maker/activity_2026-08.log`.

---

## 1. Sintesi

Dal 22/08/2026 (deploy della coda di ammissione per gli encode FFmpeg, commit `70707c6`) i log di produzione mostrano **52 traceback su 15 job distinti** nella finestra di syslog disponibile, in tre forme apparentemente diverse:

- `FileNotFoundError` su `chunk_NNNNNN.mp3` durante la sintesi;
- `FileNotFoundError` su `_silence.mp3` al concat finale;
- `FileNotFoundError` su `output_N/<Titolo>.mp3` in assembly.

Causa unica: **la job dir viene cancellata mentre thread di sintesi o di assembly stanno ancora scrivendoci dentro**.

Impatto peggiore osservato: un utente ha ricevuto **tre HTTP 404** sul download di un audiolibro che era stato prodotto correttamente.

---

## 2. Meccanismo

Tre difetti che si compongono.

**D1 — nessun ricontrollo dopo l'acquisizione dello slot.** `_acquire_assembly_slot()` puo' bloccare a lungo: con `ABM_MAX_CONCURRENT_ASSEMBLY=3` e code fino a 9 job si sono osservate attese di **241–618 s**. Al ritorno non veniva verificato nulla: ne' `gen_epoch`, ne' il flag `cancelled`, ne' l'esistenza della directory. L'ultimo `_check_cancelled()` stava prima dell'ingresso in coda.

**D2 — il purge per heartbeat perso non distingueva "in coda".** Nel cleanup, un job in stato `generating` che non riceve polling da 60 s viene marcato `cancelled` e **la sua dir viene rimossa**. Un job fermo in fila per uno slot e' indistinguibile da uno abbandonato: prima della coda l'assembly partiva pochi secondi dopo la sintesi, quindi la finestra di rischio era trascurabile; con la coda e' diventata di minuti.

**D3 — l'assembly obsoleto declassava un job gia' completato.** Il `FileNotFoundError` del thread obsoleto finiva nel gestore d'errore generico, che scriveva il marker forense e portava il job a `error`, sovrascrivendo un `done` legittimo e rendendo il file non piu' scaricabile.

### Cronologia del caso peggiore — job `Wne3EQMNT0f5tFLL5zHHKA`

```
13:47     generate (mp3) -> chunk completati 13:49 -> assembly in coda (3/3 slot occupati)
13:52:36  l'utente cancella
13:54:35  l'utente rigenera (m4b, riuso 5/6 chunk) -> seconda entry in coda
13:58:36  slot #1 concesso dopo 571 s -> merge di output_1/ -> COMPLETE
13:58:38  slot #2 concesso dopo 241 s alla epoch CANCELLATA -> parte comunque
          -> ENOENT su _silence.mp3 -> outcome=error -> entry rimossa
14:01-14:02  l'utente riceve 3x HTTP 404 su /api/download?type=m4b
```

Altri casi rappresentativi: `QfssM-DBsVv1FcgQ0rtSFQ` (purge a 80 s durante la sintesi, al chunk 33 di 298) e `HKgoZdsPNEnWyVl5lgokxA` (purge a 95 s con due epoch in coda, entrambe morte su ENOENT dopo 618 s e 469 s).

### Perimetro

Solo job **interattivi senza email registrata**: il ramo `has_email -> continue` del cleanup protegge i job batch. Perdere un job gratuito abbandonato e' tollerabile; D1 e D3 pero' non perdevano job abbandonati, rompevano il download di job consegnati a utenti presenti.

---

## 3. Correzione (v3.45.1)

1. **`_assembly_stale_reason()`** (`generation_engine.py`): valutata dopo l'attesa in coda, dichiara obsoleto il thread se la entry non e' piu' nel registro, se `gen_epoch` e' avanzata, o se la work_dir e' sparita. Nessun uso dell'heartbeat: un browser chiuso non e' un motivo per buttare via una sintesi completa. **Eccezione**: se il job ha un pagamento incassato ed e' ancora la epoch corrente, la dir mancante NON lo rende obsoleto — deve percorrere il path d'errore, che rimborsa e notifica.
2. **`_StaleAssemblyError`**: l'abort restituisce lo slot e termina il thread **senza toccare lo stato del job**, senza marker forense e senza rimborso. Lo stato appartiene alla epoch corrente.
3. **`assembly_started_at`** + **`_assembly_purge_hold()`** (`audiobook_app.py`): il purge per heartbeat resta sospeso per l'intera fase di assembly (attesa in coda + encode), con finestra di grazia `CLEANUP_ASSEMBLY_GRACE_SEC = 3600 s` — copre il timeout della coda (1800 s) piu' l'encode, oltre il quale il job torna purgabile e non puo' restare vivo per sempre.

L'attesa in coda resta **non interrompibile** dalla cancellazione, per scelta: svegliare i waiter butterebbe via audiolibri gia' sintetizzati e pagati. Il controllo e' a valle, all'uscita dalla coda.

Test: `test/test_assembly_stale_guard.py` (11 casi).

---

## 4. Punto aperto

`ABM_MAX_CONCURRENT_ASSEMBLY=3` su 4 vCPU, con FFmpeg invocato senza `-threads`: code da 9 job significano ~10 minuti di attesa a sintesi finita, con la barra ferma su "Server busy — queued for final assembly". I fix qui sopra rendono l'attesa innocua, non breve. Da rivalutare con i dati raccolti dopo il deploy.
