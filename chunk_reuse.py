"""Riuso dei chunk TTS gia' sintetizzati su disco (resume dopo crash/restart).

Un job interrotto a meta' lascia in `data/<job_id>/` i file `chunk_XXXXXX.pcm`
(o `.mp3`) gia' sintetizzati e — per le voci PREMIUM — gia' PAGATI. Rigenerarli
da zero al recovery butta via ore di TTS e ri-addebita il costo Google.

Il riuso non e' pero' incondizionato: gli indici dei chunk sono posizionali e
dipendono dal piano di chunking, quindi riusare i file di un piano diverso
consegnerebbe audio sbagliato (voce precedente, testo di un altro capitolo,
parentesi lette/non lette). Il manifest registra l'impronta del piano e dei
parametri di sintesi: si riusa SOLO se l'impronta corrente coincide byte per byte.

Invariante di sicurezza: al cambio di voce/rate/stile/accento/flag parentesi, o
a qualunque variazione del testo dei blocchi, l'impronta cambia e il riuso non
avviene (nessuna cache silenziosa fra voci diverse).

Riuso per contenuto (`align_to_plan`): il recovery ri-analizza il libro col
codice appena installato, e un deploy che tocca la preparazione del testo
cambia il piano di pochi caratteri. Il 06/11/2026 alle 15:12, 18 job su 44
sono ripartiti da zero per differenze da 4 a 83 caratteri (uno aveva 551
chunk su 1262). Con gli stessi parametri di sintesi, i chunk il cui testo
coincide con quello di un chunk del piano precedente si spostano sul nuovo
indice; tutti gli altri file del piano vecchio si cancellano, perche' un
secondo restart non li prenda per audio del piano nuovo.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from pathlib import Path
from env_utils import env_int
from fileio import file_sha256, load_json, write_json_safe

MANIFEST_NAME = ".chunks_manifest.json"

# Elenco dei chunk falliti del run corrente. Sul fallimento il file del chunk
# contiene il silenzio di ripiego: non vuoto, quindi indistinguibile da un
# chunk buono per la sola regola della dimensione. Il 12/10/2026 i restart di
# un job edge in pieno blackout hanno riusato ~180 chunk muti come audio
# sintetizzato, e il libro e' stato consegnato con 27 capitoli muti. Dopo una
# ricollocazione per contenuto (`_realign`) ci stanno anche gli indici ancora
# da sintetizzare: per il riuso valgono come falliti finche' non riescono.
FAILED_NAME = ".chunks_failed.json"
_failed_lock = threading.Lock()

# Capitoli gia' codificati dal ramo multi-file in `output_N/`. Dopo l'encode
# le parti del capitolo si cancellano e il riuso per chunk non le vede piu':
# il 26/10/2026, al restart del deploy, due job zip con piano identico sono
# ripartiti dal capitolo 1. Il segno si scrive solo a encode riuscito e porta
# l'impronta del file: un MP3 riscritto o troncato dopo non vale.
CHAPTERS_NAME = ".chapters_done.json"

# Versione dello schema: un bump invalida tutti i manifest esistenti (utile se
# cambia il modo in cui i chunk vengono scritti su disco).
SCHEMA_VERSION = 1

# Motori per cui il riuso e' abilitato. Speechify e' escluso di proposito: la
# pre-sintesi parallela popola `speechify_sample_rate` dal primo risultato API,
# che un chunk riusato non produrrebbe (rischio di assembly a sample rate errato).
# VoxCPM e' incluso ma con una regola diversa (vedi `_voxcpm_reusable_indices`):
# il job e' per capitolo, non per chunk, quindi il riuso e' per capitolo intero.
REUSABLE_ENGINES = ("gemini", "edge", "google", "voxcpm")

# Motori col riuso per contenuto: un file per chunk, funzione del solo testo
# del chunk e dei parametri di sintesi. VoxCPM no: il suo audio e' per
# segmento di capitolo e non si ricolloca a pezzi.
CONTENT_REUSE_ENGINES = ("gemini", "edge", "google")

# Chiavi dell'impronta che descrivono il testo del piano; il resto sono i
# parametri di sintesi. `chunk_sha` manca nei manifest scritti prima del
# riuso per contenuto, che restano validi.
_TEXT_KEYS = ("n_chunks", "plan_sha", "chunk_sha")

# Manifest scritto durante la ricollocazione: se il processo muore a meta',
# al restart nessun file e' affidabile e si cancellano tutti.
_REALIGN_MARK = "realign_in_progress"
_REALIGN_SUFFIX = ".realign"
_CHUNK_FILE = re.compile(r"chunk_(\d{6})\.(pcm|mp3)(\.realign)?")
_OUTPUT_DIR = re.compile(r"output_\d+")


def chunk_path(work_dir, i, ext):
    """Il file del chunk `i` nella cartella di lavoro: `chunk_000042.pcm`.
    Unico posto che conosce il nome (prima otto f-string sparse)."""
    return Path(work_dir) / f"chunk_{i:06d}.{ext}"


def plan_sha(plan) -> str:
    """SHA-256 del testo di tutti i blocchi del piano, nell'ordine del piano.

    Ancora l'impronta al contenuto reale: se il chunking cambia (anche solo per
    un capitolo deselezionato) l'hash cambia e i file su disco non sono piu'
    allineati agli indici."""
    h = hashlib.sha256()
    for block in plan:
        h.update((block.get("text") or "").encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def chunk_sha(text) -> str:
    """Impronta del testo di un chunk (64 bit, 16 hex): la chiave del riuso
    per contenuto. Il testo e' l'unico ingresso per-blocco della sintesi."""
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]


def fingerprint(voice, rate, engine, plan, style_instruction=None, accent=None,
                strip_round=True, strip_square=True) -> dict:
    """Impronta completa del run: parametri di sintesi + hash del piano e di
    ogni suo chunk."""
    return {
        "schema": SCHEMA_VERSION,
        "engine": engine or "",
        "voice": voice or "",
        "rate": rate or "",
        "style_instruction": style_instruction or "",
        "accent": accent or "",
        "strip_round": bool(strip_round),
        "strip_square": bool(strip_square),
        "n_chunks": len(plan),
        "plan_sha": plan_sha(plan),
        "chunk_sha": [chunk_sha(b.get("text")) for b in plan],
    }


def _without(fp, keys) -> dict:
    return {k: v for k, v in fp.items() if k not in keys}


def _same_run(saved, fp) -> bool:
    """Stessi parametri e stesso testo. `chunk_sha` resta fuori dal
    confronto: un manifest che non lo ha descrive lo stesso run."""
    return (isinstance(saved, dict) and isinstance(fp, dict)
            and _without(saved, ("chunk_sha",)) == _without(fp, ("chunk_sha",)))


def _same_synthesis(saved, fp) -> bool:
    """Stessi parametri di sintesi, testo a parte."""
    return (isinstance(saved, dict) and isinstance(fp, dict)
            and _without(saved, _TEXT_KEYS) == _without(fp, _TEXT_KEYS))


def manifest_path(work_dir) -> str:
    return os.path.join(str(work_dir), MANIFEST_NAME)


def read_manifest(work_dir):
    return load_json(manifest_path(work_dir), None)


def write_manifest(work_dir, fp: dict) -> bool:
    """Scrive il manifest (tmp+rename). Non solleva: il riuso e' best-effort.
    Se l'impronta cambia, l'elenco dei falliti e i capitoli codificati del
    piano precedente non valgono piu' (gli indici sono posizionali) e vengono
    rimossi."""
    if not _same_run(read_manifest(work_dir), fp):
        for _vecchio in (failed_path(work_dir), chapters_path(work_dir)):
            try:
                os.remove(_vecchio)
            except OSError:
                pass
    return write_json_safe(manifest_path(work_dir), fp, indent=2)


def failed_path(work_dir) -> str:
    return os.path.join(str(work_dir), FAILED_NAME)


def read_failed(work_dir) -> set:
    """Indici dei chunk il cui file e' il silenzio di ripiego di un fallimento."""
    data = load_json(failed_path(work_dir), None, expect=list)
    if not isinstance(data, list):
        return set()
    return {i for i in data if isinstance(i, int)}


def _update_failed(work_dir, i, add: bool) -> bool:
    with _failed_lock:
        failed = read_failed(work_dir)
        if (i in failed) == add:
            return True
        if add:
            failed.add(i)
        else:
            failed.discard(i)
        return write_json_safe(failed_path(work_dir), sorted(failed))


def mark_failed(work_dir, i) -> bool:
    """Segna il chunk `i` come fallito: il riuso non lo prendera' mai per buono."""
    return _update_failed(work_dir, i, True)


def clear_failed(work_dir, i) -> bool:
    """Toglie il segno al chunk `i`, risintetizzato con successo."""
    return _update_failed(work_dir, i, False)


def chapters_path(work_dir) -> str:
    return os.path.join(str(work_dir), CHAPTERS_NAME)


def mark_chapter_done(work_dir, ch_idx, mp3_path) -> bool:
    """Segna il capitolo `ch_idx` come codificato in `mp3_path` (dentro la
    `output_N/` del run). Solo dopo un encode riuscito e senza chunk falliti:
    il file e' audio vero e completo. Non solleva: il riuso e' best-effort."""
    try:
        rec = {"dir": Path(mp3_path).parent.name, "file": Path(mp3_path).name,
               "sha256": file_sha256(mp3_path)}
    except OSError:
        return False
    done = load_json(chapters_path(work_dir), dict)
    done[str(ch_idx)] = rec
    return write_json_safe(chapters_path(work_dir), done)


def reusable_chapters(work_dir, fp: dict, output_dir) -> dict:
    """`{chapter_index: percorso MP3}` dei capitoli che il ramo multi-file
    puo' saltare: manifest identico all'impronta corrente, motore riusabile,
    MP3 con lo stesso contenuto di quando e' stato segnato.

    Lo ZIP si fa dalla `output_N/` corrente. Un capitolo codificato in quella
    di un'altra epoch (rilancio dell'utente, poi recovery che riparte da
    epoch 1: il 07/11/2026 C-IucY4 ha rifatto 5 capitoli gia' pronti in
    `output_2/`) si copia nella corrente e il segno passa a lei. Copia e non
    link: l'originale serve ai token di download della sua epoch e un encode
    che riscrive il file della corrente non deve toccarlo."""
    if (fp or {}).get("engine") not in REUSABLE_ENGINES:
        return {}
    if not matches(work_dir, fp):
        return {}
    out_dir = Path(output_dir)
    done = load_json(chapters_path(work_dir), dict)
    out = {}
    spostati = False
    for key, rec in list(done.items()):
        try:
            ci = int(key)
            name, sha, src_dir = rec["file"], rec["sha256"], rec["dir"]
            valido = (sha and name == os.path.basename(name)
                      and _OUTPUT_DIR.fullmatch(src_dir))
        except (TypeError, ValueError, KeyError):
            continue
        if not valido:
            continue
        dest = out_dir / name
        try:
            if src_dir != out_dir.name:
                src = Path(work_dir) / src_dir / name
                if file_sha256(src) != sha:
                    continue
                shutil.copyfile(src, dest)
            if file_sha256(dest) == sha:
                out[ci] = str(dest)
                if src_dir != out_dir.name:
                    done[key] = {**rec, "dir": out_dir.name}
                    spostati = True
        except OSError:
            continue
    if spostati:
        write_json_safe(chapters_path(work_dir), done)
    return out


def matches(work_dir, fp: dict) -> bool:
    return _same_run(read_manifest(work_dir), fp)


def reusable_indices(work_dir, fp: dict, total_chunks: int, ext: str,
                      plan=None) -> set:
    """Indici dei chunk gia' su disco che e' lecito riusare.

    Per gemini/edge/google (per-chunk): un chunk e' riusabile se (a) il
    manifest coincide con l'impronta corrente, (b) il file esiste, non e'
    vuoto e — per il PCM 16 bit — ha dimensione pari, (c) non e' quello di
    indice massimo fra i presenti, (d) non e' segnato fra i falliti
    (`FAILED_NAME`: il file e' il silenzio di ripiego). La condizione (c) scarta l'ULTIMO file
    scritto, l'unico che al momento del crash poteva essere troncato a meta'
    senza che si possa rilevarlo: costa una risintesi sola. I chunk vengono
    scritti in ordine crescente, quindi un eventuale buco nella sequenza
    (sweep parziale) non rende sospetti quelli che lo precedono.

    Per voxcpm (per-capitolo, vedi `_voxcpm_reusable_indices`): la regola
    sopra non si applica, perche' il job produce un PCM per capitolo e non
    per chunk (i chunk di coda sono file vuoti per costruzione, non tronchi)."""
    if (fp or {}).get("engine") not in REUSABLE_ENGINES:
        return set()
    if not matches(work_dir, fp):
        return set()
    if (fp or {}).get("engine") == "voxcpm":
        return _voxcpm_reusable_indices(work_dir, total_chunks, ext, plan)
    return _good_chunks(work_dir, total_chunks, ext)


def _good_chunks(work_dir, total_chunks: int, ext: str) -> set:
    """Gli indici fra 0 e `total_chunks` il cui file e' audio completo, con
    le regole (b)-(d) di `reusable_indices`."""
    present = {}
    for i in range(total_chunks):
        p = str(chunk_path(work_dir, i, ext))
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if size > 0:
            present[i] = size
    if not present:
        return set()
    last_written = max(present)
    failed = read_failed(work_dir)
    out = set()
    for i, size in present.items():
        if i == last_written:
            continue  # possibile troncamento al crash -> risintetizza
        if i in failed:
            continue  # silenzio di ripiego, non audio
        if ext == "pcm" and size % 2 != 0:
            continue  # PCM 16-bit: dimensione dispari = scrittura incompleta
        out.add(i)
    return out


def _chunk_files(work_dir) -> dict:
    """`{nome: (indice, temporaneo)}` dei file di chunk della cartella di
    lavoro, di ogni estensione, compresi i temporanei di una ricollocazione."""
    try:
        names = os.listdir(str(work_dir))
    except OSError:
        return {}
    out = {}
    for name in names:
        m = _CHUNK_FILE.fullmatch(name)
        if m:
            out[name] = (int(m.group(1)), bool(m.group(3)))
    return out


def wipe_chunks(work_dir) -> int:
    """Cancella tutti i file di chunk, temporanei compresi. Ritorna quanti."""
    n = 0
    for name in _chunk_files(work_dir):
        try:
            os.remove(os.path.join(str(work_dir), name))
            n += 1
        except OSError:
            pass
    return n


def align_to_plan(work_dir, fp: dict, ext: str) -> tuple:
    """Allinea i file di chunk su disco al piano corrente, prima di
    `reusable_indices`. Ritorna `(ricollocati, scartati)`.

    - stesso run: niente da fare (per i manifest di prima vedi
      `_drop_stale_legacy`);
    - stessi parametri di sintesi, testo cambiato, motore per chunk: i file
      dei chunk il cui testo e' ancora nel piano passano al nuovo indice
      (`_realign`);
    - altrimenti (voce cambiata, manifest assente, VoxCPM, ricollocazione
      interrotta): via tutti i file di chunk. Il riuso adesso non li prende,
      ma dopo la scrittura del manifest nuovo un secondo restart li
      prenderebbe per audio del piano nuovo agli indici non ancora riscritti.
    """
    saved = read_manifest(work_dir)
    if isinstance(saved, dict) and saved.get(_REALIGN_MARK):
        return 0, wipe_chunks(work_dir)
    if _same_run(saved, fp):
        if "chunk_sha" in saved or fp.get("engine") not in CONTENT_REUSE_ENGINES:
            return 0, 0
        return 0, _drop_stale_legacy(work_dir, ext)
    old_sha = saved.get("chunk_sha") if isinstance(saved, dict) else None
    if (fp.get("engine") in CONTENT_REUSE_ENGINES and _same_synthesis(saved, fp)
            and isinstance(old_sha, list) and len(old_sha) == saved.get("n_chunks")
            and all(isinstance(s, str) for s in old_sha)):
        return _realign(work_dir, old_sha, fp, ext)
    return 0, wipe_chunks(work_dir)


def _realign(work_dir, old_sha: list, fp: dict, ext: str) -> tuple:
    """Riuso per contenuto (vedi `align_to_plan`). Ritorna `(ricollocati,
    scartati)`.

    Sorgenti: i chunk buoni del piano vecchio (`_good_chunks` sugli indici
    vecchi: fuori l'ultimo scritto, i falliti, i vuoti). Ogni indice nuovo il
    cui testo ha una sorgente ne riceve il file, copiato se lo stesso testo
    torna piu' volte. Gli altri file di chunk si cancellano e gli indici
    nuovi rimasti senza file entrano fra i falliti: scritti fuori ordine
    rispetto ai ricollocati, un crash a meta' scrittura li lascerebbe
    troncati senza essere l'indice massimo presente. Ordine: segno nel
    manifest, spostamenti, falliti, manifest nuovo; un errore a meta'
    cancella tutti i file di chunk.
    """
    sorgente = {}
    for j in sorted(_good_chunks(work_dir, len(old_sha), ext)):
        sorgente.setdefault(old_sha[j], j)
    new_sha = fp["chunk_sha"]
    posti = {i: sorgente[s] for i, s in enumerate(new_sha) if s in sorgente}
    if not posti:
        return 0, wipe_chunks(work_dir)
    usi = {}
    for j in posti.values():
        usi[j] = usi.get(j, 0) + 1
    if not write_json_safe(manifest_path(work_dir), {_REALIGN_MARK: True}):
        return 0, wipe_chunks(work_dir)
    wd = str(work_dir)
    scartati = 0
    try:
        for _vecchio in (failed_path(work_dir), chapters_path(work_dir)):
            try:
                os.remove(_vecchio)
            except FileNotFoundError:
                pass
        # Prima via i temporanei e i file che non servono, poi gli spostamenti:
        # la destinazione di ogni rename non esiste mai.
        da_spostare = []
        for name, (j, tmp) in _chunk_files(work_dir).items():
            p = os.path.join(wd, name)
            if not tmp and j in usi and name == chunk_path(wd, j, ext).name:
                da_spostare.append(p)
            else:
                os.remove(p)
                scartati += 1
        for p in da_spostare:
            os.rename(p, p + _REALIGN_SUFFIX)
        for i, j in sorted(posti.items()):
            src = str(chunk_path(wd, j, ext)) + _REALIGN_SUFFIX
            usi[j] -= 1
            if usi[j]:
                shutil.copyfile(src, chunk_path(wd, i, ext))
            else:
                os.rename(src, chunk_path(wd, i, ext))
        da_fare = sorted(set(range(len(new_sha))) - set(posti))
        if not write_json_safe(failed_path(work_dir), da_fare):
            raise OSError("elenco dei chunk da sintetizzare non scritto")
        if not write_json_safe(manifest_path(work_dir), fp, indent=2):
            raise OSError("manifest non scritto")
    except OSError as e:
        print(f"[chunk_reuse] ricollocazione fallita in {wd}: {e}; chunk cancellati")
        return 0, scartati + wipe_chunks(work_dir)
    return len(posti), scartati


def _drop_stale_legacy(work_dir, ext: str) -> int:
    """Manifest scritto prima di `align_to_plan`: al cambio di piano il codice
    di allora lasciava i chunk del piano vecchio agli indici non ancora
    riscritti, e un secondo restart li avrebbe riusati come audio del piano
    nuovo (i 18 job ripartiti da zero il 06/11/2026 alle 15:12). Il manifest
    si scrive prima della sintesi, quindi i file del run corrente sono piu'
    recenti; un file piu' vecchio con indice oltre il primo scritto dal run
    corrente non e' stato riusato e si cancella. Il run che riparte dopo i
    chunk riusati non perde nulla: i file vecchi stanno tutti prima del primo
    nuovo. Un chunk fallito risintetizzato fa scartare anche i buoni vecchi
    dopo di lui: lavoro perso, mai audio sbagliato. Solo motori a chunk
    sequenziali (`CONTENT_REUSE_ENGINES`). Ritorna i file cancellati."""
    try:
        t0 = os.path.getmtime(manifest_path(work_dir))
    except OSError:
        return 0
    wd = str(work_dir)
    eta = {}
    for name, (j, tmp) in _chunk_files(work_dir).items():
        if tmp or name != chunk_path(wd, j, ext).name:
            continue
        try:
            eta[j] = (os.path.getmtime(os.path.join(wd, name)), name)
        except OSError:
            continue
    nuovi = [j for j, (t, _n) in eta.items() if t >= t0]
    if not nuovi:
        return 0
    primo = min(nuovi)
    n = 0
    for j, (t, name) in eta.items():
        if j > primo and t < t0:
            try:
                os.remove(os.path.join(wd, name))
                n += 1
            except OSError:
                pass
    return n


# Tetto di chunk per job VoxCPM: un capitolo piu' lungo si sintetizza a
# segmenti, un job RunPod ciascuno. Il 13/10/2026 un libro senza capitoli
# rilevati (un capitolo solo, 2064 chunk, 448.662 caratteri) e' diventato un
# job unico: dopo 22 minuti di sintesi un chunk non e' tornato entro il tetto
# del worker, il motore e' stato dichiarato compromesso e il capitolo buttato
# per intero, da rifare da capo a concorrenza 8. A segmenti si perde solo il
# segmento in corso, e il riuso li riconosce uno per uno.
VOXCPM_SEGMENT_MAX_CHUNKS = 300

# Fine di frase: un taglio fra segmenti cade dopo un chunk che chiude una
# frase, cosi' la giunzione fra due job (che il worker non smussa) e' una
# pausa che il testo aveva gia'.
_FINE_FRASE = re.compile(r"[.!?…][\"'»”’)\]]*\s*$")


def voxcpm_segment_max_chunks() -> int:
    """`ABM_VOXCPM_SEGMENT_MAX_CHUNKS`, 0 = capitoli mai spezzati."""
    return max(0, env_int("ABM_VOXCPM_SEGMENT_MAX_CHUNKS",
                          VOXCPM_SEGMENT_MAX_CHUNKS))


def voxcpm_segments(plan, max_chunks=None):
    """Le unita' di lavoro VoxCPM: `[(chapter_index, parte, [indici]), ...]`.

    Un capitolo entro `max_chunks` e' una parte sola (parte 0, come prima).
    Uno piu' lungo si divide in `ceil(n / max_chunks)` parti di lunghezza
    simile; ogni taglio si sposta, entro un decimo della parte, dopo un chunk
    che chiude una frase. Deterministico sul piano: la sintesi e la regola del
    riuso lo chiamano entrambe e devono vedere gli stessi segmenti. L'audio
    di un segmento sta nel file-parte del suo primo chunk, quindi la
    concatenazione in ordine dei file resta il libro anche se il tetto cambia
    fra due tentativi.
    """
    if max_chunks is None:
        max_chunks = voxcpm_segment_max_chunks()
    ordine, per_capitolo = [], {}
    for i, blocco in enumerate(plan):
        ci = blocco.get("chapter_index", 0)
        if ci not in per_capitolo:
            per_capitolo[ci] = []
            ordine.append(ci)
        per_capitolo[ci].append(i)
    out = []
    for ci in ordine:
        indici = per_capitolo[ci]
        n = len(indici)
        if not max_chunks or n <= max_chunks:
            out.append((ci, 0, indici))
            continue
        parti = -(-n // max_chunks)
        passo = n / parti
        finestra = max(1, int(passo / 10))
        tagli, prec = [], 0
        for k in range(1, parti):
            ideale = round(k * passo)
            scelto = ideale
            # Il chunk che precede il taglio deve chiudere una frase: si
            # cerca vicino all'ideale, alternando avanti e indietro.
            for d in range(finestra + 1):
                trovato = None
                for t in (ideale + d, ideale - d):
                    if (prec < t < n and t - prec <= max_chunks
                            and _FINE_FRASE.search(
                                plan[indici[t - 1]].get("text") or "")):
                        trovato = t
                        break
                if trovato is not None:
                    scelto = trovato
                    break
            scelto = min(max(scelto, prec + 1), prec + max_chunks)
            tagli.append(scelto)
            prec = scelto
        bordi = [0] + tagli + [n]
        # L'ultimo pezzo puo' sforare di poco se i tagli si sono spostati
        # indietro: lo si accetta, il tetto e' una misura di rischio.
        for parte in range(len(bordi) - 1):
            out.append((ci, parte, indici[bordi[parte]:bordi[parte + 1]]))
    return out


def _voxcpm_reusable_indices(work_dir, total_chunks: int, ext: str,
                              plan) -> set:
    """Riuso VoxCPM: segmento-atomico, non per chunk (§7.3 — un job e' un
    capitolo, o un segmento di un capitolo lungo, vedi `voxcpm_segments`, e
    il PCM che il worker restituisce non si ricuce a pezzi). Sotto, "capitolo"
    vale per segmento.

    Un capitolo e' riusabile se e solo se: il file-parte del suo PRIMO chunk
    esiste e non e' vuoto (l'audio del capitolo ci sta tutto li', scritto in
    modo atomico da `_consegna` via .part + os.replace: se esiste con
    size > 0 e' per forza completo, mai un troncamento a meta') E il
    file-parte di OGNI chunk di coda esiste (puo' essere vuoto: e' cosi' che
    deve essere per costruzione, non e' un segnale di crash). Se anche uno
    solo manca, tutto il capitolo si rifa': non c'e' modo di riusare meta'
    capitolo quando il worker restituisce un PCM indivisibile.

    Senza `plan` (chiamante che non lo passa) non si riusa nulla: senza sapere
    quali chunk appartengono a quale capitolo non si puo' applicare la regola."""
    if not plan:
        return set()
    out = set()
    for _ci, _parte, indici in voxcpm_segments(plan[:total_chunks]):
        testa = indici[0]
        head_path = str(chunk_path(work_dir, testa, ext))
        try:
            head_size = os.path.getsize(head_path)
        except OSError:
            continue
        if head_size <= 0:
            continue
        if all(os.path.exists(str(chunk_path(work_dir, i, ext)))
               for i in indici[1:]):
            out.update(indici)
    return out
