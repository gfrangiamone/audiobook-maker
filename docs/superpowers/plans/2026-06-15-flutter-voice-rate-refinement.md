# App Flutter — Refinement wizard: lingua→voce, velocità, anteprima (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) o superpowers:executing-plans. Steps usano checkbox (`- [ ]`).

**Goal:** Rendere la selezione voce del wizard agevole come sul sito: prima la lingua (menù), poi le voci di quella lingua; aggiungere il controllo velocità di lettura (slider −30%..+30%) e un pulsante unico di anteprima che riproduce voce+velocità correnti.

**Architecture:** Si estende `WizardController` con lingua selezionata e rate; la schermata voce/formato passa da una lista piatta di tutte le voci a: menù lingua in alto → lista voci (radio) della lingua scelta → slider velocità con etichetta → pulsante "Ascolta anteprima" (voce+rate correnti, via `downloadPreview` cid-aware + `PreviewPlayer`) → formato. Il rate fluisce a `generate` e a `downloadPreview` (entrambi già lo accettano). Mirror della UX web (slider a 7 step, rate come stringa `+10%`).

**Tech Stack:** Flutter/Riverpod/just_audio (già presenti).

**Repo:** `C:\Users\gfran\NEXT srl\Progetti - Documenti\audiobook-maker-mobile` (branch main). Flutter `C:\flutter\bin\flutter.bat`. PowerShell, comandi singoli senza `&&`. Caveat OneDrive: lock su `ios\Flutter\ephemeral` → normalizza attributi e cancella la dir.

**Contesto esistente** (post 3b-1): `voice_format_step.dart` è ConsumerStatefulWidget con: lista voci edge (`catalog.edgeGroups()`) in RadioGroup, anteprima per-voce (downloadPreview+playFile), dropdown formato, bottone avvia. `WizardController`/`WizardState` ha step/book/selectedChapters/voice/format/submitting. `AbmApiClient.generate({...rate='+0%'})` e `downloadPreview(jobId, voice, savePath, {rate='+0%'})` accettano già `rate`. `VoiceCatalog.edgeGroups()` ritorna `List<VoiceGroup>` (languageCode/languageName/voices) ordinati per nome lingua.

**Decisioni (confermate con l'utente):**
- **Una schermata**: menù a tendina lingua in alto + lista voci sotto (no sotto-passi separati).
- **Velocità**: slider a 7 step (−30%, −20%, −10%, +0%, +10%, +20%, +30%) con etichetta (molto lento … normale … molto veloce). Valori inviati come stringa con segno (`"+10%"`), identici al sito.
- **Anteprima unica**: un solo pulsante "Ascolta anteprima" che usa la voce e la velocità correnti (riflette la velocità scelta). Sostituisce le icone play per-voce.
- Default lingua: `book.language` se esiste un gruppo per quella lingua, altrimenti la prima lingua disponibile. Default voce: prima voce del gruppo. Rate default `+0%`, NON resettato al cambio voce (preferenza globale per questa generazione).

## Mappa dei file
```
lib/app/create/wizard_controller.dart  # MODIFICA: +languageCode, +rate; setLanguage/setRate; setAnalyzed sceglie lingua+voce default
lib/app/create/steps/voice_format_step.dart # RISCRITTURA: lingua dropdown + voci filtrate + slider velocità + anteprima unica + formato
lib/core/api/voice.dart                # (eventuale) helper rate labels — oppure costante nello step
lib/l10n/app_*.arb                      # MODIFICA: 7 etichette velocità + label lingua/velocità/anteprima
test/wizard_controller_test.dart        # MODIFICA: +test lingua/rate
test/widget/create_wizard_test.dart     # MODIFICA: aggiorna il test voce alla nuova UI
```

---

### Task 1 — WizardController: lingua + velocità

**Files:**
- Modify: `lib/app/create/wizard_controller.dart`
- Test: `test/wizard_controller_test.dart`

- [ ] **Step 1: test (failing)** — append/aggiorna `test/wizard_controller_test.dart`:

```dart
  test('setAnalyzed con lingua del libro preseleziona languageCode', () {
    final b = BookInfo.fromJson(const {
      'job_id': 'j1', 'title': 'T', 'language': 'en', 'total_chapters': 1,
      'chapters': [{'index': 0, 'title': 'A', 'chars': 10}],
    });
    final s = WizardState.initial().setAnalyzed(b);
    expect(s.languageCode, 'en');
    expect(s.rate, '+0%'); // default
  });

  test('setLanguage e setRate', () {
    var s = WizardState.initial();
    s = s.setLanguage('fr');
    expect(s.languageCode, 'fr');
    s = s.setRate('+20%');
    expect(s.rate, '+20%');
  });

  test('setLanguage azzera la voce selezionata (cambio lingua)', () {
    var s = WizardState.initial().setVoice('it-IT-IsabellaNeural');
    s = s.setLanguage('en');
    expect(s.voice, isNull); // la voce non appartiene più alla lingua scelta
  });
```

Nota: il primo test richiede che `BookInfo` esponga `language` (già presente). Verifica che `setAnalyzed` resti compatibile coi test esistenti (lingua vuota → `languageCode` resta null o '' — adatta gli assert se un test esistente costruisce un book senza language: in quel caso `languageCode` può essere '' ).

Run: `C:\flutter\bin\flutter.bat test test/wizard_controller_test.dart` → FAIL.

- [ ] **Step 2: implementare** — in `wizard_controller.dart`:

1. Aggiungi a `WizardState` i campi `final String languageCode;` (default '') e `final String rate;` (default '+0%'); inseriscili nel costruttore, in `initial()` (languageCode: '', rate: '+0%') e in `_copy` (con `clearVoice` già esistente).
2. `setAnalyzed(BookInfo b)`: oltre a quanto già fa, imposta `languageCode: b.language` (può essere '').
3. Aggiungi metodi:
```dart
  WizardState setLanguage(String code) =>
      _copy(languageCode: code, clearVoice: true);
  WizardState setRate(String r) => _copy(rate: r);
```
4. In `WizardController` aggiungi:
```dart
  void setLanguage(String c) => state = state.setLanguage(c);
  void setRate(String r) => state = state.setRate(r);
```

Esempio firma `_copy` aggiornata (aggiungi i due parametri mantenendo gli esistenti):
```dart
  WizardState _copy({
    WizardStep? step,
    BookInfo? book,
    Set<int>? selectedChapters,
    String? voice,
    String? format,
    String? languageCode,
    String? rate,
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
        languageCode: languageCode ?? this.languageCode,
        rate: rate ?? this.rate,
        submitting: submitting ?? this.submitting,
        error: clearError ? null : (error ?? this.error),
      );
```

Run test → PASS. Verifica che i test esistenti del controller restino verdi (se uno costruiva book senza `language`, `languageCode` sarà '': adatta solo se un assert esistente fallisce).

- [ ] **Step 3: commit**

```powershell
git add lib/app/create/wizard_controller.dart test/wizard_controller_test.dart
git commit -m "feat(wizard): stato lingua selezionata e velocita di lettura"
```
(footer: riga vuota + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`, here-string `@'...'@`)

---

### Task 2 — i18n: etichette velocità e label

**Files:**
- Modify: `lib/l10n/app_*.arb` (7 lingue)

- [ ] **Step 1: chiavi** (tutti e 7 gli ARB; it/en sotto, fr/es/de/zh/hi tradotte con cura):

it:
```json
  "createLanguage": "Lingua",
  "createSpeed": "Velocità di lettura",
  "createPreviewListen": "Ascolta anteprima",
  "speedVerySlow": "Molto lento",
  "speedSlow": "Lento",
  "speedSlightlySlow": "Leggermente lento",
  "speedNormal": "Normale",
  "speedSlightlyFast": "Leggermente veloce",
  "speedFast": "Veloce",
  "speedVeryFast": "Molto veloce"
```

en:
```json
  "createLanguage": "Language",
  "createSpeed": "Reading speed",
  "createPreviewListen": "Play preview",
  "speedVerySlow": "Very slow",
  "speedSlow": "Slow",
  "speedSlightlySlow": "Slightly slow",
  "speedNormal": "Normal",
  "speedSlightlyFast": "Slightly fast",
  "speedFast": "Fast",
  "speedVeryFast": "Very fast"
```

(fr/es/de/zh/hi: traduci tutte e 9 le chiavi con ortografia corretta — diacritici/han/devanagari.)

Run: `C:\flutter\bin\flutter.bat gen-l10n` → nessun untranslated.

- [ ] **Step 2: commit**

```powershell
git add lib/l10n
git commit -m "i18n: etichette velocita di lettura e selezione lingua/anteprima (7 lingue)"
```

---

### Task 3 — Riscrittura voice_format_step (lingua→voce, slider, anteprima unica)

**Files:**
- Modify: `lib/app/create/steps/voice_format_step.dart`
- Test: `test/widget/create_wizard_test.dart`

- [ ] **Step 1: aggiornare il widget test (failing)** — in `test/widget/create_wizard_test.dart` adatta/aggiungi un test per la nuova UI dello step voce. Sostituisci eventuali asserzioni sulla vecchia lista piatta con:

```dart
  testWidgets('step voce: dropdown lingua + voci della lingua + slider velocità',
      (tester) async {
    final book = BookInfo.fromJson(const {
      'job_id': 'j1', 'title': 'T', 'language': 'it', 'total_chapters': 1,
      'chapters': [{'index': 0, 'title': 'A', 'chars': 10}],
    });
    final catalog = VoiceCatalog.fromJson(const {
      'it': {'name': 'Italian', 'voices': [
        {'id': 'it-IT-IsabellaNeural', 'name': 'Isabella', 'gender': 'Female',
         'locale': 'it-IT', 'engine': 'edge'},
      ]},
      'en': {'name': 'English', 'voices': [
        {'id': 'en-US-Ava', 'name': 'Ava', 'gender': 'Female',
         'locale': 'en-US', 'engine': 'edge'},
      ]},
    });
    await tester.pumpWidget(_wrap(overrides: [
      wizardControllerProvider.overrideWith(
          (ref) => WizardController()..analyzed(book)..goTo(WizardStep.voiceFormat)),
      voicesProvider.overrideWith((ref) async => catalog),
    ]));
    await tester.pumpAndSettle();
    // la voce della lingua del libro (it) è mostrata
    expect(find.text('Isabella'), findsOneWidget);
    // l'etichetta velocità di default "Normale" è presente
    expect(find.text('Normale'), findsOneWidget);
    // pulsante anteprima presente
    expect(find.text('Ascolta anteprima'), findsOneWidget);
    // lo slider velocità c'è
    expect(find.byType(Slider), findsOneWidget);
  });
```

Adatta `_wrap` se necessario (è già definito nel file di test del wizard) e gli import (BookInfo, VoiceCatalog, WizardStep). Verifica che gli ALTRI test del file (CTA senza server, step capitoli) restino invariati.

Run → FAIL.

- [ ] **Step 2: riscrivere** `lib/app/create/steps/voice_format_step.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../../core/api/voice.dart';
import '../../../l10n/app_localizations.dart';
import '../../providers.dart';
import '../wizard_controller.dart';

/// 7 step di velocità, valore stringa inviato all'API (mirror del sito).
const _rateValues = ['-30%', '-20%', '-10%', '+0%', '+10%', '+20%', '+30%'];

String _rateLabel(AppLocalizations t, String rate) {
  switch (rate) {
    case '-30%':
      return t.speedVerySlow;
    case '-20%':
      return t.speedSlow;
    case '-10%':
      return t.speedSlightlySlow;
    case '+10%':
      return t.speedSlightlyFast;
    case '+20%':
      return t.speedFast;
    case '+30%':
      return t.speedVeryFast;
    default:
      return t.speedNormal; // +0%
  }
}

class VoiceFormatStep extends ConsumerStatefulWidget {
  const VoiceFormatStep({super.key});
  @override
  ConsumerState<VoiceFormatStep> createState() => _VoiceFormatStepState();
}

class _VoiceFormatStepState extends ConsumerState<VoiceFormatStep> {
  String? _previewing; // voce in caricamento anteprima
  int _previewSeq = 0;

  Future<void> _preview() async {
    final state = ref.read(wizardControllerProvider);
    final voice = state.voice;
    final book = state.book;
    if (voice == null || book == null) return;
    final t = AppLocalizations.of(context)!;
    final mySeq = ++_previewSeq;
    setState(() => _previewing = voice);
    try {
      await ref.read(previewPlayerProvider).stop();
      final client = await ref.read(apiClientProvider.future);
      if (client == null) return;
      final dir = await getTemporaryDirectory();
      final safe = voice.replaceAll(RegExp(r'[^A-Za-z0-9]'), '_');
      final path = '${dir.path}/preview_$safe.mp3';
      await client.downloadPreview(book.jobId, voice, path, rate: state.rate);
      if (mySeq != _previewSeq) return; // un tap più recente ha vinto
      await ref.read(previewPlayerProvider).playFile(path);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(t.createPreviewError)));
      }
    } finally {
      if (mounted && mySeq == _previewSeq) setState(() => _previewing = null);
    }
  }

  Future<void> _submit() async {
    final ctrl = ref.read(wizardControllerProvider.notifier);
    final state = ref.read(wizardControllerProvider);
    if (state.book == null || state.voice == null) return;
    ctrl.submitting(true);
    try {
      await ref.read(previewPlayerProvider).stop();
      final client = await ref.read(apiClientProvider.future);
      if (client == null) return;
      await client.generate(
        jobId: state.book!.jobId,
        voice: state.voice!,
        outputFormat: state.format,
        selectedChapters: state.selectedChapters.toList()..sort(),
        rate: state.rate,
      );
      ctrl.reset();
      if (mounted) {
        final t = AppLocalizations.of(context)!;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(t.createStarted)));
        ref.invalidate(remoteJobsProvider);
        ref.read(activityTabRequestProvider.notifier).state++;
      }
    } catch (_) {
      if (mounted) {
        final t = AppLocalizations.of(context)!;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(t.createStartError)));
      }
    } finally {
      if (mounted) ctrl.submitting(false);
    }
  }

  /// Sceglie la lingua effettiva da mostrare: quella in stato se ha un gruppo,
  /// altrimenti la prima disponibile.
  VoiceGroup? _activeGroup(List<VoiceGroup> groups, String code) {
    if (groups.isEmpty) return null;
    return groups.firstWhere((g) => g.languageCode == code,
        orElse: () => groups.first);
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context)!;
    final state = ref.watch(wizardControllerProvider);
    final ctrl = ref.read(wizardControllerProvider.notifier);
    final voicesAsync = ref.watch(voicesProvider);

    return voicesAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text(t.activityLoadError)),
      data: (catalog) {
        if (catalog == null) return const SizedBox.shrink();
        final groups = catalog.edgeGroups();
        if (groups.isEmpty) {
          return Center(child: Text(t.activityLoadError));
        }
        final group = _activeGroup(groups, state.languageCode)!;
        // se la lingua in stato non ha gruppo, allinea lo stato + voce default
        if (state.languageCode != group.languageCode || state.voice == null) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (state.languageCode != group.languageCode) {
              ctrl.setLanguage(group.languageCode);
            }
            if (ref.read(wizardControllerProvider).voice == null &&
                group.voices.isNotEmpty) {
              ctrl.setVoice(group.voices.first.id);
            }
          });
        }
        final rateIdx = _rateValues.indexOf(state.rate).clamp(0, 6);

        return Column(
          children: [
            Expanded(
              child: ListView(
                children: [
                  // --- selettore lingua ---
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                    child: Row(
                      children: [
                        Text('${t.createLanguage}: '),
                        const SizedBox(width: 8),
                        Expanded(
                          child: DropdownButton<String>(
                            isExpanded: true,
                            value: group.languageCode,
                            items: [
                              for (final g in groups)
                                DropdownMenuItem(
                                    value: g.languageCode,
                                    child: Text(g.languageName))
                            ],
                            onChanged: (code) {
                              if (code == null) return;
                              ctrl.setLanguage(code);
                              final g = groups
                                  .firstWhere((x) => x.languageCode == code);
                              if (g.voices.isNotEmpty) {
                                ctrl.setVoice(g.voices.first.id);
                              }
                            },
                          ),
                        ),
                      ],
                    ),
                  ),
                  // --- voci della lingua ---
                  RadioGroup<String>(
                    groupValue: state.voice,
                    onChanged: (v) => v == null ? null : ctrl.setVoice(v),
                    child: Column(
                      children: [
                        for (final v in group.voices)
                          RadioListTile<String>(
                            value: v.id,
                            title: Text(v.name),
                            subtitle: Text(v.gender),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            // --- slider velocità ---
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('${t.createSpeed}: ${_rateLabel(t, state.rate)}',
                      style: Theme.of(context).textTheme.bodyMedium),
                  Slider(
                    min: 0,
                    max: 6,
                    divisions: 6,
                    value: rateIdx.toDouble(),
                    label: _rateLabel(t, _rateValues[rateIdx]),
                    onChanged: (d) => ctrl.setRate(_rateValues[d.round()]),
                  ),
                ],
              ),
            ),
            // --- anteprima unica ---
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: OutlinedButton.icon(
                icon: _previewing != null
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.play_circle_outline),
                label: Text(t.createPreviewListen),
                onPressed: (state.voice == null || _previewing != null)
                    ? null
                    : _preview,
              ),
            ),
            // --- formato ---
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
            // --- avvia ---
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
                  onPressed: state.canSubmit ? _submit : null,
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}
```

Nota esecutore: questo file usa `RadioGroup<String>` (il pattern già adottato nel 3b-1). Se la versione Flutter installata non ha `RadioGroup`, usa `RadioListTile` con `groupValue`/`onChanged` per ogni tile (forma classica) — l'importante è la selezione singola. Verifica con `flutter analyze` (deve restare pulito). Il `addPostFrameCallback` allinea lo stato lingua/voce quando il libro non ha lingua o la voce non è ancora scelta: assicurati che non causi loop (è guardato dalle condizioni `!=`/`== null`).

- [ ] **Step 3: run + commit**

Run: `C:\flutter\bin\flutter.bat test` → tutti PASS (i widget del wizard aggiornati + resto invariato). `analyze` pulito.

```powershell
git add lib/app/create/steps/voice_format_step.dart test/widget/create_wizard_test.dart
git commit -m "feat(wizard): selezione lingua->voce, slider velocita, anteprima unica"
```

---

### Task 4 — Chiusura

- [ ] **Step 1: qualità**

Run: `C:\flutter\bin\dart.bat format .` → `flutter analyze` (No issues; correggi lint nostri senza cambi logica) → `flutter test` (tutti PASS, riporta numero).

- [ ] **Step 2: smoke build APK**

Run: `C:\flutter\bin\flutter.bat build apk --debug` → deve riuscire (se lock OneDrive su build/app/intermediates: Remove-Item e riprova).

- [ ] **Step 3: commit finale**

```powershell
git add -A
git commit -m "chore: format dopo refinement voce/velocita"
```

NON pushare senza conferma utente.

---

## Note per l'esecutore
- **Rate come stringa con segno** (`+10%`, `-20%`, `+0%`): identico al sito; `generate` e `downloadPreview` lo passano così.
- **Anteprima riflette la velocità**: `downloadPreview(..., rate: state.rate)`.
- **Solo voci edge** (3b-1): Google/PREMIUM restano per il 3b-2; non toccare `edgeGroups()`.
- **OneDrive**: lock noto su ios\Flutter\ephemeral e build/app/intermediates.
- **Stringhe**: mai nominare provider AI/TTS nella UI.
