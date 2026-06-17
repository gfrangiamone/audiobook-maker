# App Flutter — Piano 3b-1: Wizard Crea (percorso gratuito) (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creazione di un audiolibro interamente dall'app, percorso gratuito: scegli file → analisi → seleziona capitoli → scegli voce standard (con anteprima) e formato → avvia → il job compare in Attività, si scarica nella libreria. Nessun pagamento, nessuna ottimizzazione AI (quelli sono il 3b-2).

**Architecture:** Una piccola estensione backend (flag `batch_mode` su `/api/generate`) marca il job come batch — niente auto-cancel a schermo bloccato e creazione del download token al COMPLETE anche senza email — riusando l'infrastruttura Attività/my_jobs del Piano 3a. Lato app, `AbmApiClient` cresce con `analyze`/`voices`/`generate`; un `CreateWizardController` (Riverpod) tiene lo stato dei 4 passi; le schermate del wizard sostituiscono il placeholder della tab Crea. L'anteprima voce usa un `AudioPlayer` dedicato (non il player della libreria).

**Tech Stack:** Flutter/Riverpod/dio/just_audio (già presenti); pytest lato backend.

**Due repository:**
- **Backend** (Task 1): `C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker\.claude\worktrees\abm_mobile` (branch `abm_mobile`, Flask). Test con `python -m pytest test/ ...`. Shell PowerShell, comandi singoli senza `&&`.
- **App** (Task 2-6): `C:\Users\gfran\NEXT srl\Progetti - Documenti\audiobook-maker-mobile` (branch main). Flutter `C:\flutter\bin\flutter.bat`. Caveat OneDrive: lock su `ios\Flutter\ephemeral` → normalizza attributi e cancella la dir.

**Spec:** `docs/superpowers/specs/2026-06-11-mobile-app-design.md` (sezione wizard). **Contratti backend** (campi esatti): vedi `audiobook_app.py` del branch abm_mobile — `/api/analyze` (multipart campo `epub`), `/api/voices`, `GET /api/preview_audio/<job_id>?voice=&rate=`, `POST /api/generate`, `GET /api/my_jobs`. I nomi dei campi nel piano sono quelli reali rilevati il 2026-06-15.

**Decisioni di piano:**
- **Solo voci standard (engine `edge`) nel 3b-1**: sono gratuite e senza budget. Google (Chirp3-HD) e PREMIUM (Gemini) arrivano nel 3b-2 col pagamento voucher. La UI del wizard filtra `engine == 'edge'`.
- **`zip_rss` escluso** (come da spec mobile): formati offerti m4b (default), mp3, zip.
- **Nessun SSE nel 3b-1**: il progress si vede nella tab Attività (polling 5s del Piano 3a). Dopo l'avvio il wizard porta l'utente in Attività. L'SSE fine arriverà solo se servirà (3b-2).
- **Email opzionale**: con `batch_mode` il job sopravvive e genera token senza email; la push è il segnale primario. Un campo email facoltativo per la notifica via mail si valuterà nel 3b-2.

## Mappa dei file

**Backend (Task 1):**
```
audiobook_app.py        # MODIFICA: batch_mode in /api/generate; token al COMPLETE senza email
generation_engine.py    # MODIFICA: _create_download_token() estratta; chiamata al COMPLETE per job batch senza notify_email
test/test_mobile_api.py # MODIFICA: +test batch_mode (no auto-cancel marker, token creato)
```

**App (Task 2-6):**
```
lib/core/api/
├── book_info.dart            # BookInfo + ChapterSummary (risposta /api/analyze)
├── voice.dart                # Voice + parse di /api/voices (gruppi per lingua, filtro edge)
└── abm_api_client.dart       # MODIFICA: analyze(file), voices(), generate(...), previewUrl(...)
lib/core/player/
└── preview_player.dart       # AudioPlayer dedicato all'anteprima voce
lib/app/
├── create/
│   ├── wizard_controller.dart # stato wizard (Riverpod StateNotifier)
│   ├── create_wizard.dart     # shell del wizard (stepper) + dispatch step
│   └── steps/
│       ├── source_step.dart   # scelta file + upload/analisi
│       ├── chapters_step.dart # selezione capitoli
│       └── voice_format_step.dart # voce (con preview) + formato + avvia
├── providers.dart            # MODIFICA: +wizard providers, +voicesProvider
└── shell.dart                # MODIFICA: tab Crea → CreateWizard
lib/l10n/app_*.arb            # MODIFICA: chiavi wizard (7 lingue)
test/
├── voice_test.dart
├── book_info_test.dart
├── abm_api_client_test.dart  # MODIFICA: +analyze/voices/generate
├── wizard_controller_test.dart
└── widget/create_wizard_test.dart
```

---

### Task 1 — Backend: flag `batch_mode` su /api/generate

Repo: **AudioBook-Maker** worktree `abm_mobile`. Obiettivo: un job avviato con `batch_mode: true` (a) non viene auto-cancellato per heartbeat, (b) crea un download token al COMPLETE anche senza `notify_email`. La push e `my_jobs` (Piano 1) già funzionano col token.

**Files:**
- Modify: `generation_engine.py` (estrai creazione token; chiama al COMPLETE per batch senza email)
- Modify: `audiobook_app.py` (`api_generate`: leggi `batch_mode`)
- Test: `test/test_mobile_api.py`

- [ ] **Step 1: capire i siti reali**

Run (PowerShell): `Select-String -Path generation_engine.py -Pattern "_download_tokens\[token\] = \{"` → individua il blocco di creazione token in `_send_completion_email` (~riga 1322-1390). Run: `Select-String -Path audiobook_app.py -Pattern "def api_generate"` e `Select-String -Path generation_engine.py -Pattern "post-COMPLETE|notify_email"`. Annota le righe reali: i numeri sotto sono indicativi (2026-06-15), usa quelli veri.

- [ ] **Step 2: test che falliscono** — append a `test/test_mobile_api.py`:

```python
# ---------------------------------------------------------------- Task 3b1: batch_mode

def test_generate_batch_mode_sets_email_registered(monkeypatch, tmp_path):
    """batch_mode=true marca il job email_registered (no auto-cancel) senza email."""
    import audiobook_app
    job_id = "bm-job-1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {
            "status": "analyzed",
            "client_id": "mobile-cid-12345",
            "info": None,
            "epub_path": str(tmp_path / "x.epub"),
            "last_poll": __import__("time").time(),
        }
    # neutralizza l'avvio reale del thread di generazione
    monkeypatch.setattr(audiobook_app, "run_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    client = audiobook_app.app.test_client()
    try:
        r = client.post("/api/generate",
                        headers={"X-ABM-Cid": "mobile-cid-12345"},
                        json={"job_id": job_id, "voice": "it-IT-IsabellaNeural",
                              "output_format": "m4b", "batch_mode": True})
        assert r.status_code == 200
        assert audiobook_app.jobs[job_id].get("email_registered") is True
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(job_id, None)


def test_create_download_token_without_email(monkeypatch, tmp_path):
    """_create_download_token crea un record token con client_id senza inviare email."""
    import generation_engine as ge
    job_id = "bm-job-2"
    out = tmp_path / "out.m4b"
    out.write_bytes(b"x")
    ge._jobs[job_id] = {
        "status": "done",
        "client_id": "mobile-cid-12345",
        "output_m4b": str(out),
        "output_format": "m4b",
        "info": None,
        "original_filename": "x.epub",
    }
    try:
        token = ge._create_download_token(job_id)
        assert token is not None
        rec = ge._download_tokens[token]
        assert rec["job_id"] == job_id
        assert rec["client_id"] == "mobile-cid-12345"
        assert bool(rec.get("output_m4b"))
    finally:
        ge._jobs.pop(job_id, None)
        for t in list(ge._download_tokens):
            if ge._download_tokens[t].get("job_id") == job_id:
                ge._download_tokens.pop(t, None)
```

Nota esecutore: adatta il seed del job ai campi minimi richiesti dai path reali (leggi `api_generate` e il blocco COMPLETE prima di eseguire). Se `run_generation` è importato in `audiobook_app` con altro nome, monkeypatcha quello giusto. Il criterio dei test resta invariato.

- [ ] **Step 3: eseguire e verificare il fallimento**

Run: `python -m pytest test/test_mobile_api.py -k "batch_mode or download_token_without_email" -v --tb=short`
Expected: FAIL (`batch_mode` ignorato; `_create_download_token` inesistente).

- [ ] **Step 4: estrarre `_create_download_token` in generation_engine.py**

Nel blocco di `_send_completion_email` che oggi costruisce `_download_tokens[token] = {...}` (grep), estrai la costruzione del record in una funzione riusabile. Aggiungi accanto a `_send_completion_email`:

```python
def _create_download_token(job_id):
    """Crea (idempotente) un download token per un job completato e lo persiste,
    SENZA inviare email. Ritorna il token, o None se il job non è valido.
    Usato dai job batch mobile (push + my_jobs) che non hanno notify_email."""
    job = _jobs.get(job_id)
    if not job:
        return None
    # se esiste già un token per questo job, riusalo
    for tok, info in _download_tokens.items():
        if isinstance(info, dict) and info.get("job_id") == job_id:
            return tok
    info = job.get("info")
    import uuid as _uuid
    token = _uuid.uuid4().hex
    _download_tokens[token] = {
        "job_id": job_id,
        "created_at": __import__("time").time(),
        "client_id": job.get("client_id", ""),
        "book_title": getattr(info, "title", "") or job.get("original_filename", ""),
        "output_format": job.get("output_format", ""),
        "output_zip": job.get("output_zip", ""),
        "output_name": job.get("output_name", ""),
        "output_file": (job.get("output_files", [""]) or [""])[0],
        "output_m4b": job.get("output_m4b", ""),
        "output_m4b_fallback_zip": job.get("output_m4b_fallback_zip", ""),
        "optimized_abm_path": job.get("optimized_abm_path", ""),
        "optimized_abm_name": job.get("optimized_abm_name", ""),
        "is_gemini": _is_gemini_voice(job.get("voice", "") or job.get("opt_voice", "")),
    }
    _save_tokens()
    return token
```

IMPORTANTE: allinea i CAMPI del dict a quelli realmente scritti dal token di `_send_completion_email` esistente (leggi il blocco reale e copia gli stessi campi, inclusa la chiave `client_id` aggiunta dal Piano 1). Se `_is_gemini_voice` ha un nome diverso, usa quello reale. Poi REFATTORA `_send_completion_email` perché, dove creava il token inline, chiami invece `token = _create_download_token(job_id)` e prosegua con l'email usando quel token (evita duplicazione: un solo punto di costruzione del record).

- [ ] **Step 5: agganciare al COMPLETE per i job batch senza email**

Nel post-COMPLETE di `run_generation` (grep `post-COMPLETE` / `if notify_email`), dove oggi c'è il ramo `else` "no notify_email", crea comunque il token per i job batch:

```python
    if notify_email:
        _send_completion_email(job_id)
    elif job.get("email_registered"):
        # job batch mobile senza email: crea solo il token (push + my_jobs)
        try:
            _create_download_token(job_id)
        except Exception as _tok_err:
            print(f"[{job_id}] batch token creation failed (non-fatal): {_tok_err}")
```

(la push è già emessa prima/indipendentemente — non toccarla).

- [ ] **Step 6: leggere `batch_mode` in api_generate**

In `audiobook_app.py`, `api_generate`, DOPO il claim atomico `job["status"] = "generating"` e prima dello spawn del thread (grep), aggiungi:

```python
        if data.get("batch_mode"):
            job["email_registered"] = True
            job.setdefault("notify_download_type", "audio")
```

Questo basta a disabilitare l'auto-cancel (la guardia heartbeat salta se `email_registered`) e a far creare il token al COMPLETE (Step 5). Non serve SMTP né email.

- [ ] **Step 7: eseguire i test e verificare**

Run: `python -m pytest test/test_mobile_api.py -k "batch_mode or download_token_without_email" -v --tb=short` → PASS.
Run: `python -m py_compile audiobook_app.py generation_engine.py`
Run: `python -m pytest test/ -q --tb=line` → nessun nuovo fallimento oltre alla baseline nota (i 4 `test_paypal_create_gemini` da pollution reload).

- [ ] **Step 8: commit (worktree abm_mobile)**

```powershell
git add generation_engine.py audiobook_app.py test/test_mobile_api.py
git commit -m "feat(mobile): batch_mode su /api/generate (token al COMPLETE senza email)"
```

(footer: riga vuota + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`, here-string `@'...'@`. NON pushare.)

Nota: aggiorna anche il piano backend di riferimento mentalmente — questo estende il Piano 1; il deploy dovrà includerlo.

---

### Task 2 — App: modelli BookInfo/Voice + estensione AbmApiClient

Repo: **audiobook-maker-mobile**.

**Files:**
- Create: `lib/core/api/book_info.dart`, `lib/core/api/voice.dart`
- Modify: `lib/core/api/abm_api_client.dart`
- Test: `test/book_info_test.dart`, `test/voice_test.dart`, `test/abm_api_client_test.dart` (append)

- [ ] **Step 1: test modelli (failing)** — `test/book_info_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/api/book_info.dart';

void main() {
  test('parse analyze response', () {
    final b = BookInfo.fromJson(const {
      'job_id': 'j1',
      'title': 'Il nome della rosa',
      'author': 'Umberto Eco',
      'language': 'it',
      'total_chapters': 2,
      'estimated_minutes': 520.0,
      'preview_text': 'In principio...',
      'chapters': [
        {'index': 0, 'title': 'Prologo', 'chars': 1200, 'estimated_minutes': 8.0},
        {'index': 1, 'title': 'Primo giorno', 'chars': 5000, 'estimated_minutes': 33.0},
      ],
    });
    expect(b.jobId, 'j1');
    expect(b.title, 'Il nome della rosa');
    expect(b.language, 'it');
    expect(b.chapters, hasLength(2));
    expect(b.chapters[1].title, 'Primo giorno');
    expect(b.chapters[1].index, 1);
  });

  test('tollerante a campi mancanti', () {
    final b = BookInfo.fromJson(const {'job_id': 'x'});
    expect(b.title, '');
    expect(b.chapters, isEmpty);
  });
}
```

`test/voice_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/api/voice.dart';

void main() {
  const json = {
    'it': {
      'name': 'Italian',
      'voices': [
        {'id': 'it-IT-IsabellaNeural', 'name': 'Isabella', 'gender': 'Female',
         'locale': 'it-IT', 'engine': 'edge'},
        {'id': 'it-IT-Chirp', 'name': 'Chirp', 'gender': 'Male',
         'locale': 'it-IT', 'engine': 'google'},
      ],
    },
    'en': {
      'name': 'English',
      'voices': [
        {'id': 'en-US-Ava', 'name': 'Ava', 'gender': 'Female',
         'locale': 'en-US', 'engine': 'edge'},
      ],
    },
    '_premium_status': {'capability_ok': true, 'admin_disabled': false},
  };

  test('parse gruppi e filtro edge', () {
    final groups = VoiceCatalog.fromJson(json).edgeGroups();
    expect(groups.map((g) => g.languageCode), containsAll(['it', 'en']));
    final it = groups.firstWhere((g) => g.languageCode == 'it');
    // solo la voce edge, non la google
    expect(it.voices, hasLength(1));
    expect(it.voices.first.id, 'it-IT-IsabellaNeural');
    expect(it.voices.first.engine, 'edge');
  });

  test('ignora chiavi che iniziano con underscore', () {
    final groups = VoiceCatalog.fromJson(json).edgeGroups();
    expect(groups.any((g) => g.languageCode.startsWith('_')), isFalse);
  });
}
```

Run → FAIL.

- [ ] **Step 2: implementare i modelli**

`lib/core/api/book_info.dart`:

```dart
import 'package:flutter/foundation.dart';

@immutable
class ChapterSummary {
  final int index;
  final String title;
  final int chars;
  final double estimatedMinutes;
  const ChapterSummary(
      {required this.index,
      required this.title,
      required this.chars,
      required this.estimatedMinutes});

  factory ChapterSummary.fromJson(Map<String, dynamic> j) => ChapterSummary(
        index: j['index'] is num ? (j['index'] as num).toInt() : 0,
        title: (j['title'] ?? '').toString(),
        chars: j['chars'] is num ? (j['chars'] as num).toInt() : 0,
        estimatedMinutes:
            j['estimated_minutes'] is num ? (j['estimated_minutes'] as num).toDouble() : 0,
      );
}

@immutable
class BookInfo {
  final String jobId;
  final String title;
  final String author;
  final String language;
  final int totalChapters;
  final double estimatedMinutes;
  final String previewText;
  final List<ChapterSummary> chapters;
  const BookInfo(
      {required this.jobId,
      required this.title,
      required this.author,
      required this.language,
      required this.totalChapters,
      required this.estimatedMinutes,
      required this.previewText,
      required this.chapters});

  factory BookInfo.fromJson(Map<String, dynamic> j) {
    final ch = <ChapterSummary>[];
    final raw = j['chapters'];
    if (raw is List) {
      for (final c in raw) {
        if (c is Map<String, dynamic>) ch.add(ChapterSummary.fromJson(c));
      }
    }
    return BookInfo(
      jobId: (j['job_id'] ?? '').toString(),
      title: (j['title'] ?? '').toString(),
      author: (j['author'] ?? '').toString(),
      language: (j['language'] ?? '').toString(),
      totalChapters:
          j['total_chapters'] is num ? (j['total_chapters'] as num).toInt() : ch.length,
      estimatedMinutes:
          j['estimated_minutes'] is num ? (j['estimated_minutes'] as num).toDouble() : 0,
      previewText: (j['preview_text'] ?? '').toString(),
      chapters: ch,
    );
  }
}
```

`lib/core/api/voice.dart`:

```dart
import 'package:flutter/foundation.dart';

@immutable
class Voice {
  final String id;
  final String name;
  final String gender;
  final String locale;
  final String engine; // edge | google | gemini
  const Voice(
      {required this.id,
      required this.name,
      required this.gender,
      required this.locale,
      required this.engine});

  factory Voice.fromJson(Map<String, dynamic> j) => Voice(
        id: (j['id'] ?? '').toString(),
        name: (j['name'] ?? '').toString(),
        gender: (j['gender'] ?? '').toString(),
        locale: (j['locale'] ?? '').toString(),
        engine: (j['engine'] ?? 'edge').toString(),
      );
}

@immutable
class VoiceGroup {
  final String languageCode; // es. 'it'
  final String languageName; // es. 'Italian'
  final List<Voice> voices;
  const VoiceGroup(
      {required this.languageCode,
      required this.languageName,
      required this.voices});
}

/// Catalogo voci da /api/voices. Le chiavi che iniziano con '_' sono metadati
/// (es. _premium_status, _google_tts) e non sono lingue.
class VoiceCatalog {
  final Map<String, dynamic> _raw;
  VoiceCatalog(this._raw);
  factory VoiceCatalog.fromJson(Map<String, dynamic> j) => VoiceCatalog(j);

  List<VoiceGroup> _groups(bool Function(Voice) keep) {
    final out = <VoiceGroup>[];
    for (final entry in _raw.entries) {
      if (entry.key.startsWith('_')) continue;
      final v = entry.value;
      if (v is! Map) continue;
      final rawVoices = v['voices'];
      if (rawVoices is! List) continue;
      final voices = <Voice>[];
      for (final rv in rawVoices) {
        if (rv is Map<String, dynamic>) {
          final voice = Voice.fromJson(rv);
          if (keep(voice)) voices.add(voice);
        }
      }
      if (voices.isNotEmpty) {
        out.add(VoiceGroup(
          languageCode: entry.key,
          languageName: (v['name'] ?? entry.key).toString(),
          voices: voices,
        ));
      }
    }
    out.sort((a, b) => a.languageName.compareTo(b.languageName));
    return out;
  }

  /// Solo voci standard gratuite (Microsoft Edge). Google/Gemini → 3b-2.
  List<VoiceGroup> edgeGroups() => _groups((v) => v.engine == 'edge');
}
```

Run i due test modello → PASS.

- [ ] **Step 3: test client (failing)** — append a `test/abm_api_client_test.dart`:

```dart
  test('voices: parse catalogo', () async {
    adapter.onGet('/api/voices', (s) => s.reply(200, {
          'it': {'name': 'Italian', 'voices': [
            {'id': 'it-IT-IsabellaNeural', 'name': 'Isabella',
             'gender': 'Female', 'locale': 'it-IT', 'engine': 'edge'}
          ]},
        }));
    final cat = await client.voices();
    expect(cat.edgeGroups().first.voices.first.id, 'it-IT-IsabellaNeural');
  });

  test('generate: body con batch_mode e parse status', () async {
    adapter.onPost(
      '/api/generate',
      (s) => s.reply(200, {'status': 'started'}),
      data: {
        'job_id': 'j1',
        'voice': 'it-IT-IsabellaNeural',
        'output_format': 'm4b',
        'rate': '+0%',
        'selected_chapters': [0, 1],
        'batch_mode': true,
      },
    );
    final status = await client.generate(
        jobId: 'j1',
        voice: 'it-IT-IsabellaNeural',
        outputFormat: 'm4b',
        selectedChapters: const [0, 1]);
    expect(status, 'started');
  });

  test('generate: 402 payment_required → ApiException', () async {
    adapter.onPost('/api/generate',
        (s) => s.reply(402, {'error': 'payment_required'}));
    expect(
        () => client.generate(
            jobId: 'j1', voice: 'gemini:x', outputFormat: 'm4b',
            selectedChapters: const []),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 's', 402)));
  });

  test('previewUrl costruisce query con voice e rate', () {
    final url = client.previewUrl('j1', 'it-IT-IsabellaNeural', rate: '+0%');
    expect(url, contains('/api/preview_audio/j1'));
    expect(url, contains('voice=it-IT-IsabellaNeural'));
    expect(url, contains('rate=%2B0%25')); // +0% url-encoded
  });
```

- [ ] **Step 4: estendere AbmApiClient** — aggiungi a `lib/core/api/abm_api_client.dart` (import di `book_info.dart`, `voice.dart`, e `dart:io` per File):

```dart
  Future<BookInfo> analyze(File file,
      {void Function(int sent, int total)? onProgress}) async {
    try {
      final form = FormData.fromMap({
        'epub': await MultipartFile.fromFile(file.path,
            filename: file.path.split(RegExp(r'[\\/]')).last),
      });
      final resp = await _dio.post<dynamic>('/api/analyze',
          data: form, onSendProgress: onProgress);
      final data = resp.data;
      if (data is Map<String, dynamic> && data['error'] != null) {
        throw ApiException(resp.statusCode, data['error'].toString());
      }
      return BookInfo.fromJson(data as Map<String, dynamic>);
    } on DioException catch (e) {
      throw ApiException(e.response?.statusCode, e.message ?? 'analyze');
    }
  }

  Future<VoiceCatalog> voices() async {
    final data = await _get('/api/voices');
    return VoiceCatalog.fromJson(
        data is Map<String, dynamic> ? data : <String, dynamic>{});
  }

  Future<String> generate({
    required String jobId,
    required String voice,
    required String outputFormat,
    required List<int> selectedChapters,
    String rate = '+0%',
    bool batchMode = true,
  }) async {
    final body = <String, dynamic>{
      'job_id': jobId,
      'voice': voice,
      'output_format': outputFormat,
      'rate': rate,
      'selected_chapters': selectedChapters,
      'batch_mode': batchMode,
    };
    final data = await _post('/api/generate', body);
    return (data is Map && data['status'] != null)
        ? data['status'].toString()
        : '';
  }

  /// URL assoluto dell'anteprima (il player la riproduce in streaming).
  String previewUrl(String jobId, String voice, {String rate = '+0%'}) {
    final base = _dio.options.baseUrl;
    final q = Uri(queryParameters: {'voice': voice, 'rate': rate}).query;
    return '$base/api/preview_audio/$jobId?$q';
  }
```

Nota: il test `generate batch_mode` si aspetta `batch_mode: true` di default → `batchMode = true`. Verifica che `_post`/`_get` esistano già (Task 2 del Piano 3a). `previewUrl` include l'header cid? No: è un URL per il player; il preview backend non richiede cid (è per-job, ownership via job — se il backend RICHIEDE il cid anche su preview, leggi `api_preview_audio` e, se serve, usa invece un download dio con header e salva un file temp da dare al player. Verifica prima di assumere).

- [ ] **Step 5: run + commit**

Run: `C:\flutter\bin\flutter.bat test` → tutti PASS. `analyze` pulito.

```powershell
git add lib/core/api test/book_info_test.dart test/voice_test.dart test/abm_api_client_test.dart
git commit -m "feat(api): analyze/voices/generate + modelli BookInfo e Voice"
```

---

### Task 3 — Wizard controller (stato dei 4 passi)

Repo: **audiobook-maker-mobile**.

**Files:**
- Create: `lib/app/create/wizard_controller.dart`
- Modify: `lib/app/providers.dart`
- Test: `test/wizard_controller_test.dart`

- [ ] **Step 1: test (failing)** — `test/wizard_controller_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/app/create/wizard_controller.dart';
import 'package:audiobook_maker_mobile/core/api/book_info.dart';

BookInfo _book() => BookInfo.fromJson(const {
      'job_id': 'j1',
      'title': 'T',
      'total_chapters': 3,
      'chapters': [
        {'index': 0, 'title': 'A', 'chars': 10},
        {'index': 1, 'title': 'B', 'chars': 10},
        {'index': 2, 'title': 'C', 'chars': 10},
      ],
    });

void main() {
  test('stato iniziale: step sorgente, niente libro', () {
    final s = WizardState.initial();
    expect(s.step, WizardStep.source);
    expect(s.book, isNull);
    expect(s.canProceed, isFalse);
  });

  test('setAnalyzed: passa a capitoli, tutti selezionati', () {
    final s = WizardState.initial().setAnalyzed(_book());
    expect(s.step, WizardStep.chapters);
    expect(s.book!.jobId, 'j1');
    expect(s.selectedChapters, {0, 1, 2});
    expect(s.canProceed, isTrue);
  });

  test('toggle capitolo e vincolo almeno uno', () {
    var s = WizardState.initial().setAnalyzed(_book());
    s = s.toggleChapter(1);
    expect(s.selectedChapters, {0, 2});
    s = s.toggleChapter(0).toggleChapter(2);
    expect(s.selectedChapters, isEmpty);
    expect(s.canProceed, isFalse); // serve almeno un capitolo
  });

  test('navigazione step avanti/indietro', () {
    var s = WizardState.initial().setAnalyzed(_book());
    s = s.goTo(WizardStep.voiceFormat);
    expect(s.step, WizardStep.voiceFormat);
    expect(s.voice, isNull);
    s = s.setVoice('it-IT-IsabellaNeural').setFormat('mp3');
    expect(s.voice, 'it-IT-IsabellaNeural');
    expect(s.format, 'mp3');
    expect(s.canSubmit, isTrue);
  });

  test('canSubmit falso senza voce o senza capitoli', () {
    var s = WizardState.initial().setAnalyzed(_book()).goTo(WizardStep.voiceFormat);
    expect(s.canSubmit, isFalse); // niente voce
    s = s.setVoice('v').toggleChapter(0).toggleChapter(1).toggleChapter(2);
    expect(s.canSubmit, isFalse); // niente capitoli
  });

  test('reset torna allo stato iniziale', () {
    final s = WizardState.initial().setAnalyzed(_book()).reset();
    expect(s.step, WizardStep.source);
    expect(s.book, isNull);
  });
}
```

Run → FAIL.

- [ ] **Step 2: implementare** — `lib/app/create/wizard_controller.dart`:

```dart
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/book_info.dart';

enum WizardStep { source, chapters, voiceFormat }

@immutable
class WizardState {
  final WizardStep step;
  final BookInfo? book;
  final Set<int> selectedChapters;
  final String? voice;
  final String format; // m4b | mp3 | zip
  final bool submitting;
  final String? error;

  const WizardState({
    required this.step,
    required this.book,
    required this.selectedChapters,
    required this.voice,
    required this.format,
    required this.submitting,
    required this.error,
  });

  factory WizardState.initial() => const WizardState(
        step: WizardStep.source,
        book: null,
        selectedChapters: {},
        voice: null,
        format: 'm4b',
        submitting: false,
        error: null,
      );

  bool get canProceed {
    switch (step) {
      case WizardStep.source:
        return book != null;
      case WizardStep.chapters:
        return selectedChapters.isNotEmpty;
      case WizardStep.voiceFormat:
        return canSubmit;
    }
  }

  bool get canSubmit =>
      book != null && voice != null && selectedChapters.isNotEmpty && !submitting;

  WizardState _copy({
    WizardStep? step,
    BookInfo? book,
    Set<int>? selectedChapters,
    String? voice,
    String? format,
    bool? submitting,
    String? error,
    bool clearError = false,
    bool clearVoice = false,
  }) =>
      WizardState(
        step: step ?? this.step,
        book: book ?? this.book,
        selectedChapters: selectedChapters ?? this.selectedChapters,
        voice: clearVoice ? null : (voice ?? this.voice),
        format: format ?? this.format,
        submitting: submitting ?? this.submitting,
        error: clearError ? null : (error ?? this.error),
      );

  WizardState setAnalyzed(BookInfo b) => _copy(
        step: WizardStep.chapters,
        book: b,
        selectedChapters: {for (final c in b.chapters) c.index},
        clearError: true,
      );

  WizardState toggleChapter(int index) {
    final next = {...selectedChapters};
    if (!next.remove(index)) next.add(index);
    return _copy(selectedChapters: next);
  }

  WizardState goTo(WizardStep s) => _copy(step: s, clearError: true);
  WizardState setVoice(String v) => _copy(voice: v);
  WizardState setFormat(String f) => _copy(format: f);
  WizardState setSubmitting(bool v) => _copy(submitting: v, clearError: true);
  WizardState setError(String e) => _copy(error: e, submitting: false);
  WizardState reset() => WizardState.initial();
}

class WizardController extends StateNotifier<WizardState> {
  WizardController() : super(WizardState.initial());

  void analyzed(BookInfo b) => state = state.setAnalyzed(b);
  void toggleChapter(int i) => state = state.toggleChapter(i);
  void goTo(WizardStep s) => state = state.goTo(s);
  void setVoice(String v) => state = state.setVoice(v);
  void setFormat(String f) => state = state.setFormat(f);
  void submitting(bool v) => state = state.setSubmitting(v);
  void error(String e) => state = state.setError(e);
  void reset() => state = state.reset();
}
```

In `lib/app/providers.dart` aggiungi:

```dart
final wizardControllerProvider =
    StateNotifierProvider<WizardController, WizardState>(
        (ref) => WizardController());

final voicesProvider = FutureProvider.autoDispose((ref) async {
  final client = await ref.watch(apiClientProvider.future);
  if (client == null) return null;
  return client.voices();
});
```

(import di wizard_controller.dart e voice.dart)

- [ ] **Step 3: run + commit**

Run: `C:\flutter\bin\flutter.bat test test/wizard_controller_test.dart` → 6 PASS; suite verde.

```powershell
git add lib/app/create/wizard_controller.dart lib/app/providers.dart test/wizard_controller_test.dart
git commit -m "feat(wizard): controller stato 4 passi (sorgente/capitoli/voce-formato)"
```

---

### Task 4 — Preview player (anteprima voce)

Repo: **audiobook-maker-mobile**. Un `AudioPlayer` dedicato per l'anteprima, separato dal player della libreria (audio_service).

**Files:**
- Create: `lib/core/player/preview_player.dart`
- Modify: `lib/app/providers.dart`
- Test: nessun test host (just_audio non gira su host). Verifica = analyze + uso nel Task 5.

- [ ] **Step 1: implementare** — `lib/core/player/preview_player.dart`:

```dart
import 'package:just_audio/just_audio.dart';

/// Player leggero per l'anteprima voce nel wizard. Indipendente dal player
/// della libreria (audio_service): non tocca la riproduzione in corso.
class PreviewPlayer {
  final _player = AudioPlayer();

  Stream<bool> get playingStream => _player.playingStream;
  bool get playing => _player.playing;

  /// Avvia (o riavvia) l'anteprima dall'URL. Ferma l'eventuale precedente.
  Future<void> play(String url) async {
    await _player.stop();
    await _player.setUrl(url);
    await _player.play();
  }

  Future<void> stop() => _player.stop();
  Future<void> dispose() => _player.dispose();
}
```

In `lib/app/providers.dart`:

```dart
final previewPlayerProvider = Provider.autoDispose<PreviewPlayer>((ref) {
  final p = PreviewPlayer();
  ref.onDispose(p.dispose);
  return p;
});
```

(import di preview_player.dart)

- [ ] **Step 2: verifica + commit**

Run: `C:\flutter\bin\flutter.bat analyze` → No issues; `flutter test` → verde.

```powershell
git add lib/core/player/preview_player.dart lib/app/providers.dart
git commit -m "feat(wizard): preview player dedicato per l'anteprima voce"
```

---

### Task 5 — Schermate del wizard + i18n + tab Crea

Repo: **audiobook-maker-mobile**.

**Files:**
- Create: `lib/app/create/create_wizard.dart`, `lib/app/create/steps/source_step.dart`, `lib/app/create/steps/chapters_step.dart`, `lib/app/create/steps/voice_format_step.dart`
- Modify: `lib/app/shell.dart`, `lib/l10n/app_*.arb`
- Test: `test/widget/create_wizard_test.dart`

- [ ] **Step 1: chiavi i18n** (7 ARB; it/en sotto, altre 5 tradotte con cura):

it:
```json
  "createTitle": "Crea audiolibro",
  "createServerMissing": "Configura l'indirizzo del server nelle impostazioni per creare audiolibri.",
  "createPickSource": "Scegli un file (EPUB, PDF, TXT, ABM)",
  "createAnalyzing": "Analisi del libro in corso…",
  "createAnalyzeError": "Analisi non riuscita. Riprova con un altro file.",
  "createStepChapters": "Capitoli",
  "createStepVoice": "Voce e formato",
  "createSelectAll": "Tutti",
  "createSelectNone": "Nessuno",
  "createChaptersSelected": "{n} di {tot} capitoli",
  "@createChaptersSelected": {"placeholders": {"n": {"type": "int"}, "tot": {"type": "int"}}},
  "createVoice": "Voce",
  "createFormat": "Formato",
  "createPreview": "Ascolta anteprima",
  "createPreviewStop": "Ferma",
  "createStart": "Avvia creazione",
  "createStarted": "Creazione avviata: la trovi in Attività.",
  "createStartError": "Avvio non riuscito. Riprova.",
  "createNext": "Avanti",
  "createBack": "Indietro"
```

en:
```json
  "createTitle": "Create audiobook",
  "createServerMissing": "Set the server address in settings to create audiobooks.",
  "createPickSource": "Choose a file (EPUB, PDF, TXT, ABM)",
  "createAnalyzing": "Analyzing the book…",
  "createAnalyzeError": "Analysis failed. Try another file.",
  "createStepChapters": "Chapters",
  "createStepVoice": "Voice and format",
  "createSelectAll": "All",
  "createSelectNone": "None",
  "createChaptersSelected": "{n} of {tot} chapters",
  "@createChaptersSelected": {"placeholders": {"n": {"type": "int"}, "tot": {"type": "int"}}},
  "createVoice": "Voice",
  "createFormat": "Format",
  "createPreview": "Play preview",
  "createPreviewStop": "Stop",
  "createStart": "Start creation",
  "createStarted": "Creation started: find it in Activity.",
  "createStartError": "Could not start. Try again.",
  "createNext": "Next",
  "createBack": "Back"
```

`flutter gen-l10n` → ok.

- [ ] **Step 2: widget test (failing)** — `test/widget/create_wizard_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:audiobook_maker_mobile/app/create/create_wizard.dart';
import 'package:audiobook_maker_mobile/app/create/wizard_controller.dart';
import 'package:audiobook_maker_mobile/app/providers.dart';
import 'package:audiobook_maker_mobile/core/api/book_info.dart';
import 'package:audiobook_maker_mobile/l10n/app_localizations.dart';

Widget _wrap({List<Override> overrides = const []}) => ProviderScope(
      overrides: overrides,
      child: const MaterialApp(
        locale: Locale('it'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: CreateWizard(),
      ),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({'server_url': 'http://x'}));

  testWidgets('senza server: CTA impostazioni', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(_wrap());
    await tester.pumpAndSettle();
    expect(find.textContaining('Configura'), findsOneWidget);
  });

  testWidgets('step capitoli: mostra selezione e conteggio', (tester) async {
    final book = BookInfo.fromJson(const {
      'job_id': 'j1', 'title': 'T', 'total_chapters': 2,
      'chapters': [
        {'index': 0, 'title': 'Capitolo A', 'chars': 10},
        {'index': 1, 'title': 'Capitolo B', 'chars': 10},
      ],
    });
    await tester.pumpWidget(_wrap(overrides: [
      wizardControllerProvider.overrideWith(
          (ref) => WizardController()..analyzed(book)),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('Capitolo A'), findsOneWidget);
    expect(find.text('Capitolo B'), findsOneWidget);
    expect(find.textContaining('2 di 2'), findsOneWidget);
    // deseleziona un capitolo
    await tester.tap(find.text('Capitolo A'));
    await tester.pumpAndSettle();
    expect(find.textContaining('1 di 2'), findsOneWidget);
  });
}
```

Run → FAIL.

- [ ] **Step 3: shell del wizard** — `lib/app/create/create_wizard.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/app_localizations.dart';
import '../providers.dart';
import 'steps/chapters_step.dart';
import 'steps/source_step.dart';
import 'steps/voice_format_step.dart';
import 'wizard_controller.dart';

class CreateWizard extends ConsumerWidget {
  const CreateWizard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context)!;
    final settings = ref.watch(settingsProvider).valueOrNull;
    if (settings != null && settings.serverUrl == null) {
      return Scaffold(
        appBar: AppBar(title: Text(t.createTitle)),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Text(t.createServerMissing, textAlign: TextAlign.center),
          ),
        ),
      );
    }
    final step = ref.watch(wizardControllerProvider).step;
    final body = switch (step) {
      WizardStep.source => const SourceStep(),
      WizardStep.chapters => const ChaptersStep(),
      WizardStep.voiceFormat => const VoiceFormatStep(),
    };
    return Scaffold(
      appBar: AppBar(
        title: Text(t.createTitle),
        leading: step == WizardStep.source
            ? null
            : IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () {
                  final prev = step == WizardStep.voiceFormat
                      ? WizardStep.chapters
                      : WizardStep.source;
                  ref.read(wizardControllerProvider.notifier).goTo(prev);
                }),
      ),
      body: body,
    );
  }
}
```

- [ ] **Step 4: step sorgente** — `lib/app/create/steps/source_step.dart`:

```dart
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../providers.dart';
import '../wizard_controller.dart';

class SourceStep extends ConsumerStatefulWidget {
  const SourceStep({super.key});
  @override
  ConsumerState<SourceStep> createState() => _SourceStepState();
}

class _SourceStepState extends ConsumerState<SourceStep> {
  bool _busy = false;

  Future<void> _pick() async {
    if (_busy) return;
    final t = AppLocalizations.of(context)!;
    final res = await FilePicker.platform.pickFiles(
        type: FileType.custom, allowedExtensions: ['epub', 'pdf', 'txt', 'abm']);
    final path = (res == null || res.files.isEmpty) ? null : res.files.first.path;
    if (path == null) return;
    setState(() => _busy = true);
    try {
      final client = await ref.read(apiClientProvider.future);
      if (client == null) return;
      final book = await client.analyze(File(path));
      ref.read(wizardControllerProvider.notifier).analyzed(book);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(t.createAnalyzeError)));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context)!;
    if (_busy) {
      return Center(
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 16),
          Text(t.createAnalyzing),
        ]),
      );
    }
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          const Icon(Icons.upload_file, size: 64),
          const SizedBox(height: 16),
          FilledButton.icon(
              onPressed: _pick,
              icon: const Icon(Icons.folder_open),
              label: Text(t.createPickSource)),
        ]),
      ),
    );
  }
}
```

- [ ] **Step 5: step capitoli** — `lib/app/create/steps/chapters_step.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../providers.dart';
import '../wizard_controller.dart';

class ChaptersStep extends ConsumerWidget {
  const ChaptersStep({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context)!;
    final state = ref.watch(wizardControllerProvider);
    final ctrl = ref.read(wizardControllerProvider.notifier);
    final book = state.book;
    if (book == null) return const SizedBox.shrink();
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: Row(
            children: [
              Expanded(
                  child: Text(
                      t.createChaptersSelected(
                          state.selectedChapters.length, book.chapters.length),
                      style: Theme.of(context).textTheme.titleSmall)),
              TextButton(
                  onPressed: () {
                    for (final c in book.chapters) {
                      if (!state.selectedChapters.contains(c.index)) {
                        ctrl.toggleChapter(c.index);
                      }
                    }
                  },
                  child: Text(t.createSelectAll)),
              TextButton(
                  onPressed: () {
                    for (final c in book.chapters) {
                      if (ref
                          .read(wizardControllerProvider)
                          .selectedChapters
                          .contains(c.index)) {
                        ctrl.toggleChapter(c.index);
                      }
                    }
                  },
                  child: Text(t.createSelectNone)),
            ],
          ),
        ),
        Expanded(
          child: ListView.builder(
            itemCount: book.chapters.length,
            itemBuilder: (ctx, i) {
              final c = book.chapters[i];
              final sel = state.selectedChapters.contains(c.index);
              return CheckboxListTile(
                value: sel,
                onChanged: (_) => ctrl.toggleChapter(c.index),
                title: Text(c.title.isNotEmpty ? c.title : 'Capitolo ${c.index + 1}',
                    maxLines: 1, overflow: TextOverflow.ellipsis),
              );
            },
          ),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: FilledButton(
              onPressed: state.selectedChapters.isEmpty
                  ? null
                  : () => ctrl.goTo(WizardStep.voiceFormat),
              child: Text(t.createNext),
            ),
          ),
        ),
      ],
    );
  }
}
```

- [ ] **Step 6: step voce/formato** — `lib/app/create/steps/voice_format_step.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/app_localizations.dart';
import '../../providers.dart';
import '../wizard_controller.dart';

class VoiceFormatStep extends ConsumerWidget {
  const VoiceFormatStep({super.key});

  Future<void> _preview(WidgetRef ref, String voice) async {
    final state = ref.read(wizardControllerProvider);
    final client = await ref.read(apiClientProvider.future);
    final book = state.book;
    if (client == null || book == null) return;
    final url = client.previewUrl(book.jobId, voice);
    await ref.read(previewPlayerProvider).play(url);
  }

  Future<void> _submit(BuildContext context, WidgetRef ref) async {
    final t = AppLocalizations.of(context)!;
    final ctrl = ref.read(wizardControllerProvider.notifier);
    final state = ref.read(wizardControllerProvider);
    ctrl.submitting(true);
    try {
      await ref.read(previewPlayerProvider).stop();
      final client = await ref.read(apiClientProvider.future);
      if (client == null || state.book == null || state.voice == null) return;
      await client.generate(
        jobId: state.book!.jobId,
        voice: state.voice!,
        outputFormat: state.format,
        selectedChapters: state.selectedChapters.toList()..sort(),
      );
      ctrl.reset();
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(t.createStarted)));
        ref.read(activityTabRequestProvider.notifier).state++;
      }
    } catch (_) {
      ctrl.error(t.createStartError);
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(t.createStartError)));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context)!;
    final state = ref.watch(wizardControllerProvider);
    final ctrl = ref.read(wizardControllerProvider.notifier);
    final voicesAsync = ref.watch(voicesProvider);
    return Column(
      children: [
        Expanded(
          child: voicesAsync.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => Center(child: Text(t.activityLoadError)),
            data: (catalog) {
              if (catalog == null) return const SizedBox.shrink();
              final groups = catalog.edgeGroups();
              return ListView(
                children: [
                  for (final g in groups) ...[
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Text(g.languageName,
                          style: Theme.of(context).textTheme.titleSmall),
                    ),
                    for (final v in g.voices)
                      RadioListTile<String>(
                        value: v.id,
                        groupValue: state.voice,
                        onChanged: (val) => ctrl.setVoice(val!),
                        title: Text(v.name),
                        subtitle: Text(v.gender),
                        secondary: IconButton(
                          icon: const Icon(Icons.play_circle_outline),
                          onPressed: () => _preview(ref, v.id),
                        ),
                      ),
                  ],
                ],
              );
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            children: [
              Text('${t.createFormat}: '),
              const SizedBox(width: 8),
              DropdownButton<String>(
                value: state.format,
                items: const [
                  DropdownMenuItem(value: 'm4b', child: Text('M4B')),
                  DropdownMenuItem(value: 'mp3', child: Text('MP3')),
                  DropdownMenuItem(value: 'zip', child: Text('ZIP')),
                ],
                onChanged: (f) => f == null ? null : ctrl.setFormat(f),
              ),
            ],
          ),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: FilledButton.icon(
              icon: state.submitting
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.auto_stories),
              label: Text(t.createStart),
              onPressed: state.canSubmit ? () => _submit(context, ref) : null,
            ),
          ),
        ),
      ],
    );
  }
}
```

- [ ] **Step 7: shell — tab Crea + richiesta passaggio ad Attività**

In `lib/app/providers.dart` aggiungi un provider per chiedere allo shell di passare alla tab Attività dopo l'avvio:

```dart
/// Incrementato dal wizard dopo l'avvio: lo shell osserva e passa ad Attività.
final activityTabRequestProvider = StateProvider<int>((ref) => 0);
```

In `lib/app/shell.dart`: sostituisci `ComingSoonScreen(title: t.tabCreate)` (tab indice 1) con `const CreateWizard()` (import). E nel `build` dello shell, osserva la richiesta:

```dart
    ref.listen(activityTabRequestProvider, (_, __) {
      setState(() => _tab = 2); // vai ad Attività dopo l'avvio creazione
    });
```

(metti la `ref.listen` all'inizio del metodo build dello State, prima di costruire le pagine).

- [ ] **Step 8: run + commit**

Run: `flutter gen-l10n`; `C:\flutter\bin\flutter.bat test` → tutti PASS (incl. 2 widget wizard); `analyze` pulito.

```powershell
git add lib/app lib/l10n test/widget/create_wizard_test.dart
git commit -m "feat(wizard): schermate sorgente/capitoli/voce-formato + tab Crea"
```

---

### Task 6 — Chiusura

Repo: **audiobook-maker-mobile**.

- [ ] **Step 1: qualità**

Run: `C:\flutter\bin\dart.bat format .` → `flutter analyze` (No issues; correggi lint nostri senza cambi logica) → `flutter test` (tutti PASS, riporta numero).

- [ ] **Step 2: smoke build APK**

Run: `C:\flutter\bin\flutter.bat build apk --debug` → deve riuscire. Se fallisce per lock OneDrive su `build/app/intermediates`, `Remove-Item` e riprova.

- [ ] **Step 3: README**

Nella sezione `## Stato`, AGGIUNGI IN TESTA:

```markdown
Fase 3b-1 completata: creazione audiolibri dall'app per il percorso gratuito —
wizard Crea (scegli file → analisi → seleziona capitoli → voce standard con
anteprima → formato → avvia), il job parte in modalità batch (sopravvive a
schermo bloccato) e compare in Attività, da cui si scarica nella libreria.
Manca: ottimizzazione AI, voci PREMIUM e pagamento voucher (fase 3b-2).
```

E alla checklist device:

```markdown
- [ ] wizard: EPUB/PDF/TXT analizzato, capitoli selezionabili, anteprima voce suona
- [ ] avvio creazione → job in Attività → al termine push + download in libreria
- [ ] creazione con schermo bloccato a metà generazione: il job NON si auto-cancella
```

- [ ] **Step 4: commit finale**

```powershell
git add -A
git commit -m "chore(3b-1): format, README aggiornato"
```

NON pushare (né app né backend) senza conferma utente.

---

## Note per l'esecutore

- **Due repo**: il Task 1 è nel backend (worktree `abm_mobile`, pytest); i Task 2-6 nell'app mobile (flutter). Non confonderli — committa nel repo giusto.
- **Contratti backend reali**: i campi di `/api/analyze`, `/api/voices`, `/api/generate` sono quelli del branch `abm_mobile`. Verifica con grep prima di assumere (specie il campo multipart `epub` e l'eventuale requisito cid sul preview).
- **Preview e cid**: se `api_preview_audio` richiede l'header `X-ABM-Cid` (ownership job), `previewUrl` da solo non basta (il player fa una GET senza header). In quel caso scarica l'anteprima con dio (header cid) in un file temp e dallo a `PreviewPlayer.play(file://...)`. Decidi leggendo la route reale.
- **Solo voci edge**: filtra `engine == 'edge'`. Google/Gemini = 3b-2.
- **Niente SSE**: il progress è in Attività (polling 3a). Dopo l'avvio si va in Attività.
- **OneDrive**: lock noto su ios\Flutter\ephemeral e build/app/intermediates.
- **Stringhe**: mai nominare provider AI/TTS nella UI (policy repo).
- **Deploy**: il Task 1 estende il backend non ancora deployato; al merge/deploy del branch abm_mobile andrà incluso.
