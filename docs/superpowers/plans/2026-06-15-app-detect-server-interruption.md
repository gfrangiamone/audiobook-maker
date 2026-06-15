# App: rilevazione interruzione job lato server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps `- [ ]`.

**Root cause (debugging):** (1) `remoteJobsProvider` (StreamProvider) emette AsyncError su OGNI poll `my_jobs` fallito → l'Activity mostra "server irraggiungibile" anche per un blip transitorio o il riavvio del servizio durante un kill admin. (2) Un'interruzione admin (`/api/cancel?force=1` con auth admin, anche da console/log-activity) imposta `cancelled=True`+`status="analyzed"`, ma `api_my_jobs` riporta `"analyzed"` → indistinguibile dal cancel utente; con `RemoteJob.isActive` ristretto il job sparisce invece di essere marcato interrotto. (3) Se il server si riavvia mentre il job è `generating`, il job in-memory sparisce del tutto da my_jobs.

**Goal:** L'app (a) NON mostra più "server irraggiungibile" per un poll fallito transitorio (mantiene l'ultima lista nota, indicatore discreto di riconnessione); (b) si accorge dell'interruzione lato server di un job (status `interrupted` dal backend, OPPURE job che era attivo e sparisce) e lo segnala all'utente una tantum; (c) marca quel job come **"Interrotto dal server"** in una sezione dedicata. Il cancel volontario dell'utente NON deve essere scambiato per interruzione server.

**Architecture:** Backend: l'admin-kill marca `job["server_interrupted"]=True`; `api_my_jobs` mappa cancelled+server_interrupted → status `"interrupted"`. App: `remoteJobsProvider` (Stream) → `jobsProvider` (NotifierProvider.autoDispose con polling Timer) che espone `JobsState {jobs, reachable, interrupted}`: mantiene l'ultima lista su poll fallito (reachable=false, niente throw), e con una funzione pura `reconcileInterruptions` rileva i job che erano attivi e ora sono `interrupted` o spariti → li aggiunge agli "interrotti". `markUserCancelled(jobId)` evita falsi positivi sul cancel utente.

**Repo backend (Task 1):** `C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker\.claude\worktrees\abm_mobile` (branch abm_mobile, pytest, `python -m pytest`). ⚠️ working copy condivisa: `git add` SOLO path espliciti, mai `-A`/reset; verifica `git branch --show-current` == abm_mobile prima del commit.
**Repo app (Task 2-6):** `C:\Users\gfran\NEXT srl\Progetti - Documenti\audiobook-maker-mobile` (branch main). Flutter `C:\flutter\bin\flutter.bat`. **NON `flutter build apk`** (solo analyze+test). Caveat OneDrive ios\Flutter\ephemeral.

## Mappa dei file
```
# backend
audiobook_app.py            # MOD: is_admin_kill → server_interrupted; api_my_jobs map → "interrupted"
test/test_mobile_api.py     # MOD: test interrupted in my_jobs
# app
lib/core/api/remote_job.dart        # MOD: isInterrupted; isActive invariato {generating,optimizing,translating}
lib/core/api/jobs_reconcile.dart    # NEW: funzione pura reconcileInterruptions + JobsState
lib/app/jobs_notifier.dart          # NEW: JobsNotifier (polling, reachable, interrupted, markUserCancelled)
lib/app/providers.dart              # MOD: jobsProvider (sostituisce remoteJobsProvider)
lib/app/screens/activity_screen.dart # MOD: usa jobsProvider; UI resiliente; sezione "Interrotti dal server"; notifica
lib/app/screens/voice_format_step.dart # MOD: invalidate → jobsProvider refresh
lib/app/shell.dart                  # MOD: push handler → jobsProvider refresh
lib/l10n/app_*.arb                  # MOD: chiavi (7 lingue)
test/jobs_reconcile_test.dart       # NEW
test/widget/activity_screen_test.dart # MOD
```

---

### Task 1 — Backend: status `interrupted` per kill admin/server

Repo abm_mobile. **Solo path espliciti nel commit.**

**Files:** Modify `audiobook_app.py`, `test/test_mobile_api.py`.

- [ ] **Step 1: test (failing)** — append a `test/test_mobile_api.py`:

```python
def test_my_jobs_reports_interrupted_for_admin_kill(monkeypatch):
    import audiobook_app
    jid = "intj1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "status": "analyzed", "cancelled": True, "server_interrupted": True,
            "client_id": "mobile-cid-12345", "info": None,
            "start_time": __import__("time").time(),
        }
    try:
        c = audiobook_app.app.test_client()
        r = c.get("/api/my_jobs", headers={"X-ABM-Cid": "mobile-cid-12345"})
        jobs = r.get_json()["jobs"]
        e = next(j for j in jobs if j["job_id"] == jid)
        assert e["status"] == "interrupted"
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(jid, None)


def test_my_jobs_user_cancel_not_interrupted(monkeypatch):
    import audiobook_app
    jid = "intj2"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {
            "status": "analyzed", "cancelled": True,  # niente server_interrupted
            "client_id": "mobile-cid-12345", "info": None,
            "start_time": __import__("time").time(),
        }
    try:
        c = audiobook_app.app.test_client()
        r = c.get("/api/my_jobs", headers={"X-ABM-Cid": "mobile-cid-12345"})
        jobs = r.get_json()["jobs"]
        e = next((j for j in jobs if j["job_id"] == jid), None)
        # user-cancel resta "analyzed" (poi filtrato dall'app), NON interrupted
        assert e is None or e["status"] == "analyzed"
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(jid, None)
```

Run: `python -m pytest test/test_mobile_api.py -k "interrupted or user_cancel_not" -v --tb=short` → FAIL.

- [ ] **Step 2: implementare.**
  1. In `api_cancel`, ramo `if is_admin_kill:` (dopo `job["cancelled"]=True`, prima/dentro il blocco admin log, grep riga ~7706): aggiungi `job["server_interrupted"] = True`. (Va impostato sotto `_jobs_lock`: l'assegnazione è dentro il `with _jobs_lock` se possibile; se il log ADMIN_CANCEL è fuori dal lock, metti il flag dentro il `with` accanto a `job["cancelled"]=True` guardato da `is_admin_kill`.)
  
  Concretamente, dentro il `with _jobs_lock:` dopo `job["status"] = "analyzed"` aggiungi:
  ```python
        if is_admin_kill:
            job["server_interrupted"] = True
  ```
  2. In `api_my_jobs`, dove costruisce `entry["status"]` per i job in-memory (grep `_MY_JOBS_LIVE_STATUSES` / `status = job.get("status", "")`): prima di usare `status`, rimappa:
  ```python
        status = job.get("status", "")
        if job.get("server_interrupted"):
            status = "interrupted"
        if status not in _MY_JOBS_LIVE_STATUSES:
            continue
  ```
  e aggiungi `"interrupted"` alla tupla `_MY_JOBS_LIVE_STATUSES`.
  
  Nota: NON mappare il semplice `cancelled` (user-cancel) → resta "analyzed". Solo `server_interrupted` → "interrupted".

- [ ] **Step 3:** `python -m pytest test/test_mobile_api.py -k "interrupted or user_cancel_not" -v --tb=short` → PASS; `python -m py_compile audiobook_app.py`; `python -m pytest test/ -q --tb=line` → solo i 4 paypal pre-esistenti falliscono.

- [ ] **Step 4: commit** (solo i 2 path):
```powershell
git add audiobook_app.py test/test_mobile_api.py
git commit -m "feat(mobile): status 'interrupted' in my_jobs per kill admin/server"
```
footer Co-Authored-By Claude Fable 5 (here-string). NON pushare.

---

### Task 2 — App: RemoteJob.isInterrupted + funzione pura reconcileInterruptions

Repo app.

**Files:** Modify `lib/core/api/remote_job.dart`; Create `lib/core/api/jobs_reconcile.dart`; Test `test/jobs_reconcile_test.dart`, `test/remote_job_test.dart`.

- [ ] **Step 1: RemoteJob.isInterrupted** — in `remote_job.dart` aggiungi getter:
```dart
  bool get isInterrupted => status == 'interrupted';
```
(lascia `isActive` = {optimizing,translating,generating}; `isInterrupted` separato. `isFailed` resta {error,cancelled}.) Aggiungi un test in `remote_job_test.dart`: status 'interrupted' → isInterrupted true, isActive false, isDone false.

- [ ] **Step 2: test funzione pura (failing)** — `test/jobs_reconcile_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:audiobook_maker_mobile/core/api/remote_job.dart';
import 'package:audiobook_maker_mobile/core/api/jobs_reconcile.dart';

RemoteJob _job(String id, String status) =>
    RemoteJob.fromJson({'job_id': id, 'status': status});

void main() {
  test('job attivo che diventa interrupted → newlyInterrupted', () {
    final prev = {'a'}; // 'a' era attivo
    final now = [_job('a', 'interrupted')];
    final r = reconcileInterruptions(
        previousActiveIds: prev, current: now, userCancelled: const {});
    expect(r.newlyInterrupted.map((j) => j.jobId), contains('a'));
  });

  test('job attivo che sparisce → newlyInterrupted (sintetico)', () {
    final prev = {'a'};
    final now = <RemoteJob>[]; // 'a' sparito (restart server)
    final lastKnown = {'a': _job('a', 'generating')};
    final r = reconcileInterruptions(
        previousActiveIds: prev, current: now, userCancelled: const {},
        lastKnownById: lastKnown);
    expect(r.newlyInterrupted.map((j) => j.jobId), contains('a'));
    expect(r.newlyInterrupted.first.isInterrupted, isTrue); // entry sintetica
  });

  test('job cancellato dall’utente che sparisce → NON interrupted', () {
    final prev = {'a'};
    final now = <RemoteJob>[];
    final r = reconcileInterruptions(
        previousActiveIds: prev, current: now, userCancelled: const {'a'},
        lastKnownById: {'a': _job('a', 'generating')});
    expect(r.newlyInterrupted, isEmpty);
  });

  test('job completato (done) non è interruzione', () {
    final prev = {'a'};
    final now = [_job('a', 'done')];
    final r = reconcileInterruptions(
        previousActiveIds: prev, current: now, userCancelled: const {});
    expect(r.newlyInterrupted, isEmpty);
  });

  test('nuovi activeIds calcolati per il giro successivo', () {
    final now = [_job('b', 'generating'), _job('c', 'done')];
    final r = reconcileInterruptions(
        previousActiveIds: const {}, current: now, userCancelled: const {});
    expect(r.activeIds, {'b'});
  });
}
```

Run → FAIL.

- [ ] **Step 3: implementare** — `lib/core/api/jobs_reconcile.dart`:

```dart
import 'remote_job.dart';

class ReconcileResult {
  final List<RemoteJob> newlyInterrupted; // job appena interrotti dal server
  final Set<String> activeIds; // job attivi ORA (per il giro successivo)
  const ReconcileResult(this.newlyInterrupted, this.activeIds);
}

/// Rileva interruzioni lato server confrontando i job attivi del giro
/// precedente con la lista corrente. Un job è "appena interrotto" se era
/// attivo e ora: (a) ha status 'interrupted', oppure (b) è sparito del tutto
/// (restart server) — purché NON sia stato cancellato dall'utente.
ReconcileResult reconcileInterruptions({
  required Set<String> previousActiveIds,
  required List<RemoteJob> current,
  required Set<String> userCancelled,
  Map<String, RemoteJob> lastKnownById = const {},
}) {
  final byId = {for (final j in current) j.jobId: j};
  final newly = <RemoteJob>[];
  for (final id in previousActiveIds) {
    if (userCancelled.contains(id)) continue;
    final cur = byId[id];
    if (cur != null && cur.isInterrupted) {
      newly.add(cur);
    } else if (cur == null) {
      // sparito mentre era attivo → interruzione (entry sintetica)
      final last = lastKnownById[id];
      newly.add(RemoteJob.fromJson({
        'job_id': id,
        'status': 'interrupted',
        'title': last?.title ?? '',
      }));
    }
  }
  final activeIds = {for (final j in current) if (j.isActive) j.jobId};
  return ReconcileResult(newly, activeIds);
}
```

Run test → PASS.

- [ ] **Step 4: commit**
```powershell
git add lib/core/api/remote_job.dart lib/core/api/jobs_reconcile.dart test/jobs_reconcile_test.dart test/remote_job_test.dart
git commit -m "feat(activity): modello interrupted + reconcile interruzioni (funzione pura testata)"
```

---

### Task 3 — App: JobsNotifier (polling resiliente + stato interruzioni)

Repo app.

**Files:** Create `lib/app/jobs_notifier.dart`; Modify `lib/app/providers.dart`.

- [ ] **Step 1: JobsState + JobsNotifier** — `lib/app/jobs_notifier.dart`:

```dart
import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/abm_api_client.dart';
import '../core/api/jobs_reconcile.dart';
import '../core/api/remote_job.dart';
import 'providers.dart';

class JobsState {
  final List<RemoteJob> jobs; // lista server corrente (ultima nota)
  final List<RemoteJob> interrupted; // job interrotti dal server (persistiti in sessione)
  final bool reachable; // false dopo un poll fallito (mantiene la lista)
  final bool everLoaded; // true dopo il primo poll riuscito
  final List<RemoteJob> newlyInterrupted; // per notifica una-tantum (consumato dalla UI)
  const JobsState({
    required this.jobs,
    required this.interrupted,
    required this.reachable,
    required this.everLoaded,
    required this.newlyInterrupted,
  });
  factory JobsState.initial() => const JobsState(
      jobs: [], interrupted: [], reachable: true, everLoaded: false,
      newlyInterrupted: []);
  JobsState copyWith({
    List<RemoteJob>? jobs,
    List<RemoteJob>? interrupted,
    bool? reachable,
    bool? everLoaded,
    List<RemoteJob>? newlyInterrupted,
  }) =>
      JobsState(
        jobs: jobs ?? this.jobs,
        interrupted: interrupted ?? this.interrupted,
        reachable: reachable ?? this.reachable,
        everLoaded: everLoaded ?? this.everLoaded,
        newlyInterrupted: newlyInterrupted ?? this.newlyInterrupted,
      );
}

class JobsNotifier extends AutoDisposeNotifier<JobsState> {
  Timer? _timer;
  Set<String> _prevActive = {};
  final Map<String, RemoteJob> _lastKnown = {};
  final Set<String> _userCancelled = {};
  final Set<String> _interruptedIds = {};

  @override
  JobsState build() {
    ref.onDispose(() => _timer?.cancel());
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _poll());
    return JobsState.initial();
  }

  /// Segnala che il job è stato cancellato dall'utente (no falso positivo).
  void markUserCancelled(String jobId) => _userCancelled.add(jobId);

  /// Forza un refresh immediato (es. dopo avvio generazione / push).
  Future<void> refresh() => _poll();

  /// La UI chiama questo dopo aver mostrato la notifica, per non ripeterla.
  void clearNewlyInterrupted() {
    if (state.newlyInterrupted.isNotEmpty) {
      state = state.copyWith(newlyInterrupted: const []);
    }
  }

  Future<void> _poll() async {
    AbmApiClient? client;
    try {
      client = await ref.read(apiClientProvider.future);
    } catch (_) {
      client = null;
    }
    if (client == null) {
      state = state.copyWith(reachable: true, everLoaded: true);
      return;
    }
    try {
      final jobs = await client.myJobs();
      final rec = reconcileInterruptions(
        previousActiveIds: _prevActive,
        current: jobs,
        userCancelled: _userCancelled,
        lastKnownById: Map.of(_lastKnown),
      );
      _prevActive = rec.activeIds;
      _lastKnown
        ..clear()
        ..addEntries(jobs.map((j) => MapEntry(j.jobId, j)));
      // accumula interrotti (dedup per jobId)
      final freshInterrupted = <RemoteJob>[];
      for (final j in rec.newlyInterrupted) {
        if (_interruptedIds.add(j.jobId)) freshInterrupted.add(j);
      }
      final allInterrupted = [
        ...state.interrupted,
        ...freshInterrupted,
      ];
      state = JobsState(
        jobs: jobs,
        interrupted: allInterrupted,
        reachable: true,
        everLoaded: true,
        newlyInterrupted: freshInterrupted,
      );
    } catch (_) {
      // poll fallito: mantieni l'ultima lista, segnala non raggiungibile
      state = state.copyWith(reachable: false, everLoaded: true);
    }
  }
}
```

- [ ] **Step 2: provider** — in `lib/app/providers.dart`: SOSTITUISCI `remoteJobsProvider` con:
```dart
final jobsProvider =
    AutoDisposeNotifierProvider<JobsNotifier, JobsState>(JobsNotifier.new);
```
(import jobs_notifier.dart). Rimuovi il vecchio `remoteJobsProvider` (StreamProvider). Cerca tutti gli usi di `remoteJobsProvider` nel repo (`activity_screen.dart`, `voice_format_step.dart`, `shell.dart`) — verranno aggiornati nei Task 4-5; per ora il commit di questo task può lasciare il vecchio provider se serve a compilare. MEGLIO: fai questo task INSIEME ai Task 4-5 in un unico commit per non rompere la compilazione. (Vedi nota sotto.)

NOTA esecutore: i Task 3-5 vanno fatti come un blocco coeso e committati insieme (sostituire il provider rompe i 3 call-site finché non li aggiorni). Procedi: crea jobs_notifier.dart, sostituisci il provider, aggiorna i 3 call-site (Task 4-5), poi un commit unico. Test/analyze alla fine.

- [ ] (commit unico a fine Task 5)

---

### Task 4 — App: ActivityScreen resiliente + sezione "Interrotti dal server" + notifica

Repo app.

**Files:** Modify `lib/app/screens/activity_screen.dart`; i18n.

- [ ] **Step 1: i18n** (7 ARB): it/en sotto, +fr/es/de/zh/hi:
```
it: "activityInterrupted":"Interrotti dal server", "activityInterruptedNote":"Interrotto dal server", "activityInterruptedToast":"Un lavoro è stato interrotto dal server.", "activityReconnecting":"Riconnessione in corso…"
en: "activityInterrupted":"Interrupted by the server", "activityInterruptedNote":"Interrupted by the server", "activityInterruptedToast":"A job was interrupted by the server.", "activityReconnecting":"Reconnecting…"
```
`flutter gen-l10n`.

- [ ] **Step 2: ActivityScreen.** Sostituisci l'uso di `remoteJobsProvider` con `jobsProvider`:
  - `final s = ref.watch(jobsProvider);`
  - **UI resiliente:** NON mostrare più il grande errore "server irraggiungibile" su singolo fallimento. Logica:
    - se `!s.everLoaded` → `CircularProgressIndicator` (primo caricamento).
    - altrimenti mostra SEMPRE la lista (`s.jobs` + sezione interrotti), e se `!s.reachable` mostra un banner/striscia discreta in cima con `t.activityReconnecting` (es. `MaterialBanner` o un piccolo Container colorato), senza nascondere la lista.
  - **Notifica una-tantum:** in un `ref.listen(jobsProvider, (prev, next) { if (next.newlyInterrupted.isNotEmpty && mounted) { ScaffoldMessenger...showSnackBar(activityInterruptedToast); ref.read(jobsProvider.notifier).clearNewlyInterrupted(); } })` dentro il build (ConsumerStatefulWidget).
  - **Sezioni** in `_JobsList`: oltre a in-lavorazione/pronti/falliti, aggiungi una sezione `activityInterrupted` che elenca `s.interrupted` (passali a `_JobsList`), ciascuno come tile con icona warning e sottotitolo `t.activityInterruptedNote`. (Gli interrotti vengono da `s.interrupted`, NON da `s.jobs`.)
  - **RefreshIndicator.onRefresh** → `ref.read(jobsProvider.notifier).refresh()`.
  - **Retry** (se mai server proprio giù e !everLoaded non si applica; il banner reconnecting basta): rimuovi il vecchio bottone retry o collegalo a `refresh()`.
  - Il download e il cancel restano; in `_cancel` aggiungi `ref.read(jobsProvider.notifier).markUserCancelled(job.jobId)` PRIMA di `cancelJob`, e dopo usa `refresh()` invece di `invalidate(remoteJobsProvider)`.
  - `_download` success: `ref.read(jobsProvider.notifier).refresh()` invece di `invalidate(remoteJobsProvider)`.

- [ ] (commit unico a fine Task 5)

---

### Task 5 — App: aggiorna gli altri call-site di remoteJobsProvider

Repo app.

**Files:** Modify `lib/app/screens/voice_format_step.dart`, `lib/app/shell.dart`.

- [ ] **Step 1:** in `voice_format_step.dart` `_submit`, sostituisci `ref.invalidate(remoteJobsProvider)` con `ref.read(jobsProvider.notifier).refresh()`.
- [ ] **Step 2:** in `shell.dart`, nel `PushSetup.onJobEvent` handler, sostituisci `ref.invalidate(remoteJobsProvider)` con `ref.read(jobsProvider.notifier).refresh()` (mantieni il passaggio a tab Attività).
- [ ] **Step 3:** verifica che NON resti alcun riferimento a `remoteJobsProvider` (grep). Aggiorna i widget test che lo usavano (`activity_screen_test.dart`): ora si fa override di `jobsProvider`? È un NotifierProvider con polling reale — nei widget test SOVRASCRIVILO con un fake notifier o costruisci uno stato fisso. Approccio semplice: estrai un piccolo override `jobsProvider.overrideWith(() => _FakeJobsNotifier(state))` dove `_FakeJobsNotifier` estende JobsNotifier e in `build()` ritorna uno stato fornito senza avviare il Timer. Aggiorna i 2-3 widget test esistenti dell'activity (lista, download bottone unico, cancel) per usare questo fake con `JobsState(jobs:[...], reachable:true, everLoaded:true, interrupted:[...], newlyInterrupted:[])`. Aggiungi un test: stato con `interrupted:[job 'interrupted']` → la sezione "Interrotti dal server" e il tile compaiono.

- [ ] **Step 4: run + COMMIT UNICO (Task 3+4+5)**

Run: `flutter analyze` → No issues; `flutter test` → tutti PASS (riporta numero). NIENTE build APK.
```powershell
git add lib test
git commit -m "feat(activity): polling resiliente + rilevazione e marcatura 'Interrotto dal server'"
```
footer Co-Authored-By Claude Fable 5 (here-string). NON pushare.

---

### Task 6 — Chiusura + review finale

Repo app.
- [ ] `dart format .` → `flutter analyze` (No issues) → `flutter test` (riporta numero). NIENTE APK.
- [ ] README sezione Stato: nota "Activity resiliente ai poll falliti; job interrotti lato server marcati 'Interrotto dal server' con notifica".
- [ ] commit `chore: README` se ci sono modifiche. NON pushare.
- [ ] Review finale d'insieme (spec + quality) dell'intera feature (backend interrupted + notifier + UI), con focus su: nessun falso positivo sul cancel utente; nessun "server irraggiungibile" su blip; dedup interrotti; niente leak del Timer (onDispose).

---

## Note per l'esecutore
- **Backend**: working copy condivisa → solo path espliciti, mai `-A`/reset; verifica branch.
- **Niente APK** (direttiva utente): solo analyze+test.
- **Falso positivo cancel utente**: `markUserCancelled` va chiamato PRIMA di `cancelJob`; il backend per user-cancel NON setta server_interrupted (status resta analyzed) → non finisce in "interrupted".
- **Timer**: `ref.onDispose(_timer.cancel)` obbligatorio (autoDispose quando la tab non è osservata).
- **Stringhe**: mai nominare provider AI/TTS nella UI.
- **OneDrive**: lock noto su ios\Flutter\ephemeral / build dirs.
