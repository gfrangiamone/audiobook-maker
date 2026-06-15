# Fix: download/libreria su Android (cartella gestita + ibrido) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps `- [ ]`.

**Root cause (da debugging sistematico):** il download scriveva via `dart:io` nella cartella condivisa scelta dall'utente, ma l'app Android non ha permessi di scrittura su storage condiviso (scoped storage) → ogni download fallisce ("Download non riuscito"). Il backend è OK (`/dl/<token>/m4b` → 200, file valido, verificato sul server di test). Inoltre per un job m4b `my_jobs` riporta `formats {m4b, mp3}` → due bottoni invece di uno.

**Goal:** (1) L'app usa una **cartella gestita** (app-owned, sempre read+write) come libreria primaria: download, import e file creati ci finiscono e compaiono in libreria. (2) La libreria scandisce ANCHE una **cartella esterna opzionale** scelta dall'utente (sola lettura, best-effort su Android moderno). (3) Nel pannello Attività **un solo bottone** "Scarica e aggiungi in libreria".

**Architecture:** nuovo `LibraryPaths` (cartella gestita via path_provider: Android `getExternalStorageDirectory()/library`, iOS `getApplicationDocumentsDirectory()/library`). `LibraryRepository.scanFolders(List<String>)` (multi-root; `scanFolder` resta wrapper). `SettingsService.folderPath` diventa la cartella **esterna opzionale** (non più obbligatoria all'avvio). Download e import scrivono SEMPRE nella cartella gestita. Activity: bottone unico che sceglie il formato primario (m4b→mp3→zip→abm) e scarica nella gestita.

**Repo:** `C:\Users\gfran\NEXT srl\Progetti - Documenti\audiobook-maker-mobile` (branch main). Flutter `C:\flutter\bin\flutter.bat`. PowerShell, comandi singoli senza `&&`. **NON eseguire `flutter build apk`** (direttiva utente: solo `flutter analyze` + `flutter test`). Caveat OneDrive: lock `ios\Flutter\ephemeral` → normalizza attributi+cancella.

## Mappa dei file
```
lib/core/library/library_paths.dart        # NEW: managed dir + lista scan roots
lib/core/library/library_repository.dart    # MOD: scanFolders(List<String>) multi-root
lib/app/providers.dart                       # MOD: managedLibraryDirProvider, scanRoots, library auto-scan
lib/app/screens/library_screen.dart          # MOD: niente gate onboarding; import→gestita; rescan multi-root
lib/app/screens/settings_screen.dart         # MOD: tile "Cartella esterna (opzionale)" + path gestita info
lib/app/screens/activity_screen.dart         # MOD: bottone unico download→gestita
lib/l10n/app_*.arb                           # MOD: nuove chiavi (7 lingue)
test/library_repository_test.dart            # MOD: test multi-root
test/widget/activity_screen_test.dart        # MOD: test bottone unico
```

---

### Task 1 — LibraryPaths + scanFolders multi-root

**Files:** Create `lib/core/library/library_paths.dart`; Modify `lib/core/library/library_repository.dart`; Test `test/library_repository_test.dart`.

- [ ] **Step 1: LibraryPaths** — `lib/core/library/library_paths.dart`:

```dart
import 'dart:io';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

/// Cartella libreria GESTITA dall'app: sempre leggibile e scrivibile via dart:io
/// (niente permessi storage). Android: dir esterna app-specific; iOS: Documents
/// dell'app (esposta in File). È la posizione primaria di download/import.
class LibraryPaths {
  static Directory? _cached;

  static Future<Directory> managedDir() async {
    if (_cached != null) return _cached!;
    Directory base;
    if (Platform.isAndroid) {
      base = await getExternalStorageDirectory() ??
          await getApplicationDocumentsDirectory();
    } else {
      base = await getApplicationDocumentsDirectory();
    }
    final dir = Directory(p.join(base.path, 'library'));
    if (!dir.existsSync()) dir.createSync(recursive: true);
    _cached = dir;
    return dir;
  }
}
```

- [ ] **Step 2: test multi-root (failing)** — append a `test/library_repository_test.dart`:

```dart
  test('scanFolders unisce più root e tombstona solo se assente ovunque',
      () async {
    final dirA = Directory.systemTemp.createTempSync('abm_a_');
    final dirB = Directory.systemTemp.createTempSync('abm_b_');
    File('test/fixtures/book_chaptered.m4b').copySync('${dirA.path}/a.m4b');
    File('test/fixtures/sample.mp3').copySync('${dirB.path}/b.mp3');
    try {
      final r = await repo.scanFolders([dirA.path, dirB.path]);
      expect(r.added, 2);
      expect((await repo.allBooks()).length, 2);
      // rimuovo il file da dirA → tombstone solo per quello
      File('${dirA.path}/a.m4b').deleteSync();
      final r2 = await repo.scanFolders([dirA.path, dirB.path]);
      expect(r2.removed, 1);
      final paths = (await repo.allBooks()).map((b) => b.path).toList();
      expect(paths.any((x) => x.endsWith('b.mp3')), isTrue);
      expect(paths.any((x) => x.endsWith('a.m4b')), isFalse);
    } finally {
      dirA.deleteSync(recursive: true);
      dirB.deleteSync(recursive: true);
    }
  });

  test('scanFolder resta wrapper di scanFolders([folder])', () async {
    final r = await repo.scanFolder(dir.path);
    expect(r.added, 2); // libro1.m4b + traccia.mp3 dalla fixture setUp
  });
```

Run: `C:\flutter\bin\flutter.bat test test/library_repository_test.dart` → FAIL (scanFolders inesistente).

- [ ] **Step 3: refactor scanFolder→scanFolders** in `library_repository.dart`. Sostituisci l'attuale `scanFolder` con:

```dart
  /// Scansiona PIÙ cartelle (root multipli). Un libro noto è tombstonato solo
  /// se il suo path non è presente in NESSUNA root. File illeggibile → entry
  /// generica, mai errore. Cartelle inesistenti/non leggibili sono saltate.
  Future<ScanResult> scanFolders(List<String> folders, {int? nowMs}) async {
    final now = nowMs ?? DateTime.now().millisecondsSinceEpoch;
    final found = <String, File>{};
    for (final folder in folders) {
      final dir = Directory(folder);
      if (!dir.existsSync()) continue;
      try {
        for (final ent in dir.listSync(recursive: false)) {
          if (ent is File &&
              _audioExts.contains(p.extension(ent.path).toLowerCase())) {
            found[ent.path] = ent;
          }
        }
      } catch (_) {
        // root non leggibile (es. scoped storage): salta, non bloccare
      }
    }
    final known = await db.select(db.books).get();
    final knownByPath = {for (final b in known) b.path: b};
    var added = 0, removed = 0;

    for (final entry in found.entries) {
      final existing = knownByPath[entry.key];
      if (existing == null) {
        await _insertBook(entry.value, now);
        added++;
      } else {
        if (existing.removedAtMs != null) {
          await (db.update(db.books)..where((b) => b.id.equals(existing.id)))
              .write(const BooksCompanion(removedAtMs: Value(null)));
          added++;
        }
        await _reparseIfChanged(existing, entry.value, now);
      }
    }
    for (final b in known) {
      if (b.removedAtMs == null && !found.containsKey(b.path)) {
        await (db.update(db.books)..where((x) => x.id.equals(b.id)))
            .write(BooksCompanion(removedAtMs: Value(now)));
        removed++;
      }
    }
    return ScanResult(added, removed);
  }

  /// Compat: scansione di una sola cartella.
  Future<ScanResult> scanFolder(String folder, {int? nowMs}) =>
      scanFolders([folder], nowMs: nowMs);
```

IMPORTANTE: la logica di re-parse su size/mtime oggi è INLINE dentro l'attuale `scanFolder` (nel ramo `existing != null`). Estrarla in un metodo privato `_reparseIfChanged(Book existing, File f, int now)` che contiene ESATTAMENTE la logica attuale (confronto `stat.size`/`stat.modified` vs `existing.fileSize`/`fileMtimeMs`; se diversi → re-parse in transazione, update riga + delete/insert chapters; reset positionMs/finished se size diversa, conserva se solo mtime). Leggi il codice attuale e spostalo 1:1 nel metodo, richiamandolo dal ramo `existing != null` di `scanFolders`. Non cambiare il comportamento di re-parse.

Run test → PASS (inclusi i test esistenti del repository).

- [ ] **Step 4: commit**

```powershell
git add lib/core/library/library_paths.dart lib/core/library/library_repository.dart test/library_repository_test.dart
git commit -m "feat(library): cartella gestita app-owned + scanFolders multi-root"
```
(footer: riga vuota + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`, here-string `@'...'@`)

---

### Task 2 — Providers: managed dir + scan roots

**Files:** Modify `lib/app/providers.dart`.

- [ ] **Step 1: provider** — aggiungi (import di library_paths.dart):

```dart
/// Cartella gestita dall'app (sempre scrivibile). Sorgente primaria libreria.
final managedLibraryDirProvider =
    FutureProvider<String>((ref) async => (await LibraryPaths.managedDir()).path);

/// Tutte le root da scandire: gestita + esterna opzionale (settings.folderPath).
final scanRootsProvider = FutureProvider<List<String>>((ref) async {
  final managed = await ref.watch(managedLibraryDirProvider.future);
  final settings = await ref.watch(settingsProvider.future);
  final ext = settings.folderPath;
  return (ext == null || ext == managed) ? [managed] : [managed, ext];
});
```

- [ ] **Step 2: verifica + commit**

Run: `C:\flutter\bin\flutter.bat analyze` → No issues; `flutter test` → verde.

```powershell
git add lib/app/providers.dart
git commit -m "feat(library): provider cartella gestita e scan roots (gestita+esterna)"
```

---

### Task 3 — LibraryScreen: niente onboarding obbligatorio, import nella gestita

**Files:** Modify `lib/app/screens/library_screen.dart`; i18n.

- [ ] **Step 1: i18n** (7 ARB; it/en sotto, altre tradotte):

it:
```json
  "libraryRescan": "Aggiorna",
  "settingsExternalFolder": "Cartella esterna (opzionale)",
  "settingsExternalFolderHint": "Aggiungi una cartella da cui leggere altri file audio (sola lettura).",
  "settingsManagedFolder": "Cartella della libreria (app)",
  "settingsRemoveExternal": "Rimuovi cartella esterna"
```
en:
```json
  "libraryRescan": "Refresh",
  "settingsExternalFolder": "External folder (optional)",
  "settingsExternalFolderHint": "Add a folder to read other audio files from (read-only).",
  "settingsManagedFolder": "Library folder (app)",
  "settingsRemoveExternal": "Remove external folder"
```
(se `libraryRescan` esiste già, lascialo; le altre 4 nuove in tutte e 7 le lingue.) `flutter gen-l10n`.

- [ ] **Step 2: modifica LibraryScreen.** Il gate onboarding (`if (settings.folderPath == null) return _Onboarding(...)`) e il ramo iOS auto-set vanno RIMOSSI: la libreria è sempre disponibile (scandisce la cartella gestita). Cambia:
  - `_rescan`: usa `ref.read(scanRootsProvider.future)` e `repo.scanFolders(roots)` + `purgeTombstones()`.
  - All'apertura schermata, fai uno scan iniziale (es. in un `ConsumerStatefulWidget` initState → `_rescan`, oppure un FutureProvider che scansiona una volta). Mantieni il pull-to-refresh.
  - `_importFile`: copia il file nella **cartella gestita** (`await LibraryPaths.managedDir()`), non in folderPath; poi rescan.
  - Rimuovi `_Onboarding`/`_pickFolder` da qui (la scelta cartella esterna si sposta in Settings, Task 4) — oppure lascia `_pickFolder` solo se riusato; in ogni caso niente gate.
  Mostra la lista `booksProvider` come ora. Se vuota → testo `libraryEmpty` (esistente).

Nota esecutore: leggi il file attuale e adatta con cura (il widget potrebbe essere ConsumerWidget; convertilo a ConsumerStatefulWidget se serve l'initState per lo scan iniziale). Mantieni i widget test esistenti verdi (aggiornali se il gate cambia: il test "senza cartella → CTA" non ha più senso → sostituiscilo con "mostra la libreria gestita vuota").

- [ ] **Step 3: run + commit**

Run: `flutter analyze` pulito; `flutter test` verde.

```powershell
git add lib/app/screens/library_screen.dart lib/l10n test/widget
git commit -m "feat(library): libreria sempre attiva su cartella gestita, import nella gestita"
```

---

### Task 4 — Settings: cartella esterna opzionale + info cartella gestita

**Files:** Modify `lib/app/screens/settings_screen.dart`.

- [ ] **Step 1: modifica.** Sostituisci/integra la tile cartella esistente con:
  - Una tile READONLY "Cartella della libreria (app)" (`settingsManagedFolder`) con sottotitolo = path della cartella gestita (`ref.watch(managedLibraryDirProvider).valueOrNull`).
  - Una tile "Cartella esterna (opzionale)" (`settingsExternalFolder`) con sottotitolo = `settings.folderPath ?? '—'` e hint `settingsExternalFolderHint`; onTap → `FilePicker.platform.getDirectoryPath()` → `settings.setFolderPath(path)` → invalida `scanRootsProvider`. Se già impostata, mostra anche un'azione "Rimuovi cartella esterna" (`settingsRemoveExternal`) → `settings.setFolderPath('')` (vuoto → null) + invalida.
  Mantieni le tile esistenti (Server, salti). Import `file_picker`, `providers`.

- [ ] **Step 2: run + commit**

Run: `flutter analyze` pulito; `flutter test` verde.

```powershell
git add lib/app/screens/settings_screen.dart
git commit -m "feat(settings): cartella gestita (info) + cartella esterna opzionale"
```

---

### Task 5 — Activity: bottone unico "Scarica e aggiungi in libreria"

**Files:** Modify `lib/app/screens/activity_screen.dart`; i18n; test.

- [ ] **Step 1: i18n** (7 ARB):

it: `"activityDownloadAdd": "Scarica e aggiungi in libreria"`
en: `"activityDownloadAdd": "Download and add to library"`
(+ fr/es/de/zh/hi). `flutter gen-l10n`.

- [ ] **Step 2: widget test (failing)** — aggiorna `test/widget/activity_screen_test.dart`: il test della lista con un job done `formats {m4b:true, abm:true}` (o {m4b,mp3}) deve ora trovare UN SOLO bottone con testo `Scarica e aggiungi in libreria` (non "Scarica M4B"/"Scarica ABM"). Adatta le asserzioni.

- [ ] **Step 3: modifica `_DoneTile` + `_download`.**
  - `_DoneTile`: invece di `for (final fmt in job.formats) OutlinedButton(...)`, un SOLO bottone (se `job.formats.isNotEmpty`) etichettato `t.activityDownloadAdd`, con spinner durante il download (chiave `_downloading` = `job.jobId`). Se `job.formats.isEmpty` → `activityNoFormats` (come ora).
  - Il formato scaricato = primario per preferenza: `_primaryFormat(job.formats)` con ordine m4b → mp3 → zip → abm.
  - `onDownload(job)` (firma cambia: solo job; il formato lo sceglie il tile o il callback). Aggiorna la firma `onDownload` e `_download` di conseguenza.
  - `_download(RemoteJob job)`: il `folder` diventa la **cartella gestita**: `final folder = (await LibraryPaths.managedDir()).path;` (NON più settings.folderPath). Scarica il formato primario, poi `scanFolders(await scanRootsProvider.future)` (così compare in libreria). Snackbar `activityDownloaded`/`activityDownloadError` come ora. Rimuovi la dipendenza da `settings.folderPath`/`activityFolderMissing` in questo flusso (la gestita esiste sempre).

Snippet helper:
```dart
  static const _fmtPriority = ['m4b', 'mp3', 'zip', 'abm'];
  String? _primaryFormat(List<String> formats) {
    for (final f in _fmtPriority) {
      if (formats.contains(f)) return f;
    }
    return formats.isNotEmpty ? formats.first : null;
  }
```

Nota: import `library_paths.dart` e `scanRootsProvider`. Mantieni il guard anti doppio-download (`_downloading` con key = jobId).

- [ ] **Step 4: run + commit**

Run: `flutter analyze` pulito; `flutter test` verde (il test bottone-unico passa).

```powershell
git add lib/app/screens/activity_screen.dart lib/l10n test/widget/activity_screen_test.dart
git commit -m "fix(activity): bottone unico 'Scarica e aggiungi in libreria' nella cartella gestita"
```

---

### Task 6 — Chiusura

- [ ] **Step 1:** `C:\flutter\bin\dart.bat format .` → `flutter analyze` (No issues) → `flutter test` (tutti PASS, riporta numero). **NIENTE build APK** (direttiva utente).
- [ ] **Step 2:** README sezione Stato: nota breve "download/libreria su cartella gestita app (Android scoped-storage safe) + cartella esterna opzionale; bottone unico download".
- [ ] **Step 3:** commit `git add -A` + `chore(fix-storage): README` + footer Co-Authored-By. NON pushare.

---

## Note per l'esecutore
- **Niente APK** in nessun task (solo analyze+test). Lo costruirà l'utente quando lo dirà.
- **iOS**: la cartella gestita = Documents dell'app (già esposta in File via Info.plist) → su iOS è anche "alimentabile da altre app" nativamente. Bene.
- **Cartella esterna su Android 13+**: la lettura via dart:io può fallire (scoped storage) → `scanFolders` la salta silenziosamente (try/catch). È best-effort, documentalo nella tile hint. Il core (gestita) funziona sempre.
- **Backend NON va toccato**: la causa non era lato server (verificato: /dl serve 200).
- **Stringhe**: mai nominare provider AI/TTS nella UI.
