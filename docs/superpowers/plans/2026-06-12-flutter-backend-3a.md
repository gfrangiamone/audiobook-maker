# App Flutter — Piano 3a: Client API, Attività, Download, FCM (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collegare l'app al backend: identità client persistente, client API (`/api/my_jobs`, `/api/device/register`), tab Attività con job in corso/completati/falliti, download dei file nella cartella libreria, notifiche push FCM (degradabili se Firebase non configurato).

**Architecture:** `AbmApiClient` (dio) incapsula HTTP + header `X-ABM-Cid`; `RemoteJob` modella la risposta di `my_jobs`; un provider Riverpod con polling periodico alimenta `ActivityScreen`; il download scrive nella cartella libreria e triggera la riscansione (il libro appare in Libreria). FCM è un modulo opzionale: senza config Firebase l'app funziona identica, solo senza push. Tutto il networking è mockato nei test (`http_mock_adapter`).

**Tech Stack:** dio + http_mock_adapter, firebase_core + firebase_messaging (opzionali a runtime), uuid; riverpod/drift già presenti.

**Repo target:** `C:\Users\gfran\NEXT srl\Progetti - Documenti\audiobook-maker-mobile` (branch main, remoto GitHub attivo: NIENTE push senza conferma utente). Flutter `C:\flutter\bin\flutter.bat`, Dart `C:\flutter\bin\dart.bat`. PowerShell, comandi singoli senza `&&`. Caveat OneDrive: lock su `ios\Flutter\ephemeral` → normalizzare attributi e cancellare la dir.

**Backend di riferimento:** branch `abm_mobile` del repo AudioBook-Maker (endpoint: `GET /api/my_jobs`, `POST /api/device/register`, `/dl/<token>/m4b|abm|download` con Range; contratti nel piano `2026-06-12-mobile-backend-api.md`). Per i test end-to-end manuali: backend locale `python audiobook_app.py` su `http://<ip-pc>:5601` (il deploy in produzione avviene DOPO il 3a, su decisione utente).

**Decisioni di piano:**
- **URL server configurabile, nessun default inventato**: `SettingsService.serverUrl` parte null; la tab Attività senza URL mostra una CTA di configurazione (campo nelle Impostazioni). In sviluppo si imposta l'IP locale; quando il backend sarà in prod si metterà l'URL pubblico.
- **Polling, non SSE, per l'MVP della tab Attività**: `my_jobs` ogni 5s mentre la tab è visibile (semplice, robusto su rete mobile). L'SSE per-job arriva col wizard (Piano 3b) dove serve il progress fine.
- **Download senza resume client-side nell'MVP**: download in file `.part` + rename atomico; il supporto Range del backend resta per il futuro. Fallimento → file .part cancellato, retry manuale.

## Mappa dei file

```
lib/
├── core/
│   ├── api/
│   │   ├── client_identity.dart      # cid persistente (uuid, charset X-ABM-Cid)
│   │   ├── remote_job.dart           # modello RemoteJob (da JSON my_jobs)
│   │   ├── abm_api_client.dart       # dio: myJobs, registerDevice, downloadToFile
│   │   └── download_service.dart     # download nel folder libreria + rescan
│   ├── push/push_setup.dart          # init Firebase tollerante + registrazione token
│   └── settings/settings_service.dart # MODIFICA: +serverUrl
├── app/
│   ├── providers.dart                # MODIFICA: +apiClient, +remoteJobs (polling)
│   ├── shell.dart                    # MODIFICA: tab Attività → ActivityScreen
│   └── screens/
│       ├── activity_screen.dart      # in corso / completati / falliti
│       └── settings_screen.dart      # MODIFICA: tile URL server
lib/l10n/app_*.arb                    # MODIFICA: nuove chiavi (7 lingue)
test/
├── client_identity_test.dart
├── remote_job_test.dart
├── abm_api_client_test.dart          # http_mock_adapter
├── download_service_test.dart
└── widget/activity_screen_test.dart
```

---

### Task 1: Identità client + serverUrl nelle impostazioni

**Files:**
- Create: `lib/core/api/client_identity.dart`
- Modify: `lib/core/settings/settings_service.dart`
- Test: `test/client_identity_test.dart`, `test/settings_service_test.dart` (append)

- [ ] **Step 1: dipendenza uuid**

`pubspec.yaml` → dependencies: `uuid: ^4.4.0`. Run `C:\flutter\bin\flutter.bat pub get`.

- [ ] **Step 2: test che falliscono** — `test/client_identity_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:audiobook_maker_mobile/core/api/client_identity.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('genera un cid valido e lo persiste', () async {
    SharedPreferences.setMockInitialValues({});
    final cid = await ClientIdentity.obtain();
    // charset accettato dal backend: ^[A-Za-z0-9_-]{8,64}$
    expect(RegExp(r'^[A-Za-z0-9_-]{8,64}$').hasMatch(cid), isTrue);
    final again = await ClientIdentity.obtain();
    expect(again, cid); // stabile tra chiamate
  });

  test('riusa il cid già salvato', () async {
    SharedPreferences.setMockInitialValues({'abm_cid': 'mobile-cid-fisso1'});
    expect(await ClientIdentity.obtain(), 'mobile-cid-fisso1');
  });
}
```

In `test/settings_service_test.dart` append:

```dart
  test('serverUrl: default null, set normalizza lo slash finale', () async {
    SharedPreferences.setMockInitialValues({});
    final s = await SettingsService.load();
    expect(s.serverUrl, isNull);
    await s.setServerUrl('http://192.168.1.10:5601/');
    expect(s.serverUrl, 'http://192.168.1.10:5601'); // niente trailing slash
    await s.setServerUrl('');
    expect(s.serverUrl, isNull); // stringa vuota = non configurato
  });
```

Run: `C:\flutter\bin\flutter.bat test test/client_identity_test.dart test/settings_service_test.dart` → FAIL.

- [ ] **Step 3: implementare**

`lib/core/api/client_identity.dart`:

```dart
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

/// Identità persistente del client verso il backend (header X-ABM-Cid).
/// Stesso modello di fiducia del cookie web: chi presenta il cid è il
/// proprietario dei job. Charset backend: ^[A-Za-z0-9_-]{8,64}$.
class ClientIdentity {
  static const _key = 'abm_cid';

  static Future<String> obtain() async {
    final prefs = await SharedPreferences.getInstance();
    final existing = prefs.getString(_key);
    if (existing != null && existing.isNotEmpty) return existing;
    final cid = 'app-${const Uuid().v4().replaceAll('-', '')}'; // 36 char
    await prefs.setString(_key, cid);
    return cid;
  }
}
```

In `settings_service.dart` aggiungere:

```dart
  static const _kServerUrl = 'server_url';

  String? get serverUrl {
    final v = _prefs.getString(_kServerUrl);
    return (v == null || v.isEmpty) ? null : v;
  }

  Future<void> setServerUrl(String url) async {
    var v = url.trim();
    while (v.endsWith('/')) {
      v = v.substring(0, v.length - 1);
    }
    await _prefs.setString(_kServerUrl, v);
    notifyListeners();
  }
```

- [ ] **Step 4: run + commit**

Run: i due file di test → PASS (e suite intera verde).

```powershell
git add lib/core/api/client_identity.dart lib/core/settings/settings_service.dart test/client_identity_test.dart test/settings_service_test.dart pubspec.yaml pubspec.lock
git commit -m "feat(api): identita client persistente e serverUrl configurabile"
```

(footer: riga vuota + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`, here-string `@'...'@`)

---

### Task 2: Modello RemoteJob + AbmApiClient

**Files:**
- Create: `lib/core/api/remote_job.dart`, `lib/core/api/abm_api_client.dart`
- Test: `test/remote_job_test.dart`, `test/abm_api_client_test.dart`

- [ ] **Step 1: dipendenze**

`pubspec.yaml`: dependencies `dio: ^5.7.0`; dev_dependencies `http_mock_adapter: ^0.6.1`. `flutter pub get` (alza i floor se serve, annota).

- [ ] **Step 2: test del modello (failing)** — `test/remote_job_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/api/remote_job.dart';

void main() {
  test('parse job attivo (generating)', () {
    final j = RemoteJob.fromJson(const {
      'job_id': 'j1',
      'status': 'generating',
      'title': 'Il mio libro',
      'output_format': 'm4b',
      'created_at': 1765000000.0,
      'progress_current': 3,
      'progress_total': 10,
      'progress_message': 'Chapter 3...',
    });
    expect(j.jobId, 'j1');
    expect(j.isActive, isTrue);
    expect(j.progressFraction, closeTo(0.3, 0.001));
    expect(j.downloadToken, isNull);
  });

  test('parse job completato da token', () {
    final j = RemoteJob.fromJson(const {
      'job_id': 'j2',
      'status': 'done',
      'title': 'Cime tempestose',
      'output_format': 'm4b',
      'created_at': 1765000000.0,
      'download_token': 'TOK123',
      'expires_at': 1765086400.0,
      'downloaded_at': null,
      'formats': {'m4b': true, 'zip': false, 'mp3': false, 'abm': true},
    });
    expect(j.isDone, isTrue);
    expect(j.downloadToken, 'TOK123');
    expect(j.formats, containsAll(['m4b', 'abm']));
    expect(j.expiresAt!.millisecondsSinceEpoch, 1765086400000);
  });

  test('parse tollerante: campi mancanti non crashano', () {
    final j = RemoteJob.fromJson(const {'job_id': 'j3'});
    expect(j.status, '');
    expect(j.title, '');
    expect(j.progressFraction, isNull);
    expect(j.formats, isEmpty);
  });
}
```

- [ ] **Step 3: implementare il modello** — `lib/core/api/remote_job.dart`:

```dart
import 'package:flutter/foundation.dart';

/// Un job del backend visto da /api/my_jobs. Parse tollerante: il contratto
/// JSON è additivo, i campi possono mancare a seconda dello status.
@immutable
class RemoteJob {
  final String jobId;
  final String status;
  final String title;
  final String outputFormat;
  final DateTime? createdAt;
  final int? progressCurrent;
  final int? progressTotal;
  final String progressMessage;
  final String? downloadToken;
  final DateTime? expiresAt;
  final DateTime? downloadedAt;
  final List<String> formats; // tra: m4b, zip, mp3, abm

  const RemoteJob({
    required this.jobId,
    required this.status,
    required this.title,
    required this.outputFormat,
    required this.createdAt,
    required this.progressCurrent,
    required this.progressTotal,
    required this.progressMessage,
    required this.downloadToken,
    required this.expiresAt,
    required this.downloadedAt,
    required this.formats,
  });

  bool get isActive => const {
        'analyzed',
        'optimizing',
        'optimized',
        'translating',
        'generating'
      }.contains(status);
  bool get isDone => status == 'done';
  bool get isFailed => status == 'error' || status == 'cancelled';

  double? get progressFraction {
    final c = progressCurrent, t = progressTotal;
    if (c == null || t == null || t <= 0) return null;
    return (c / t).clamp(0.0, 1.0);
  }

  static DateTime? _ts(dynamic v) {
    if (v is num && v > 0) {
      return DateTime.fromMillisecondsSinceEpoch((v * 1000).round());
    }
    return null;
  }

  factory RemoteJob.fromJson(Map<String, dynamic> json) {
    final fmts = <String>[];
    final f = json['formats'];
    if (f is Map) {
      for (final e in f.entries) {
        if (e.value == true) fmts.add(e.key.toString());
      }
    }
    return RemoteJob(
      jobId: (json['job_id'] ?? '').toString(),
      status: (json['status'] ?? '').toString(),
      title: (json['title'] ?? '').toString(),
      outputFormat: (json['output_format'] ?? '').toString(),
      createdAt: _ts(json['created_at']),
      progressCurrent: json['progress_current'] is num
          ? (json['progress_current'] as num).toInt()
          : null,
      progressTotal: json['progress_total'] is num
          ? (json['progress_total'] as num).toInt()
          : null,
      progressMessage: (json['progress_message'] ?? '').toString(),
      downloadToken: json['download_token']?.toString(),
      expiresAt: _ts(json['expires_at']),
      downloadedAt: _ts(json['downloaded_at']),
      formats: fmts,
    );
  }
}
```

Run test modello → PASS.

- [ ] **Step 4: test del client (failing)** — `test/abm_api_client_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:audiobook_maker_mobile/core/api/abm_api_client.dart';

void main() {
  late Dio dio;
  late DioAdapter adapter;
  late AbmApiClient client;

  setUp(() {
    dio = Dio(BaseOptions(baseUrl: 'http://test.local'));
    adapter = DioAdapter(dio: dio);
    client = AbmApiClient(dio: dio, cid: 'mobile-cid-12345');
  });

  test('myJobs: header cid e parse della lista', () async {
    adapter.onGet(
      '/api/my_jobs',
      (server) => server.reply(200, {
        'jobs': [
          {'job_id': 'a', 'status': 'generating', 'title': 'T'},
          {'job_id': 'b', 'status': 'done', 'download_token': 'TOK'},
        ]
      }),
      headers: {'X-ABM-Cid': 'mobile-cid-12345'},
    );
    final jobs = await client.myJobs();
    expect(jobs, hasLength(2));
    expect(jobs[1].downloadToken, 'TOK');
  });

  test('registerDevice: POST col payload giusto', () async {
    adapter.onPost(
      '/api/device/register',
      (server) => server.reply(200, {'ok': true}),
      data: {
        'fcm_token': 'tok-abcdefghij',
        'platform': 'android',
        'app_version': '1.0.0',
      },
    );
    await client.registerDevice(
        fcmToken: 'tok-abcdefghij', platform: 'android', appVersion: '1.0.0');
  });

  test('errore HTTP → ApiException con status', () async {
    adapter.onGet('/api/my_jobs', (server) => server.reply(500, 'boom'));
    expect(() => client.myJobs(),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'status', 500)));
  });
}
```

- [ ] **Step 5: implementare il client** — `lib/core/api/abm_api_client.dart`:

```dart
import 'package:dio/dio.dart';

import 'remote_job.dart';

class ApiException implements Exception {
  final int? statusCode;
  final String message;
  ApiException(this.statusCode, this.message);
  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// Client HTTP verso il backend AudioBook Maker. Header X-ABM-Cid su ogni
/// chiamata. Le eccezioni dio sono normalizzate in ApiException.
class AbmApiClient {
  final Dio _dio;
  final String cid;

  AbmApiClient({required Dio dio, required this.cid}) : _dio = dio {
    _dio.options.headers['X-ABM-Cid'] = cid;
    _dio.options.connectTimeout = const Duration(seconds: 10);
    _dio.options.receiveTimeout = const Duration(seconds: 30);
  }

  /// Costruttore comodo da URL base (usato dall'app; i test iniettano dio).
  factory AbmApiClient.forServer(String baseUrl, String cid) =>
      AbmApiClient(dio: Dio(BaseOptions(baseUrl: baseUrl)), cid: cid);

  Future<List<RemoteJob>> myJobs() async {
    final data = await _get('/api/my_jobs');
    final raw = (data is Map && data['jobs'] is List)
        ? data['jobs'] as List
        : const [];
    return [
      for (final j in raw)
        if (j is Map<String, dynamic>) RemoteJob.fromJson(j)
    ];
  }

  Future<void> registerDevice(
      {required String fcmToken,
      required String platform,
      required String appVersion}) async {
    await _post('/api/device/register', {
      'fcm_token': fcmToken,
      'platform': platform,
      'app_version': appVersion,
    });
  }

  /// Scarica un file di download (`/dl/<token>/...`) su [savePath].
  Future<void> downloadToFile(String urlPath, String savePath,
      {void Function(int received, int total)? onProgress}) async {
    try {
      await _dio.download(urlPath, savePath,
          onReceiveProgress: onProgress,
          options: Options(receiveTimeout: const Duration(minutes: 30)));
    } on DioException catch (e) {
      throw ApiException(e.response?.statusCode, e.message ?? 'download');
    }
  }

  Future<dynamic> _get(String path) async {
    try {
      return (await _dio.get<dynamic>(path)).data;
    } on DioException catch (e) {
      throw ApiException(e.response?.statusCode, e.message ?? 'GET $path');
    }
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    try {
      return (await _dio.post<dynamic>(path, data: body)).data;
    } on DioException catch (e) {
      throw ApiException(e.response?.statusCode, e.message ?? 'POST $path');
    }
  }
}
```

- [ ] **Step 6: run + commit**

Run: `C:\flutter\bin\flutter.bat test` → tutti PASS (31 + 6 nuovi = 37, oltre a quelli del Task 1).

```powershell
git add lib/core/api test/remote_job_test.dart test/abm_api_client_test.dart pubspec.yaml pubspec.lock
git commit -m "feat(api): AbmApiClient (my_jobs, device/register, download) + RemoteJob"
```

---

### Task 3: DownloadService (file nella cartella libreria)

**Files:**
- Create: `lib/core/api/download_service.dart`
- Test: `test/download_service_test.dart`

- [ ] **Step 1: test (failing)** — `test/download_service_test.dart`:

```dart
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/api/abm_api_client.dart';
import 'package:audiobook_maker_mobile/core/api/download_service.dart';
import 'package:audiobook_maker_mobile/core/api/remote_job.dart';

class _FakeClient implements DownloadCapable {
  String? lastUrl;
  bool fail = false;
  @override
  Future<void> downloadToFile(String urlPath, String savePath,
      {void Function(int, int)? onProgress}) async {
    lastUrl = urlPath;
    if (fail) throw ApiException(410, 'gone');
    onProgress?.call(50, 100);
    File(savePath).writeAsBytesSync(List.filled(16, 7));
    onProgress?.call(100, 100);
  }
}

RemoteJob _job({List<String> formats = const ['m4b']}) =>
    RemoteJob.fromJson({
      'job_id': 'j1',
      'status': 'done',
      'title': 'Il mio: libro? <test>',
      'output_format': 'm4b',
      'download_token': 'TOK',
      'formats': {for (final f in formats) f: true},
    });

void main() {
  late Directory dir;
  late _FakeClient client;
  late DownloadService svc;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('abm_dl_');
    client = _FakeClient();
    svc = DownloadService(client);
  });

  tearDown(() => dir.deleteSync(recursive: true));

  test('scarica m4b: url giusto, nome sanitizzato, niente .part residuo',
      () async {
    final path = await svc.downloadJob(_job(), 'm4b', dir.path);
    expect(client.lastUrl, '/dl/TOK/m4b');
    expect(path, endsWith('.m4b'));
    final name = path.split(Platform.pathSeparator).last;
    expect(name, isNot(contains(':')));
    expect(name, isNot(contains('<')));
    expect(File(path).existsSync(), isTrue);
    expect(
        dir.listSync().where((f) => f.path.endsWith('.part')), isEmpty);
  });

  test('mappa formati → endpoint', () async {
    await svc.downloadJob(_job(formats: ['abm']), 'abm', dir.path);
    expect(client.lastUrl, '/dl/TOK/abm');
    await svc.downloadJob(_job(formats: ['zip']), 'zip', dir.path);
    expect(client.lastUrl, '/dl/TOK/download');
    await svc.downloadJob(_job(formats: ['mp3']), 'mp3', dir.path);
    expect(client.lastUrl, '/dl/TOK/download');
  });

  test('fallimento: .part rimosso, eccezione propagata', () async {
    client.fail = true;
    await expectLater(
        svc.downloadJob(_job(), 'm4b', dir.path), throwsA(isA<ApiException>()));
    expect(dir.listSync(), isEmpty);
  });

  test('job senza token → ArgumentError', () async {
    final j = RemoteJob.fromJson(const {'job_id': 'x', 'status': 'done'});
    expect(() => svc.downloadJob(j, 'm4b', dir.path), throwsArgumentError);
  });
}
```

- [ ] **Step 2: implementare** — `lib/core/api/download_service.dart`:

```dart
import 'dart:io';

import 'package:path/path.dart' as p;

import 'abm_api_client.dart';
import 'remote_job.dart';

/// Sottoinsieme del client usato dal download (mockabile nei test).
abstract class DownloadCapable {
  Future<void> downloadToFile(String urlPath, String savePath,
      {void Function(int received, int total)? onProgress});
}

// AbmApiClient soddisfa l'interfaccia.
// (dichiarazione: vedi nota sotto per l'implements)

class DownloadService {
  final DownloadCapable client;
  DownloadService(this.client);

  static const _extByFormat = {
    'm4b': '.m4b',
    'mp3': '.mp3',
    'zip': '.zip',
    'abm': '.abm',
  };

  static String _endpointFor(String token, String format) {
    switch (format) {
      case 'm4b':
        return '/dl/$token/m4b';
      case 'abm':
        return '/dl/$token/abm';
      default: // zip, mp3: file principale servito da /download
        return '/dl/$token/download';
    }
  }

  /// Caratteri vietati nei filesystem Android/iOS/exFAT.
  static String sanitizeFileName(String name) {
    var s = name.replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1f]'), ' ');
    s = s.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (s.isEmpty) s = 'audiobook';
    return s.length > 120 ? s.substring(0, 120).trim() : s;
  }

  /// Scarica [format] del [job] dentro [folder]. Ritorna il path finale.
  /// Scrive su .part e rinomina a fine download (mai file parziali visibili).
  Future<String> downloadJob(RemoteJob job, String format, String folder,
      {void Function(int received, int total)? onProgress}) async {
    final token = job.downloadToken;
    if (token == null || token.isEmpty) {
      throw ArgumentError('job senza download token');
    }
    final ext = _extByFormat[format] ?? '.bin';
    final base = sanitizeFileName(job.title.isNotEmpty ? job.title : job.jobId);
    var target = p.join(folder, '$base$ext');
    var n = 1;
    while (File(target).existsSync()) {
      target = p.join(folder, '$base (${++n})$ext');
    }
    final part = '$target.part';
    try {
      await client.downloadToFile(_endpointFor(token, format), part,
          onProgress: onProgress);
      File(part).renameSync(target);
      return target;
    } catch (_) {
      try {
        if (File(part).existsSync()) File(part).deleteSync();
      } catch (_) {}
      rethrow;
    }
  }
}
```

E in `abm_api_client.dart`: far dichiarare `class AbmApiClient implements DownloadCapable` (aggiungi l'import di download_service o sposta l'interfaccia in un file condiviso se crea ciclo: `download_service.dart` importa `abm_api_client.dart` per ApiException → metti `DownloadCapable` in `abm_api_client.dart` per evitare il ciclo, e download_service la importa da lì. Scegli questa seconda forma: interfaccia dichiarata in abm_api_client.dart).

- [ ] **Step 3: run + commit**

Run: `C:\flutter\bin\flutter.bat test test/download_service_test.dart` → 4 PASS; suite intera verde.

```powershell
git add lib/core/api test/download_service_test.dart
git commit -m "feat(api): DownloadService con nome sanitizzato e .part atomico"
```

---

### Task 4: Provider API + polling job

**Files:**
- Modify: `lib/app/providers.dart`
- Test: niente test dedicato qui (i provider sono cablaggio; la logica è nei task 2-3 e la UI nel task 5)

- [ ] **Step 1: estendere providers.dart** (append; import necessari in testa):

```dart
/// Cid del client: caricato una volta a runtime.
final clientIdProvider =
    FutureProvider<String>((ref) => ClientIdentity.obtain());

/// Client API: null finché l'URL server non è configurato.
final apiClientProvider = FutureProvider<AbmApiClient?>((ref) async {
  final settings = await ref.watch(settingsProvider.future);
  final url = settings.serverUrl;
  if (url == null) return null;
  final cid = await ref.watch(clientIdProvider.future);
  return AbmApiClient.forServer(url, cid);
});

final downloadServiceProvider = FutureProvider<DownloadService?>((ref) async {
  final client = await ref.watch(apiClientProvider.future);
  return client == null ? null : DownloadService(client);
});

/// Lista job remoti con polling: si riemette ogni [interval] finché osservato.
final remoteJobsProvider =
    StreamProvider.autoDispose<List<RemoteJob>>((ref) async* {
  final client = await ref.watch(apiClientProvider.future);
  if (client == null) {
    yield const [];
    return;
  }
  while (true) {
    yield await client.myJobs();
    await Future<void>.delayed(const Duration(seconds: 5));
  }
});
```

Nota: il while(true) dentro async* è il pattern semplice voluto: `autoDispose` chiude lo stream quando la tab non è più osservata; un errore di rete fa terminare lo stream in AsyncError → la UI mostra l'errore col retry (pull-to-refresh/invalidate). NON aggiungere retry automatico qui (YAGNI; il refresh è esplicito).

Aggiungere anche un piccolo provider per il refresh manuale, usato dalla UI: `ref.invalidate(remoteJobsProvider)` direttamente — nessun codice extra.

- [ ] **Step 2: verifica statica + commit**

Run: `C:\flutter\bin\flutter.bat analyze` → No issues; `flutter test` → verdi.

```powershell
git add lib/app/providers.dart
git commit -m "feat(app): provider api client e polling my_jobs"
```

---

### Task 5: ActivityScreen + i18n + Impostazioni server

**Files:**
- Create: `lib/app/screens/activity_screen.dart`
- Modify: `lib/app/shell.dart` (tab Attività → ActivityScreen), `lib/app/screens/settings_screen.dart` (tile URL server), `lib/l10n/app_*.arb`
- Test: `test/widget/activity_screen_test.dart`

- [ ] **Step 1: chiavi i18n** (tutti e 7 gli ARB; it e en sotto, altre 5 tradotte con cura):

it:
```json
  "activityEmpty": "Nessun lavoro sul server. Crea un audiolibro dal sito (o dall'app, prossimamente) e lo vedrai qui.",
  "activityServerMissing": "Configura l'indirizzo del server nelle impostazioni per vedere i tuoi lavori.",
  "activityInProgress": "In lavorazione",
  "activityCompleted": "Pronti da scaricare",
  "activityFailed": "Non riusciti",
  "activityExpires": "Scade {when}",
  "@activityExpires": {"placeholders": {"when": {"type": "String"}}},
  "activityDownloadFmt": "Scarica {fmt}",
  "@activityDownloadFmt": {"placeholders": {"fmt": {"type": "String"}}},
  "activityDownloaded": "Salvato in libreria: {name}",
  "@activityDownloaded": {"placeholders": {"name": {"type": "String"}}},
  "activityDownloadError": "Download non riuscito, riprova.",
  "activityLoadError": "Impossibile contattare il server.",
  "retry": "Riprova",
  "settingsServer": "Server",
  "settingsServerHint": "https://esempio.com oppure http://192.168.1.10:5601",
  "save": "Salva"
```

en:
```json
  "activityEmpty": "No jobs on the server. Create an audiobook from the website (or from the app, soon) and it will show up here.",
  "activityServerMissing": "Set the server address in settings to see your jobs.",
  "activityInProgress": "In progress",
  "activityCompleted": "Ready to download",
  "activityFailed": "Failed",
  "activityExpires": "Expires {when}",
  "@activityExpires": {"placeholders": {"when": {"type": "String"}}},
  "activityDownloadFmt": "Download {fmt}",
  "@activityDownloadFmt": {"placeholders": {"fmt": {"type": "String"}}},
  "activityDownloaded": "Saved to library: {name}",
  "@activityDownloaded": {"placeholders": {"name": {"type": "String"}}},
  "activityDownloadError": "Download failed, try again.",
  "activityLoadError": "Could not reach the server.",
  "retry": "Retry",
  "settingsServer": "Server",
  "settingsServerHint": "https://example.com or http://192.168.1.10:5601",
  "save": "Save"
```

`flutter gen-l10n` → ok.

- [ ] **Step 2: widget test (failing)** — `test/widget/activity_screen_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:audiobook_maker_mobile/app/providers.dart';
import 'package:audiobook_maker_mobile/app/screens/activity_screen.dart';
import 'package:audiobook_maker_mobile/core/api/remote_job.dart';
import 'package:audiobook_maker_mobile/l10n/app_localizations.dart';

Widget _wrap(Widget child, {List<Override> overrides = const []}) =>
    ProviderScope(
      overrides: overrides,
      child: MaterialApp(
        locale: const Locale('it'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: child,
      ),
    );

RemoteJob _gen() => RemoteJob.fromJson(const {
      'job_id': 'g1',
      'status': 'generating',
      'title': 'In corso',
      'progress_current': 4,
      'progress_total': 10,
    });

RemoteJob _done() => RemoteJob.fromJson({
      'job_id': 'd1',
      'status': 'done',
      'title': 'Pronto',
      'download_token': 'TOK',
      'expires_at':
          DateTime.now().add(const Duration(hours: 20)).millisecondsSinceEpoch /
              1000,
      'formats': const {'m4b': true, 'abm': true},
    });

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('senza server configurato: CTA impostazioni', (tester) async {
    await tester.pumpWidget(_wrap(const ActivityScreen()));
    await tester.pumpAndSettle();
    expect(find.textContaining('Configura'), findsOneWidget);
  });

  testWidgets('lista: sezioni in lavorazione e pronti, bottoni formato',
      (tester) async {
    await tester.pumpWidget(_wrap(const ActivityScreen(), overrides: [
      remoteJobsProvider.overrideWith((ref) => Stream.value([_gen(), _done()])),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('In lavorazione'), findsOneWidget);
    expect(find.text('Pronti da scaricare'), findsOneWidget);
    expect(find.text('In corso'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.text('Scarica M4B'), findsOneWidget);
    expect(find.text('Scarica ABM'), findsOneWidget);
  });
}
```

Run → FAIL (screen inesistente).

- [ ] **Step 3: ActivityScreen** — `lib/app/screens/activity_screen.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/remote_job.dart';
import '../../l10n/app_localizations.dart';
import '../providers.dart';

class ActivityScreen extends ConsumerStatefulWidget {
  const ActivityScreen({super.key});
  @override
  ConsumerState<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends ConsumerState<ActivityScreen> {
  final _downloading = <String>{};

  Future<void> _download(RemoteJob job, String fmt) async {
    final key = '${job.jobId}:$fmt';
    if (_downloading.contains(key)) return;
    setState(() => _downloading.add(key));
    final t = AppLocalizations.of(context)!;
    try {
      final svc = await ref.read(downloadServiceProvider.future);
      final settings = await ref.read(settingsProvider.future);
      final folder = settings.folderPath;
      if (svc == null || folder == null) return;
      final path = await svc.downloadJob(job, fmt, folder);
      final repo = ref.read(libraryRepositoryProvider);
      await repo.scanFolder(folder);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(t.activityDownloaded(
                path.split(RegExp(r'[\\/]')).last))));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(t.activityDownloadError)));
      }
    } finally {
      if (mounted) setState(() => _downloading.remove(key));
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context)!;
    final settings = ref.watch(settingsProvider).valueOrNull;
    if (settings != null && settings.serverUrl == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(t.activityServerMissing, textAlign: TextAlign.center),
        ),
      );
    }
    final jobsAsync = ref.watch(remoteJobsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(t.tabActivity)),
      body: jobsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(t.activityLoadError),
              const SizedBox(height: 12),
              FilledButton(
                  onPressed: () => ref.invalidate(remoteJobsProvider),
                  child: Text(t.retry)),
            ],
          ),
        ),
        data: (jobs) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(remoteJobsProvider),
          child: _JobsList(
              jobs: jobs,
              downloading: _downloading,
              onDownload: _download),
        ),
      ),
    );
  }
}

class _JobsList extends StatelessWidget {
  final List<RemoteJob> jobs;
  final Set<String> downloading;
  final void Function(RemoteJob, String) onDownload;
  const _JobsList(
      {required this.jobs,
      required this.downloading,
      required this.onDownload});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context)!;
    final active = jobs.where((j) => j.isActive).toList();
    final done = jobs.where((j) => j.isDone).toList();
    final failed = jobs.where((j) => j.isFailed).toList();
    if (jobs.isEmpty) {
      return ListView(children: [
        Padding(
            padding: const EdgeInsets.all(32),
            child: Text(t.activityEmpty, textAlign: TextAlign.center)),
      ]);
    }
    return ListView(children: [
      if (active.isNotEmpty) _section(context, t.activityInProgress),
      for (final j in active) _ActiveTile(job: j),
      if (done.isNotEmpty) _section(context, t.activityCompleted),
      for (final j in done)
        _DoneTile(job: j, downloading: downloading, onDownload: onDownload),
      if (failed.isNotEmpty) _section(context, t.activityFailed),
      for (final j in failed)
        ListTile(
            leading: const Icon(Icons.error_outline),
            title: Text(j.title.isNotEmpty ? j.title : j.jobId)),
    ]);
  }

  Widget _section(BuildContext context, String label) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
        child: Text(label, style: Theme.of(context).textTheme.titleSmall),
      );
}

class _ActiveTile extends StatelessWidget {
  final RemoteJob job;
  const _ActiveTile({required this.job});

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: const Icon(Icons.autorenew),
      title: Text(job.title.isNotEmpty ? job.title : job.jobId,
          maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (job.progressMessage.isNotEmpty)
            Text(job.progressMessage,
                maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 4),
          LinearProgressIndicator(value: job.progressFraction),
        ],
      ),
    );
  }
}

class _DoneTile extends StatelessWidget {
  final RemoteJob job;
  final Set<String> downloading;
  final void Function(RemoteJob, String) onDownload;
  const _DoneTile(
      {required this.job,
      required this.downloading,
      required this.onDownload});

  String _expiresLabel(BuildContext context, DateTime when) {
    final left = when.difference(DateTime.now());
    if (left.isNegative) return '—';
    if (left.inHours >= 1) return '${left.inHours}h';
    return '${left.inMinutes}m';
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context)!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ListTile(
          leading: const Icon(Icons.check_circle_outline),
          title: Text(job.title.isNotEmpty ? job.title : job.jobId,
              maxLines: 1, overflow: TextOverflow.ellipsis),
          subtitle: job.expiresAt != null
              ? Text(t.activityExpires(_expiresLabel(context, job.expiresAt!)))
              : null,
        ),
        Padding(
          padding: const EdgeInsets.only(left: 72, right: 16, bottom: 8),
          child: Wrap(
            spacing: 8,
            children: [
              for (final fmt in job.formats)
                downloading.contains('${job.jobId}:$fmt')
                    ? const SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : OutlinedButton.icon(
                        icon: const Icon(Icons.download, size: 18),
                        label:
                            Text(t.activityDownloadFmt(fmt.toUpperCase())),
                        onPressed: () => onDownload(job, fmt),
                      ),
            ],
          ),
        ),
      ],
    );
  }
}
```

- [ ] **Step 4: shell + impostazioni**

`lib/app/shell.dart`: sostituire `ComingSoonScreen(title: t.tabActivity)` con `const ActivityScreen()` (import). La tab Crea resta ComingSoon (Piano 3b).

`lib/app/screens/settings_screen.dart`: aggiungere (dopo la tile cartella) una tile Server che apre un dialog con TextField precompilato (`settings.serverUrl ?? ''`), hint `t.settingsServerHint`, bottoni annulla/`t.save` → `settings.setServerUrl(testo)`:

```dart
          ListTile(
            leading: const Icon(Icons.cloud_outlined),
            title: Text(t.settingsServer),
            subtitle: Text(settings.serverUrl ?? '—'),
            onTap: () async {
              final ctrl =
                  TextEditingController(text: settings.serverUrl ?? '');
              final ok = await showDialog<bool>(
                context: context,
                builder: (ctx) => AlertDialog(
                  title: Text(t.settingsServer),
                  content: TextField(
                    controller: ctrl,
                    keyboardType: TextInputType.url,
                    decoration:
                        InputDecoration(hintText: t.settingsServerHint),
                  ),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(ctx, false),
                        child: Text(MaterialLocalizations.of(ctx)
                            .cancelButtonLabel)),
                    FilledButton(
                        onPressed: () => Navigator.pop(ctx, true),
                        child: Text(t.save)),
                  ],
                ),
              );
              if (ok == true) await settings.setServerUrl(ctrl.text);
            },
          ),
```

- [ ] **Step 5: run + commit**

Run: `flutter gen-l10n`; `C:\flutter\bin\flutter.bat test` → tutti PASS (incl. 2 widget activity); `analyze` pulito.

```powershell
git add lib/app lib/l10n test/widget/activity_screen_test.dart
git commit -m "feat(ui): tab Attivita con polling, download in libreria, server configurabile"
```

---

### Task 6: FCM (degradabile senza Firebase)

⚠️ **Prerequisito manuale UTENTE**: progetto Firebase + `flutterfire configure` (genera `lib/firebase_options.dart`, `android/app/google-services.json`). Se il prerequisito NON è ancora soddisfatto, implementare comunque: il codice compila e degrada (niente init Firebase → niente push), e `flutterfire configure` attiverà tutto senza cambi di codice. iOS/APNs: fase successiva su CI/Mac.

**Files:**
- Create: `lib/core/push/push_setup.dart`
- Modify: `pubspec.yaml`, `lib/main.dart`, `lib/app/shell.dart` (tap notifica → tab Attività)
- Test: nessun test host (firebase_messaging non gira su host); verifica = analyze + compilazione + degradazione senza config.

- [ ] **Step 1: dipendenze**

`pubspec.yaml`: `firebase_core: ^3.6.0`, `firebase_messaging: ^15.1.0` (floor 2026-06: alza se pub get chiede). `flutter pub get`. In `android/build.gradle`/`settings.gradle` la toolchain google-services si aggiunge SOLO quando l'utente esegue flutterfire configure — NON aggiungerla ora a mano (senza google-services.json la build fallirebbe).

- [ ] **Step 2: push_setup** — `lib/core/push/push_setup.dart`:

```dart
import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import '../api/abm_api_client.dart';

/// Inizializzazione push best-effort. Senza config Firebase (file
/// firebase_options/google-services assenti) ogni passo fallisce in modo
/// silenzioso e l'app funziona senza push.
class PushSetup {
  /// Callback invocata quando arriva una notifica col job_id (foreground o tap).
  static void Function(String jobId, String event)? onJobEvent;

  static Future<void> init({
    required Future<AbmApiClient?> Function() clientFactory,
    required String appVersion,
  }) async {
    try {
      await Firebase.initializeApp();
    } catch (e) {
      debugPrint('[push] Firebase non configurato, push disattive: $e');
      return;
    }
    try {
      final messaging = FirebaseMessaging.instance;
      await messaging.requestPermission();
      final token = await messaging.getToken();
      if (token != null) {
        await _register(clientFactory, token, appVersion);
      }
      messaging.onTokenRefresh
          .listen((t) => _register(clientFactory, t, appVersion));
      FirebaseMessaging.onMessage.listen(_dispatch);
      FirebaseMessaging.onMessageOpenedApp.listen(_dispatch);
      final initial = await messaging.getInitialMessage();
      if (initial != null) _dispatch(initial);
    } catch (e) {
      debugPrint('[push] init FCM fallita (non fatale): $e');
    }
  }

  static Future<void> _register(
      Future<AbmApiClient?> Function() clientFactory,
      String token,
      String appVersion) async {
    try {
      final client = await clientFactory();
      if (client == null) return; // server non configurato: riproverà al refresh
      await client.registerDevice(
          fcmToken: token,
          platform: Platform.isIOS ? 'ios' : 'android',
          appVersion: appVersion);
    } catch (e) {
      debugPrint('[push] register device fallita (non fatale): $e');
    }
  }

  static void _dispatch(RemoteMessage msg) {
    final jobId = msg.data['job_id'];
    final event = msg.data['event'];
    if (jobId is String && event is String) {
      onJobEvent?.call(jobId, event);
    }
  }
}
```

- [ ] **Step 3: wiring in main.dart e shell**

`lib/main.dart`, dopo il runApp setup esistente (PRIMA di runApp, dopo aver creato settings/db):

```dart
  // push best-effort: senza Firebase configurato è un no-op
  unawaited(PushSetup.init(
    clientFactory: () async {
      final url = settings.serverUrl;
      if (url == null) return null;
      final cid = await ClientIdentity.obtain();
      return AbmApiClient.forServer(url, cid);
    },
    appVersion: '1.0.0',
  ));
```

(import `dart:async` per unawaited + gli altri; la versione hardcoded '1.0.0' è accettabile per l'MVP — nota: allineala a pubspec quando si introdurrà package_info, YAGNI ora).

`lib/app/shell.dart`: in `initState` dello stato esistente, registrare il listener che porta alla tab Attività e aggiorna i job:

```dart
  @override
  void initState() {
    super.initState();
    PushSetup.onJobEvent = (jobId, event) {
      if (!mounted) return;
      setState(() => _tab = 2); // tab Attività
      ref.invalidate(remoteJobsProvider);
    };
  }

  @override
  void dispose() {
    PushSetup.onJobEvent = null;
    super.dispose();
  }
```

- [ ] **Step 4: verifica + commit**

Run: `C:\flutter\bin\flutter.bat analyze` → No issues; `flutter test` → tutti verdi (firebase non inizializzato nei test: nessun test lo tocca).

```powershell
git add pubspec.yaml pubspec.lock lib/core/push lib/main.dart lib/app/shell.dart
git commit -m "feat(push): FCM best-effort (degrada senza Firebase) + tap verso Attivita"
```

---

### Task 7: Chiusura

- [ ] **Step 1: qualità**

`C:\flutter\bin\dart.bat format .` → `flutter analyze` (No issues) → `flutter test` (tutti PASS, riporta il numero).

- [ ] **Step 2: smoke build APK**

`C:\flutter\bin\flutter.bat build apk --debug` → deve riuscire ANCHE senza Firebase configurato (se fallisse per i plugin firebase senza google-services, vuol dire che è stata aggiunta per errore la toolchain google-services: rimuovila — vedi Task 6 Step 1).

- [ ] **Step 3: README**

Sezione `## Stato`: aggiungere in testa:

```markdown
Fase 3a completata: l'app è collegata al backend — tab Attività con i lavori
del server (polling), download di m4b/mp3/zip/abm direttamente nella cartella
libreria, indirizzo server configurabile nelle impostazioni, notifiche push
FCM pronte (si attivano con `flutterfire configure`; senza Firebase l'app
funziona senza push). Manca: wizard Crea in-app (fase 3b).
```

E aggiungere alla checklist device:

```markdown
- [ ] con backend locale raggiungibile: job creato dal sito appare in Attività
- [ ] download m4b da Attività → libro appare in Libreria e si apre nel player
- [ ] countdown scadenza visibile sui job completati
- [ ] (post flutterfire configure) push al completamento con app chiusa
```

- [ ] **Step 4: commit finale**

```powershell
git add -A
git commit -m "chore(3a): format, README aggiornato"
```

NON fare push (il remoto esiste: serve conferma esplicita dell'utente).

---

## Note per l'esecutore

- **Contratti backend**: i JSON di `my_jobs` e gli endpoint `/dl/<token>/*` sono quelli implementati sul branch `abm_mobile` del repo AudioBook-Maker (vedi `docs/superpowers/plans/2026-06-12-mobile-backend-api.md` per i campi esatti). In caso di dubbio sul contratto, leggere `api_my_jobs` in `audiobook_app.py` di quel branch — non inventare campi.
- **Niente segreti nel repo**: `google-services.json` e `firebase_options.dart` quando arriveranno NON vanno committati se contengono chiavi che l'utente considera private (default Firebase: committabili, ma decide l'utente — aggiungere intanto entrambi a .gitignore con commento).
- **Versioni pub**: floor al 2026-06, alzare se serve annotando.
- **OneDrive**: lock noto su ios\Flutter\ephemeral.
- **Stringhe**: mai nominare provider AI/TTS nella UI.
