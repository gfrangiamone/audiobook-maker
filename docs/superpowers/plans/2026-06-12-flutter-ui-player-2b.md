# App Flutter — Piano 2b: UI e Player (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trasformare il core 2a in un'app usabile: navigazione a 4 tab con mini-player, Libreria con onboarding cartella, schermata Player (copertina grande, capitoli in bottom sheet, velocità, sleep timer, salti configurabili) con riproduzione in background e controlli lock screen, posizioni persistite.

**Architecture:** La UI (Riverpod + Material 3) parla solo con tre contratti: `LibraryRepository` (esteso con watch/bookById/lista senza blob), `SettingsService` (cartella + preferenze, shared_preferences) e `PlaybackController` (astrazione testabile; implementazione `AudioPlayerHandler` su audio_service + just_audio). I widget test usano un `FakePlaybackController`; l'audio reale si verifica su device.

**Tech Stack:** flutter_riverpod, audio_service + just_audio, shared_preferences, file_picker, permission_handler, path_provider; drift (già presente).

**Repo target:** `C:\Users\gfran\NEXT srl\Progetti - Documenti\audiobook-maker-mobile` (branch main). Flutter: `C:\flutter\bin\flutter.bat`, Dart: `C:\flutter\bin\dart.bat`. PowerShell, comandi singoli senza `&&`. Spec: `docs/superpowers/specs/2026-06-11-mobile-app-design.md` (repo AudioBook-Maker, branch abm_mobile).

**Vincoli noti:** niente build iOS in locale (Windows); l'APK si builda solo se l'Android SDK è stato configurato (primo avvio GUI di Android Studio — può essere ancora pendente: la build finale è facoltativa). Le decisioni UI vengono dalla spec: 4 tab fisse di pari importanza; player con copertina grande e capitoli in bottom sheet.

**Scelta cartella su Android (decisione di piano):** `file_picker.getDirectoryPath()` (SAF) che su storage primario ritorna un path filesystem reale; lettura file via dart:io con permesso `READ_MEDIA_AUDIO` (Android 13+) / `READ_EXTERNAL_STORAGE` (≤12). Cartelle non risolvibili a path (SD secondarie, provider cloud) → messaggio e ri-scelta. La scrittura nella cartella da parte di ALTRE app è garantita dalla natura shared-storage; la scrittura da parte NOSTRA (download Piano 3) userà lo stesso path. iOS: default = Documents dell'app (esposta in File con le chiavi Info.plist), nessun picker nell'MVP.

## Mappa dei file (nuovi/modificati)

```
lib/
├── main.dart                      # MODIFICA: init audio_service + ProviderScope + app
├── app/
│   ├── app.dart                   # MaterialApp, localizations, tema
│   ├── providers.dart             # provider Riverpod: db, repo, settings, playback, streams
│   ├── shell.dart                 # NavigationBar 4 tab + mini-player persistente
│   ├── screens/
│   │   ├── library_screen.dart    # lista libri, onboarding cartella, import, rescan
│   │   ├── player_screen.dart     # copertina grande, controlli, chips, bottom sheet capitoli
│   │   ├── settings_screen.dart   # cartella, salti, lingua (info), versione
│   │   └── coming_soon_screen.dart # placeholder Crea/Attività (Piano 3)
│   └── widgets/
│       └── mini_player.dart
├── core/
│   ├── library/library_repository.dart  # MODIFICA: +bookById, +watchBooks, +allBooksLite, +coverOf
│   ├── settings/settings_service.dart   # cartella, skip sec, speed (shared_preferences)
│   └── player/
│       ├── chapter_utils.dart           # indice capitolo da posizione, target sleep fine-capitolo
│       ├── playback_types.dart          # PlaybackSnapshot, SleepSetting
│       ├── playback_controller.dart     # contratto astratto
│       └── audio_player_handler.dart    # audio_service + just_audio + persistenza posizioni
android/app/src/main/AndroidManifest.xml # MODIFICA: permessi + service + receiver
android/app/src/main/kotlin/.../MainActivity.kt # MODIFICA: AudioServiceActivity
ios/Runner/Info.plist                    # MODIFICA: UIBackgroundModes audio + file sharing
lib/l10n/app_*.arb                       # MODIFICA: nuove chiavi UI (7 lingue)
test/
├── chapter_utils_test.dart
├── settings_service_test.dart
├── library_repository_test.dart         # MODIFICA: +test watch/lite/coverOf
├── helpers/fake_playback.dart           # FakePlaybackController per widget test
└── widget/
    ├── shell_test.dart
    ├── library_screen_test.dart
    └── player_screen_test.dart
```

---

### Task 1: Dipendenze, configurazione piattaforme, main.dart

**Files:**
- Modify: `pubspec.yaml`, `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/kotlin/it/nextsw/audiobook_maker_mobile/MainActivity.kt`, `ios/Runner/Info.plist`, `lib/main.dart`, `test/widget_test.dart` (eliminato)

- [ ] **Step 1: dipendenze**

In `pubspec.yaml`, aggiungere a `dependencies:` (lasciare le esistenti):

```yaml
  flutter_riverpod: ^2.6.0
  just_audio: ^0.10.0
  audio_service: ^0.18.15
  shared_preferences: ^2.3.0
  file_picker: ^8.1.0
  permission_handler: ^11.3.0
  path_provider: ^2.1.0
```

Run: `C:\flutter\bin\flutter.bat pub get` → `Got dependencies!`. Conflitti → alzare i vincoli all'ultima compatibile e annotare nel commit (questi sono floor al 2026-06).

- [ ] **Step 2: AndroidManifest**

In `android/app/src/main/AndroidManifest.xml`, PRIMA di `<application`:

```xml
    <uses-permission android:name="android.permission.WAKE_LOCK"/>
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK"/>
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>
    <uses-permission android:name="android.permission.READ_MEDIA_AUDIO"/>
    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE"
        android:maxSdkVersion="32"/>
```

DENTRO `<application>` (accanto ad `<activity>`):

```xml
        <service android:name="com.ryanheise.audioservice.AudioService"
            android:foregroundServiceType="mediaPlayback"
            android:exported="true">
            <intent-filter>
                <action android:name="android.media.browse.MediaBrowserService"/>
            </intent-filter>
        </service>
        <receiver android:name="com.ryanheise.audioservice.MediaButtonReceiver"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MEDIA_BUTTON"/>
            </intent-filter>
        </receiver>
```

(Riferimento ufficiale: README di audio_service — se la versione installata documenta nomi diversi, segui il README della versione reale e annota.)

- [ ] **Step 3: MainActivity**

Sostituire il contenuto di `android/app/src/main/kotlin/it/nextsw/audiobook_maker_mobile/MainActivity.kt` (verifica il path reale del package generato):

```kotlin
package it.nextsw.audiobook_maker_mobile

import com.ryanheise.audioservice.AudioServiceActivity

class MainActivity : AudioServiceActivity()
```

- [ ] **Step 4: Info.plist (iOS, solo config — non si builda)**

In `ios/Runner/Info.plist`, dentro il `<dict>` principale:

```xml
	<key>UIBackgroundModes</key>
	<array>
		<string>audio</string>
	</array>
	<key>UIFileSharingEnabled</key>
	<true/>
	<key>LSSupportsOpeningDocumentsInPlace</key>
	<true/>
```

- [ ] **Step 5: main.dart**

Sostituire `lib/main.dart`:

```dart
import 'package:audio_service/audio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
import 'app/providers.dart';
import 'core/player/audio_player_handler.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final handler = await AudioService.init(
    builder: AudioPlayerHandler.new,
    config: const AudioServiceConfig(
      androidNotificationChannelId: 'it.nextsw.audiobook_maker_mobile.audio',
      androidNotificationChannelName: 'AudioBook Maker',
      androidNotificationOngoing: true,
    ),
  );
  runApp(ProviderScope(
    overrides: [playbackControllerProvider.overrideWithValue(handler)],
    child: const AbmApp(),
  ));
}
```

NOTA ordine: `app/app.dart`, `app/providers.dart` e `audio_player_handler.dart` nascono nei Task 5-6; per far compilare questo task SUBITO, crea ora versioni minime: `app.dart` con `class AbmApp extends StatelessWidget` che ritorna `MaterialApp(home: Scaffold(body: Center(child: Text('2b in costruzione'))))`, `providers.dart` con `final playbackControllerProvider = Provider<PlaybackController>((ref) => throw UnimplementedError());` + import del contratto, e il contratto `PlaybackController` vuoto del Task 4/5 (vedi firma completa al Task 5 — incollala da lì). In alternativa committa questo Step insieme al Task 5/6. Scegli la strada che mantiene `flutter analyze` verde a ogni commit.

- [ ] **Step 6: eliminare il counter test**

`test/widget_test.dart` (counter di flutter create) va eliminato: la home cambia. I widget test veri arrivano nei Task 6-8.

- [ ] **Step 7: verifica e commit**

Run: `C:\flutter\bin\flutter.bat analyze` → No issues. `C:\flutter\bin\flutter.bat test` → verdi (18 test core).

```powershell
git add pubspec.yaml pubspec.lock android ios lib/main.dart lib/app lib/core/player
git rm test/widget_test.dart
git commit -m "feat(app): dipendenze player/UI, config piattaforme, bootstrap audio_service"
```

(footer: riga vuota + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`, here-string `@'...'@`)

---

### Task 2: Estensioni LibraryRepository (watch, bookById, lista senza blob)

**Files:**
- Modify: `lib/core/library/library_repository.dart`
- Test: `test/library_repository_test.dart` (append)

- [ ] **Step 1: test che falliscono** (append a `test/library_repository_test.dart`):

```dart
  test('bookById e coverOf', () async {
    await repo.scanFolder(dir.path);
    final book = (await repo.allBooks())
        .firstWhere((b) => b.path.endsWith('libro1.m4b'));
    final fetched = await repo.bookById(book.id);
    expect(fetched!.title, 'Libro di prova');
    final cover = await repo.coverOf(book.id);
    expect(cover, isNotNull); // la fixture ha la cover PNG
    expect(await repo.bookById(999999), isNull);
  });

  test('allBooksLite non materializza il blob cover', () async {
    await repo.scanFolder(dir.path);
    final lite = await repo.allBooksLite();
    expect(lite, hasLength(2));
    final m4b = lite.firstWhere((b) => b.path.endsWith('libro1.m4b'));
    expect(m4b.title, 'Libro di prova');
    expect(m4b.hasCover, isTrue);
    expect(m4b.durationMs, greaterThan(0));
  });

  test('watchBooks emette dopo una scansione', () async {
    final emissions = <int>[];
    final sub = repo.watchBooks().listen((rows) => emissions.add(rows.length));
    await repo.scanFolder(dir.path);
    await Future<void>.delayed(const Duration(milliseconds: 300));
    await sub.cancel();
    expect(emissions.last, 2);
  });
```

Run: `C:\flutter\bin\flutter.bat test test/library_repository_test.dart` → FAIL (metodi inesistenti).

- [ ] **Step 2: implementare** (append a `LibraryRepository`):

```dart
  /// Vista leggera per le liste: tutte le colonne TRANNE il blob cover.
  Future<List<BookLite>> allBooksLite() async {
    final rows = await db.customSelect(
      'SELECT id, path, title, author, duration_ms, added_at_ms, '
      'position_ms, finished, (cover IS NOT NULL) AS has_cover '
      'FROM books WHERE removed_at_ms IS NULL ORDER BY added_at_ms DESC',
      readsFrom: {db.books},
    ).get();
    return [
      for (final r in rows)
        BookLite(
          id: r.read<int>('id'),
          path: r.read<String>('path'),
          title: r.read<String>('title'),
          author: r.read<String>('author'),
          durationMs: r.read<int>('duration_ms'),
          addedAtMs: r.read<int>('added_at_ms'),
          positionMs: r.read<int>('position_ms'),
          finished: r.read<bool>('finished'),
          hasCover: r.read<bool>('has_cover'),
        )
    ];
  }

  /// Stream reattivo della lista leggera (si riemette a ogni modifica Books).
  Stream<List<BookLite>> watchBooks() {
    return db
        .customSelect(
          'SELECT id, path, title, author, duration_ms, added_at_ms, '
          'position_ms, finished, (cover IS NOT NULL) AS has_cover '
          'FROM books WHERE removed_at_ms IS NULL ORDER BY added_at_ms DESC',
          readsFrom: {db.books},
        )
        .watch()
        .map((rows) => [
              for (final r in rows)
                BookLite(
                  id: r.read<int>('id'),
                  path: r.read<String>('path'),
                  title: r.read<String>('title'),
                  author: r.read<String>('author'),
                  durationMs: r.read<int>('duration_ms'),
                  addedAtMs: r.read<int>('added_at_ms'),
                  positionMs: r.read<int>('position_ms'),
                  finished: r.read<bool>('finished'),
                  hasCover: r.read<bool>('has_cover'),
                )
            ]);
  }

  Future<Book?> bookById(int id) => (db.select(db.books)
        ..where((b) => b.id.equals(id) & b.removedAtMs.isNull()))
      .getSingleOrNull();

  Future<Uint8List?> coverOf(int bookId) async {
    final b = await bookById(bookId);
    return b?.cover;
  }
```

DRY: il mapping riga→BookLite compare due volte — estrarre un helper privato `BookLite _liteFromRow(QueryRow r)` e usarlo in entrambi. Aggiungere in testa al file `import 'dart:typed_data';` e la classe:

```dart
class BookLite {
  final int id;
  final String path;
  final String title;
  final String author;
  final int durationMs;
  final int addedAtMs;
  final int positionMs;
  final bool finished;
  final bool hasCover;
  const BookLite({
    required this.id,
    required this.path,
    required this.title,
    required this.author,
    required this.durationMs,
    required this.addedAtMs,
    required this.positionMs,
    required this.finished,
    required this.hasCover,
  });
}
```

Nota colonne: drift genera snake_case (`duration_ms`...) — verifica i nomi reali in `library_db.g.dart` se il customSelect fallisce. `r.read<bool>` su un'espressione SQLite intera: se lancia, usare `r.read<int>(...) != 0`.

- [ ] **Step 3: run + commit**

Run: `C:\flutter\bin\flutter.bat test` → 21/21 PASS.

```powershell
git add lib/core/library/library_repository.dart test/library_repository_test.dart
git commit -m "feat(library): watchBooks, allBooksLite senza blob, bookById, coverOf"
```

---

### Task 3: SettingsService

**Files:**
- Create: `lib/core/settings/settings_service.dart`
- Test: `test/settings_service_test.dart`

- [ ] **Step 1: test che falliscono** — `test/settings_service_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:audiobook_maker_mobile/core/settings/settings_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('default: cartella null, salti 30/10, velocità 1.0', () async {
    SharedPreferences.setMockInitialValues({});
    final s = await SettingsService.load();
    expect(s.folderPath, isNull);
    expect(s.skipForwardSec, 30);
    expect(s.skipBackSec, 10);
    expect(s.playbackSpeed, 1.0);
  });

  test('set e reload persistono', () async {
    SharedPreferences.setMockInitialValues({});
    final s = await SettingsService.load();
    await s.setFolderPath('C:/audiolibri');
    await s.setSkipForwardSec(45);
    await s.setSkipBackSec(15);
    await s.setPlaybackSpeed(1.5);
    final s2 = await SettingsService.load();
    expect(s2.folderPath, 'C:/audiolibri');
    expect(s2.skipForwardSec, 45);
    expect(s2.skipBackSec, 15);
    expect(s2.playbackSpeed, 1.5);
  });
}
```

Run → FAIL.

- [ ] **Step 2: implementare** — `lib/core/settings/settings_service.dart`:

```dart
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Preferenze persistenti dell'app. ChangeNotifier: la UI si aggiorna al volo.
class SettingsService extends ChangeNotifier {
  static const _kFolder = 'folder_path';
  static const _kSkipFwd = 'skip_forward_sec';
  static const _kSkipBack = 'skip_back_sec';
  static const _kSpeed = 'playback_speed';

  final SharedPreferences _prefs;
  SettingsService._(this._prefs);

  static Future<SettingsService> load() async =>
      SettingsService._(await SharedPreferences.getInstance());

  String? get folderPath => _prefs.getString(_kFolder);
  int get skipForwardSec => _prefs.getInt(_kSkipFwd) ?? 30;
  int get skipBackSec => _prefs.getInt(_kSkipBack) ?? 10;
  double get playbackSpeed => _prefs.getDouble(_kSpeed) ?? 1.0;

  Future<void> setFolderPath(String path) async {
    await _prefs.setString(_kFolder, path);
    notifyListeners();
  }

  Future<void> setSkipForwardSec(int v) async {
    await _prefs.setInt(_kSkipFwd, v);
    notifyListeners();
  }

  Future<void> setSkipBackSec(int v) async {
    await _prefs.setInt(_kSkipBack, v);
    notifyListeners();
  }

  Future<void> setPlaybackSpeed(double v) async {
    await _prefs.setDouble(_kSpeed, v);
    notifyListeners();
  }
}
```

- [ ] **Step 3: run + commit**

Run: `C:\flutter\bin\flutter.bat test test/settings_service_test.dart` → 2/2 PASS.

```powershell
git add lib/core/settings test/settings_service_test.dart
git commit -m "feat(settings): preferenze persistenti (cartella, salti, velocita)"
```

---

### Task 4: Logica pura del player (capitoli, sleep, tipi)

**Files:**
- Create: `lib/core/player/chapter_utils.dart`, `lib/core/player/playback_types.dart`
- Test: `test/chapter_utils_test.dart`

- [ ] **Step 1: test che falliscono** — `test/chapter_utils_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/player/chapter_utils.dart';

void main() {
  const starts = [0, 120000, 360000]; // 0:00, 2:00, 6:00

  test('indice capitolo dalla posizione', () {
    expect(currentChapterIndex(starts, 0), 0);
    expect(currentChapterIndex(starts, 119999), 0);
    expect(currentChapterIndex(starts, 120000), 1);
    expect(currentChapterIndex(starts, 999999), 2);
    expect(currentChapterIndex(const [], 5000), -1);
  });

  test('inizio capitolo successivo/precedente', () {
    expect(nextChapterStartMs(starts, 0), 120000);
    expect(nextChapterStartMs(starts, 360000), isNull); // ultimo
    // "precedente": se sono oltre 3s nel capitolo torno al suo inizio
    expect(previousChapterTargetMs(starts, 130000), 120000);
    // se sono nei primi 3s vado al capitolo prima
    expect(previousChapterTargetMs(starts, 121000), 0);
    expect(previousChapterTargetMs(starts, 1000), 0);
  });

  test('target sleep fine capitolo', () {
    expect(sleepEndOfChapterTargetMs(starts, 130000, 600000), 360000);
    // ultimo capitolo: fine libro
    expect(sleepEndOfChapterTargetMs(starts, 400000, 600000), 600000);
    expect(sleepEndOfChapterTargetMs(const [], 1000, 600000), 600000);
  });
}
```

Run → FAIL.

- [ ] **Step 2: implementare** — `lib/core/player/chapter_utils.dart`:

```dart
/// Indice del capitolo che contiene [positionMs] (-1 se lista vuota).
int currentChapterIndex(List<int> startsMs, int positionMs) {
  if (startsMs.isEmpty) return -1;
  var idx = 0;
  for (var i = 0; i < startsMs.length; i++) {
    if (startsMs[i] <= positionMs) idx = i;
  }
  return idx;
}

/// Inizio del capitolo successivo, o null se siamo nell'ultimo.
int? nextChapterStartMs(List<int> startsMs, int positionMs) {
  final idx = currentChapterIndex(startsMs, positionMs);
  if (idx < 0 || idx + 1 >= startsMs.length) return null;
  return startsMs[idx + 1];
}

/// Comportamento standard "capitolo precedente": entro i primi 3s del
/// capitolo si va a quello prima, altrimenti si torna al suo inizio.
int previousChapterTargetMs(List<int> startsMs, int positionMs) {
  final idx = currentChapterIndex(startsMs, positionMs);
  if (idx <= 0) return 0;
  final intoChapter = positionMs - startsMs[idx];
  return intoChapter > 3000 ? startsMs[idx] : startsMs[idx - 1];
}

/// Posizione a cui fermarsi per lo sleep "fine capitolo".
int sleepEndOfChapterTargetMs(
    List<int> startsMs, int positionMs, int durationMs) {
  return nextChapterStartMs(startsMs, positionMs) ?? durationMs;
}
```

E `lib/core/player/playback_types.dart`:

```dart
import 'dart:typed_data';
import 'package:flutter/foundation.dart';

@immutable
class SleepSetting {
  /// null ⇒ "fine capitolo"; altrimenti countdown.
  final Duration? duration;
  const SleepSetting.minutes(int min) : duration = Duration(minutes: min);
  const SleepSetting.endOfChapter() : duration = null;
  bool get isEndOfChapter => duration == null;
}

/// Fotografia immutabile dello stato di riproduzione per la UI.
@immutable
class PlaybackSnapshot {
  final int bookId;
  final String title;
  final String author;
  final Uint8List? coverBytes;
  final bool playing;
  final Duration position;
  final Duration duration;
  final double speed;
  final List<String> chapterTitles;
  final List<int> chapterStartsMs;
  final int chapterIndex; // -1 se senza capitoli
  final Duration? sleepRemaining; // null = sleep spento
  const PlaybackSnapshot({
    required this.bookId,
    required this.title,
    required this.author,
    required this.coverBytes,
    required this.playing,
    required this.position,
    required this.duration,
    required this.speed,
    required this.chapterTitles,
    required this.chapterStartsMs,
    required this.chapterIndex,
    required this.sleepRemaining,
  });
}
```

- [ ] **Step 3: run + commit**

Run: `C:\flutter\bin\flutter.bat test test/chapter_utils_test.dart` → 3/3 PASS.

```powershell
git add lib/core/player/chapter_utils.dart lib/core/player/playback_types.dart test/chapter_utils_test.dart
git commit -m "feat(player): chapter utils e tipi snapshot/sleep (logica pura testata)"
```

---

### Task 5: PlaybackController + AudioPlayerHandler

**Files:**
- Create: `lib/core/player/playback_controller.dart`, `lib/core/player/audio_player_handler.dart`
- Test: nessun test host per l'audio reale (just_audio richiede piattaforma); la logica pura è già coperta dal Task 4 e il contratto sarà esercitato dai widget test col fake (Task 6-8). Verifica su device nel Task 9.

- [ ] **Step 1: contratto** — `lib/core/player/playback_controller.dart`:

```dart
import 'library_imports.dart'; // NO: vedi import reali sotto
```

Import reali del file:

```dart
import '../library/library_db.dart';
import 'playback_types.dart';

/// Contratto del player visto dalla UI. Implementazioni: AudioPlayerHandler
/// (reale) e FakePlaybackController (test).
abstract class PlaybackController {
  /// Stream dello stato corrente; emette null quando nessun libro è caricato.
  Stream<PlaybackSnapshot?> get snapshots;

  /// Ultimo valore emesso (per build sincroni della UI).
  PlaybackSnapshot? get current;

  /// Carica un libro e riprende dalla posizione salvata.
  Future<void> loadBook(Book book, List<Chapter> chapters,
      {bool autoPlay = true});

  Future<void> play();
  Future<void> pause();
  Future<void> seek(Duration position);
  Future<void> skipForward();
  Future<void> skipBack();
  Future<void> nextChapter();
  Future<void> previousChapter();
  Future<void> setSpeed(double speed);
  void setSleep(SleepSetting? setting); // null = annulla
}
```

- [ ] **Step 2: implementazione** — `lib/core/player/audio_player_handler.dart`:

```dart
import 'dart:async';
import 'dart:io';

import 'package:audio_service/audio_service.dart';
import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:rxdart/rxdart.dart';

import '../library/library_db.dart';
import '../library/library_repository.dart';
import 'chapter_utils.dart';
import 'playback_controller.dart';
import 'playback_types.dart';

/// Player reale: just_audio per l'audio, audio_service per notifica media,
/// lock screen e cuffie. Persiste la posizione su LibraryRepository.
class AudioPlayerHandler extends BaseAudioHandler
    with SeekHandler
    implements PlaybackController {
  final _player = AudioPlayer();
  final _snapshots = BehaviorSubject<PlaybackSnapshot?>.seeded(null);

  // iniettati post-costruzione (AudioService.init non accetta parametri)
  LibraryRepository? _repo;
  int _skipForwardSec = 30;
  int _skipBackSec = 10;

  Book? _book;
  List<Chapter> _chapters = const [];
  Timer? _saveTimer;
  Timer? _sleepTimer;
  DateTime? _sleepDeadline;
  int? _sleepStopAtMs; // sleep "fine capitolo"

  AudioPlayerHandler() {
    _player.playbackEventStream.listen(_broadcastState);
    _player.positionStream.listen((_) => _emitSnapshot());
    _player.processingStateStream.listen((st) async {
      if (st == ProcessingState.completed && _book != null) {
        await _repo?.markFinished(_book!.id);
        await pause();
      }
    });
  }

  void configure(
      {required LibraryRepository repo,
      required int skipForwardSec,
      required int skipBackSec}) {
    _repo = repo;
    _skipForwardSec = skipForwardSec;
    _skipBackSec = skipBackSec;
  }

  @override
  Stream<PlaybackSnapshot?> get snapshots => _snapshots.stream;

  @override
  PlaybackSnapshot? get current => _snapshots.value;

  @override
  Future<void> loadBook(Book book, List<Chapter> chapters,
      {bool autoPlay = true}) async {
    _book = book;
    _chapters = chapters;
    _cancelSleep();
    await _player.setAudioSource(AudioSource.file(book.path),
        initialPosition: Duration(milliseconds: book.positionMs));
    mediaItem.add(MediaItem(
      id: book.path,
      title: book.title,
      artist: book.author,
      duration: _player.duration,
      artUri: await _coverUri(book),
    ));
    _startSaveTimer();
    _emitSnapshot();
    if (autoPlay) await play();
  }

  Future<Uri?> _coverUri(Book book) async {
    final bytes = book.cover;
    if (bytes == null) return null;
    final dir = await getTemporaryDirectory();
    final f = File('${dir.path}/cover_${book.id}.img');
    await f.writeAsBytes(bytes, flush: true);
    return Uri.file(f.path);
  }

  // ---- controlli ----------------------------------------------------------
  @override
  Future<void> play() => _player.play();

  @override
  Future<void> pause() async {
    await _player.pause();
    await _savePosition();
  }

  @override
  Future<void> seek(Duration position) => _player.seek(position);

  @override
  Future<void> skipForward() =>
      seek(_player.position + Duration(seconds: _skipForwardSec));

  @override
  Future<void> skipBack() => seek(Duration(
      milliseconds: (_player.position.inMilliseconds -
              _skipBackSec * 1000)
          .clamp(0, 1 << 62)));

  @override
  Future<void> nextChapter() async {
    final next = nextChapterStartMs(
        _starts, _player.position.inMilliseconds);
    if (next != null) await seek(Duration(milliseconds: next));
  }

  @override
  Future<void> previousChapter() => seek(Duration(
      milliseconds:
          previousChapterTargetMs(_starts, _player.position.inMilliseconds)));

  @override
  Future<void> setSpeed(double speed) => _player.setSpeed(speed);

  // mapping bottoni notifica/cuffie → capitoli (standard audiolibri)
  @override
  Future<void> skipToNext() => nextChapter();
  @override
  Future<void> skipToPrevious() => previousChapter();
  @override
  Future<void> fastForward() => skipForward();
  @override
  Future<void> rewind() => skipBack();
  @override
  Future<void> stop() async {
    await _savePosition();
    await _player.stop();
    await super.stop();
  }

  // ---- sleep timer ---------------------------------------------------------
  @override
  void setSleep(SleepSetting? setting) {
    _cancelSleep();
    if (setting == null) {
      _emitSnapshot();
      return;
    }
    if (setting.isEndOfChapter) {
      _sleepStopAtMs = sleepEndOfChapterTargetMs(
          _starts,
          _player.position.inMilliseconds,
          _player.duration?.inMilliseconds ?? 0);
    } else {
      _sleepDeadline = DateTime.now().add(setting.duration!);
    }
    _sleepTimer = Timer.periodic(const Duration(seconds: 1), (_) async {
      final stopByClock = _sleepDeadline != null &&
          DateTime.now().isAfter(_sleepDeadline!);
      final stopByChapter = _sleepStopAtMs != null &&
          _player.position.inMilliseconds >= _sleepStopAtMs!;
      if (stopByClock || stopByChapter) {
        _cancelSleep();
        await pause();
      }
      _emitSnapshot();
    });
    _emitSnapshot();
  }

  void _cancelSleep() {
    _sleepTimer?.cancel();
    _sleepTimer = null;
    _sleepDeadline = null;
    _sleepStopAtMs = null;
  }

  // ---- persistenza posizione ----------------------------------------------
  void _startSaveTimer() {
    _saveTimer?.cancel();
    _saveTimer = Timer.periodic(
        const Duration(seconds: 5), (_) => _savePosition());
  }

  Future<void> _savePosition() async {
    final b = _book;
    if (b == null) return;
    await _repo?.savePosition(b.id, _player.position.inMilliseconds);
  }

  // ---- broadcast -----------------------------------------------------------
  List<int> get _starts => [for (final c in _chapters) c.startMs];

  void _emitSnapshot() {
    final b = _book;
    if (b == null) {
      _snapshots.add(null);
      return;
    }
    Duration? sleepRemaining;
    if (_sleepDeadline != null) {
      final d = _sleepDeadline!.difference(DateTime.now());
      sleepRemaining = d.isNegative ? Duration.zero : d;
    } else if (_sleepStopAtMs != null) {
      sleepRemaining = Duration(
          milliseconds: (_sleepStopAtMs! - _player.position.inMilliseconds)
              .clamp(0, 1 << 62));
    }
    _snapshots.add(PlaybackSnapshot(
      bookId: b.id,
      title: b.title,
      author: b.author,
      coverBytes: b.cover,
      playing: _player.playing,
      position: _player.position,
      duration: _player.duration ?? Duration(milliseconds: b.durationMs),
      speed: _player.speed,
      chapterTitles: [for (final c in _chapters) c.title],
      chapterStartsMs: _starts,
      chapterIndex:
          currentChapterIndex(_starts, _player.position.inMilliseconds),
      sleepRemaining: sleepRemaining,
    ));
  }

  void _broadcastState(PlaybackEvent event) {
    playbackState.add(playbackState.value.copyWith(
      controls: [
        MediaControl.skipToPrevious,
        MediaControl.rewind,
        if (_player.playing) MediaControl.pause else MediaControl.play,
        MediaControl.fastForward,
        MediaControl.skipToNext,
      ],
      systemActions: const {MediaAction.seek},
      processingState: const {
        ProcessingState.idle: AudioProcessingState.idle,
        ProcessingState.loading: AudioProcessingState.loading,
        ProcessingState.buffering: AudioProcessingState.buffering,
        ProcessingState.ready: AudioProcessingState.ready,
        ProcessingState.completed: AudioProcessingState.completed,
      }[_player.processingState]!,
      playing: _player.playing,
      updatePosition: _player.position,
      bufferedPosition: _player.bufferedPosition,
      speed: _player.speed,
    ));
    _emitSnapshot();
  }
}
```

Aggiungere `rxdart: ^0.28.0` alle dependencies (`flutter pub get`).

Nota esecutore: le API di audio_service 0.18 (`BaseAudioHandler`, `playbackState.copyWith`, `MediaControl`) e just_audio sono qui per come documentate; se la versione installata differisce in firme minori, adattare seguendo il loro README mantenendo il CONTRATTO `PlaybackController` invariato (i widget dipendono solo da quello).

- [ ] **Step 3: verifica statica + commit**

Run: `C:\flutter\bin\flutter.bat analyze` → No issues. `C:\flutter\bin\flutter.bat test` → verdi.

```powershell
git add lib/core/player pubspec.yaml pubspec.lock
git commit -m "feat(player): PlaybackController + AudioPlayerHandler (audio_service/just_audio)"
```

---

### Task 6: Providers, App, Shell con 4 tab e mini-player

**Files:**
- Create/Modify: `lib/app/providers.dart`, `lib/app/app.dart`, `lib/app/shell.dart`, `lib/app/screens/coming_soon_screen.dart`, `lib/app/widgets/mini_player.dart`
- Modify: `lib/l10n/app_*.arb` (nuove chiavi)
- Test: `test/helpers/fake_playback.dart`, `test/widget/shell_test.dart`

- [ ] **Step 1: chiavi i18n**

Aggiungere a TUTTI e 7 gli `lib/l10n/app_<lang>.arb` (qui it e en; tradurre con cura le altre 5):

it:
```json
  "tabLibrary": "Libreria",
  "tabCreate": "Crea",
  "tabActivity": "Attività",
  "tabSettings": "Impostazioni",
  "comingSoon": "Disponibile prossimamente",
  "comingSoonDetail": "Questa sezione arriverà con il collegamento al sito.",
  "playerChapters": "Capitoli",
  "playerSpeed": "Velocità",
  "playerSleep": "Sleep",
  "sleepOff": "Spento",
  "sleepEndOfChapter": "Fine capitolo",
  "sleepNMinutes": "{min} minuti",
  "@sleepNMinutes": {"placeholders": {"min": {"type": "int"}}},
  "pickFolderTitle": "Scegli la cartella degli audiolibri",
  "pickFolderBody": "L'app indicizza i file mp3/m4b di una cartella a tua scelta. Potrai cambiarla dalle impostazioni.",
  "pickFolderButton": "Scegli cartella",
  "pickFolderUnresolved": "Cartella non utilizzabile da questa app: scegline una sullo storage del telefono.",
  "importFile": "Importa file audio",
  "rescanDone": "Libreria aggiornata: {added} nuovi, {removed} rimossi",
  "@rescanDone": {"placeholders": {"added": {"type": "int"}, "removed": {"type": "int"}}}
```

en:
```json
  "tabLibrary": "Library",
  "tabCreate": "Create",
  "tabActivity": "Activity",
  "tabSettings": "Settings",
  "comingSoon": "Coming soon",
  "comingSoonDetail": "This section will arrive with the website integration.",
  "playerChapters": "Chapters",
  "playerSpeed": "Speed",
  "playerSleep": "Sleep",
  "sleepOff": "Off",
  "sleepEndOfChapter": "End of chapter",
  "sleepNMinutes": "{min} minutes",
  "@sleepNMinutes": {"placeholders": {"min": {"type": "int"}}},
  "pickFolderTitle": "Choose your audiobooks folder",
  "pickFolderBody": "The app indexes mp3/m4b files from a folder you choose. You can change it later in settings.",
  "pickFolderButton": "Choose folder",
  "pickFolderUnresolved": "This folder can't be used by the app: pick one on the phone storage.",
  "importFile": "Import audio file",
  "rescanDone": "Library refreshed: {added} new, {removed} removed",
  "@rescanDone": {"placeholders": {"added": {"type": "int"}, "removed": {"type": "int"}}}
```

Run: `C:\flutter\bin\flutter.bat gen-l10n` → ok (tutte le lingue complete).

- [ ] **Step 2: providers** — `lib/app/providers.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../core/library/library_db.dart';
import '../core/library/library_repository.dart';
import '../core/player/playback_controller.dart';
import '../core/player/playback_types.dart';
import '../core/settings/settings_service.dart';

/// Override in main() col vero AudioPlayerHandler; nei test col fake.
final playbackControllerProvider =
    Provider<PlaybackController>((ref) => throw UnimplementedError());

final settingsProvider = FutureProvider<SettingsService>(
    (ref) async => SettingsService.load());

final libraryDbProvider = Provider<LibraryDb>((ref) {
  throw UnimplementedError(); // override in main()
});

final libraryRepositoryProvider = Provider<LibraryRepository>(
    (ref) => LibraryRepository(ref.watch(libraryDbProvider)));

final booksProvider = StreamProvider<List<BookLite>>(
    (ref) => ref.watch(libraryRepositoryProvider).watchBooks());

final playbackSnapshotProvider = StreamProvider<PlaybackSnapshot?>(
    (ref) => ref.watch(playbackControllerProvider).snapshots);
```

In `lib/main.dart`, dopo `AudioService.init`, creare il DB reale e completare gli override (sostituire il runApp del Task 1):

```dart
  final supportDir = await getApplicationSupportDirectory();
  final db = LibraryDb.file('${supportDir.path}/library.sqlite');
  final settings = await SettingsService.load();
  handler.configure(
      repo: LibraryRepository(db),
      skipForwardSec: settings.skipForwardSec,
      skipBackSec: settings.skipBackSec);
  runApp(ProviderScope(
    overrides: [
      playbackControllerProvider.overrideWithValue(handler),
      libraryDbProvider.overrideWithValue(db),
    ],
    child: const AbmApp(),
  ));
```

(con i relativi import; su Android `LibraryDb.file` richiede sqlite3 nativa: aggiungere `sqlite3_flutter_libs: ^0.5.24` alle dependencies + `flutter pub get`)

- [ ] **Step 3: app + shell + placeholder + mini-player**

`lib/app/app.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../l10n/app_localizations.dart'; // path reale del generato: verifica
import 'shell.dart';

class AbmApp extends StatelessWidget {
  const AbmApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      onGenerateTitle: (ctx) => AppLocalizations.of(ctx)!.appTitle,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF4A6FA5)),
        useMaterial3: true,
      ),
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: const AppShell(),
    );
  }
}
```

NOTA import generato: con `generate: true` recente l'output è `lib/l10n/app_localizations.dart`; se il progetto lo genera in `.dart_tool/flutter_gen/gen_l10n/`, l'import è `package:flutter_gen/gen_l10n/app_localizations.dart`. Guarda dove sta il file (è già committato da 2a) e usa quello, in TUTTI i file UI.

`lib/app/shell.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import 'providers.dart';
import 'screens/coming_soon_screen.dart';
import 'screens/library_screen.dart';
import 'screens/settings_screen.dart';
import 'widgets/mini_player.dart';

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});
  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  var _tab = 0;

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context)!;
    final snapshot = ref.watch(playbackSnapshotProvider).valueOrNull;
    final pages = [
      const LibraryScreen(),
      ComingSoonScreen(title: t.tabCreate),
      ComingSoonScreen(title: t.tabActivity),
      const SettingsScreen(),
    ];
    return Scaffold(
      body: SafeArea(child: pages[_tab]),
      bottomNavigationBar: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (snapshot != null) const MiniPlayer(),
          NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            destinations: [
              NavigationDestination(
                  icon: const Icon(Icons.library_books_outlined),
                  selectedIcon: const Icon(Icons.library_books),
                  label: t.tabLibrary),
              NavigationDestination(
                  icon: const Icon(Icons.add_circle_outline),
                  selectedIcon: const Icon(Icons.add_circle),
                  label: t.tabCreate),
              NavigationDestination(
                  icon: const Icon(Icons.schedule_outlined),
                  selectedIcon: const Icon(Icons.schedule),
                  label: t.tabActivity),
              NavigationDestination(
                  icon: const Icon(Icons.settings_outlined),
                  selectedIcon: const Icon(Icons.settings),
                  label: t.tabSettings),
            ],
          ),
        ],
      ),
    );
  }
}
```

`lib/app/screens/coming_soon_screen.dart`:

```dart
import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';

class ComingSoonScreen extends StatelessWidget {
  final String title;
  const ComingSoonScreen({super.key, required this.title});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context)!;
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(title, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 12),
          Text(t.comingSoon,
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(t.comingSoonDetail,
              style: Theme.of(context).textTheme.bodyMedium,
              textAlign: TextAlign.center),
        ],
      ),
    );
  }
}
```

`lib/app/widgets/mini_player.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import '../screens/player_screen.dart';

class MiniPlayer extends ConsumerWidget {
  const MiniPlayer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final snap = ref.watch(playbackSnapshotProvider).valueOrNull;
    if (snap == null) return const SizedBox.shrink();
    final controller = ref.read(playbackControllerProvider);
    final chapter = snap.chapterIndex >= 0 &&
            snap.chapterIndex < snap.chapterTitles.length
        ? snap.chapterTitles[snap.chapterIndex]
        : '';
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: InkWell(
        onTap: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const PlayerScreen())),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Row(
            children: [
              if (snap.coverBytes != null)
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: Image.memory(snap.coverBytes!,
                      width: 36, height: 36, fit: BoxFit.cover),
                )
              else
                const Icon(Icons.menu_book, size: 36),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(snap.title,
                        maxLines: 1, overflow: TextOverflow.ellipsis),
                    if (chapter.isNotEmpty)
                      Text(chapter,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
              IconButton(
                icon: Icon(snap.playing ? Icons.pause : Icons.play_arrow),
                onPressed: () =>
                    snap.playing ? controller.pause() : controller.play(),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
```

(`SettingsScreen` e `LibraryScreen`/`PlayerScreen` nascono nei Task 7-8: per compilare ORA crea file minimi `class SettingsScreen extends StatelessWidget` → `Center(child: Text('...'))`, idem LibraryScreen/PlayerScreen, che i Task 7-8 sostituiranno integralmente.)

- [ ] **Step 4: fake + widget test** — `test/helpers/fake_playback.dart`:

```dart
import 'dart:async';
import 'package:audiobook_maker_mobile/core/library/library_db.dart';
import 'package:audiobook_maker_mobile/core/player/playback_controller.dart';
import 'package:audiobook_maker_mobile/core/player/playback_types.dart';

class FakePlaybackController implements PlaybackController {
  final _ctrl = StreamController<PlaybackSnapshot?>.broadcast();
  PlaybackSnapshot? _current;
  final calls = <String>[];

  void emit(PlaybackSnapshot? s) {
    _current = s;
    _ctrl.add(s);
  }

  @override
  Stream<PlaybackSnapshot?> get snapshots => _ctrl.stream;
  @override
  PlaybackSnapshot? get current => _current;
  @override
  Future<void> loadBook(Book book, List<Chapter> chapters,
      {bool autoPlay = true}) async {
    calls.add('loadBook:${book.id}');
  }

  @override
  Future<void> play() async => calls.add('play');
  @override
  Future<void> pause() async => calls.add('pause');
  @override
  Future<void> seek(Duration position) async =>
      calls.add('seek:${position.inMilliseconds}');
  @override
  Future<void> skipForward() async => calls.add('skipForward');
  @override
  Future<void> skipBack() async => calls.add('skipBack');
  @override
  Future<void> nextChapter() async => calls.add('nextChapter');
  @override
  Future<void> previousChapter() async => calls.add('previousChapter');
  @override
  Future<void> setSpeed(double speed) async => calls.add('speed:$speed');
  @override
  void setSleep(SleepSetting? setting) => calls.add('sleep');
}

PlaybackSnapshot snapshotFixture({bool playing = true}) => PlaybackSnapshot(
      bookId: 1,
      title: 'Il nome della rosa',
      author: 'Umberto Eco',
      coverBytes: null,
      playing: playing,
      position: const Duration(minutes: 12),
      duration: const Duration(hours: 8),
      speed: 1.0,
      chapterTitles: const ['Uno', 'Due', 'Tre'],
      chapterStartsMs: const [0, 120000, 360000],
      chapterIndex: 0,
      sleepRemaining: null,
    );
```

`test/widget/shell_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:audiobook_maker_mobile/app/app.dart';
import 'package:audiobook_maker_mobile/app/providers.dart';
import 'package:audiobook_maker_mobile/core/library/library_db.dart';

import '../helpers/fake_playback.dart';
import '../helpers/sqlite.dart';

void main() {
  setUpAll(ensureSqlite);

  Future<(FakePlaybackController, Widget)> buildApp() async {
    SharedPreferences.setMockInitialValues({'folder_path': 'C:/x'});
    final fake = FakePlaybackController();
    final db = LibraryDb.memory();
    addTearDown(db.close);
    return (
      fake,
      ProviderScope(
        overrides: [
          playbackControllerProvider.overrideWithValue(fake),
          libraryDbProvider.overrideWithValue(db),
        ],
        child: const AbmApp(),
      )
    );
  }

  testWidgets('4 tab presenti, mini-player nascosto senza riproduzione',
      (tester) async {
    final (_, app) = await buildApp();
    await tester.pumpWidget(app);
    await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.byType(NavigationDestination), findsNWidgets(4));
    expect(find.byIcon(Icons.pause), findsNothing);
  });

  testWidgets('mini-player appare quando arriva uno snapshot',
      (tester) async {
    final (fake, app) = await buildApp();
    await tester.pumpWidget(app);
    await tester.pumpAndSettle();
    fake.emit(snapshotFixture());
    await tester.pumpAndSettle();
    expect(find.text('Il nome della rosa'), findsOneWidget);
    expect(find.byIcon(Icons.pause), findsOneWidget);
    await tester.tap(find.byIcon(Icons.pause));
    expect(fake.calls, contains('pause'));
  });
}
```

- [ ] **Step 5: run + commit**

Run: `C:\flutter\bin\flutter.bat test` → tutti PASS (core + 2 widget). `analyze` pulito.

```powershell
git add lib/app lib/l10n lib/main.dart pubspec.yaml pubspec.lock test/helpers/fake_playback.dart test/widget
git commit -m "feat(ui): shell 4 tab, mini-player, providers, i18n UI"
```

---

### Task 7: LibraryScreen con onboarding cartella e import

**Files:**
- Create: `lib/app/screens/library_screen.dart` (sostituisce lo stub), `lib/app/screens/settings_screen.dart` (sostituisce lo stub)
- Test: `test/widget/library_screen_test.dart`

- [ ] **Step 1: widget test (failing)** — `test/widget/library_screen_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:audiobook_maker_mobile/app/app.dart';
import 'package:audiobook_maker_mobile/app/providers.dart';
import 'package:audiobook_maker_mobile/core/library/library_db.dart';
import 'package:drift/drift.dart' hide Column;

import '../helpers/fake_playback.dart';
import '../helpers/sqlite.dart';

void main() {
  setUpAll(ensureSqlite);

  Future<Widget> buildApp(LibraryDb db,
      {Map<String, Object> prefs = const {'folder_path': 'C:/x'}}) async {
    SharedPreferences.setMockInitialValues(prefs);
    return ProviderScope(
      overrides: [
        playbackControllerProvider.overrideWithValue(FakePlaybackController()),
        libraryDbProvider.overrideWithValue(db),
      ],
      child: const AbmApp(locale: Locale('it')),
    );
  }

  testWidgets('senza cartella: CTA onboarding', (tester) async {
    final db = LibraryDb.memory();
    addTearDown(db.close);
    await tester.pumpWidget(await buildApp(db, prefs: {}));
    await tester.pumpAndSettle();
    expect(find.text('Scegli cartella'), findsOneWidget);
  });

  testWidgets('con libri: lista con titolo, autore e progresso',
      (tester) async {
    final db = LibraryDb.memory();
    addTearDown(db.close);
    await db.into(db.books).insert(BooksCompanion.insert(
          path: 'C:/x/a.m4b',
          fileSize: 1,
          fileMtimeMs: 1,
          title: 'Cime tempestose',
          author: const Value('Emily Brontë'),
          durationMs: const Value(3600000),
          addedAtMs: 1,
          positionMs: const Value(1800000),
        ));
    await tester.pumpWidget(await buildApp(db));
    await tester.pumpAndSettle();
    expect(find.text('Cime tempestose'), findsOneWidget);
    expect(find.textContaining('Emily Brontë'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
  });
}
```

Nota lingua nei test: i widget test usano la locale di default `it` (prima del supportedLocales)? NON fare affidamento: in `buildApp` la MaterialApp risolve la lingua di sistema del test host (en di solito). Per assert stabili sulle stringhe, forza la locale italiana aggiungendo a `AbmApp` un parametro opzionale `locale` (passato a MaterialApp) e usalo SOLO nei test: `child: const AbmApp(locale: Locale('it'))`. Implementalo in app.dart (campo `final Locale? locale;`).

Run → FAIL.

- [ ] **Step 2: LibraryScreen** — `lib/app/screens/library_screen.dart`:

```dart
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../core/library/library_repository.dart';
import '../../l10n/app_localizations.dart';
import '../providers.dart';
import 'player_screen.dart';

class LibraryScreen extends ConsumerWidget {
  const LibraryScreen({super.key});

  Future<void> _pickFolder(BuildContext context, WidgetRef ref) async {
    if (Platform.isAndroid) {
      await Permission.audio.request(); // Android 13+; no-op altrove
    }
    final path = await FilePicker.platform.getDirectoryPath();
    if (path == null) return; // annullato
    final settings = await ref.read(settingsProvider.future);
    if (!Directory(path).existsSync()) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content:
                Text(AppLocalizations.of(context)!.pickFolderUnresolved)));
      }
      return;
    }
    await settings.setFolderPath(path);
    await _rescan(context, ref);
  }

  Future<void> _rescan(BuildContext context, WidgetRef ref) async {
    final settings = await ref.read(settingsProvider.future);
    final folder = settings.folderPath;
    if (folder == null) return;
    final repo = ref.read(libraryRepositoryProvider);
    final result = await repo.scanFolder(folder);
    await repo.purgeTombstones();
    if (context.mounted) {
      final t = AppLocalizations.of(context)!;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(t.rescanDone(result.added, result.removed))));
    }
  }

  Future<void> _importFile(BuildContext context, WidgetRef ref) async {
    final settings = await ref.read(settingsProvider.future);
    final folder = settings.folderPath;
    if (folder == null) return;
    final res = await FilePicker.platform.pickFiles(
        type: FileType.custom, allowedExtensions: ['mp3', 'm4b', 'm4a']);
    final src = res?.files.single.path;
    if (src == null) return;
    await File(src).copy(p.join(folder, p.basename(src)));
    if (context.mounted) await _rescan(context, ref);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context)!;
    final settingsAsync = ref.watch(settingsProvider);
    final books = ref.watch(booksProvider).valueOrNull ?? const [];

    final settings = settingsAsync.valueOrNull;
    if (settings == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (settings.folderPath == null) {
      // iOS: niente picker nell'MVP — la cartella è la Documents dell'app
      // (esposta nell'app File). Auto-set al primo avvio.
      if (Platform.isIOS) {
        getApplicationDocumentsDirectory().then((d) async {
          await settings.setFolderPath(d.path);
          if (context.mounted) await _rescan(context, ref);
        });
        return const Center(child: CircularProgressIndicator());
      }
      return _Onboarding(onPick: () => _pickFolder(context, ref));
    }
    return Scaffold(
      appBar: AppBar(title: Text(t.libraryTitle), actions: [
        IconButton(
            tooltip: t.importFile,
            icon: const Icon(Icons.add),
            onPressed: () => _importFile(context, ref)),
      ]),
      body: RefreshIndicator(
        onRefresh: () => _rescan(context, ref),
        child: books.isEmpty
            ? ListView(children: [
                Padding(
                    padding: const EdgeInsets.all(32),
                    child:
                        Text(t.libraryEmpty, textAlign: TextAlign.center)),
              ])
            : ListView.builder(
                itemCount: books.length,
                itemBuilder: (ctx, i) => _BookTile(book: books[i]),
              ),
      ),
    );
  }
}

class _Onboarding extends StatelessWidget {
  final VoidCallback onPick;
  const _Onboarding({required this.onPick});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context)!;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.folder_open, size: 64),
            const SizedBox(height: 16),
            Text(t.pickFolderTitle,
                style: Theme.of(context).textTheme.headlineSmall,
                textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text(t.pickFolderBody, textAlign: TextAlign.center),
            const SizedBox(height: 24),
            FilledButton.icon(
                onPressed: onPick,
                icon: const Icon(Icons.folder),
                label: Text(t.pickFolderButton)),
          ],
        ),
      ),
    );
  }
}

class _BookTile extends ConsumerWidget {
  final BookLite book;
  const _BookTile({required this.book});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context)!;
    final progress = book.durationMs > 0
        ? (book.positionMs / book.durationMs).clamp(0.0, 1.0)
        : 0.0;
    final repo = ref.read(libraryRepositoryProvider);
    return ListTile(
      leading: FutureBuilder(
        future: book.hasCover ? repo.coverOf(book.id) : Future.value(null),
        builder: (ctx, snap) => snap.data != null
            ? ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: Image.memory(snap.data!,
                    width: 48, height: 48, fit: BoxFit.cover))
            : const Icon(Icons.menu_book, size: 48),
      ),
      title: Text(book.title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
              book.author.isNotEmpty
                  ? book.author
                  : (book.finished ? t.bookFinished : t.bookNew),
              maxLines: 1,
              overflow: TextOverflow.ellipsis),
          const SizedBox(height: 4),
          LinearProgressIndicator(value: progress),
        ],
      ),
      onTap: () async {
        final repo = ref.read(libraryRepositoryProvider);
        final full = await repo.bookById(book.id);
        if (full == null) return;
        final chapters = await repo.chaptersOf(book.id);
        await ref
            .read(playbackControllerProvider)
            .loadBook(full, chapters);
        if (context.mounted) {
          Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const PlayerScreen()));
        }
      },
    );
  }
}
```

- [ ] **Step 3: SettingsScreen** — `lib/app/screens/settings_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/app_localizations.dart';
import '../providers.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context)!;
    final settings = ref.watch(settingsProvider).valueOrNull;
    if (settings == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return Scaffold(
      appBar: AppBar(title: Text(t.settingsTitle)),
      body: ListenableBuilder(
        listenable: settings,
        builder: (ctx, _) => ListView(children: [
          ListTile(
            leading: const Icon(Icons.folder),
            title: Text(t.settingsFolder),
            subtitle: Text(settings.folderPath ?? '—'),
          ),
          ListTile(
            leading: const Icon(Icons.fast_forward),
            title: const Text('+'),
            trailing: DropdownButton<int>(
              value: settings.skipForwardSec,
              items: const [10, 15, 30, 45, 60]
                  .map((s) =>
                      DropdownMenuItem(value: s, child: Text('${s}s')))
                  .toList(),
              onChanged: (v) =>
                  v == null ? null : settings.setSkipForwardSec(v),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.fast_rewind),
            title: const Text('−'),
            trailing: DropdownButton<int>(
              value: settings.skipBackSec,
              items: const [5, 10, 15, 30]
                  .map((s) =>
                      DropdownMenuItem(value: s, child: Text('${s}s')))
                  .toList(),
              onChanged: (v) =>
                  v == null ? null : settings.setSkipBackSec(v),
            ),
          ),
        ]),
      ),
    );
  }
}
```

(la voce cartella è informativa qui; il cambio cartella resta nell'onboarding/Libreria per l'MVP — YAGNI)

- [ ] **Step 4: run + commit**

Run: `C:\flutter\bin\flutter.bat test` → tutti PASS. `analyze` pulito.

```powershell
git add lib/app test/widget/library_screen_test.dart
git commit -m "feat(ui): Libreria con onboarding cartella, lista, import e rescan"
```

---

### Task 8: PlayerScreen (copertina grande + bottom sheet capitoli)

**Files:**
- Create: `lib/app/screens/player_screen.dart` (sostituisce lo stub)
- Test: `test/widget/player_screen_test.dart`

- [ ] **Step 1: widget test (failing)** — `test/widget/player_screen_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:audiobook_maker_mobile/app/providers.dart';
import 'package:audiobook_maker_mobile/app/screens/player_screen.dart';
import 'package:audiobook_maker_mobile/core/library/library_db.dart';
import 'package:audiobook_maker_mobile/l10n/app_localizations.dart';

import '../helpers/fake_playback.dart';
import '../helpers/sqlite.dart';

void main() {
  setUpAll(ensureSqlite);

  Future<FakePlaybackController> pumpPlayer(WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    final fake = FakePlaybackController();
    final db = LibraryDb.memory();
    addTearDown(db.close);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        playbackControllerProvider.overrideWithValue(fake),
        libraryDbProvider.overrideWithValue(db),
      ],
      child: const MaterialApp(
        locale: Locale('it'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: PlayerScreen(),
      ),
    ));
    fake.emit(snapshotFixture());
    await tester.pumpAndSettle();
    return fake;
  }

  testWidgets('mostra titolo, capitolo corrente e controlli', (tester) async {
    final fake = await pumpPlayer(tester);
    expect(find.text('Il nome della rosa'), findsOneWidget);
    expect(find.textContaining('Uno'), findsWidgets);
    await tester.tap(find.byIcon(Icons.pause_circle_filled));
    expect(fake.calls, contains('pause'));
    await tester.tap(find.byIcon(Icons.replay_10));
    expect(fake.calls, contains('skipBack'));
    await tester.tap(find.byIcon(Icons.forward_30));
    expect(fake.calls, contains('skipForward'));
  });

  testWidgets('bottom sheet capitoli: tap naviga al capitolo',
      (tester) async {
    final fake = await pumpPlayer(tester);
    await tester.tap(find.text('Capitoli'));
    await tester.pumpAndSettle();
    expect(find.text('Due'), findsOneWidget);
    await tester.tap(find.text('Due'));
    await tester.pumpAndSettle();
    expect(fake.calls, contains('seek:120000'));
  });
}
```

Nota: `AppLocalizations.localizationsDelegates` esiste nel generato recente; se assente, elenca i 4 delegate come in app.dart.

Run → FAIL.

- [ ] **Step 2: PlayerScreen** — `lib/app/screens/player_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/player/playback_types.dart';
import '../../l10n/app_localizations.dart';
import '../providers.dart';

class PlayerScreen extends ConsumerWidget {
  const PlayerScreen({super.key});

  String _fmt(Duration d) {
    final h = d.inHours;
    final m = (d.inMinutes % 60).toString().padLeft(2, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    return h > 0 ? '$h:$m:$s' : '$m:$s';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context)!;
    final snap = ref.watch(playbackSnapshotProvider).valueOrNull;
    final controller = ref.read(playbackControllerProvider);
    if (snap == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final chapter = snap.chapterIndex >= 0 &&
            snap.chapterIndex < snap.chapterTitles.length
        ? snap.chapterTitles[snap.chapterIndex]
        : '';
    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            children: [
              const Spacer(),
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: snap.coverBytes != null
                    ? Image.memory(snap.coverBytes!,
                        width: 240, height: 240, fit: BoxFit.cover)
                    : Container(
                        width: 240,
                        height: 240,
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest,
                        child: const Icon(Icons.menu_book, size: 96)),
              ),
              const SizedBox(height: 20),
              Text(snap.title,
                  style: Theme.of(context).textTheme.titleLarge,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center),
              if (chapter.isNotEmpty)
                Text(chapter,
                    style: Theme.of(context).textTheme.bodyMedium,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis),
              const SizedBox(height: 16),
              Slider(
                value: snap.position.inMilliseconds
                    .clamp(0, snap.duration.inMilliseconds)
                    .toDouble(),
                max: snap.duration.inMilliseconds.toDouble().clamp(1, 1e15),
                onChanged: (v) =>
                    controller.seek(Duration(milliseconds: v.round())),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(_fmt(snap.position),
                      style: Theme.of(context).textTheme.bodySmall),
                  Text('-${_fmt(snap.duration - snap.position)}',
                      style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  IconButton(
                      iconSize: 32,
                      icon: const Icon(Icons.skip_previous),
                      onPressed: controller.previousChapter),
                  IconButton(
                      iconSize: 36,
                      icon: const Icon(Icons.replay_10),
                      onPressed: controller.skipBack),
                  IconButton(
                      iconSize: 72,
                      icon: Icon(snap.playing
                          ? Icons.pause_circle_filled
                          : Icons.play_circle_filled),
                      onPressed: () =>
                          snap.playing ? controller.pause() : controller.play()),
                  IconButton(
                      iconSize: 36,
                      icon: const Icon(Icons.forward_30),
                      onPressed: controller.skipForward),
                  IconButton(
                      iconSize: 32,
                      icon: const Icon(Icons.skip_next),
                      onPressed: controller.nextChapter),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  ActionChip(
                    avatar: const Icon(Icons.speed, size: 18),
                    label: Text('${snap.speed}×'),
                    onPressed: () => _showSpeedSheet(context, controller),
                  ),
                  const SizedBox(width: 12),
                  ActionChip(
                    avatar: const Icon(Icons.nightlight_round, size: 18),
                    label: Text(snap.sleepRemaining != null
                        ? _fmt(snap.sleepRemaining!)
                        : t.playerSleep),
                    onPressed: () => _showSleepSheet(context, controller, t),
                  ),
                  const SizedBox(width: 12),
                  if (snap.chapterTitles.isNotEmpty)
                    ActionChip(
                      avatar: const Icon(Icons.list, size: 18),
                      label: Text(t.playerChapters),
                      onPressed: () => _showChaptersSheet(context, snap,
                          controller),
                    ),
                ],
              ),
              const Spacer(flex: 2),
            ],
          ),
        ),
      ),
    );
  }

  void _showSpeedSheet(BuildContext context, controller) {
    showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Wrap(children: [
          for (final s in const [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0])
            ListTile(
              title: Text('$s×'),
              onTap: () {
                controller.setSpeed(s);
                Navigator.pop(ctx);
              },
            ),
        ]),
      ),
    );
  }

  void _showSleepSheet(
      BuildContext context, controller, AppLocalizations t) {
    showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Wrap(children: [
          ListTile(
              title: Text(t.sleepOff),
              onTap: () {
                controller.setSleep(null);
                Navigator.pop(ctx);
              }),
          for (final min in const [5, 15, 30, 60])
            ListTile(
                title: Text(t.sleepNMinutes(min)),
                onTap: () {
                  controller.setSleep(SleepSetting.minutes(min));
                  Navigator.pop(ctx);
                }),
          ListTile(
              title: Text(t.sleepEndOfChapter),
              onTap: () {
                controller.setSleep(const SleepSetting.endOfChapter());
                Navigator.pop(ctx);
              }),
        ]),
      ),
    );
  }

  void _showChaptersSheet(
      BuildContext context, PlaybackSnapshot snap, controller) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: ListView.builder(
          itemCount: snap.chapterTitles.length,
          itemBuilder: (c, i) => ListTile(
            selected: i == snap.chapterIndex,
            title: Text(snap.chapterTitles[i]),
            trailing: Text(_fmt(
                Duration(milliseconds: snap.chapterStartsMs[i]))),
            onTap: () {
              controller
                  .seek(Duration(milliseconds: snap.chapterStartsMs[i]));
              Navigator.pop(c);
            },
          ),
        ),
      ),
    );
  }
}
```

Tipizza i parametri `controller` come `PlaybackController` (import del contratto) — il codice sopra li lascia dynamic per brevità: NON farlo, dichiara il tipo.

- [ ] **Step 3: run + commit**

Run: `C:\flutter\bin\flutter.bat test` → tutti PASS (incl. 2 widget player). `analyze` pulito.

```powershell
git add lib/app/screens/player_screen.dart test/widget/player_screen_test.dart
git commit -m "feat(ui): PlayerScreen con copertina grande, chips e bottom sheet capitoli"
```

---

### Task 9: Chiusura — analyze, smoke build, README, checklist device

- [ ] **Step 1: qualità**

Run: `C:\flutter\bin\dart.bat format .` poi `C:\flutter\bin\flutter.bat analyze` → No issues. `C:\flutter\bin\flutter.bat test` → tutti PASS (attesi ~25+).

- [ ] **Step 2: smoke build APK**

Run: `C:\flutter\bin\flutter.bat build apk --debug`
Se l'Android SDK non è configurato (setup GUI di Android Studio pendente): annota BLOCKED-parziale nel report e prosegui — la build resta da verificare a SDK pronto.

- [ ] **Step 3: README — aggiornare la sezione Stato**

Sostituire la sezione `## Stato` di `README.md` con:

```markdown
## Stato

Fase 2b completata: app player funzionante — navigazione 4 tab con mini-player,
Libreria con onboarding cartella/import/rescan, Player (copertina, capitoli in
bottom sheet, velocità 0.5–3×, sleep timer, salti configurabili), riproduzione
in background con notifica media e lock screen (audio_service), posizioni
persistite. Manca: integrazione col backend (wizard Crea, tab Attività, push) —
fase 3.

### Verifica su device reale (checklist manuale, da fare a ogni release)

- [ ] riproduzione continua a schermo spento ≥10 min
- [ ] controlli notifica media: play/pausa, ±salti, capitoli prev/next
- [ ] cuffie bluetooth: play/pausa e next/prev
- [ ] posizione ripresa dopo kill dell'app
- [ ] sleep timer "fine capitolo" ferma al capitolo giusto
- [ ] cartella SAF su storage primario + import file da file manager
```

- [ ] **Step 4: commit finale**

```powershell
git add -A
git commit -m "chore(2b): format, README con checklist device"
```

NON fare push. NON creare repo GitHub.

---

## Note per l'esecutore

- **Contratto stabile:** la UI dipende SOLO da `PlaybackController`/`PlaybackSnapshot`. Qualunque adattamento alle API reali di audio_service/just_audio NON deve cambiare il contratto.
- **Import del generato l10n:** verificare il path reale (`lib/l10n/app_localizations.dart` vs `flutter_gen`) PRIMA di scrivere gli import UI; usarlo ovunque coerentemente.
- **Audio su host:** mai istanziare `AudioPlayer`/`AudioService` nei test host — solo il fake. Se un widget test trascina l'import dell'handler reale va bene (compila), ma non costruirlo.
- **Versioni pub:** floor al 2026-06; alzare se `pub get` chiede, annotando nel commit.
- **OneDrive:** attributo ReadOnly sulle cartelle nuove già visto in 2a — rimuoverlo se le scritture falliscono.
- **Stringhe UI:** mai nominare provider AI/TTS (policy repo).
