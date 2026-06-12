# App Flutter — Piano 2a: Core senza UI (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creare il repo `audiobook-maker-mobile` (Flutter) con il core testabile senza UI né emulatore: scaffold, i18n 7 lingue (ARB + script di conversione dai JSON del sito), parser m4b in Dart (capitoli, cover, metadata), indice libreria SQLite (drift) con scansione cartella e posizioni di ascolto.

**Architecture:** Pure-Dart core in `lib/core/` (nessuna dipendenza Flutter UI): `m4b/` parser degli atom MP4, `library/` repository con DB drift e scansione directory basata su path. La UI (Piano 2b) consumerà queste API. I test girano su host Windows con `flutter test` (sqlite3 nativo via dll locale).

**Tech Stack:** Flutter stable (canale stable, ultima), Dart ≥3, drift + sqlite3, audio_metadata_reader (tag mp3), flutter_localizations + ARB, FFmpeg (solo per generare fixture di test).

**Spec di riferimento:** `docs/superpowers/specs/2026-06-11-mobile-app-design.md` (repo AudioBook-Maker, branch abm_mobile).

---

## Prerequisiti e vincoli ambiente (leggere prima di iniziare)

- **Flutter NON è installato** sulla macchina di sviluppo (verificato 2026-06-12). Il Task 0 lo installa.
- **Solo Android in locale**: siamo su Windows → niente build/test iOS in locale. Il progetto resta cross-platform (`flutter create` genera anche ios/); la pipeline iOS arriverà con una CI macOS in fase successiva. NON tentare `flutter build ios`.
- **Percorso repo**: `C:\Users\gfran\NEXT srl\Progetti - Documenti\audiobook-maker-mobile` (cartella sorella di AudioBook-Maker). ⚠️ L'area è sincronizzata OneDrive/SharePoint: la cartella `build/` e `.dart_tool/` generano migliaia di file — se la sync dà fastidio, escludere la cartella dalla sincronizzazione OneDrive (Impostazioni → Sincronizza → Escludi cartelle) o spostare il repo: non è un requisito del piano, solo un avviso.
- **Shell**: PowerShell, comandi singoli senza `&&`.
- **FFmpeg**: richiesto per generare le fixture m4b di test (il backend lo usa già: verifica con `ffmpeg -version`; se assente, `winget install Gyan.FFmpeg` e riapri la shell).
- **Backend repo** (per lo script i18n): `C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker` — i JSON sono in `i18n\*.json` (it, en, fr, es, de, zh + altri). Lo script li legge in sola lettura.
- Convenzioni commit: conventional commits in italiano (`feat:`, `test:`, `chore:`) come nel repo backend, footer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Mappa dei file (risultato finale del 2a)

```
audiobook-maker-mobile/
├── pubspec.yaml                      # deps: drift, sqlite3, audio_metadata_reader, intl
├── l10n.yaml                         # config gen ARB
├── lib/
│   ├── l10n/                         # app_it.arb, app_en.arb, ... (7 lingue)
│   └── core/
│       ├── m4b/
│       │   ├── mp4_atoms.dart        # walker generico degli atom MP4
│       │   └── m4b_parser.dart       # capitoli (chpl + QT chap track), cover, title/author/durata
│       └── library/
│           ├── book_metadata.dart    # modello BookMetadata + ChapterInfo
│           ├── metadata_reader.dart  # dispatch per estensione (m4b/m4a → parser; mp3 → audio_metadata_reader)
│           ├── library_db.dart       # schema drift: Books, Chapters (+ posizioni ascolto)
│           └── library_repository.dart  # scanFolder (diff add/remove), posizioni, retention 30gg
├── tool/
│   ├── convert_i18n.dart             # JSON sito → ARB (mappa chiavi dichiarata)
│   ├── make_fixtures.ps1             # genera test/fixtures/*.m4b|mp3 con FFmpeg
│   └── sqlite3.dll                   # runtime sqlite per i test host Windows (non committato: vedi .gitignore)
└── test/
    ├── helpers/sqlite.dart           # override caricamento sqlite3.dll su Windows
    ├── fixtures/                     # book_chaptered.m4b, book_nochap.m4b, sample.mp3 (committate, ~100KB)
    ├── m4b_parser_test.dart
    ├── metadata_reader_test.dart
    └── library_repository_test.dart
```

---

### Task 0: Setup ambiente (Flutter SDK + Android toolchain)

Nessun TDD: solo installazione e verifica. Se un passo risulta già soddisfatto (`flutter doctor` pulito), saltare al successivo.

- [ ] **Step 1: Installare Flutter SDK**

```powershell
winget install --id=Flutter.Flutter -e --accept-package-agreements --accept-source-agreements
```

Se winget non trova il pacchetto: clone manuale (stabile e affidabile):

```powershell
git clone https://github.com/flutter/flutter.git -b stable C:\flutter
```

e aggiungere `C:\flutter\bin` al PATH utente:

```powershell
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\flutter\bin", "User")
```

Riaprire la shell (le env var non si aggiornano nella sessione corrente).

- [ ] **Step 2: Verifica base**

Run: `flutter --version`
Expected: `Flutter 3.x.x • channel stable`. Se "command not found": PATH non aggiornato, riaprire la shell.

- [ ] **Step 3: Android toolchain**

Per i test host del 2a NON serve; per `flutter build apk` (smoke test finale) sì. Installare Android Studio (include SDK + cmdline-tools):

```powershell
winget install --id=Google.AndroidStudio -e --accept-package-agreements --accept-source-agreements
```

Poi accettare le licenze:

```powershell
flutter doctor --android-licenses
```

- [ ] **Step 4: Verifica finale**

Run: `flutter doctor`
Expected: sezioni `Flutter` e `Android toolchain` con ✓. (`Visual Studio`, `Chrome`, dispositivi: ignorabili per questo piano. iOS assente: atteso su Windows.)

---

### Task 1: Scaffold repo + dipendenze

**Files:**
- Create: intero progetto in `C:\Users\gfran\NEXT srl\Progetti - Documenti\audiobook-maker-mobile`
- Modify: `pubspec.yaml`, `.gitignore`

- [ ] **Step 1: Creare il progetto**

```powershell
Set-Location "C:\Users\gfran\NEXT srl\Progetti - Documenti"
flutter create --org it.nextsw --project-name audiobook_maker_mobile --platforms android,ios audiobook-maker-mobile
Set-Location audiobook-maker-mobile
```

(`--org it.nextsw` → applicationId Android `it.nextsw.audiobook_maker_mobile`, bundle id iOS analogo; si potrà raffinare prima della pubblicazione store.)

- [ ] **Step 2: Git init + primo commit**

```powershell
git init -b main
git add -A
git commit -m "chore: scaffold Flutter (flutter create, android+ios)"
```

- [ ] **Step 3: Dipendenze del core**

Sostituire le sezioni `dependencies`/`dev_dependencies` di `pubspec.yaml` (conservare `environment:` generato da flutter create):

```yaml
dependencies:
  flutter:
    sdk: flutter
  flutter_localizations:
    sdk: flutter
  intl: any            # versione vincolata da flutter_localizations
  drift: ^2.20.0
  sqlite3: ^2.4.0
  path: ^1.9.0
  audio_metadata_reader: ^1.4.0

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^5.0.0
  drift_dev: ^2.20.0
  build_runner: ^2.4.0
```

E in fondo a `pubspec.yaml`, nella sezione `flutter:`, aggiungere `generate: true` (abilita il codegen l10n):

```yaml
flutter:
  uses-material-design: true
  generate: true
```

- [ ] **Step 4: Risolvere e verificare**

Run: `flutter pub get`
Expected: `Got dependencies!` senza conflitti di versione. (Se `audio_metadata_reader ^1.4.0` non esiste più con quel major: `flutter pub add audio_metadata_reader` e annotare la versione scelta nel commit.)

- [ ] **Step 5: .gitignore**

Aggiungere in coda a `.gitignore` (quello generato copre già build/ e .dart_tool/):

```
tool/sqlite3.dll
```

- [ ] **Step 6: Commit**

```powershell
git add pubspec.yaml pubspec.lock .gitignore
git commit -m "chore: dipendenze core (drift, sqlite3, audio_metadata_reader, l10n)"
```

---

### Task 2: i18n — ARB 7 lingue + script di conversione dai JSON del sito

L'app ha chiavi proprie; dove una stringa esiste già nel sito la si riusa via mappa esplicita `chiave-app → chiave-sito`. Lo script si rilancia a ogni nuova chiave riusabile.

**Files:**
- Create: `l10n.yaml`, `lib/l10n/app_it.arb` (+ 6 lingue), `tool/convert_i18n.dart`

- [ ] **Step 1: Config l10n**

Creare `l10n.yaml` (root):

```yaml
arb-dir: lib/l10n
template-arb-file: app_it.arb
output-localization-file: app_localizations.dart
```

- [ ] **Step 2: ARB template italiano**

Creare `lib/l10n/app_it.arb` con le chiavi del core (la UI del 2b ne aggiungerà altre):

```json
{
  "@@locale": "it",
  "appTitle": "AudioBook Maker",
  "libraryTitle": "La mia libreria",
  "libraryEmpty": "Nessun audiolibro nella cartella. Scarica un lavoro dall'app o copia file mp3/m4b nella cartella repository.",
  "libraryRescan": "Aggiorna libreria",
  "bookChapters": "{count} capitoli",
  "@bookChapters": {"placeholders": {"count": {"type": "int"}}},
  "bookFinished": "Finito",
  "bookInProgress": "In corso",
  "bookNew": "Nuovo",
  "settingsTitle": "Impostazioni",
  "settingsFolder": "Cartella repository",
  "settingsLanguage": "Lingua"
}
```

- [ ] **Step 3: Script di conversione**

Creare `tool/convert_i18n.dart`:

```dart
// Converte i JSON i18n del sito (AudioBook-Maker/i18n/<lang>.json) negli ARB
// dell'app per le chiavi dichiarate in _reuseMap. Le chiavi solo-app vivono
// negli ARB e NON vengono toccate. Uso:
//   dart run tool/convert_i18n.dart "C:\...\AudioBook-Maker\i18n"
import 'dart:convert';
import 'dart:io';

const langs = ['it', 'en', 'fr', 'es', 'de', 'zh', 'hi'];

// chiave ARB app -> chiave JSON sito (aggiungere qui le stringhe riusate)
const _reuseMap = <String, String>{
  // esempio: 'wizardOptimize': 'optimize_with_ai',
};

void main(List<String> args) {
  if (args.isEmpty) {
    stderr.writeln('uso: dart run tool/convert_i18n.dart <dir i18n del sito>');
    exit(2);
  }
  final srcDir = Directory(args[0]);
  for (final lang in langs) {
    final srcFile = File('${srcDir.path}/$lang.json');
    final arbFile = File('lib/l10n/app_$lang.arb');
    final site = srcFile.existsSync()
        ? jsonDecode(srcFile.readAsStringSync()) as Map<String, dynamic>
        : <String, dynamic>{};
    final arb = arbFile.existsSync()
        ? jsonDecode(arbFile.readAsStringSync()) as Map<String, dynamic>
        : <String, dynamic>{'@@locale': lang};
    var updated = 0;
    _reuseMap.forEach((appKey, siteKey) {
      final v = site[siteKey];
      if (v is String && v.isNotEmpty) {
        arb[appKey] = v;
        updated++;
      }
    });
    const enc = JsonEncoder.withIndent('  ');
    arbFile.writeAsStringSync('${enc.convert(arb)}\n');
    stdout.writeln('app_$lang.arb: $updated chiavi riusate dal sito');
  }
}
```

- [ ] **Step 4: ARB delle altre 6 lingue**

Creare `lib/l10n/app_<lang>.arb` per en/fr/es/de/zh/hi con le stesse chiavi del template tradotte. Contenuto `app_en.arb` (gli altri 5: tradurre coerentemente — de/fr/es/zh/hi con diacritici/han corretti):

```json
{
  "@@locale": "en",
  "appTitle": "AudioBook Maker",
  "libraryTitle": "My library",
  "libraryEmpty": "No audiobooks in the folder. Download a job from the app or copy mp3/m4b files into the repository folder.",
  "libraryRescan": "Refresh library",
  "bookChapters": "{count} chapters",
  "@bookChapters": {"placeholders": {"count": {"type": "int"}}},
  "bookFinished": "Finished",
  "bookInProgress": "In progress",
  "bookNew": "New",
  "settingsTitle": "Settings",
  "settingsFolder": "Repository folder",
  "settingsLanguage": "Language"
}
```

- [ ] **Step 5: Generare e verificare**

Run: `flutter gen-l10n`
Expected: nessun errore; generati i file in `.dart_tool/flutter_gen/gen_l10n/` (o `lib/l10n/generated` a seconda della versione). Un errore "untranslated messages" indica chiavi mancanti in una lingua: completarle.

Run: `dart run tool/convert_i18n.dart "C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker\i18n"`
Expected: `app_<lang>.arb: 0 chiavi riusate dal sito` per ogni lingua (mappa vuota per ora) e ARB riscritti identici.

- [ ] **Step 6: Commit**

```powershell
git add l10n.yaml lib/l10n tool/convert_i18n.dart
git commit -m "feat(i18n): ARB 7 lingue + script conversione dai JSON del sito"
```

---

### Task 3: Parser m4b (atom MP4, capitoli, cover, metadata)

Cuore del 2a. TDD contro fixture REALI generate con FFmpeg (stesso muxer del backend): le fixture sono la ground truth — se un dettaglio di layout binario nel codice sotto differisce da ciò che FFmpeg scrive, fidarsi del test e correggere il parser, non la fixture.

**Files:**
- Create: `tool/make_fixtures.ps1`, `test/fixtures/book_chaptered.m4b`, `test/fixtures/book_nochap.m4b`, `lib/core/m4b/mp4_atoms.dart`, `lib/core/m4b/m4b_parser.dart`
- Test: `test/m4b_parser_test.dart`

- [ ] **Step 1: Script fixture**

Creare `tool/make_fixtures.ps1`:

```powershell
# Genera fixture m4b/mp3 piccole per i test. Richiede ffmpeg nel PATH.
$fix = "test/fixtures"
New-Item -ItemType Directory -Force $fix | Out-Null

# 6 secondi di tono, 3 capitoli da 2s, title/author, cover 64x64
$meta = @"
;FFMETADATA1
title=Libro di prova
artist=Autore Prova
[CHAPTER]
TIMEBASE=1/1000
START=0
END=2000
title=Capitolo uno
[CHAPTER]
TIMEBASE=1/1000
START=2000
END=4000
title=Capitolo due
[CHAPTER]
TIMEBASE=1/1000
START=4000
END=6000
title=Capitolo tre
"@
Set-Content -Path "$fix/meta.txt" -Value $meta -Encoding UTF8

ffmpeg -y -f lavfi -i "sine=frequency=440:duration=6" -f lavfi -i "color=c=blue:s=64x64:d=1" -frames:v 1 "$fix/cover.png"
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=6" -i "$fix/meta.txt" -map_metadata 1 -map 0:a -c:a aac -b:a 32k -f ipod "$fix/book_tmp.m4b"
ffmpeg -y -i "$fix/book_tmp.m4b" -i "$fix/cover.png" -map 0 -map 1 -c copy -disposition:v attached_pic -f ipod "$fix/book_chaptered.m4b"
ffmpeg -y -f lavfi -i "sine=frequency=330:duration=3" -c:a aac -b:a 32k -metadata title="Senza capitoli" -f ipod "$fix/book_nochap.m4b"
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=3" -codec:a libmp3lame -b:a 32k -metadata title="MP3 di prova" -metadata artist="Autore MP3" "$fix/sample.mp3"
Remove-Item "$fix/book_tmp.m4b", "$fix/meta.txt", "$fix/cover.png"
```

Run: `powershell -File tool/make_fixtures.ps1`
Expected: 3 file in `test/fixtures/` (m4b ~30-50KB l'uno). Verifica capitoli presenti: `ffprobe -show_chapters test/fixtures/book_chaptered.m4b` → 3 capitoli.

- [ ] **Step 2: Test che falliscono**

Creare `test/m4b_parser_test.dart`:

```dart
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/m4b/m4b_parser.dart';

void main() {
  final chaptered = File('test/fixtures/book_chaptered.m4b');
  final nochap = File('test/fixtures/book_nochap.m4b');

  test('legge title, author e durata', () async {
    final meta = await M4bParser.parse(chaptered);
    expect(meta.title, 'Libro di prova');
    expect(meta.author, 'Autore Prova');
    expect(meta.durationMs, closeTo(6000, 200));
  });

  test('legge i 3 capitoli con tempi e titoli', () async {
    final meta = await M4bParser.parse(chaptered);
    expect(meta.chapters, hasLength(3));
    expect(meta.chapters[0].title, 'Capitolo uno');
    expect(meta.chapters[0].startMs, closeTo(0, 50));
    expect(meta.chapters[1].title, 'Capitolo due');
    expect(meta.chapters[1].startMs, closeTo(2000, 50));
    expect(meta.chapters[2].startMs, closeTo(4000, 50));
  });

  test('estrae la cover', () async {
    final meta = await M4bParser.parse(chaptered);
    expect(meta.coverBytes, isNotNull);
    // PNG magic
    expect(meta.coverBytes!.sublist(0, 4), [0x89, 0x50, 0x4E, 0x47]);
  });

  test('file senza capitoli: lista vuota, non errore', () async {
    final meta = await M4bParser.parse(nochap);
    expect(meta.title, 'Senza capitoli');
    expect(meta.chapters, isEmpty);
  });

  test('file non-mp4: FormatException', () async {
    final junk = File('test/fixtures/junk.bin');
    junk.writeAsBytesSync(List.filled(64, 0x42));
    expect(() => M4bParser.parse(junk), throwsFormatException);
    junk.deleteSync();
  });
}
```

Run: `flutter test test/m4b_parser_test.dart`
Expected: FAIL (import inesistente).

- [ ] **Step 3: Walker degli atom**

Creare `lib/core/m4b/mp4_atoms.dart`:

```dart
import 'dart:io';
import 'dart:typed_data';

/// Un atom MP4: [type] a 4 char, payload [start]..[end] (esclusi header).
class Mp4Atom {
  final String type;
  final int start; // offset payload nel file
  final int end; // offset fine atom
  Mp4Atom(this.type, this.start, this.end);
  int get size => end - start;
}

/// Lettura sequenziale degli atom in [from]..[to]. Gli atom "container" noti
/// si esplorano richiamando atomsIn sul loro payload.
class Mp4Reader {
  final RandomAccessFile _f;
  Mp4Reader(this._f);

  Future<Uint8List> bytes(int offset, int length) async {
    await _f.setPosition(offset);
    return Uint8List.fromList(await _f.read(length));
  }

  Future<List<Mp4Atom>> atomsIn(int from, int to) async {
    final out = <Mp4Atom>[];
    var pos = from;
    while (pos + 8 <= to) {
      final hdr = await bytes(pos, 8);
      var size = ByteData.sublistView(hdr).getUint32(0);
      final type = String.fromCharCodes(hdr.sublist(4, 8));
      var payload = pos + 8;
      if (size == 1) {
        final ext = await bytes(pos + 8, 8);
        size = ByteData.sublistView(ext).getUint64(0);
        payload = pos + 16;
      } else if (size == 0) {
        size = to - pos; // fino a fine contenitore
      }
      if (size < 8 || pos + size > to) break; // atom corrotto: stop pulito
      out.add(Mp4Atom(type, payload, pos + size));
      pos += size;
    }
    return out;
  }

  /// Primo atom [type] tra i figli di [parent] (o a livello file se null).
  Future<Mp4Atom?> find(String type, {Mp4Atom? parent, int? fileEnd}) async {
    final from = parent?.start ?? 0;
    final to = parent?.end ?? fileEnd!;
    for (final a in await atomsIn(from, to)) {
      if (a.type == type) return a;
    }
    return null;
  }
}
```

- [ ] **Step 4: Parser m4b**

Creare `lib/core/m4b/m4b_parser.dart`:

```dart
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'mp4_atoms.dart';

@immutable
class M4bChapter {
  final String title;
  final int startMs;
  const M4bChapter(this.title, this.startMs);
}

@immutable
class M4bMetadata {
  final String title;
  final String author;
  final int durationMs;
  final Uint8List? coverBytes;
  final List<M4bChapter> chapters;
  const M4bMetadata({
    required this.title,
    required this.author,
    required this.durationMs,
    required this.coverBytes,
    required this.chapters,
  });
}

class M4bParser {
  /// Estrae metadata da un m4b/m4a. FormatException se non è un MP4.
  static Future<M4bMetadata> parse(File file) async {
    final raf = await file.open();
    try {
      final len = await raf.length();
      final r = Mp4Reader(raf);
      final top = await r.atomsIn(0, len);
      final isMp4 = top.any((a) => a.type == 'ftyp') &&
          top.any((a) => a.type == 'moov');
      if (!isMp4) throw const FormatException('non è un file MP4');
      final moov = top.firstWhere((a) => a.type == 'moov');

      final durationMs = await _readMvhdDurationMs(r, moov);
      final ilst = await _findIlst(r, moov);
      final title = ilst == null
          ? ''
          : await _ilstString(r, ilst, '©nam') ?? '';
      final author = ilst == null
          ? ''
          : await _ilstString(r, ilst, '©ART') ?? '';
      final cover = ilst == null ? null : await _ilstData(r, ilst, 'covr');

      var chapters = await _readChplChapters(r, moov);
      chapters ??= await _readQtChapters(r, moov);

      return M4bMetadata(
        title: title,
        author: author,
        durationMs: durationMs,
        coverBytes: cover,
        chapters: chapters ?? const [],
      );
    } finally {
      await raf.close();
    }
  }

  static Future<int> _readMvhdDurationMs(Mp4Reader r, Mp4Atom moov) async {
    final mvhd = await r.find('mvhd', parent: moov);
    if (mvhd == null) return 0;
    final b = ByteData.sublistView(await r.bytes(mvhd.start, 32));
    final version = b.getUint8(0);
    if (version == 1) {
      final ts = b.getUint32(20);
      final dur = b.getUint64(24);
      return ts == 0 ? 0 : (dur * 1000 ~/ ts);
    }
    final ts = b.getUint32(12);
    final dur = b.getUint32(16);
    return ts == 0 ? 0 : (dur * 1000 ~/ ts);
  }

  static Future<Mp4Atom?> _findIlst(Mp4Reader r, Mp4Atom moov) async {
    final udta = await r.find('udta', parent: moov);
    if (udta == null) return null;
    final meta = await r.find('meta', parent: udta);
    if (meta == null) return null;
    // 'meta' è un fullbox: il payload inizia con 4 byte version+flags
    final inner = Mp4Atom(meta.type, meta.start + 4, meta.end);
    return r.find('ilst', parent: inner);
  }

  /// payload del primo atom 'data' dentro ilst/<key> (salta 8 byte type+locale)
  static Future<Uint8List?> _ilstData(
      Mp4Reader r, Mp4Atom ilst, String key) async {
    final entry = await r.find(key, parent: ilst);
    if (entry == null) return null;
    final data = await r.find('data', parent: entry);
    if (data == null || data.size <= 8) return null;
    return r.bytes(data.start + 8, data.size - 8);
  }

  static Future<String?> _ilstString(
      Mp4Reader r, Mp4Atom ilst, String key) async {
    final raw = await _ilstData(r, ilst, key);
    return raw == null ? null : String.fromCharCodes(raw); // UTF-8 → vedi nota
  }

  /// Capitoli Nero: moov/udta/chpl. Ritorna null se assente.
  static Future<List<M4bChapter>?> _readChplChapters(
      Mp4Reader r, Mp4Atom moov) async {
    final udta = await r.find('udta', parent: moov);
    if (udta == null) return null;
    final chpl = await r.find('chpl', parent: udta);
    if (chpl == null) return null;
    final raw = await r.bytes(chpl.start, chpl.size);
    final b = ByteData.sublistView(raw);
    final version = b.getUint8(0);
    var off = 4; // version+flags
    if (version != 0) off += 4; // 4 byte riservati nel formato v1
    final count = b.getUint8(off);
    off += 1;
    final out = <M4bChapter>[];
    for (var i = 0; i < count && off + 9 <= raw.length; i++) {
      final start100ns = b.getUint64(off);
      final titleLen = b.getUint8(off + 8);
      off += 9;
      final title = String.fromCharCodes(raw.sublist(off, off + titleLen));
      off += titleLen;
      out.add(M4bChapter(_utf8Fix(title), start100ns ~/ 10000));
    }
    return out;
  }

  /// Capitoli QuickTime: traccia text referenziata da tref/chap.
  static Future<List<M4bChapter>?> _readQtChapters(
      Mp4Reader r, Mp4Atom moov) async {
    final traks = (await r.atomsIn(moov.start, moov.end))
        .where((a) => a.type == 'trak')
        .toList();
    // 1) trova l'id della traccia capitoli via tref/chap di una traccia audio
    int? chapTrackId;
    for (final trak in traks) {
      final tref = await r.find('tref', parent: trak);
      if (tref == null) continue;
      final chap = await r.find('chap', parent: tref);
      if (chap == null || chap.size < 4) continue;
      final b = ByteData.sublistView(await r.bytes(chap.start, 4));
      chapTrackId = b.getUint32(0);
      break;
    }
    if (chapTrackId == null) return null;
    // 2) trova la trak con quell'id e leggi la sample table
    for (final trak in traks) {
      final tkhd = await r.find('tkhd', parent: trak);
      if (tkhd == null) continue;
      final tb = ByteData.sublistView(await r.bytes(tkhd.start, 28));
      final v = tb.getUint8(0);
      final trackId = v == 1 ? tb.getUint32(20) : tb.getUint32(12);
      if (trackId != chapTrackId) continue;
      return _readTextTrackSamples(r, trak);
    }
    return null;
  }

  static Future<List<M4bChapter>?> _readTextTrackSamples(
      Mp4Reader r, Mp4Atom trak) async {
    final mdia = await r.find('mdia', parent: trak);
    if (mdia == null) return null;
    final mdhd = await r.find('mdhd', parent: mdia);
    if (mdhd == null) return null;
    final hb = ByteData.sublistView(await r.bytes(mdhd.start, 32));
    final hv = hb.getUint8(0);
    final timescale = hv == 1 ? hb.getUint32(20) : hb.getUint32(12);
    final minf = await r.find('minf', parent: mdia);
    final stbl = minf == null ? null : await r.find('stbl', parent: minf);
    if (stbl == null || timescale == 0) return null;

    // durate (stts) → tempi di inizio cumulativi
    final stts = await r.find('stts', parent: stbl);
    if (stts == null) return null;
    final sb = ByteData.sublistView(await r.bytes(stts.start, stts.size));
    final entryCount = sb.getUint32(4);
    final startsTicks = <int>[];
    var t = 0;
    for (var i = 0; i < entryCount; i++) {
      final cnt = sb.getUint32(8 + i * 8);
      final dur = sb.getUint32(12 + i * 8);
      for (var j = 0; j < cnt; j++) {
        startsTicks.add(t);
        t += dur;
      }
    }

    // offset dei sample: stco/co64 (un chunk per sample nel caso capitoli,
    // ma gestiamo stsc>1 sommando le size dentro al chunk)
    final stsz = await r.find('stsz', parent: stbl);
    if (stsz == null) return null;
    final zb = ByteData.sublistView(await r.bytes(stsz.start, stsz.size));
    final defaultSize = zb.getUint32(4);
    final sampleCount = zb.getUint32(8);
    final sizes = List<int>.generate(
        sampleCount, (i) => defaultSize != 0 ? defaultSize : zb.getUint32(12 + i * 4));

    final co64 = await r.find('co64', parent: stbl);
    final stco = co64 ?? await r.find('stco', parent: stbl);
    if (stco == null) return null;
    final cb = ByteData.sublistView(await r.bytes(stco.start, stco.size));
    final chunkCount = cb.getUint32(4);
    final chunkOffsets = List<int>.generate(
        chunkCount,
        (i) => co64 != null ? cb.getUint64(8 + i * 8) : cb.getUint32(8 + i * 4));

    // stsc: mappa sample→chunk
    final stsc = await r.find('stsc', parent: stbl);
    if (stsc == null) return null;
    final scb = ByteData.sublistView(await r.bytes(stsc.start, stsc.size));
    final stscCount = scb.getUint32(4);
    final out = <M4bChapter>[];
    var sample = 0;
    for (var e = 0; e < stscCount && sample < sampleCount; e++) {
      final firstChunk = scb.getUint32(8 + e * 12);
      final perChunk = scb.getUint32(12 + e * 12);
      final nextFirst = e + 1 < stscCount
          ? scb.getUint32(8 + (e + 1) * 12)
          : chunkCount + 1;
      for (var c = firstChunk; c < nextFirst && sample < sampleCount; c++) {
        var off = chunkOffsets[c - 1];
        for (var s = 0; s < perChunk && sample < sampleCount; s++) {
          final raw = await r.bytes(off, sizes[sample]);
          if (raw.length >= 2) {
            final tlen = ByteData.sublistView(raw).getUint16(0);
            final title = String.fromCharCodes(
                raw.sublist(2, (2 + tlen).clamp(0, raw.length)));
            out.add(M4bChapter(
                _utf8Fix(title), startsTicks[sample] * 1000 ~/ timescale));
          }
          off += sizes[sample];
          sample++;
        }
      }
    }
    return out.isEmpty ? null : out;
  }

  /// I byte letti come char-codes vanno re-interpretati UTF-8.
  static String _utf8Fix(String latin) {
    try {
      return const Utf8Decoder().convert(latin.codeUnits);
    } catch (_) {
      return latin;
    }
  }
}
```

Aggiungere in testa al file gli import mancanti: `import 'dart:convert' show Utf8Decoder;`.

Nota per l'esecutore: i dettagli binari (offset riservati di `chpl` v1, layout `tkhd`) sono scritti secondo le specifiche note, ma la GROUND TRUTH sono le fixture FFmpeg: se un test fallisce con valori sballati, stampare un hexdump dell'atom (`raw.take(64)`) e correggere gli offset nel parser finché i 3 capitoli con i tempi attesi non tornano. Non "aggiustare" il test.

- [ ] **Step 5: Eseguire i test**

Run: `flutter test test/m4b_parser_test.dart`
Expected: 5/5 PASS. (Se `chpl` assente nelle fixture FFmpeg e i capitoli arrivano dalla traccia QT: va bene, il parser prova entrambe le strade.)

- [ ] **Step 6: Commit**

```powershell
git add lib/core/m4b tool/make_fixtures.ps1 test/fixtures test/m4b_parser_test.dart
git commit -m "feat(m4b): parser atom MP4 con capitoli chpl/QT, cover, metadata"
```

---

### Task 4: Modello, metadata reader e LibraryRepository (drift)

**Files:**
- Create: `lib/core/library/book_metadata.dart`, `lib/core/library/metadata_reader.dart`, `lib/core/library/library_db.dart`, `lib/core/library/library_repository.dart`, `test/helpers/sqlite.dart`
- Test: `test/metadata_reader_test.dart`, `test/library_repository_test.dart`

- [ ] **Step 1: sqlite3 per i test host Windows**

I test drift su host Windows richiedono `sqlite3.dll`. Scaricarla (una tantum, non committata):

```powershell
Invoke-WebRequest -Uri "https://www.sqlite.org/2024/sqlite-dll-win-x64-3460000.zip" -OutFile "$env:TEMP\sqlite.zip"
Expand-Archive "$env:TEMP\sqlite.zip" -DestinationPath tool -Force
```

(se l'URL è datato, prendere la "Precompiled Binaries for Windows" 64-bit corrente da sqlite.org/download.html)

Creare `test/helpers/sqlite.dart`:

```dart
import 'dart:ffi';
import 'dart:io';
import 'package:sqlite3/open.dart';

/// Da chiamare in setUpAll: su Windows carica la dll locale del repo.
void ensureSqlite() {
  if (Platform.isWindows) {
    open.overrideFor(
        OperatingSystem.windows, () => DynamicLibrary.open('tool/sqlite3.dll'));
  }
}
```

- [ ] **Step 2: Modello condiviso**

Creare `lib/core/library/book_metadata.dart`:

```dart
import 'dart:typed_data';
import 'package:flutter/foundation.dart';

@immutable
class ChapterInfo {
  final String title;
  final int startMs;
  const ChapterInfo(this.title, this.startMs);
}

@immutable
class BookMetadata {
  final String title;
  final String author;
  final int durationMs;
  final Uint8List? coverBytes;
  final List<ChapterInfo> chapters;
  const BookMetadata({
    required this.title,
    required this.author,
    required this.durationMs,
    this.coverBytes,
    this.chapters = const [],
  });
}
```

- [ ] **Step 3: Test del metadata reader (failing)**

Creare `test/metadata_reader_test.dart`:

```dart
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/library/metadata_reader.dart';

void main() {
  test('m4b → parser interno con capitoli', () async {
    final meta =
        await readBookMetadata(File('test/fixtures/book_chaptered.m4b'));
    expect(meta.title, 'Libro di prova');
    expect(meta.chapters, hasLength(3));
  });

  test('mp3 → tag id3 senza capitoli', () async {
    final meta = await readBookMetadata(File('test/fixtures/sample.mp3'));
    expect(meta.title, 'MP3 di prova');
    expect(meta.author, 'Autore MP3');
    expect(meta.chapters, isEmpty);
  });

  test('file illeggibile → fallback nome file', () async {
    final junk = File('test/fixtures/garbage.m4b');
    junk.writeAsBytesSync(List.filled(32, 1));
    final meta = await readBookMetadata(junk);
    expect(meta.title, 'garbage'); // nome file senza estensione
    expect(meta.chapters, isEmpty);
    junk.deleteSync();
  });
}
```

Run: `flutter test test/metadata_reader_test.dart` → FAIL (file inesistente).

- [ ] **Step 4: Metadata reader**

Creare `lib/core/library/metadata_reader.dart`:

```dart
import 'dart:io';
import 'package:audio_metadata_reader/audio_metadata_reader.dart' as amr;
import 'package:path/path.dart' as p;
import '../m4b/m4b_parser.dart';
import 'book_metadata.dart';

/// Estrae i metadata da un file audio. Mai eccezioni: file illeggibile →
/// entry generica col nome file (la scansione non si deve mai fermare).
Future<BookMetadata> readBookMetadata(File file) async {
  final ext = p.extension(file.path).toLowerCase();
  final fallback = BookMetadata(
    title: p.basenameWithoutExtension(file.path),
    author: '',
    durationMs: 0,
  );
  try {
    if (ext == '.m4b' || ext == '.m4a') {
      final m = await M4bParser.parse(file);
      return BookMetadata(
        title: m.title.isNotEmpty ? m.title : fallback.title,
        author: m.author,
        durationMs: m.durationMs,
        coverBytes: m.coverBytes,
        chapters: [
          for (final c in m.chapters) ChapterInfo(c.title, c.startMs)
        ],
      );
    }
    if (ext == '.mp3') {
      final m = amr.readMetadata(file, getImage: true);
      return BookMetadata(
        title: (m.title ?? '').isNotEmpty ? m.title! : fallback.title,
        author: m.artist ?? '',
        durationMs: m.duration?.inMilliseconds ?? 0,
        coverBytes: m.pictures.isNotEmpty ? m.pictures.first.bytes : null,
      );
    }
    return fallback;
  } catch (_) {
    return fallback;
  }
}
```

Nota: verificare l'API reale di `audio_metadata_reader` installato (`readMetadata` sync vs async, campi `title/artist/duration/pictures`) con la doc del package su pub.dev; adattare mantenendo il contratto del test.

Run: `flutter test test/metadata_reader_test.dart` → 3/3 PASS.

- [ ] **Step 5: Schema drift**

Creare `lib/core/library/library_db.dart`:

```dart
import 'dart:io';
import 'dart:typed_data';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';

part 'library_db.g.dart';

class Books extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get path => text().unique()();
  IntColumn get fileSize => integer()();
  IntColumn get fileMtimeMs => integer()();
  TextColumn get title => text()();
  TextColumn get author => text().withDefault(const Constant(''))();
  IntColumn get durationMs => integer().withDefault(const Constant(0))();
  BlobColumn get cover => blob().nullable()();
  IntColumn get addedAtMs => integer()();
  // posizione di ascolto
  IntColumn get positionMs => integer().withDefault(const Constant(0))();
  IntColumn get lastPlayedAtMs => integer().nullable()();
  BoolColumn get finished => boolean().withDefault(const Constant(false))();
  // file sparito dalla cartella: tombstone per retention posizioni (30gg)
  IntColumn get removedAtMs => integer().nullable()();
}

class Chapters extends Table {
  IntColumn get bookId => integer().references(Books, #id)();
  IntColumn get idx => integer()();
  TextColumn get title => text()();
  IntColumn get startMs => integer()();
  @override
  Set<Column> get primaryKey => {bookId, idx};
}

@DriftDatabase(tables: [Books, Chapters])
class LibraryDb extends _$LibraryDb {
  LibraryDb(super.e);
  LibraryDb.file(String path) : super(NativeDatabase(File(path)));
  LibraryDb.memory() : super(NativeDatabase.memory());

  @override
  int get schemaVersion => 1;
}
```

Run: `dart run build_runner build --delete-conflicting-outputs`
Expected: genera `lib/core/library/library_db.g.dart` senza errori.

- [ ] **Step 6: Test del repository (failing)**

Creare `test/library_repository_test.dart`:

```dart
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/library/library_db.dart';
import 'package:audiobook_maker_mobile/core/library/library_repository.dart';
import 'helpers/sqlite.dart';

void main() {
  setUpAll(ensureSqlite);

  late Directory dir;
  late LibraryDb db;
  late LibraryRepository repo;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('abm_lib_');
    db = LibraryDb.memory();
    repo = LibraryRepository(db);
    File('test/fixtures/book_chaptered.m4b')
        .copySync('${dir.path}/libro1.m4b');
    File('test/fixtures/sample.mp3').copySync('${dir.path}/traccia.mp3');
    File('${dir.path}/note.txt').writeAsStringSync('non audio');
  });

  tearDown(() async {
    await db.close();
    dir.deleteSync(recursive: true);
  });

  test('scan: indicizza solo mp3/m4b con metadata e capitoli', () async {
    final result = await repo.scanFolder(dir.path);
    expect(result.added, 2);
    final books = await repo.allBooks();
    expect(books, hasLength(2));
    final m4b = books.firstWhere((b) => b.path.endsWith('libro1.m4b'));
    expect(m4b.title, 'Libro di prova');
    final chapters = await repo.chaptersOf(m4b.id);
    expect(chapters, hasLength(3));
  });

  test('scan idempotente: secondo giro non duplica', () async {
    await repo.scanFolder(dir.path);
    final second = await repo.scanFolder(dir.path);
    expect(second.added, 0);
    expect(second.removed, 0);
    expect(await repo.allBooks(), hasLength(2));
  });

  test('file rimosso: sparisce dalla lista ma conserva la posizione 30gg',
      () async {
    await repo.scanFolder(dir.path);
    final book = (await repo.allBooks()).first;
    await repo.savePosition(book.id, 12345);
    File(book.path).deleteSync();
    await repo.scanFolder(dir.path);
    expect((await repo.allBooks()).map((b) => b.id), isNot(contains(book.id)));
    // re-import entro 30gg: posizione recuperata
    File('test/fixtures/book_chaptered.m4b').copySync(book.path);
    await repo.scanFolder(dir.path);
    final back = (await repo.allBooks())
        .firstWhere((b) => b.path == book.path);
    expect(back.positionMs, 12345);
  });

  test('tombstone oltre 30gg: posizione dimenticata', () async {
    await repo.scanFolder(dir.path);
    final book = (await repo.allBooks()).first;
    await repo.savePosition(book.id, 999);
    File(book.path).deleteSync();
    final t31 = DateTime.now()
        .subtract(const Duration(days: 31))
        .millisecondsSinceEpoch;
    await repo.scanFolder(dir.path, nowMs: t31 + 31 * 86400000);
    await repo.purgeTombstones(nowMs: t31 + 62 * 86400000);
    File('test/fixtures/book_chaptered.m4b').copySync(book.path);
    await repo.scanFolder(dir.path);
    final back = (await repo.allBooks())
        .firstWhere((b) => b.path == book.path);
    expect(back.positionMs, 0);
  });

  test('savePosition + finished', () async {
    await repo.scanFolder(dir.path);
    final book = (await repo.allBooks()).first;
    await repo.savePosition(book.id, 5000);
    await repo.markFinished(book.id);
    final again = (await repo.allBooks()).firstWhere((b) => b.id == book.id);
    expect(again.positionMs, 5000);
    expect(again.finished, true);
  });
}
```

Run: `flutter test test/library_repository_test.dart` → FAIL.

- [ ] **Step 7: LibraryRepository**

Creare `lib/core/library/library_repository.dart`:

```dart
import 'dart:io';
import 'package:drift/drift.dart';
import 'package:path/path.dart' as p;
import 'library_db.dart';
import 'metadata_reader.dart';

class ScanResult {
  final int added;
  final int removed;
  const ScanResult(this.added, this.removed);
}

const _audioExts = {'.mp3', '.m4b', '.m4a'};
const tombstoneRetention = Duration(days: 30);

class LibraryRepository {
  final LibraryDb db;
  LibraryRepository(this.db);

  Future<List<Book>> allBooks() => (db.select(db.books)
        ..where((b) => b.removedAtMs.isNull())
        ..orderBy([(b) => OrderingTerm.desc(b.addedAtMs)]))
      .get();

  Future<List<Chapter>> chaptersOf(int bookId) => (db.select(db.chapters)
        ..where((c) => c.bookId.equals(bookId))
        ..orderBy([(c) => OrderingTerm.asc(c.idx)]))
      .get();

  /// Scansione della cartella: aggiunge i nuovi file audio, marca tombstone
  /// i file spariti, resuscita i tombstone se il file ricompare (posizione
  /// conservata). Un file illeggibile produce una entry generica, mai errore.
  Future<ScanResult> scanFolder(String folder, {int? nowMs}) async {
    final now = nowMs ?? DateTime.now().millisecondsSinceEpoch;
    final found = <String, File>{};
    final dir = Directory(folder);
    if (dir.existsSync()) {
      for (final ent in dir.listSync(recursive: false)) {
        if (ent is File &&
            _audioExts.contains(p.extension(ent.path).toLowerCase())) {
          found[ent.path] = ent;
        }
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
      } else if (existing.removedAtMs != null) {
        // tombstone resuscitato: file ricomparso, posizione conservata
        await (db.update(db.books)..where((b) => b.id.equals(existing.id)))
            .write(const BooksCompanion(removedAtMs: Value(null)));
        added++;
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

  Future<void> _insertBook(File f, int now) async {
    final stat = f.statSync();
    final meta = await readBookMetadata(f);
    final id = await db.into(db.books).insert(BooksCompanion.insert(
          path: f.path,
          fileSize: stat.size,
          fileMtimeMs: stat.modified.millisecondsSinceEpoch,
          title: meta.title,
          author: Value(meta.author),
          durationMs: Value(meta.durationMs),
          cover: Value(meta.coverBytes),
          addedAtMs: now,
        ));
    for (var i = 0; i < meta.chapters.length; i++) {
      await db.into(db.chapters).insert(ChaptersCompanion.insert(
            bookId: id,
            idx: i,
            title: meta.chapters[i].title,
            startMs: meta.chapters[i].startMs,
          ));
    }
  }

  Future<void> savePosition(int bookId, int positionMs) =>
      (db.update(db.books)..where((b) => b.id.equals(bookId))).write(
          BooksCompanion(
              positionMs: Value(positionMs),
              lastPlayedAtMs:
                  Value(DateTime.now().millisecondsSinceEpoch)));

  Future<void> markFinished(int bookId) =>
      (db.update(db.books)..where((b) => b.id.equals(bookId)))
          .write(const BooksCompanion(finished: Value(true)));

  /// Elimina i tombstone più vecchi della retention (posizioni dimenticate).
  Future<void> purgeTombstones({int? nowMs}) async {
    final now = nowMs ?? DateTime.now().millisecondsSinceEpoch;
    final cutoff = now - tombstoneRetention.inMilliseconds;
    final dead = await (db.select(db.books)
          ..where((b) => b.removedAtMs.isSmallerThanValue(cutoff)))
        .get();
    for (final b in dead) {
      await (db.delete(db.chapters)..where((c) => c.bookId.equals(b.id))).go();
      await (db.delete(db.books)..where((x) => x.id.equals(b.id))).go();
    }
  }
}
```

Nota tipi generati: `Book`, `Chapter`, `BooksCompanion`, `ChaptersCompanion` arrivano da `library_db.g.dart` (build_runner). Se i nomi generati differiscono (es. `BooksData`), usare quelli reali — il contratto dei test non cambia.

- [ ] **Step 8: Eseguire tutti i test**

Run: `flutter test`
Expected: tutti PASS (m4b 5, metadata reader 3, repository 5, più l'eventuale widget test di default di flutter create — se `test/widget_test.dart` generato fallisce perché la home è cambiata, eliminarlo: la UI arriva nel 2b).

- [ ] **Step 9: Commit**

```powershell
git add lib/core/library test/helpers test/metadata_reader_test.dart test/library_repository_test.dart pubspec.yaml
git commit -m "feat(library): indice drift, metadata reader, scansione cartella con tombstone 30gg"
```

---

### Task 5: Qualità, CI e chiusura

**Files:**
- Create: `.github/workflows/ci.yml`, `README.md`
- Modify: eventuali finding di analyze

- [ ] **Step 1: Analisi statica e format**

Run: `dart format .`
Run: `flutter analyze`
Expected: `No issues found!` — correggere ogni warning (gli `avoid_print` ecc. del lint set standard).

- [ ] **Step 2: CI minimale**

Creare `.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          channel: stable
      - run: flutter pub get
      - run: dart run build_runner build --delete-conflicting-outputs
      - run: flutter analyze
      - run: flutter test
```

Nota: su ubuntu i test drift trovano libsqlite3 di sistema; se il job fallisce per sqlite mancante aggiungere uno step `sudo apt-get install -y libsqlite3-dev` prima dei test.

- [ ] **Step 3: README**

Creare `README.md`:

```markdown
# AudioBook Maker Mobile

App Flutter (Android/iOS) companion di [AudioBook Maker](https://github.com/<org>/AudioBook-Maker):
player di audiolibri locale (mp3/m4b con capitoli e copertina) + client del flusso
di produzione TTS del sito.

## Stato
Fase 2a: core senza UI (parser m4b, indice libreria drift, i18n 7 lingue).

## Sviluppo
- `flutter pub get`
- `dart run build_runner build` (codegen drift)
- `flutter test` (su Windows: scaricare sqlite3.dll in `tool/` — vedi `test/helpers/sqlite.dart`)
- Fixture test: `powershell -File tool/make_fixtures.ps1` (richiede FFmpeg)

Spec e piani: repo AudioBook-Maker, `docs/superpowers/specs/2026-06-11-mobile-app-design.md`.
```

- [ ] **Step 4: Smoke build Android (facoltativo ma raccomandato)**

Run: `flutter build apk --debug`
Expected: `Built build\app\outputs\flutter-apk\app-debug.apk`. Richiede Android SDK del Task 0; se fallisce per toolchain, annotare e proseguire (non blocca il 2a: la build è verificata di nuovo nel 2b).

- [ ] **Step 5: Commit finale**

```powershell
git add -A
git commit -m "chore: analyze pulito, CI flutter test, README"
```

NON creare il repo GitHub né fare push senza conferma dell'utente.

---

## Note per l'esecutore

- **Fixture = ground truth.** Il parser m4b è scritto secondo le specifiche MP4/Nero note, ma i dettagli binari vanno validati contro i file generati da FFmpeg (lo stesso muxer usato dal backend). Test rosso → debug con hexdump → correggere il parser.
- **Versioni pub**: le versioni in pubspec sono floor ragionevoli al 2026-06; se `pub get` segnala conflitti, alzare il vincolo e annotarlo nel commit.
- **Niente UI in questo piano**: nessun widget, nessun provider Riverpod, nessun package audio. Se senti il bisogno di aggiungerli, è scope del 2b.
- **iOS**: la cartella ios/ esiste ma non si tocca né si builda in questo piano.
