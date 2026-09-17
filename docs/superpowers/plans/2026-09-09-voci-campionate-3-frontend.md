# Voci campionate — piano 3/3: frontend (wizard, combo, gestione, privacy)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dare all'utente il wizard «Campiona la tua voce» (condizioni, campione, pagamento, demo), la ripresa della procedura, il pannello «Le tue voci» e la presenza delle voci personali nella combo VoxCPM, sopra le API costruite nei piani 1 e 2.

**Architecture:** un nuovo file `static/js/voice_clone.js` con un nucleo puro (`VcCore`, testato con node:test) e un ramo DOM che pilota un modal a cinque pannelli; il markup vive in `html_head.html` accanto al box d'ascolto VoxCPM; `app.js` cambia in quattro punti chirurgici (capture PayPal con `captureJobId`, optgroup «Le tue voci», player mine-aware, errori di generazione `voice_*`); la logica di filtro delle voci personali sta in `audio_cascade.js` come funzione pura. Nessuna nuova dipendenza. Tutte le stringhe UI passano da `i18n_data.js` nelle sette lingue.

**Tech Stack:** vanilla JS (ES2018, niente bundler), MediaRecorder + Web Audio API per registrare, EventSource per l'avanzamento, `_openPayModalCtx` esistente per il pagamento, node:test per i test JS (wrapper pytest `test/test_js_cascade.py`), pytest per i test statici sul sorgente.

**Spec:** `docs/superpowers/specs/2026-09-09-voci-campionate-design.md` (§3 esperienza utente, §5.3 motivi di scarto, §6.4 codice-voce, §11 privacy). I piani precedenti: `docs/superpowers/plans/2026-09-09-voci-campionate-1-campione.md`, `docs/superpowers/plans/2026-09-09-voci-campionate-2-flusso.md`.

## Global Constraints

- **I contratti API sono quelli implementati nel piano 2, non la lettera della spec** quando divergono: l'id pubblico si chiama `clone_id` (la spec dice `sample_id`); il motivo di scarto della trascrizione e' `vc_gate_transcript` (la spec dice `vc_gate_text`) ed esistono anche `vc_gate_format` e `vc_gate_asr`; il record NON ha un nome dichiarato per le voci ricevute (spec §3.7 «Voce di <nome>»): le voci non proprie si etichettano con la stringa generica `vc_voice_shared`.
- Contratti (tutti gli errori sono `{error, error_code}`; 404 `voice_clone_disabled` quando la feature e' spenta):
  - `GET /api/voice_clone/config` → `{enabled, price_eur, free, max_upload_mb, regen_max, languages:{lang:[locale,...]}, min_sec, max_sec, asr}`.
  - `GET /api/voice_clone/prompt?lang=&gender=` (gender `m`|`f`) → `{text, version, lang, gender}`.
  - `POST /api/voice_clone/sample` multipart `file, lang, locale, gender` → `{clone_id, state:"sample_ok", expires_at, metrics, cer}`; 400 `sample_rejected` con `reason` in `vc_gate_short|long|noise|pauses|nopause|band|clip|transcript|format|asr`; 413 `too_large`; 503 `asr_unavailable`; 429 `rate_limited` (+`retry_after`).
  - `GET /api/voice_clone/<id>/sample.wav`; `GET /api/voice_clone/<id>/demo/<common|extra>`.
  - `GET /api/voice_clone/demo_texts?locale=` → `{common:{id,text}, extra:[{id,text},...]}`.
  - `POST /api/paypal_create_order_voice_clone` `{clone_id}` → `{order_id, amount_eur, status}`; capture via `POST /api/paypal_capture_order` `{order_id, job_id:"vc:"+clone_id}` → `{payment_token}`.
  - `POST /api/voucher_validate` `{code, email, purpose:"voice_clone", amount_eur}`.
  - `POST /api/voice_clone/commit` `{clone_id, email, email2, extra_id, payment_token}` → `{clone_id, voice_code, state:"paid", created}`; 400 `email_mismatch`/`bad_request`, 402 `payment_invalid`, 403 `not_authorized`, 404 `voice_not_found`, 409 `email_has_voice`, 410 `voice_gone`.
  - `GET /api/voice_clone/progress/<id>` SSE: ogni evento `data: <json>` e' la vista pubblica (`id, state, lang, locale, gender, created_at, expires_at, regen_left, extra_id, demo_urls{common,extra}` quando `demos_ready`/`ready`); il flusso chiude su `demos_ready|demo_failed|ready|refunded|expired|deleted` o dopo 1800 s.
  - `POST /api/voice_clone/<id>/approve|retry|reject` `{}` e `.../regenerate` `{extra_id}` → vista pubblica; 409 `regen_exhausted`/`bad_state`, 410 `voice_gone`, 403 `not_authorized`.
  - `GET /api/voice_clone/mine` → `{voices:[{...vista, owner:bool, pending:bool, voice_code (solo owner), demo_urls (solo ready), voice_id (solo ready)}]}` ordinate: pendenti in coda, poi piu' recenti prima.
  - `POST /api/voice_clone/claim` `{voice_code}` → `{status:"ok", voice}` | `{status:"pending"}`; 404 `code_unknown`, 423 `code_locked`, 429 `rate_limited`.
  - `POST /api/voice_clone/confirm` `{voice_code, confirm_code}` → `{status:"ok", voice}`; 400 `confirm_wrong`, 404 `confirm_none`/`code_unknown`, 410 `confirm_expired`, 423 `code_locked`.
  - `POST /api/voice_clone/<id>/forget` `{}` (409 `bad_state` sul dispositivo creatore); `POST /api/voice_clone/<id>/resend` `{}` (solo owner, 3 per 24 h → 429 `rate_limited`).
  - `GET /api/voices` porta `_voxcpm:{available, model_label, personas}` e `_mine` (stessa lista di `mine`).
  - `/api/generate` risponde 410 `voice_gone`, 403 `voice_not_authorized`, 400 `voice_lang_mismatch` per le voci `voxcpm:mine:*`.
- **Segreti**: il frontend non logga mai in console `voice_code`, codici di conferma, email; `voice_code` si mostra a schermo solo al proprietario (risposta di `commit` e voci `owner` di `mine`).
- **Niente nomi di fornitori** AI/TTS nelle stringhe utente. Il modello si chiama con `_voxcpm.model_label` o «voci PREMIUM».
- **Stringhe UI** solo in `templates/_fragments/i18n_data.js` con blocchi `Object.assign(L.<lang>,{...})` per `it,en,fr,es,de,zh,hi`; i fallback monolingua nel JS (`t(k)||'...'`) sono in inglese. Ogni chiave nuova va in tutte e sette le lingue con formulazione nativa, non traduzione parola per parola.
- **Testi UI vincolati dalla spec** (IT): bottone «Campiona la tua voce» con tooltip «Registra la tua voce per poter ottenere libri letti con essa»; «Le tue voci»; spunta «È la mia voce e ho il diritto di usarla»; indicazione «leggila di seguito, con calma, in 15-18 secondi»; attesa «da uno a quattro minuti»; «Va bene, avanti» / «Rifaccio»; «Approva» / «Rigenera» / «Rifiuta e chiedi rimborso»; «rigenerazioni rimaste: N»; «Riprova più tardi»; banner «Hai una voce campione in sospeso: riprendi»; «Aggiungi con codice-voce», «Rimuovi da questo dispositivo», «Rimanda l'email con il codice».
- **Registrazione**: MediaRecorder con `getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}})`, indicatore di livello, timer, stop automatico a 25 s. Upload: estensioni `wav,mp3,webm,opus,ogg,m4a,mp4`, dimensione ≤ `max_upload_mb` verificata anche lato client.
- **Nessuna cache**: la ripresa e il pannello «Le tue voci» rileggono `mine` a ogni apertura.
- **File CRLF**: `app.js`, `html_head.html`, `style.css`, `i18n_data.js`, `audiobook_app.py`, `privacy_content.py`, `seo_content.py` sono CRLF; modificare con un editor che conserva i fine riga (o Python in modalita' bytes) e verificare con `git diff --stat` che nessun file risulti riscritto per intero. I file nuovi (`voice_clone.js`, test, doc) nascono LF.
- **Commit**: Conventional Commits `type(scope): summary`, nessun trailer (no Co-Authored-By, no Claude-Session, no Generated-with). Stage solo per path espliciti (`git add <file>`, mai `-A`/`.`); `docs/*.md` e `md_files/*.md` sono gitignored → `git add -f`. Nessun file temporaneo nella radice del repo. Shell di sviluppo: PowerShell, un comando per volta.
- **Test**: ogni task termina con `python -m pytest <test del task> -q` verde; il wrapper JS e' `python -m pytest test/test_js_cascade.py -q` (richiede `node`); i test statici sul sorgente seguono lo stile di `test/test_voxcpm_frontend_assets.py` (`_estrai_funzione`, regex sul sorgente). La suite completa e' `python -m pytest test/ -q --deselect test/test_voxcpm_runpod.py::test_il_capitolo_inoltra_gli_avanzamenti --deselect test/test_voxcpm_runpod.py::test_l_interruttore_spegne_l_inoltro` (i due deselezionati falliscono solo per un file gitignored assente in locale).

## File structure

| File | Ruolo |
|------|-------|
| `static/js/audio_cascade.js` (modifica) | `vociMie(catalog, lang, locale)`: le voci personali pronte del dispositivo nella forma delle voci di catalogo (id, gender, demos, sample_url). Pura, esportata. |
| `static/js/voice_clone.js` (nuovo) | `VcCore` (funzioni pure: pannello per stato, chiave del motivo di scarto, controlli upload, visibilita' del bottone) + ramo DOM: bottone, modal a cinque pannelli, registratore, upload, pagamento, SSE, ripresa, gestione. Espone `window.vcSyncButton`, `window.vcOpen`, `window._vcJustCreated`. |
| `static/js/app.js` (modifica) | capture PayPal con `captureJobId`; `_openPayModalCtx` con `titleKey`/`noticeKey`; optgroup «Le tue voci» e preselezione; `_voxcpmSelectedVoice` mine-aware; `_handleVcGenerateError`; chiamate a `vcSyncButton()`. |
| `templates/_fragments/html_head.html` (modifica) | riga bottone + banner di ripresa dopo `#voxcpmSampleRow`; modal `#vcModal` dopo `#geminiPayModal`. |
| `templates/_fragments/html_tail.html` (modifica) | `<script defer src="/static/js/voice_clone.js?v=__APP_VERSION__">` prima di `app.js`. |
| `static/css/style.css` (modifica) | classi `vc-*` (frase guidata, riga registratore, lista voci). |
| `templates/_fragments/i18n_data.js` (modifica) | chiavi `vc_*` nelle sette lingue. |
| `test/js/voice_clone.test.js` (nuovo) | test node:test di `VcCore` e di `vociMie`. |
| `test/test_voice_clone_frontend.py` (nuovo) | test statici: markup, script tag, i18n parity, cablaggi in `app.js`. |
| `test/test_js_cascade.py` (modifica) | `TEST_ATTESI` alzato. |
| `privacy_content.py`, `seo_content.py` (modifica) | sezione privacy «Voci campionate» IT/EN + riga di riassunto per lingua. |
| `docs/MANUAL_TESTS_VOCI_CAMPIONATE.md` (nuovo) | collaudo manuale end-to-end. |
| `voice_clone.py`, `audiobook_app.py` (modifica) | `accepted_ext()` pubblico al posto di `voice_clone._ACCEPTED_EXT` letto dall'app. |

---

### Task 1: voci personali nella combo VoxCPM

**Files:**
- Modify: `static/js/audio_cascade.js` (dopo `vociPremium`, ~riga 108; export in coda ~riga 225-232)
- Modify: `static/js/app.js` (`_voxcpmSelectedVoice` ~1424, ramo VoxCPM di `updVoicesPremium` ~1591-1621)
- Modify: `templates/_fragments/i18n_data.js` (coda)
- Test: `test/js/voice_clone.test.js` (nuovo), `test/test_js_cascade.py`, `test/test_voice_clone_frontend.py` (nuovo)

**Interfaces:**
- Consumes: `voices._mine` (lista di `mine`), `voices[lang].voices`, `_voxcpmAccentSel`, `bookLangState.code`, `_voxcpmLocaleLabel(loc)`, `_loadVoxcpmSample()` (legge `v.demos=[{common,url}]` e `v.sample_url`).
- Produces: `vociMie(catalog, lang, locale)` → `[{id, clone_id, mine:true, owner, lang, locale, gender:'Female'|'Male', demos:[{common:true,url},{common:false,url}], sample_url}]`; variabile globale `window._vcJustCreated` (voice_id appena approvato, consumato alla prima popolazione); chiavi i18n `vc_group_mine`, `vc_voice_own`, `vc_voice_shared`.

- [ ] **Step 1: test node della funzione pura**

Crea `test/js/voice_clone.test.js`:

```js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {vociMie} = require('../../static/js/audio_cascade.js');

const CAT = {
  it: {voices: [{id: 'voxcpm:it-IT/Elena', locale: 'it-IT', gender: 'Female'}]},
  _voxcpm: {available: true, model_label: 'VoxCPM2', personas: {}},
  _mine: [
    {id: 'vc_a1', state: 'ready', voice_id: 'voxcpm:mine:TOKA', lang: 'it', locale: 'it-IT',
     gender: 'f', owner: true, pending: false,
     demo_urls: {common: '/api/voice_clone/vc_a1/demo/common', extra: '/api/voice_clone/vc_a1/demo/extra'}},
    {id: 'vc_b2', state: 'ready', voice_id: 'voxcpm:mine:TOKB', lang: 'it', locale: 'it-CH',
     gender: 'm', owner: false, pending: false,
     demo_urls: {common: '/api/voice_clone/vc_b2/demo/common', extra: '/api/voice_clone/vc_b2/demo/extra'}},
    {id: 'vc_c3', state: 'demos_ready', lang: 'it', locale: 'it-IT', gender: 'f', owner: true, pending: true},
    {id: 'vc_d4', state: 'ready', voice_id: 'voxcpm:mine:TOKD', lang: 'en', locale: 'en-US',
     gender: 'f', owner: true, pending: false, demo_urls: {common: '/c', extra: '/e'}},
  ],
};

test('vociMie: solo le voci pronte con lingua e accento coincidenti', () => {
  const out = vociMie(CAT, 'it', 'it-IT');
  assert.deepEqual(out.map(v => v.id), ['voxcpm:mine:TOKA']);
  assert.equal(out[0].mine, true);
  assert.equal(out[0].owner, true);
  assert.equal(out[0].clone_id, 'vc_a1');
  assert.equal(out[0].gender, 'Female');
  assert.equal(out[0].sample_url, '/api/voice_clone/vc_a1/sample.wav');
  assert.deepEqual(out[0].demos, [
    {common: true, url: '/api/voice_clone/vc_a1/demo/common'},
    {common: false, url: '/api/voice_clone/vc_a1/demo/extra'},
  ]);
});

test('vociMie: senza locale filtra solo per lingua', () => {
  assert.deepEqual(vociMie(CAT, 'it', '').map(v => v.id), ['voxcpm:mine:TOKA', 'voxcpm:mine:TOKB']);
  assert.equal(vociMie(CAT, 'it', '')[1].gender, 'Male');
});

test('vociMie: catalogo senza _mine o nullo -> lista vuota', () => {
  assert.deepEqual(vociMie({it: {voices: []}}, 'it', 'it-IT'), []);
  assert.deepEqual(vociMie(null, 'it', 'it-IT'), []);
  assert.deepEqual(vociMie({_mine: 'x'}, 'it', 'it-IT'), []);
});

test('vociMie: una voce pronta senza voice_id o senza demo non rompe', () => {
  const cat = {_mine: [{id: 'vc_z', state: 'ready', lang: 'it', locale: 'it-IT', gender: 'f'},
                       {id: 'vc_y', state: 'ready', voice_id: 'voxcpm:mine:Y', lang: 'it', locale: 'it-IT', gender: 'f'}]};
  const out = vociMie(cat, 'it', 'it-IT');
  assert.deepEqual(out.map(v => v.id), ['voxcpm:mine:Y']);
  assert.deepEqual(out[0].demos, []);
});
```

- [ ] **Step 2: eseguilo, deve fallire**

Run: `node --test "test/js/**/*.test.js"`
Expected: i quattro test `vociMie` falliscono con `TypeError: vociMie is not a function`; i 22 test della cascata restano verdi.

- [ ] **Step 3: implementa `vociMie` in `audio_cascade.js`**

Dopo `vociPremium` (prima di `_preserva`):

```js
/* Voci personali del dispositivo (voci campionate, spec §3.8): solo quelle
   pronte, con lingua e accento coincidenti, nella STESSA forma delle voci di
   catalogo — id, genere, clip demo, campione — cosi' la combo e i player di
   app.js non devono distinguere una voce campionata da una di catalogo.
   `locale` vuoto = qualunque accento della lingua. */
function vociMie(catalog, lang, locale) {
  const mine = (catalog && Array.isArray(catalog._mine)) ? catalog._mine : [];
  const out = [];
  for (const m of mine) {
    if (!m || m.state !== 'ready' || !m.voice_id) continue;
    if (lang && m.lang !== lang) continue;
    if (locale && m.locale !== locale) continue;
    const d = m.demo_urls || {};
    const demos = [];
    if (d.common) demos.push({common: true, url: d.common});
    if (d.extra) demos.push({common: false, url: d.extra});
    out.push({
      id: m.voice_id, clone_id: m.id, mine: true, owner: !!m.owner,
      lang: m.lang, locale: m.locale,
      gender: m.gender === 'f' ? 'Female' : 'Male',
      demos: demos,
      sample_url: '/api/voice_clone/' + m.id + '/sample.wav',
    });
  }
  return out;
}
```

Nell'export in coda aggiungi `vociMie` sia a `window` sia a `module.exports`:

```js
if (typeof window !== 'undefined') {
  window.resolveAudioSelection = resolveAudioSelection;
  window.modelliPer = modelliPer;
  window.vociMie = vociMie;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {resolveAudioSelection: resolveAudioSelection,
                    modelliPer: modelliPer, vociMie: vociMie};
}
```

(Se l'export attuale ha una forma diversa, aggiungi solo la riga `vociMie` mantenendo il resto.)

- [ ] **Step 4: verifica verde e alza il pavimento**

Run: `node --test "test/js/**/*.test.js"` → tutti verdi, riepilogo `tests 26`.
In `test/test_js_cascade.py` porta `TEST_ATTESI = 22` a `TEST_ATTESI = 26` e aggiorna il commento: il pavimento copre `audio_cascade.test.js` **e** `voice_clone.test.js`.
Run: `python -m pytest test/test_js_cascade.py -q` → 1 passed.

- [ ] **Step 5: chiavi i18n del gruppo**

In coda a `templates/_fragments/i18n_data.js` (nuovo blocco commentato `// Voci campionate: combo`):

```js
// Voci campionate: gruppo «Le tue voci» nella combo VoxCPM (spec §3.8)
Object.assign(L.it,{vc_group_mine:"Le tue voci",vc_voice_own:"La tua voce",vc_voice_shared:"Voce ricevuta"});
Object.assign(L.en,{vc_group_mine:"Your voices",vc_voice_own:"Your voice",vc_voice_shared:"Shared voice"});
Object.assign(L.fr,{vc_group_mine:"Vos voix",vc_voice_own:"Votre voix",vc_voice_shared:"Voix reçue"});
Object.assign(L.es,{vc_group_mine:"Tus voces",vc_voice_own:"Tu voz",vc_voice_shared:"Voz recibida"});
Object.assign(L.de,{vc_group_mine:"Deine Stimmen",vc_voice_own:"Deine Stimme",vc_voice_shared:"Erhaltene Stimme"});
Object.assign(L.zh,{vc_group_mine:"你的声音",vc_voice_own:"你的声音",vc_voice_shared:"收到的声音"});
Object.assign(L.hi,{vc_group_mine:"आपकी आवाज़ें",vc_voice_own:"आपकी आवाज़",vc_voice_shared:"साझा की गई आवाज़"});
```

- [ ] **Step 6: test statici sul cablaggio in `app.js`**

Crea `test/test_voice_clone_frontend.py`:

```python
"""Il wizard «Campiona la tua voce» e le voci personali nella combo: markup,
script, i18n e cablaggi in app.js. Asserzioni statiche sul sorgente, come
test_voxcpm_frontend_assets.py; la logica pura gira in test/js/."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
TAIL = (ROOT / "templates/_fragments/html_tail.html").read_text(encoding="utf-8")
JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
CASCATA = (ROOT / "static/js/audio_cascade.js").read_text(encoding="utf-8")
I18N = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
VC_PATH = ROOT / "static/js/voice_clone.js"

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]


def _estrai_funzione(src, nome):
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    assert m, "funzione %s non trovata" % nome
    apertura = src.index("{", m.end())
    profondita = 0
    for i in range(apertura, len(src)):
        if src[i] == "{":
            profondita += 1
        elif src[i] == "}":
            profondita -= 1
            if profondita == 0:
                return src[apertura:i + 1]
    raise AssertionError("corpo non bilanciato: %s" % nome)


def _chiavi_i18n(lang):
    chiavi = set()
    for blocco in re.findall(r"Object\.assign\(L\." + lang + r",\{(.*?)\}\);", I18N, re.S):
        chiavi.update(re.findall(r"(?:^|,)\s*([a-z_0-9]+)\s*:", blocco))
    return chiavi


def test_vociMie_esportata():
    assert "function vociMie(" in CASCATA
    assert re.search(r"module\.exports\s*=\s*\{[^}]*vociMie", CASCATA, re.S)
    assert "window.vociMie = vociMie" in CASCATA


def test_combo_voxcpm_mette_le_voci_personali_in_testa():
    corpo = _estrai_funzione(JS, "updVoicesPremium")
    ramo = corpo[corpo.index("vmEl.value==='voxcpm'"):corpo.index("simba-3.2")]
    assert "vociMie(" in ramo
    assert "t('vc_group_mine')" in ramo
    assert ramo.index("vc_group_mine") < ramo.index("'♀'"), "il gruppo Le tue voci deve precedere i gruppi di catalogo"
    assert "_vcJustCreated" in ramo


def test_voce_selezionata_cerca_anche_le_voci_personali():
    corpo = _estrai_funzione(JS, "_voxcpmSelectedVoice")
    assert "vociMie(" in corpo


def test_chiavi_combo_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        for k in ("vc_group_mine", "vc_voice_own", "vc_voice_shared"):
            assert k in chiavi, f"{k} manca in {lang}"
```

Run: `python -m pytest test/test_voice_clone_frontend.py -q` → i tre test su `app.js` falliscono (`vociMie(` assente), `test_vociMie_esportata` e i18n passano.

- [ ] **Step 7: `_voxcpmSelectedVoice` mine-aware e optgroup in `updVoicesPremium`**

Sostituisci `_voxcpmSelectedVoice`:

```js
function _voxcpmSelectedVoice(){
  const sel=document.getElementById('vvPremium');
  const id=sel?sel.value:'';
  if(!_isVoxcpmVoiceId(id))return null;
  for(const v of _voxcpmVoicesForLang())if(v.id===id)return v;
  // Voci personali (campionate): stessa forma delle voci di catalogo.
  const mie=(typeof vociMie==='function')?vociMie(voices,bookLangState.code||'it',''):[];
  for(const v of mie)if(v.id===id)return v;
  return null;
}
```

Nel ramo VoxCPM di `updVoicesPremium`, subito dopo `sel.innerHTML='';` e prima del ciclo `for(const v of lista)`, inserisci:

```js
    // Le voci personali del dispositivo con lingua e accento coincidenti
    // stanno in un gruppo in testa (spec §3.8). Se ce n'e' una sola ed e' la
    // prima popolazione dopo la creazione, e' preselezionata.
    const mie=(typeof vociMie==='function')?vociMie(voices,bookLangState.code||'it',loc):[];
    if(mie.length){
      const gm=document.createElement('optgroup');
      gm.label=t('vc_group_mine');
      for(const v of mie){
        const o=document.createElement('option');
        o.value=v.id;
        o.textContent=(v.owner?t('vc_voice_own'):t('vc_voice_shared'))+' · '+_voxcpmLocaleLabel(v.locale);
        gm.appendChild(o);
      }
      sel.appendChild(gm);
    }
    if(window._vcJustCreated&&mie.length===1&&mie[0].id===window._vcJustCreated){
      prevVoice=window._vcJustCreated;window._vcJustCreated=null;
    }
```

e cambia `const prevVoice=_voxcpmVoiceSel||sel.value;` in `let prevVoice=_voxcpmVoiceSel||sel.value;` (la riga sta PRIMA di `sel.innerHTML=''`: lasciala li'). Il ciclo del catalogo resta com'e': crea i propri optgroup ♀/♂ dopo quello delle voci personali; `sel.lastElementChild.appendChild(o)` continua a funzionare perche' ogni voce di catalogo e' preceduta dal proprio optgroup.

Alla fine del ramo, prima del `return;`, aggiungi `if(typeof vcSyncButton==='function')vcSyncButton();` (la funzione arriva col Task 2; il guard la rende innocua ora).

- [ ] **Step 8: verifica**

Run: `python -m pytest test/test_voice_clone_frontend.py test/test_voxcpm_frontend_assets.py test/test_js_cascade.py test/test_voxcpm_i18n.py -q` → tutti verdi.
Run: `node --check static/js/app.js` e `node --check static/js/audio_cascade.js` → nessun errore.
`git diff --stat` → `app.js`, `audio_cascade.js`, `i18n_data.js` con poche righe cambiate (non riscritti).

- [ ] **Step 9: commit**

```
git add static/js/audio_cascade.js static/js/app.js templates/_fragments/i18n_data.js test/js/voice_clone.test.js test/test_js_cascade.py test/test_voice_clone_frontend.py
git commit -m "feat(voice-clone): le voci personali entrano nella combo VoxCPM"
```

---

### Task 2: bottone, modal, nucleo `VcCore` e pannello condizioni

**Files:**
- Create: `static/js/voice_clone.js`
- Modify: `templates/_fragments/html_head.html` (dopo `#voxcpmSampleRow`, ~riga 544; dopo `#geminiPayModal`, ~riga 1155)
- Modify: `templates/_fragments/html_tail.html` (righe 1-4, script tag)
- Modify: `static/css/style.css` (coda)
- Modify: `static/js/app.js` (`_onPremiumModelChanged` ~1288, `switchAudioTab` ~1803)
- Modify: `templates/_fragments/i18n_data.js` (coda)
- Test: `test/js/voice_clone.test.js`, `test/test_voice_clone_frontend.py`, `test/test_js_cascade.py`

**Interfaces:**
- Consumes: `GET /api/voice_clone/config`, `GET /api/voice_clone/mine`, `t()`, `applyI18n()`, `voices._voxcpm.available`, `bookLangState.code`, `document.getElementById('vmPremium').value==='voxcpm'`, tab premium attiva (`document.getElementById('tabPremium')` con classe `active` — verificare il nome reale nel markup di `switchAudioTab` e usare quello).
- Produces: `window.VcCore` (funzioni pure), `window.vcSyncButton()`, `window.vcOpen(panel)`, `window.vcRefreshMine()` → Promise<lista mine>, `window._vcJustCreated`, `window._vcState = {cfg, mine, cur:{clone_id, view, voice_code}, media}`; ids DOM: `#vcBtnRow #vcOpenBtn #vcResumeBanner #vcResumeBtn #vcModal #vcClose #vcErr #vcP1 #vcConsent #vcP1Next #vcP1Cancel #vcP2 #vcP3 #vcP4 #vcPMine`; chiavi i18n `vc_*` di questo task.

- [ ] **Step 1: test node del nucleo puro**

Aggiungi in coda a `test/js/voice_clone.test.js`:

```js
const VcCore = require('../../static/js/voice_clone.js');

test('vcPanelFor: lo stato del record decide il pannello di ripresa', () => {
  assert.equal(VcCore.vcPanelFor('sample_ok'), 3);
  for (const s of ['paid', 'demos_generating', 'demos_ready', 'demo_failed']) assert.equal(VcCore.vcPanelFor(s), 4);
  for (const s of ['ready', 'refunded', 'expired', 'deleted', '', undefined]) assert.equal(VcCore.vcPanelFor(s), 0);
});

test('vcGateKey: motivo di scarto -> chiave i18n, generico per i motivi ignoti', () => {
  assert.equal(VcCore.vcGateKey('short'), 'vc_gate_short');
  assert.equal(VcCore.vcGateKey('transcript'), 'vc_gate_transcript');
  assert.equal(VcCore.vcGateKey('asr'), 'vc_gate_asr');
  assert.equal(VcCore.vcGateKey('boh'), 'vc_gate_generic');
  assert.equal(VcCore.vcGateKey(''), 'vc_gate_generic');
});

test('vcPending: la prima voce in sospeso, altrimenti null', () => {
  const p = {id: 'vc_1', pending: true, state: 'sample_ok'};
  assert.equal(VcCore.vcPending([{id: 'vc_0', pending: false, state: 'ready'}, p]), p);
  assert.equal(VcCore.vcPending([{id: 'vc_0', pending: false, state: 'ready'}]), null);
  assert.equal(VcCore.vcPending(null), null);
});

test('vcButtonKey: crea, gestisci o riprendi', () => {
  assert.equal(VcCore.vcButtonKey([]), 'vc_btn_start');
  assert.equal(VcCore.vcButtonKey([{pending: false, state: 'ready'}]), 'vc_btn_mine');
  assert.equal(VcCore.vcButtonKey([{pending: true, state: 'paid'}]), 'vc_btn_resume');
});

test('vcVisible: solo con feature attiva, modello disponibile e lingua offerta', () => {
  const cfg = {enabled: true, languages: {it: ['it-IT'], en: ['en-US']}};
  assert.equal(VcCore.vcVisible(cfg, true, 'it'), true);
  assert.equal(VcCore.vcVisible(cfg, true, 'de'), false);
  assert.equal(VcCore.vcVisible(cfg, false, 'it'), false);
  assert.equal(VcCore.vcVisible({enabled: false, languages: {it: []}}, true, 'it'), false);
  assert.equal(VcCore.vcVisible(null, true, 'it'), false);
});

test('vcUploadCheck: estensione ammessa e dimensione entro il tetto', () => {
  assert.deepEqual(VcCore.vcUploadCheck('voce.WAV', 1000, 20), {ok: true, ext: 'wav'});
  assert.deepEqual(VcCore.vcUploadCheck('voce.m4a', 1000, 20), {ok: true, ext: 'm4a'});
  assert.deepEqual(VcCore.vcUploadCheck('voce.flac', 1000, 20), {ok: false, reason: 'format'});
  assert.deepEqual(VcCore.vcUploadCheck('senzaestensione', 1000, 20), {ok: false, reason: 'format'});
  assert.deepEqual(VcCore.vcUploadCheck('voce.mp3', 21 * 1024 * 1024, 20), {ok: false, reason: 'too_large'});
});

test('vcRecordExt: dal mimeType del registratore all estensione del file', () => {
  assert.equal(VcCore.vcRecordExt('audio/webm;codecs=opus'), 'webm');
  assert.equal(VcCore.vcRecordExt('audio/mp4'), 'mp4');
  assert.equal(VcCore.vcRecordExt('audio/ogg;codecs=opus'), 'ogg');
  assert.equal(VcCore.vcRecordExt(''), 'webm');
});

test('vcRegenAllowed: solo con rigenerazioni residue', () => {
  assert.equal(VcCore.vcRegenAllowed({regen_left: 2}), true);
  assert.equal(VcCore.vcRegenAllowed({regen_left: 0}), false);
  assert.equal(VcCore.vcRegenAllowed({}), false);
});

test('vcHasReadyFor: una voce pronta nella lingua', () => {
  const mine = [{state: 'ready', lang: 'it', voice_id: 'x'}, {state: 'paid', lang: 'en'}];
  assert.equal(VcCore.vcHasReadyFor(mine, 'it'), true);
  assert.equal(VcCore.vcHasReadyFor(mine, 'en'), false);
});
```

Run: `node --test "test/js/**/*.test.js"` → i nuovi test falliscono (`Cannot find module '../../static/js/voice_clone.js'`).

- [ ] **Step 2: crea `static/js/voice_clone.js` con il nucleo e lo scheletro DOM**

```js
/* Voci campionate (spec docs/superpowers/specs/2026-09-09-voci-campionate-design.md §3):
   bottone «Campiona la tua voce», modal a cinque pannelli, registratore,
   pagamento, avanzamento, ripresa e gestione «Le tue voci».
   La parte pura (VcCore) non tocca il DOM ed e' testata con node:test;
   il ramo DOM parte solo nel browser. Caricato prima di app.js: app.js
   chiama vcSyncButton() dopo ogni cambio di modello/lingua/tab. */
(function () {
  'use strict';

  /* ---------- nucleo puro ---------- */

  var GATE_REASONS = ['short', 'long', 'noise', 'pauses', 'nopause', 'band', 'clip', 'transcript', 'format', 'asr'];
  var ACCEPTED_EXT = ['wav', 'mp3', 'webm', 'opus', 'ogg', 'm4a', 'mp4'];

  function vcPanelFor(state) {
    if (state === 'sample_ok') return 3;
    if (state === 'paid' || state === 'demos_generating' || state === 'demos_ready' || state === 'demo_failed') return 4;
    return 0;
  }

  function vcGateKey(reason) {
    return GATE_REASONS.indexOf(reason) >= 0 ? 'vc_gate_' + reason : 'vc_gate_generic';
  }

  function vcPending(mine) {
    if (!Array.isArray(mine)) return null;
    for (var i = 0; i < mine.length; i++) if (mine[i] && mine[i].pending) return mine[i];
    return null;
  }

  function vcHasReadyFor(mine, lang) {
    if (!Array.isArray(mine)) return false;
    for (var i = 0; i < mine.length; i++) {
      var m = mine[i];
      if (m && m.state === 'ready' && m.voice_id && m.lang === lang) return true;
    }
    return false;
  }

  function vcButtonKey(mine) {
    if (vcPending(mine)) return 'vc_btn_resume';
    return (Array.isArray(mine) && mine.length) ? 'vc_btn_mine' : 'vc_btn_start';
  }

  function vcVisible(cfg, voxAvailable, lang) {
    if (!cfg || !cfg.enabled || !voxAvailable) return false;
    var langs = cfg.languages || {};
    return Array.isArray(langs[lang]) && langs[lang].length > 0;
  }

  function vcUploadCheck(name, size, maxMb) {
    var m = /\.([A-Za-z0-9]+)$/.exec(name || '');
    var ext = m ? m[1].toLowerCase() : '';
    if (ACCEPTED_EXT.indexOf(ext) < 0) return {ok: false, reason: 'format'};
    if (size > maxMb * 1024 * 1024) return {ok: false, reason: 'too_large'};
    return {ok: true, ext: ext};
  }

  function vcRecordExt(mime) {
    var base = String(mime || '').split(';')[0].trim();
    if (base === 'audio/mp4') return 'mp4';
    if (base === 'audio/ogg') return 'ogg';
    return 'webm';
  }

  function vcRegenAllowed(view) {
    return !!(view && Number(view.regen_left) > 0);
  }

  var VcCore = {
    vcPanelFor: vcPanelFor, vcGateKey: vcGateKey, vcPending: vcPending,
    vcHasReadyFor: vcHasReadyFor, vcButtonKey: vcButtonKey, vcVisible: vcVisible,
    vcUploadCheck: vcUploadCheck, vcRecordExt: vcRecordExt, vcRegenAllowed: vcRegenAllowed,
    ACCEPTED_EXT: ACCEPTED_EXT,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = VcCore;
  if (typeof window === 'undefined') return;
  window.VcCore = VcCore;

  /* ---------- ramo DOM ---------- */

  var S = {cfg: null, mine: [], cur: null, media: null, es: null};
  window._vcState = S;
  window._vcJustCreated = null;

  function $(id) { return document.getElementById(id); }
  function tt(k, r) { return (typeof t === 'function') ? t(k, r) : k; }

  function vcErr(msg) {
    var e = $('vcErr');
    if (!e) return;
    if (!msg) { e.hidden = true; e.textContent = ''; return; }
    e.textContent = msg; e.hidden = false;
  }

  /* Messaggio per una risposta d'errore dell'API: chiave i18n per codice,
     altrimenti il testo generico. Mai il testo grezzo del server. */
  function vcApiErrMsg(d, fallbackKey) {
    var code = d && d.error_code;
    if (code === 'rate_limited') return tt('vc_err_rate_limited', {n: (d && d.retry_after) || 60});
    if (code === 'sample_rejected') return tt(vcGateKey(d.reason));
    var k = code ? 'vc_err_' + code : (fallbackKey || 'vc_err_generic');
    var s = tt(k);
    return (s && s !== k) ? s : tt(fallbackKey || 'vc_err_generic');
  }

  function vcFetch(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        return {ok: r.ok, status: r.status, data: d};
      });
    });
  }

  function vcPost(url, body) {
    return vcFetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  }

  function vcRefreshMine() {
    return vcFetch('/api/voice_clone/mine').then(function (r) {
      S.mine = (r.ok && Array.isArray(r.data.voices)) ? r.data.voices : [];
      return S.mine;
    }).catch(function () { S.mine = []; return S.mine; });
  }
  window.vcRefreshMine = vcRefreshMine;

  function vcLang() {
    return (typeof bookLangState === 'object' && bookLangState && bookLangState.code) ? bookLangState.code : 'it';
  }

  function vcVoxSelected() {
    var vm = $('vmPremium');
    var tab = $('tabPremium');
    var voxOk = (typeof voices === 'object' && voices && voices._voxcpm && voices._voxcpm.available);
    return !!(vm && vm.value === 'voxcpm' && voxOk && (!tab || tab.classList.contains('active')));
  }

  /* Il bottone compare solo con il modello VoxCPM scelto sulla scheda PREMIUM,
     feature attiva e lingua del libro offerta; l'etichetta segue lo stato. */
  function vcSyncButton() {
    var row = $('vcBtnRow'); var btn = $('vcOpenBtn'); var banner = $('vcResumeBanner');
    if (!row || !btn) return;
    var show = vcVoxSelected() && vcVisible(S.cfg, true, vcLang());
    row.hidden = !show;
    if (!show) { if (banner) banner.hidden = true; return; }
    btn.textContent = tt(vcButtonKey(S.mine));
    btn.title = tt('vc_btn_tip');
    if (banner) banner.hidden = !vcPending(S.mine);
  }
  window.vcSyncButton = vcSyncButton;

  function vcShow(n) {
    ['vcP1', 'vcP2', 'vcP3', 'vcP4', 'vcPMine'].forEach(function (id) { var e = $(id); if (e) e.hidden = true; });
    var id = n === 'mine' ? 'vcPMine' : 'vcP' + n;
    var e = $(id); if (e) e.hidden = false;
    vcErr('');
    var m = $('vcModal'); if (m) m.hidden = false;
    var hooks = S.panelHooks || {};
    if (typeof hooks[id] === 'function') hooks[id]();
  }
  window.vcShow = vcShow;

  function vcClose() {
    var m = $('vcModal'); if (m) m.hidden = true;
    if (S.es) { try { S.es.close(); } catch (e) {} S.es = null; }
    if (typeof S.stopMedia === 'function') S.stopMedia();
  }
  window.vcClose = vcClose;

  /* Apre il wizard dal bottone: in sospeso -> pannello dello stato;
     con voci -> «Le tue voci»; altrimenti condizioni. */
  function vcOpen(force) {
    vcRefreshMine().then(function (mine) {
      if (force) return vcShow(force);
      var p = vcPending(mine);
      if (p) return vcResume(p.id);
      vcShow(mine.length ? 'mine' : 1);
    });
  }
  window.vcOpen = vcOpen;

  /* Ripresa di una procedura: rilegge la vista e apre il pannello dello stato. */
  function vcResume(cloneId) {
    var rec = null;
    for (var i = 0; i < S.mine.length; i++) if (S.mine[i].id === cloneId) rec = S.mine[i];
    if (!rec) return vcShow(1);
    S.cur = {clone_id: rec.id, view: rec, voice_code: rec.voice_code || null};
    var n = vcPanelFor(rec.state);
    if (n === 0) return vcShow('mine');
    vcShow(n);
  }
  window.vcResume = vcResume;

  function vcInitPanel1() {
    var c = $('vcConsent'); var next = $('vcP1Next');
    if (!c || !next) return;
    c.checked = false; next.disabled = true;
    c.onchange = function () { next.disabled = !c.checked; };
    next.onclick = function () { if (c.checked) vcShow(2); };
    var cancel = $('vcP1Cancel'); if (cancel) cancel.onclick = vcClose;
    var price = $('vcP1Price');
    if (price && S.cfg) price.textContent = S.cfg.free ? tt('vc_price_free') : tt('vc_price', {p: Number(S.cfg.price_eur).toFixed(2)});
  }

  function vcInit() {
    var btn = $('vcOpenBtn'); if (btn) btn.onclick = function () { vcOpen(); };
    var rb = $('vcResumeBtn'); if (rb) rb.onclick = function () { vcOpen(); };
    var close = $('vcClose'); if (close) close.onclick = vcClose;
    var modal = $('vcModal');
    if (modal) modal.addEventListener('click', function (ev) { if (ev.target === modal) vcClose(); });
    S.panelHooks = S.panelHooks || {};
    S.panelHooks.vcP1 = vcInitPanel1;
    vcFetch('/api/voice_clone/config').then(function (r) {
      S.cfg = r.ok ? r.data : null;
      return vcRefreshMine();
    }).then(function () {
      vcSyncButton();
      var q = new URLSearchParams(location.search);
      var vc = q.get('vc');
      if (vc) {
        q.delete('vc');
        var qs = q.toString();
        history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
        S.resumeId = vc;
      }
    }).catch(function () { S.cfg = null; });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', vcInit);
  else vcInit();
})();
```

Nota: `S.resumeId` viene consumato nel Task 6 (dopo che `app.js` ha popolato la combo). Il modal e' il `.modal-backdrop` gia' stilizzato per `#geminiPayModal`.

- [ ] **Step 3: verifica i test node**

Run: `node --test "test/js/**/*.test.js"` → tutti verdi (`tests 35`). Porta `TEST_ATTESI` in `test/test_js_cascade.py` a `35`.

- [ ] **Step 4: markup**

In `templates/_fragments/html_head.html`, subito dopo la chiusura di `#voxcpmSampleRow` (prima di `<details class="adv-options" id="advOptions">`):

```html
<div id="vcBtnRow" class="vc-btn-row" hidden>
  <button type="button" id="vcOpenBtn" class="btn-outline btn-sm vc-open-btn" data-t="vc_btn_start" data-t-title="vc_btn_tip">Sample your voice</button>
  <div id="vcResumeBanner" class="al al-i vc-resume" hidden>
    <span data-t="vc_resume_banner">You have a pending voice sample:</span>
    <button type="button" id="vcResumeBtn" class="btn-outline btn-sm" data-t="vc_resume_btn">resume</button>
  </div>
</div>
```

Dopo la chiusura di `#geminiPayModal`:

```html
<div id="vcModal" class="modal-backdrop" hidden>
  <div class="modal payment-modal vc-modal" role="dialog" aria-modal="true" aria-labelledby="vcTitle">
    <header class="modal-header">
      <h3 id="vcTitle" data-t="vc_title">Sample your voice</h3>
      <button type="button" id="vcClose" class="modal-close" aria-label="Close">&times;</button>
    </header>
    <div class="modal-body">
      <div id="vcErr" class="al al-e" hidden></div>

      <section id="vcP1" hidden>
        <p data-t-html="vc_p1_intro"></p>
        <ul class="vc-terms">
          <li data-t="vc_p1_t1"></li>
          <li data-t="vc_p1_t2"></li>
          <li data-t="vc_p1_t3"></li>
          <li data-t="vc_p1_t4"></li>
          <li data-t="vc_p1_t5"></li>
        </ul>
        <p class="vc-price"><span data-t="vc_p1_price_lbl"></span> <strong id="vcP1Price"></strong></p>
        <label class="vc-consent"><input type="checkbox" id="vcConsent"> <span data-t="vc_consent"></span></label>
        <div class="modal-footer vc-footer">
          <button type="button" id="vcP1Cancel" class="btn-secondary" data-t="vc_cancel"></button>
          <button type="button" id="vcP1Next" class="btn-primary" data-t="vc_next" disabled></button>
        </div>
      </section>

      <section id="vcP2" hidden></section>
      <section id="vcP3" hidden></section>
      <section id="vcP4" hidden></section>
      <section id="vcPMine" hidden></section>
    </div>
  </div>
</div>
```

(I pannelli 2-4 e «Le tue voci» si riempiono nei Task 3-6.) Se `#geminiPayModal` non ha una classe `.modal-close` per il bottone di chiusura, usa la classe che usa lui e adegua il CSS.

In `templates/_fragments/html_tail.html` aggiungi, prima della riga di `app.js`:

```html
<script defer src="/static/js/voice_clone.js?v=__APP_VERSION__"></script>
```

- [ ] **Step 5: CSS**

In coda a `static/css/style.css`:

```css
/* Voci campionate */
.vc-btn-row{margin:.6rem 0 0;display:flex;flex-direction:column;gap:.5rem}
.vc-open-btn{width:100%}
.vc-resume{display:flex;justify-content:space-between;align-items:center;gap:.5rem;flex-wrap:wrap}
.vc-modal{max-width:560px}
.vc-modal .modal-body{max-height:70vh;overflow-y:auto}
.vc-terms{padding-left:1.2rem;margin:.5rem 0}
.vc-terms li{margin:.25rem 0}
.vc-consent{display:flex;gap:.5rem;align-items:flex-start;margin:.8rem 0;font-weight:600}
.vc-footer{display:flex;justify-content:flex-end;gap:.5rem;margin-top:1rem;padding:0;border:0}
.vc-prompt{background:var(--bg-soft,#f5f5f7);border-radius:8px;padding:.8rem;font-size:1.05rem;line-height:1.5;margin:.6rem 0}
.vc-rec-row{display:flex;align-items:center;gap:.6rem;margin:.6rem 0;flex-wrap:wrap}
.vc-rec-row meter{flex:1;min-width:120px;height:14px}
.vc-timer{font-variant-numeric:tabular-nums;min-width:3.5em}
.vc-rec-dot{width:12px;height:12px;border-radius:50%;background:#c33;display:inline-block;animation:vcblink 1s infinite}
@keyframes vcblink{50%{opacity:.2}}
.vc-code{font-family:monospace;font-size:1.3rem;letter-spacing:.15em;background:var(--bg-soft,#f5f5f7);padding:.5rem .8rem;border-radius:8px;display:inline-block;margin:.4rem 0}
.vc-demo-row{display:flex;flex-direction:column;gap:.4rem;margin:.6rem 0}
.vc-demo-row audio{width:100%}
.vc-mine-list{list-style:none;padding:0;margin:.5rem 0}
.vc-mine-item{border:1px solid var(--border,#ddd);border-radius:8px;padding:.6rem;margin:.4rem 0}
.vc-mine-item .vc-actions{display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.4rem}
.vc-claim-row{display:flex;gap:.4rem;flex-wrap:wrap;margin:.5rem 0}
.vc-claim-row input{flex:1;min-width:160px}
.vc-wait{display:flex;align-items:center;gap:.6rem;margin:.6rem 0}
```

- [ ] **Step 6: chiavi i18n del Task 2**

Aggiungi in coda a `i18n_data.js` (blocco `// Voci campionate: bottone, modal, condizioni`). IT ed EN sono vincolanti; fr/es/de/zh/hi vanno scritte dall'implementatore con formulazione nativa, stesse chiavi:

```js
// Voci campionate: bottone, modal, condizioni (spec §3.1-3.2)
Object.assign(L.it,{
vc_btn_start:"Campiona la tua voce",
vc_btn_mine:"Le tue voci",
vc_btn_resume:"Riprendi il campionamento",
vc_btn_tip:"Registra la tua voce per poter ottenere libri letti con essa",
vc_resume_banner:"Hai una voce campione in sospeso:",
vc_resume_btn:"riprendi",
vc_title:"Campiona la tua voce",
vc_p1_intro:"Registri 15-18 secondi della tua voce leggendo una frase; dopo il pagamento ascolti due brani letti con la tua voce e decidi se tenerla. Prima leggi queste condizioni.",
vc_p1_t1:"Campiona solo la tua voce: con la spunta dichiari che è tua e che hai il diritto di usarla.",
vc_p1_t2:"Il campione viene analizzato e trascritto automaticamente per verificarne la qualità; i dati vocali sono trattati come spiegato nell'informativa privacy.",
vc_p1_t3:"Dopo il pagamento ricevi due brani di prova: se non ti convincono puoi rigenerarli o chiedere il rimborso.",
vc_p1_t4:"La voce resta disponibile su questo dispositivo e su quelli che aggiungerai con il codice-voce; puoi eliminarla quando vuoi dal link nell'email.",
vc_p1_t5:"La voce scade dopo un periodo di inattività: te lo ricordiamo via email prima della scadenza.",
vc_p1_price_lbl:"Costo:",
vc_price:"€ {p}",
vc_price_free:"gratis",
vc_consent:"È la mia voce e ho il diritto di usarla",
vc_next:"Avanti",
vc_cancel:"Annulla",
vc_back:"Indietro",
vc_close:"Chiudi",
vc_err_generic:"Qualcosa non ha funzionato. Riprova.",
vc_err_rate_limited:"Troppi tentativi: riprova tra {n} secondi.",
vc_err_voice_clone_disabled:"Il campionamento vocale non è disponibile al momento."
});
Object.assign(L.en,{
vc_btn_start:"Sample your voice",
vc_btn_mine:"Your voices",
vc_btn_resume:"Resume voice sampling",
vc_btn_tip:"Record your voice to get books read with it",
vc_resume_banner:"You have a pending voice sample:",
vc_resume_btn:"resume",
vc_title:"Sample your voice",
vc_p1_intro:"Record 15-18 seconds of your voice reading a sentence; after payment you listen to two passages read with your voice and decide whether to keep it. Read these terms first.",
vc_p1_t1:"Sample only your own voice: by ticking the box you declare it is yours and you have the right to use it.",
vc_p1_t2:"The sample is analysed and transcribed automatically to check its quality; voice data is handled as described in the privacy notice.",
vc_p1_t3:"After payment you get two trial passages: if they do not convince you, you can regenerate them or ask for a refund.",
vc_p1_t4:"The voice stays available on this device and on those you add with the voice code; you can delete it at any time from the link in the email.",
vc_p1_t5:"The voice expires after a period of inactivity: we remind you by email before it does.",
vc_p1_price_lbl:"Cost:",
vc_price:"€ {p}",
vc_price_free:"free",
vc_consent:"This is my voice and I have the right to use it",
vc_next:"Next",
vc_cancel:"Cancel",
vc_back:"Back",
vc_close:"Close",
vc_err_generic:"Something went wrong. Please try again.",
vc_err_rate_limited:"Too many attempts: try again in {n} seconds.",
vc_err_voice_clone_disabled:"Voice sampling is not available right now."
});
// + Object.assign(L.fr,{...}), L.es, L.de, L.zh, L.hi con le stesse 24 chiavi
```

Verifica che `t()` sostituisca `{p}` e `{n}`: leggi `t(k, replacements)` in `app.js` (~riga 165) e usa la stessa sintassi dei segnaposto che usa (se e' `{p}` bene, altrimenti adegua le stringhe).

- [ ] **Step 7: cablaggi in `app.js`**

In `_onPremiumModelChanged`, come ultima istruzione: `if(typeof vcSyncButton==='function')vcSyncButton();`.
In `switchAudioTab`, come ultima istruzione: `if(typeof vcSyncButton==='function')vcSyncButton();`.
(Il ramo VoxCPM di `updVoicesPremium` lo chiama gia' dal Task 1.)

- [ ] **Step 8: test statici**

Aggiungi a `test/test_voice_clone_frontend.py`:

```python
VC = VC_PATH.read_text(encoding="utf-8")
CSS = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

TASK2_KEYS = ["vc_btn_start", "vc_btn_mine", "vc_btn_resume", "vc_btn_tip", "vc_resume_banner",
              "vc_resume_btn", "vc_title", "vc_p1_intro", "vc_p1_t1", "vc_p1_t2", "vc_p1_t3",
              "vc_p1_t4", "vc_p1_t5", "vc_p1_price_lbl", "vc_price", "vc_price_free", "vc_consent",
              "vc_next", "vc_cancel", "vc_back", "vc_close", "vc_err_generic",
              "vc_err_rate_limited", "vc_err_voice_clone_disabled"]


def test_script_voice_clone_prima_di_app():
    assert 'src="/static/js/voice_clone.js?v=__APP_VERSION__"' in TAIL
    assert TAIL.index("voice_clone.js") < TAIL.index("/static/js/app.js")


def test_markup_bottone_e_modal():
    for i in ("vcBtnRow", "vcOpenBtn", "vcResumeBanner", "vcResumeBtn", "vcModal", "vcClose",
              "vcErr", "vcP1", "vcConsent", "vcP1Next", "vcP1Cancel", "vcP2", "vcP3", "vcP4", "vcPMine"):
        assert f'id="{i}"' in HTML, i
    assert HTML.index('id="voxcpmSampleRow"') < HTML.index('id="vcBtnRow"') < HTML.index('id="advOptions"')
    assert 'data-t-title="vc_btn_tip"' in HTML
    assert HTML.index('id="geminiPayModal"') < HTML.index('id="vcModal"')


def test_nucleo_puro_esportato_e_senza_dom():
    testa = VC[:VC.index("/* ---------- ramo DOM")]
    assert "document." not in testa and "window." not in testa.replace("typeof window", "")
    assert "module.exports = VcCore" in VC
    for f in ("vcPanelFor", "vcGateKey", "vcPending", "vcHasReadyFor", "vcButtonKey", "vcVisible",
              "vcUploadCheck", "vcRecordExt", "vcRegenAllowed"):
        assert f"function {f}(" in VC


def test_app_sincronizza_il_bottone():
    for fn in ("_onPremiumModelChanged", "switchAudioTab", "updVoicesPremium"):
        assert "vcSyncButton()" in _estrai_funzione(JS, fn), fn


def test_css_vc():
    for c in (".vc-btn-row", ".vc-modal", ".vc-consent", ".vc-prompt", ".vc-code", ".vc-mine-item"):
        assert c in CSS, c


def test_chiavi_task2_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK2_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"


def test_nessun_nome_di_fornitore_nelle_chiavi_vc():
    for blocco in re.findall(r"Object\.assign\(L\.[a-z]+,\{(.*?)\}\);", I18N, re.S):
        for k, v in re.findall(r"(vc_[a-z_0-9]+)\s*:\s*\"((?:[^\"\\]|\\.)*)\"", blocco):
            for brand in ("VoxCPM", "DeepSeek", "Gemini", "RunPod", "Google", "Microsoft"):
                assert brand.lower() not in v.lower(), f"{k}: {brand}"


def test_hindi_in_devanagari():
    chiavi_hi = re.findall(r"Object\.assign\(L\.hi,\{(.*?)\}\);", I18N, re.S)
    testo = "".join(b for b in chiavi_hi if "vc_" in b)
    assert re.search(r"[ऀ-ॿ]", testo), "le stringhe vc_ in hindi devono essere in devanagari"
```

Run: `python -m pytest test/test_voice_clone_frontend.py test/test_js_cascade.py test/test_i18n_completeness.py test/test_voxcpm_i18n.py -q` → verdi. `node --check static/js/voice_clone.js` e `node --check static/js/app.js` → ok.

- [ ] **Step 9: prova manuale rapida**

Avvia l'app (`python audiobook_app.py`, con le env del worktree), carica un libro in italiano, scheda PREMIUM, modello VoxCPM: il bottone «Campiona la tua voce» compare sotto il box d'ascolto; con un altro modello sparisce; il click apre il modal sulle condizioni, «Avanti» resta disabilitato senza spunta. Se `ABM_VOICE_CLONE_ENABLE` (leggi il nome esatto in `voice_clone.enabled()`) e' spento, il bottone non compare.

- [ ] **Step 10: commit**

```
git add static/js/voice_clone.js templates/_fragments/html_head.html templates/_fragments/html_tail.html static/css/style.css static/js/app.js templates/_fragments/i18n_data.js test/js/voice_clone.test.js test/test_js_cascade.py test/test_voice_clone_frontend.py
git commit -m "feat(voice-clone): bottone, modal e pannello condizioni del wizard"
```

---

### Task 3: pannello 2 — registrazione o caricamento del campione

**Files:**
- Modify: `static/js/voice_clone.js` (ramo DOM: pannello 2)
- Modify: `templates/_fragments/html_head.html` (`#vcP2`)
- Modify: `templates/_fragments/i18n_data.js`
- Test: `test/test_voice_clone_frontend.py`

**Interfaces:**
- Consumes: `S.cfg.languages`, `S.cfg.max_upload_mb`, `S.cfg.min_sec/max_sec`, `GET /api/voice_clone/prompt`, `POST /api/voice_clone/sample`, `VcCore.vcUploadCheck/vcRecordExt/vcGateKey`, `_voxcpmLocaleLabel(loc)` (app.js) e `_voxcpmAccentSel` per la preselezione dell'accento, `vcLang()`.
- Produces: `S.cur = {clone_id, view:{state:'sample_ok', expires_at, metrics, cer}, lang, locale, gender}` e passaggio a `vcShow(3)`; `S.stopMedia()`.

- [ ] **Step 1: markup di `#vcP2`**

Sostituisci `<section id="vcP2" hidden></section>` con:

```html
<section id="vcP2" hidden>
  <div class="vc-rec-row">
    <label><span data-t="vc_lang"></span> <select id="vcLang"></select></label>
    <label><span data-t="vc_locale"></span> <select id="vcLocale"></select></label>
    <label><span data-t="vc_gender"></span>
      <select id="vcGender">
        <option value="f" data-t="vc_gender_f"></option>
        <option value="m" data-t="vc_gender_m"></option>
      </select>
    </label>
  </div>
  <p data-t="vc_p2_read"></p>
  <div id="vcPromptText" class="vc-prompt"></div>
  <div class="vc-rec-row">
    <button type="button" id="vcRecBtn" class="btn-primary" data-t="vc_rec_start"></button>
    <span id="vcRecDot" class="vc-rec-dot" hidden></span>
    <meter id="vcLevel" min="0" max="1" value="0"></meter>
    <span id="vcTimer" class="vc-timer">0.0 s</span>
  </div>
  <p class="vc-or"><span data-t="vc_or_upload"></span> <input type="file" id="vcFile" accept=".wav,.mp3,.webm,.opus,.ogg,.m4a,.mp4,audio/*"></p>
  <div id="vcSampleBlock" hidden>
    <p data-t="vc_sample_listen"></p>
    <audio id="vcSampleAudio" controls preload="none"></audio>
    <div class="vc-footer">
      <button type="button" id="vcSampleRedo" class="btn-secondary" data-t="vc_sample_redo"></button>
      <button type="button" id="vcSampleNext" class="btn-primary" data-t="vc_sample_ok"></button>
    </div>
  </div>
  <div id="vcUploading" class="vc-wait" hidden><span class="spinner"></span> <span data-t="vc_checking"></span></div>
  <div class="vc-footer">
    <button type="button" id="vcP2Back" class="btn-secondary" data-t="vc_back"></button>
  </div>
</section>
```

(Se il progetto non ha una classe `.spinner`, usa quella che usa `#generationProgress` o un semplice testo.)

- [ ] **Step 2: logica del pannello 2 in `voice_clone.js`**

Aggiungi nel ramo DOM, prima di `vcInit`:

```js
  /* ---------- pannello 2: campione ---------- */

  var REC_MAX_MS = 25000;

  function vcFillLangs() {
    var ls = $('vcLang'); var loc = $('vcLocale');
    if (!ls || !loc || !S.cfg) return;
    var langs = S.cfg.languages || {};
    ls.innerHTML = '';
    Object.keys(langs).sort().forEach(function (l) {
      var o = document.createElement('option'); o.value = l;
      o.textContent = (typeof _langName === 'function') ? _langName(l) : l.toUpperCase();
      ls.appendChild(o);
    });
    var cur = vcLang();
    if (langs[cur]) ls.value = cur;
    vcFillLocales();
    ls.onchange = function () { vcFillLocales(); vcLoadPrompt(); };
    loc.onchange = vcLoadPrompt;
    var g = $('vcGender'); if (g) g.onchange = vcLoadPrompt;
  }

  function vcFillLocales() {
    var ls = $('vcLang'); var loc = $('vcLocale');
    var list = (S.cfg && S.cfg.languages && S.cfg.languages[ls.value]) || [];
    loc.innerHTML = '';
    list.forEach(function (l) {
      var o = document.createElement('option'); o.value = l;
      o.textContent = (typeof _voxcpmLocaleLabel === 'function') ? _voxcpmLocaleLabel(l) : l;
      loc.appendChild(o);
    });
    var pre = (typeof _voxcpmAccentSel === 'string') ? _voxcpmAccentSel : '';
    if (pre && list.indexOf(pre) >= 0) loc.value = pre;
  }

  function vcLoadPrompt() {
    var box = $('vcPromptText'); if (!box) return;
    box.textContent = '…';
    var lang = $('vcLang').value; var gender = $('vcGender').value;
    vcFetch('/api/voice_clone/prompt?lang=' + encodeURIComponent(lang) + '&gender=' + encodeURIComponent(gender)).then(function (r) {
      if (!r.ok) { box.textContent = ''; vcErr(vcApiErrMsg(r.data)); return; }
      box.textContent = r.data.text || '';
      S.promptVersion = r.data.version;
    });
  }

  function vcSetRecording(on) {
    var b = $('vcRecBtn'); var dot = $('vcRecDot');
    if (b) b.textContent = tt(on ? 'vc_rec_stop' : 'vc_rec_start');
    if (dot) dot.hidden = !on;
  }

  function vcStopMedia() {
    var m = S.media; S.media = null;
    if (!m) return;
    try { if (m.rec && m.rec.state !== 'inactive') m.rec.stop(); } catch (e) {}
    try { if (m.timer) clearInterval(m.timer); } catch (e) {}
    try { if (m.stream) m.stream.getTracks().forEach(function (tr) { tr.stop(); }); } catch (e) {}
    try { if (m.ctx) m.ctx.close(); } catch (e) {}
    vcSetRecording(false);
  }
  S.stopMedia = vcStopMedia;

  /* Registrazione: niente cancellazione dell'eco, niente soppressione del
     rumore, niente guadagno automatico (spec §3.3): il modello vuole la voce
     com'e'. Livello con AnalyserNode; stop automatico a 25 s. */
  function vcStartRecording() {
    if (!navigator.mediaDevices || !window.MediaRecorder) { vcErr(tt('vc_err_no_mic')); return; }
    vcErr('');
    navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false}}).then(function (stream) {
      var mime = '';
      ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].some(function (m) {
        if (MediaRecorder.isTypeSupported(m)) { mime = m; return true; } return false;
      });
      var rec = mime ? new MediaRecorder(stream, {mimeType: mime}) : new MediaRecorder(stream);
      var chunks = [];
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      var src = ctx.createMediaStreamSource(stream);
      var an = ctx.createAnalyser(); an.fftSize = 512; src.connect(an);
      var buf = new Uint8Array(an.fftSize);
      var t0 = Date.now();
      var meter = $('vcLevel'); var timer = $('vcTimer');
      var tick = setInterval(function () {
        an.getByteTimeDomainData(buf);
        var peak = 0;
        for (var i = 0; i < buf.length; i++) { var v = Math.abs(buf[i] - 128) / 128; if (v > peak) peak = v; }
        if (meter) meter.value = peak;
        var el = (Date.now() - t0) / 1000;
        if (timer) timer.textContent = el.toFixed(1) + ' s';
        if (el * 1000 >= REC_MAX_MS) vcStopMedia();
      }, 100);
      rec.ondataavailable = function (ev) { if (ev.data && ev.data.size) chunks.push(ev.data); };
      rec.onstop = function () {
        var blob = new Blob(chunks, {type: rec.mimeType || mime || 'audio/webm'});
        var ext = vcRecordExt(rec.mimeType || mime);
        vcUploadSample(blob, 'sample.' + ext);
      };
      S.media = {rec: rec, stream: stream, ctx: ctx, timer: tick};
      vcSetRecording(true);
      rec.start();
    }).catch(function () { vcErr(tt('vc_err_no_mic')); });
  }

  function vcUploadSample(blob, filename) {
    var fd = new FormData();
    fd.append('file', blob, filename);
    fd.append('lang', $('vcLang').value);
    fd.append('locale', $('vcLocale').value);
    fd.append('gender', $('vcGender').value);
    var wait = $('vcUploading'); if (wait) wait.hidden = false;
    var blk = $('vcSampleBlock'); if (blk) blk.hidden = true;
    vcErr('');
    vcFetch('/api/voice_clone/sample', {method: 'POST', body: fd}).then(function (r) {
      if (wait) wait.hidden = true;
      if (!r.ok) { vcErr(vcApiErrMsg(r.data, 'vc_err_generic')); return; }
      S.cur = {clone_id: r.data.clone_id, view: r.data, lang: $('vcLang').value, locale: $('vcLocale').value, gender: $('vcGender').value, voice_code: null};
      var a = $('vcSampleAudio');
      if (a) { a.src = '/api/voice_clone/' + encodeURIComponent(r.data.clone_id) + '/sample.wav?ts=' + Date.now(); }
      if (blk) blk.hidden = false;
    }).catch(function () { if (wait) wait.hidden = true; vcErr(tt('vc_err_generic')); });
  }

  function vcInitPanel2() {
    vcStopMedia();
    var blk = $('vcSampleBlock'); if (blk) blk.hidden = true;
    var wait = $('vcUploading'); if (wait) wait.hidden = true;
    var timer = $('vcTimer'); if (timer) timer.textContent = '0.0 s';
    vcFillLangs();
    vcLoadPrompt();
    $('vcRecBtn').onclick = function () { if (S.media) vcStopMedia(); else vcStartRecording(); };
    $('vcFile').onchange = function () {
      var f = this.files && this.files[0]; if (!f) return;
      var chk = vcUploadCheck(f.name, f.size, (S.cfg && S.cfg.max_upload_mb) || 20);
      if (!chk.ok) { vcErr(tt(chk.reason === 'too_large' ? 'vc_err_too_large' : 'vc_gate_format', {mb: (S.cfg && S.cfg.max_upload_mb) || 20})); this.value = ''; return; }
      vcUploadSample(f, f.name);
      this.value = '';
    };
    $('vcSampleRedo').onclick = function () { if (blk) blk.hidden = true; var a = $('vcSampleAudio'); if (a) { a.pause(); a.removeAttribute('src'); } };
    $('vcSampleNext').onclick = function () { if (S.cur && S.cur.clone_id) vcShow(3); };
    $('vcP2Back').onclick = function () { vcStopMedia(); vcShow(1); };
  }
```

e in `vcInit`, accanto a `S.panelHooks.vcP1`: `S.panelHooks.vcP2 = vcInitPanel2;`.

Verifica in `app.js` se esiste una funzione che da' il nome della lingua (`_langName`, `langLabel`, o un dizionario tipo `LANG_NAMES`): usa quella al posto di `_langName`, o il codice maiuscolo come fallback.

- [ ] **Step 3: chiavi i18n del Task 3** (IT/EN vincolanti, le altre cinque lingue native)

```js
// Voci campionate: pannello 2, campione (spec §3.3, §5.3)
Object.assign(L.it,{
vc_lang:"Lingua",vc_locale:"Accento",vc_gender:"Voce",vc_gender_f:"femminile",vc_gender_m:"maschile",
vc_p2_read:"Leggi la frase qui sotto ad alta voce: leggila di seguito, con calma, in 15-18 secondi, in un ambiente silenzioso.",
vc_rec_start:"Registra",vc_rec_stop:"Ferma",
vc_or_upload:"oppure carica un file audio (wav, mp3, m4a, ogg, webm; max {mb} MB):",
vc_checking:"Sto verificando il campione…",
vc_sample_listen:"Riascolta il campione:",
vc_sample_ok:"Va bene, avanti",vc_sample_redo:"Rifaccio",
vc_err_no_mic:"Microfono non disponibile: controlla i permessi del browser o carica un file.",
vc_err_too_large:"File troppo grande: il limite è {mb} MB.",
vc_gate_short:"Registrazione troppo corta: servono almeno 12 secondi di parlato.",
vc_gate_long:"Registrazione troppo lunga: resta entro 20 secondi.",
vc_gate_noise:"Troppo rumore di fondo: registra in un ambiente più silenzioso.",
vc_gate_pauses:"Troppe pause o troppo lunghe: leggi di seguito, senza fermarti.",
vc_gate_nopause:"Nessuna pausa rilevata: respira tra una frase e l'altra.",
vc_gate_band:"Audio troppo compresso o ovattato: usa un microfono migliore o disattiva i filtri.",
vc_gate_clip:"Audio distorto (volume troppo alto): allontana il microfono.",
vc_gate_transcript:"Non riconosco la frase richiesta: leggila per intero, parola per parola.",
vc_gate_format:"Formato non supportato: usa wav, mp3, m4a, ogg o webm.",
vc_gate_asr:"Verifica del testo non riuscita: riprova tra poco.",
vc_gate_generic:"Campione non accettato: riprova.",
vc_err_asr_unavailable:"Il servizio di verifica non è disponibile: riprova tra qualche minuto.",
vc_err_sample_rejected:"Campione non accettato."
});
Object.assign(L.en,{
vc_lang:"Language",vc_locale:"Accent",vc_gender:"Voice",vc_gender_f:"female",vc_gender_m:"male",
vc_p2_read:"Read the sentence below aloud: read it straight through, calmly, in 15-18 seconds, in a quiet room.",
vc_rec_start:"Record",vc_rec_stop:"Stop",
vc_or_upload:"or upload an audio file (wav, mp3, m4a, ogg, webm; max {mb} MB):",
vc_checking:"Checking the sample…",
vc_sample_listen:"Listen to your sample:",
vc_sample_ok:"Sounds good, next",vc_sample_redo:"Redo",
vc_err_no_mic:"Microphone unavailable: check the browser permissions or upload a file.",
vc_err_too_large:"File too large: the limit is {mb} MB.",
vc_gate_short:"Recording too short: at least 12 seconds of speech are needed.",
vc_gate_long:"Recording too long: stay within 20 seconds.",
vc_gate_noise:"Too much background noise: record in a quieter room.",
vc_gate_pauses:"Too many or too long pauses: read straight through without stopping.",
vc_gate_nopause:"No pause detected: breathe between sentences.",
vc_gate_band:"Audio too compressed or muffled: use a better microphone or turn off filters.",
vc_gate_clip:"Distorted audio (volume too high): move the microphone further away.",
vc_gate_transcript:"The requested sentence was not recognised: read it in full, word by word.",
vc_gate_format:"Unsupported format: use wav, mp3, m4a, ogg or webm.",
vc_gate_asr:"Text check failed: try again shortly.",
vc_gate_generic:"Sample not accepted: try again.",
vc_err_asr_unavailable:"The verification service is unavailable: try again in a few minutes.",
vc_err_sample_rejected:"Sample not accepted."
});
```

I secondi delle soglie (12/20) devono coincidere con `S.cfg.min_sec`/`max_sec`: se i valori reali di `voice_clone` differiscono, usa quelli nel testo (leggi `GET /api/voice_clone/config` dai test del piano 1) — oppure sostituisci con `{n}` e passa `S.cfg.min_sec` in `vcApiErrMsg` (scelta consentita; in tal caso `vcApiErrMsg` passa `{n: S.cfg.min_sec}` per `short` e `{n: S.cfg.max_sec}` per `long`).

- [ ] **Step 4: test statici**

Aggiungi a `test/test_voice_clone_frontend.py`:

```python
TASK3_KEYS = ["vc_lang", "vc_locale", "vc_gender", "vc_gender_f", "vc_gender_m", "vc_p2_read",
              "vc_rec_start", "vc_rec_stop", "vc_or_upload", "vc_checking", "vc_sample_listen",
              "vc_sample_ok", "vc_sample_redo", "vc_err_no_mic", "vc_err_too_large",
              "vc_gate_short", "vc_gate_long", "vc_gate_noise", "vc_gate_pauses", "vc_gate_nopause",
              "vc_gate_band", "vc_gate_clip", "vc_gate_transcript", "vc_gate_format", "vc_gate_asr",
              "vc_gate_generic", "vc_err_asr_unavailable", "vc_err_sample_rejected"]


def test_markup_pannello_2():
    p2 = HTML[HTML.index('id="vcP2"'):HTML.index('id="vcP3"')]
    for i in ("vcLang", "vcLocale", "vcGender", "vcPromptText", "vcRecBtn", "vcLevel", "vcTimer",
              "vcFile", "vcSampleBlock", "vcSampleAudio", "vcSampleRedo", "vcSampleNext", "vcP2Back"):
        assert f'id="{i}"' in p2, i
    assert 'accept=".wav,.mp3,.webm,.opus,.ogg,.m4a,.mp4' in p2


def test_registratore_senza_filtri_e_con_stop_automatico():
    assert "echoCancellation: false" in VC
    assert "noiseSuppression: false" in VC
    assert "autoGainControl: false" in VC
    assert "REC_MAX_MS = 25000" in VC
    assert "/api/voice_clone/sample" in VC
    assert "vcUploadCheck(f.name, f.size" in VC


def test_chiavi_task3_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK3_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"
```

Run: `python -m pytest test/test_voice_clone_frontend.py test/test_i18n_completeness.py test/test_voxcpm_i18n.py -q` → verdi. `node --check static/js/voice_clone.js` → ok.

- [ ] **Step 5: prova manuale**

Con l'app avviata e `ABM_VOICE_CLONE_*` configurate (ASR compreso, altrimenti il campione risponde 503 `asr_unavailable` e il messaggio deve comparire nel modal): pannello 2 → la frase compare e cambia con lingua/genere; «Registra» accende il pallino, il livello si muove, il timer sale, si ferma da solo a 25 s; al termine il campione viene inviato, in caso di scarto compare il motivo, in caso di successo il player riproduce il WAV normalizzato e «Va bene, avanti» porta al pannello 3 (ancora vuoto). Caricare un `.flac` mostra l'errore di formato senza chiamare il server.

- [ ] **Step 6: commit**

```
git add static/js/voice_clone.js templates/_fragments/html_head.html templates/_fragments/i18n_data.js test/test_voice_clone_frontend.py
git commit -m "feat(voice-clone): pannello di registrazione e caricamento del campione"
```

---

### Task 4: pannello 3 — email, brano extra, pagamento e codice-voce

**Files:**
- Modify: `static/js/voice_clone.js` (pannello 3)
- Modify: `static/js/app.js` (`_openPayModalCtx` ~2080-2124: `titleKey`/`noticeKey`; capture PayPal ~2284: `captureJobId`)
- Modify: `templates/_fragments/html_head.html` (`#vcP3`)
- Modify: `templates/_fragments/i18n_data.js`
- Test: `test/test_voice_clone_frontend.py`

**Interfaces:**
- Consumes: `GET /api/voice_clone/demo_texts?locale=`, `POST /api/voice_clone/commit`, `_openPayModalCtx(ctx)` (app.js), `_payState`, `S.cfg.free/price_eur`, `S.cur`.
- Produces: `S.cur.voice_code`, `S.cur.view` con `state:"paid"`, passaggio a `vcShow(4)`; in `app.js` `_openPayModalCtx` accetta `titleKey` (default `'pay_modal_title'`) e `noticeKey` (default: chiave attuale di `#payEmailNotice`), e la capture PayPal usa `_payCtx.paypal.captureJobId` se presente al posto di `jobId`.

- [ ] **Step 1: markup di `#vcP3`**

```html
<section id="vcP3" hidden>
  <p data-t="vc_p3_intro"></p>
  <label><span data-t="vc_email"></span> <input type="email" id="vcEmail" autocomplete="email" required></label>
  <label><span data-t="vc_email2"></span> <input type="email" id="vcEmail2" autocomplete="off" required></label>
  <p data-t="vc_p3_extra"></p>
  <select id="vcExtraSel"></select>
  <p class="vc-price"><span data-t="vc_p1_price_lbl"></span> <strong id="vcPrice"></strong></p>
  <div class="vc-footer">
    <button type="button" id="vcP3Back" class="btn-secondary" data-t="vc_back"></button>
    <button type="button" id="vcPayBtn" class="btn-primary" data-t="vc_pay_btn"></button>
  </div>
</section>
```

- [ ] **Step 2: `app.js` — pay modal parametrizzato e capture con `captureJobId`**

In `_openPayModalCtx(ctx)`: dove imposta il titolo del modal (`pay_modal_title`) usa `t(ctx.titleKey||'pay_modal_title')`; dove riempie `#payEmailNotice` usa `t(ctx.noticeKey||'<chiave attuale>')`. Se il titolo/avviso sono impostati via `data-t` statico nel markup e non nella funzione, aggiungi nella funzione le due righe che li impostano (e ripristina la chiave di default per gli altri flussi: la funzione viene chiamata a ogni apertura, quindi basta la scelta con `||`).

Nel punto della capture (`fetch('/api/paypal_capture_order', ...` con `job_id: jobId`, ~riga 2284): sostituisci il body con
```js
{order_id: orderId, job_id: (_payCtx&&_payCtx.paypal&&_payCtx.paypal.captureJobId)||jobId}
```
(mantieni i nomi reali delle variabili locali del punto).

- [ ] **Step 3: logica del pannello 3**

```js
  /* ---------- pannello 3: email, brano extra, pagamento ---------- */

  function vcLoadExtraTexts() {
    var sel = $('vcExtraSel'); if (!sel || !S.cur) return;
    sel.innerHTML = '';
    var loc = S.cur.locale || (S.cur.view && S.cur.view.locale) || '';
    vcFetch('/api/voice_clone/demo_texts?locale=' + encodeURIComponent(loc)).then(function (r) {
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return; }
      (r.data.extra || []).forEach(function (x) {
        var o = document.createElement('option'); o.value = x.id;
        o.textContent = (x.text || '').slice(0, 90) + ((x.text || '').length > 90 ? '…' : '');
        sel.appendChild(o);
      });
    });
  }

  function vcEmailsOk() {
    var a = ($('vcEmail').value || '').trim(); var b = ($('vcEmail2').value || '').trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a)) { vcErr(tt('vc_err_email_bad')); return false; }
    if (a.toLowerCase() !== b.toLowerCase()) { vcErr(tt('vc_err_email_mismatch')); return false; }
    return true;
  }

  function vcCommit(paymentToken) {
    var body = {clone_id: S.cur.clone_id, email: $('vcEmail').value.trim(), email2: $('vcEmail2').value.trim(),
                extra_id: $('vcExtraSel').value, payment_token: paymentToken || ''};
    var btn = $('vcPayBtn'); if (btn) btn.disabled = true;
    vcPost('/api/voice_clone/commit', body).then(function (r) {
      if (btn) btn.disabled = false;
      if (!r.ok) {
        var m = $('vcModal'); if (m) m.hidden = false;
        vcShow(3); vcErr(vcApiErrMsg(r.data)); return;
      }
      S.cur.voice_code = r.data.voice_code || null;
      S.cur.view = {id: r.data.clone_id, state: 'paid'};
      vcShow(4);
    }).catch(function () { if (btn) btn.disabled = false; vcShow(3); vcErr(tt('vc_err_generic')); });
  }

  /* Gratis -> commit diretto. A pagamento -> il modal di pagamento gia' in
     uso per le voci premium (PayPal o voucher), poi commit col token. Il
     modal del wizard si nasconde intanto: i due hanno lo stesso z-index. */
  function vcPay() {
    if (!S.cur || !S.cur.clone_id) { vcShow(2); return; }
    if (!vcEmailsOk()) return;
    vcErr('');
    if (S.cfg && S.cfg.free) { vcCommit(''); return; }
    if (typeof _openPayModalCtx !== 'function') { vcErr(tt('vc_err_generic')); return; }
    var price = Number(S.cfg.price_eur) || 0;
    var m = $('vcModal'); if (m) m.hidden = true;
    _openPayModalCtx({
      lines: [{labelKey: 'vc_pay_line', amount: price}],
      total: price, geminiAmount: 0,
      voucherPurpose: 'voice_clone',
      titleKey: 'vc_pay_title', noticeKey: 'vc_pay_notice',
      paypal: {endpoint: '/api/paypal_create_order_voice_clone',
               buildBody: function () { return {clone_id: S.cur.clone_id}; },
               captureJobId: 'vc:' + S.cur.clone_id},
      onConfirm: function (token) { vcCommit(token); },
      onCancel: function () { if (m) m.hidden = false; vcShow(3); },
    });
  }

  function vcInitPanel3() {
    var price = $('vcPrice');
    if (price && S.cfg) price.textContent = S.cfg.free ? tt('vc_price_free') : tt('vc_price', {p: Number(S.cfg.price_eur).toFixed(2)});
    var pb = $('vcPayBtn'); if (pb) { pb.disabled = false; pb.textContent = tt(S.cfg && S.cfg.free ? 'vc_pay_btn_free' : 'vc_pay_btn'); pb.onclick = vcPay; }
    $('vcP3Back').onclick = function () { vcShow(2); };
    vcLoadExtraTexts();
  }
```

`S.panelHooks.vcP3 = vcInitPanel3;` in `vcInit`. Se l'email del voucher va passata al modal (leggi il punto in cui il pay modal legge l'email per `voucher_validate`, ~2340-2385): precompila con `$('vcEmail').value` se il modal ha un campo email, altrimenti lascia com'e'.

- [ ] **Step 4: chiavi i18n del Task 4** (IT/EN vincolanti, le altre lingue native)

```js
// Voci campionate: pannello 3, email e pagamento (spec §3.4)
Object.assign(L.it,{
vc_p3_intro:"Indica l'email a cui inviare il codice-voce e il link di gestione. Scegli anche il secondo brano di prova che sentirai letto con la tua voce.",
vc_email:"Email",vc_email2:"Ripeti l'email",
vc_p3_extra:"Secondo brano di prova:",
vc_pay_btn:"Paga e genera le prove",vc_pay_btn_free:"Genera le prove",
vc_pay_title:"Pagamento voce campionata",
vc_pay_line:"Campionamento della voce",
vc_pay_notice:"Dopo il pagamento riceverai un'email con il codice-voce e il link per gestire o eliminare la voce.",
vc_err_email_bad:"Indica un'email valida.",
vc_err_email_mismatch:"Le due email non coincidono.",
vc_err_email_has_voice:"Questa email ha già una voce campionata: eliminala prima dal link nell'email, oppure usa un'altra email.",
vc_err_payment_invalid:"Pagamento non valido o già utilizzato.",
vc_err_voice_not_found:"Campione non trovato: ricomincia dalla registrazione.",
vc_err_voice_gone:"Il campione è scaduto o è stato eliminato: ricomincia dalla registrazione.",
vc_err_not_authorized:"Questo dispositivo non è autorizzato per questa voce.",
vc_err_bad_request:"Dati mancanti o non validi."
});
Object.assign(L.en,{
vc_p3_intro:"Enter the email where we will send the voice code and the management link. Also choose the second trial passage you will hear read with your voice.",
vc_email:"Email",vc_email2:"Repeat email",
vc_p3_extra:"Second trial passage:",
vc_pay_btn:"Pay and generate the trials",vc_pay_btn_free:"Generate the trials",
vc_pay_title:"Sampled voice payment",
vc_pay_line:"Voice sampling",
vc_pay_notice:"After payment you will receive an email with the voice code and the link to manage or delete the voice.",
vc_err_email_bad:"Enter a valid email.",
vc_err_email_mismatch:"The two emails do not match.",
vc_err_email_has_voice:"This email already has a sampled voice: delete it first from the link in the email, or use another email.",
vc_err_payment_invalid:"Payment invalid or already used.",
vc_err_voice_not_found:"Sample not found: start again from the recording.",
vc_err_voice_gone:"The sample has expired or was deleted: start again from the recording.",
vc_err_not_authorized:"This device is not authorised for this voice.",
vc_err_bad_request:"Missing or invalid data."
});
```

- [ ] **Step 5: test statici**

```python
TASK4_KEYS = ["vc_p3_intro", "vc_email", "vc_email2", "vc_p3_extra", "vc_pay_btn", "vc_pay_btn_free",
              "vc_pay_title", "vc_pay_line", "vc_pay_notice", "vc_err_email_bad", "vc_err_email_mismatch",
              "vc_err_email_has_voice", "vc_err_payment_invalid", "vc_err_voice_not_found",
              "vc_err_voice_gone", "vc_err_not_authorized", "vc_err_bad_request"]


def test_markup_pannello_3():
    p3 = HTML[HTML.index('id="vcP3"'):HTML.index('id="vcP4"')]
    for i in ("vcEmail", "vcEmail2", "vcExtraSel", "vcPrice", "vcP3Back", "vcPayBtn"):
        assert f'id="{i}"' in p3, i


def test_pagamento_passa_dal_modal_esistente():
    assert "_openPayModalCtx({" in VC
    assert "voucherPurpose: 'voice_clone'" in VC
    assert "endpoint: '/api/paypal_create_order_voice_clone'" in VC
    assert "captureJobId: 'vc:' + S.cur.clone_id" in VC
    assert "geminiAmount: 0" in VC
    assert "/api/voice_clone/commit" in VC


def test_capture_paypal_usa_capture_job_id():
    corpo = _estrai_funzione(JS, "renderPaypalGeminiButtons")
    assert "captureJobId" in corpo
    corpo2 = _estrai_funzione(JS, "_openPayModalCtx")
    assert "titleKey" in corpo2 and "noticeKey" in corpo2


def test_chiavi_task4_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK4_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"
```

Run: `python -m pytest test/test_voice_clone_frontend.py test/test_i18n_completeness.py test/test_voxcpm_i18n.py -q` → verdi. `node --check` su `app.js` e `voice_clone.js`.

- [ ] **Step 6: regressione del pagamento premium**

Esegui i test che coprono il pay modal e la capture premium: `python -m pytest test/ -q -k "paypal or voucher or pay_modal or premium"` → verdi. Prova manuale: un flusso premium Gemini con voucher deve funzionare come prima (il `job_id` della capture resta `jobId` quando `captureJobId` manca).

- [ ] **Step 7: commit**

```
git add static/js/voice_clone.js static/js/app.js templates/_fragments/html_head.html templates/_fragments/i18n_data.js test/test_voice_clone_frontend.py
git commit -m "feat(voice-clone): pannello email e pagamento del wizard"
```

---

### Task 5: pannello 4 — attesa, demo, approva/rigenera/rifiuta

**Files:**
- Modify: `static/js/voice_clone.js` (pannello 4)
- Modify: `templates/_fragments/html_head.html` (`#vcP4`)
- Modify: `templates/_fragments/i18n_data.js`
- Test: `test/test_voice_clone_frontend.py`

**Interfaces:**
- Consumes: `GET /api/voice_clone/progress/<id>` (SSE), `POST /api/voice_clone/<id>/approve|regenerate|retry|reject`, `GET /api/voice_clone/demo_texts`, `VcCore.vcRegenAllowed`, `loadVoices()` e `updVoicesPremium()` di `app.js`, `window._vcJustCreated`.
- Produces: al termine `S.cur.view.state` in `ready`/`refunded`; `window._vcJustCreated = view.voice_id` all'approvazione; ricarico della combo.

- [ ] **Step 1: markup di `#vcP4`**

```html
<section id="vcP4" hidden>
  <div id="vcCodeBox" hidden>
    <p data-t="vc_code_intro"></p>
    <div id="vcCode" class="vc-code"></div>
    <p class="small" data-t="vc_code_note"></p>
  </div>
  <div id="vcWait" class="vc-wait" hidden><span class="spinner"></span> <span data-t="vc_wait"></span></div>
  <div id="vcDemos" hidden>
    <p data-t="vc_demos_intro"></p>
    <div class="vc-demo-row">
      <span data-t="vc_demo_common"></span><audio id="vcDemoCommon" controls preload="none"></audio>
      <span data-t="vc_demo_extra"></span><audio id="vcDemoExtra" controls preload="none"></audio>
    </div>
    <div class="vc-footer">
      <button type="button" id="vcApprove" class="btn-primary" data-t="vc_approve"></button>
    </div>
    <div class="vc-rec-row">
      <select id="vcRegenSel"></select>
      <button type="button" id="vcRegen" class="btn-outline btn-sm" data-t="vc_regen"></button>
      <span id="vcRegenLeft" class="small"></span>
    </div>
    <div class="vc-rec-row">
      <button type="button" id="vcReject" class="btn-outline btn-sm" data-t="vc_reject"></button>
      <span id="vcRejectConfirm" hidden><span data-t="vc_reject_sure"></span>
        <button type="button" id="vcRejectYes" class="btn-outline btn-sm" data-t="vc_yes"></button>
        <button type="button" id="vcRejectNo" class="btn-outline btn-sm" data-t="vc_no"></button></span>
    </div>
  </div>
  <div id="vcFailed" hidden>
    <p class="al al-e" data-t="vc_demo_failed"></p>
    <div class="vc-footer">
      <button type="button" id="vcReject2" class="btn-secondary" data-t="vc_reject"></button>
      <button type="button" id="vcRetry" class="btn-primary" data-t="vc_retry"></button>
    </div>
  </div>
  <div id="vcDone" hidden>
    <p class="al al-i" data-t="vc_done"></p>
    <div class="vc-footer"><button type="button" id="vcDoneClose" class="btn-primary" data-t="vc_close"></button></div>
  </div>
  <div id="vcRefunded" hidden>
    <p class="al al-i" data-t="vc_refunded"></p>
    <div class="vc-footer"><button type="button" id="vcRefundedClose" class="btn-primary" data-t="vc_close"></button></div>
  </div>
</section>
```

- [ ] **Step 2: logica del pannello 4**

```js
  /* ---------- pannello 4: attesa, demo, decisione ---------- */

  function vcRenderP4(view) {
    S.cur.view = view;
    var st = view.state;
    var show = function (id, on) { var e = $(id); if (e) e.hidden = !on; };
    show('vcWait', st === 'paid' || st === 'demos_generating');
    show('vcDemos', st === 'demos_ready');
    show('vcFailed', st === 'demo_failed');
    show('vcDone', st === 'ready');
    show('vcRefunded', st === 'refunded' || st === 'expired' || st === 'deleted');
    if (st === 'demos_ready') {
      var du = view.demo_urls || {};
      var c = $('vcDemoCommon'); var x = $('vcDemoExtra');
      if (c && du.common) c.src = du.common + '?ts=' + Date.now();
      if (x && du.extra) x.src = du.extra + '?ts=' + Date.now();
      var left = Number(view.regen_left) || 0;
      var rl = $('vcRegenLeft'); if (rl) rl.textContent = tt('vc_regen_left', {n: left});
      var rb = $('vcRegen'); if (rb) rb.disabled = !vcRegenAllowed(view);
      var rs = $('vcRegenSel'); if (rs) rs.disabled = !vcRegenAllowed(view);
      var rc = $('vcRejectConfirm'); if (rc) rc.hidden = true;
    }
  }

  /* Avanzamento via SSE: ogni evento e' la vista pubblica; il flusso chiude
     da solo su uno stato finale. Alla chiusura senza stato finale (rete,
     1800 s) si rilegge `mine`. */
  function vcWatch() {
    if (S.es) { try { S.es.close(); } catch (e) {} S.es = null; }
    if (!S.cur || !S.cur.clone_id || !window.EventSource) return;
    var es = new EventSource('/api/voice_clone/progress/' + encodeURIComponent(S.cur.clone_id));
    S.es = es;
    es.onmessage = function (ev) {
      var v; try { v = JSON.parse(ev.data); } catch (e) { return; }
      if (!v || !v.state) return;
      vcRenderP4(v);
      if (vcPanelFor(v.state) !== 4 || v.state === 'demos_ready' || v.state === 'demo_failed') { es.close(); S.es = null; }
    };
    es.onerror = function () {
      es.close(); S.es = null;
      vcRefreshMine().then(function () {
        for (var i = 0; i < S.mine.length; i++) if (S.mine[i].id === S.cur.clone_id) vcRenderP4(S.mine[i]);
      });
    };
  }

  function vcAction(name, body) {
    vcErr('');
    return vcPost('/api/voice_clone/' + encodeURIComponent(S.cur.clone_id) + '/' + name, body || {}).then(function (r) {
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return null; }
      vcRenderP4(r.data);
      return r.data;
    }).catch(function () { vcErr(tt('vc_err_generic')); return null; });
  }

  function vcAfterApprove(view) {
    window._vcJustCreated = view.voice_id || null;
    vcRefreshMine().then(function () {
      if (typeof loadVoices === 'function') {
        Promise.resolve(loadVoices()).then(function () {
          if (typeof updVoicesPremium === 'function') updVoicesPremium();
          vcSyncButton();
        });
      }
    });
  }

  function vcInitPanel4() {
    var cb = $('vcCodeBox');
    if (cb) {
      cb.hidden = !S.cur.voice_code;
      var c = $('vcCode'); if (c) c.textContent = S.cur.voice_code || '';
    }
    var sel = $('vcRegenSel');
    if (sel) {
      sel.innerHTML = '';
      var loc = (S.cur.view && S.cur.view.locale) || S.cur.locale || '';
      vcFetch('/api/voice_clone/demo_texts?locale=' + encodeURIComponent(loc)).then(function (r) {
        if (!r.ok) return;
        (r.data.extra || []).forEach(function (x) {
          var o = document.createElement('option'); o.value = x.id;
          o.textContent = (x.text || '').slice(0, 60) + '…';
          sel.appendChild(o);
        });
        if (S.cur.view && S.cur.view.extra_id) sel.value = S.cur.view.extra_id;
      });
    }
    $('vcApprove').onclick = function () { vcAction('approve').then(function (v) { if (v) vcAfterApprove(v); }); };
    $('vcRegen').onclick = function () { vcAction('regenerate', {extra_id: sel ? sel.value : ''}).then(function (v) { if (v) vcWatch(); }); };
    $('vcReject').onclick = function () { var rc = $('vcRejectConfirm'); if (rc) rc.hidden = false; };
    $('vcRejectNo').onclick = function () { var rc = $('vcRejectConfirm'); if (rc) rc.hidden = true; };
    $('vcRejectYes').onclick = function () { vcAction('reject').then(function () { vcRefreshMine().then(vcSyncButton); }); };
    $('vcReject2').onclick = function () { vcAction('reject').then(function () { vcRefreshMine().then(vcSyncButton); }); };
    $('vcRetry').onclick = function () { vcAction('retry').then(function (v) { if (v) vcWatch(); }); };
    $('vcDoneClose').onclick = vcClose;
    $('vcRefundedClose').onclick = vcClose;
    vcRenderP4(S.cur.view || {state: 'paid'});
    var st = (S.cur.view || {}).state;
    if (st === 'paid' || st === 'demos_generating') vcWatch();
  }
```

`S.panelHooks.vcP4 = vcInitPanel4;` in `vcInit`. Nota: `vcAction('regenerate')` e `retry` riportano il record in `demos_generating`, quindi la vista di risposta nasconde le demo e `vcWatch()` riparte. La spec §3.5: «Rifiuta e chiedi rimborso» chiede conferma inline, mai `confirm()` del browser.

- [ ] **Step 3: chiavi i18n del Task 5** (IT/EN vincolanti, le altre lingue native)

```js
// Voci campionate: pannello 4, demo e decisione (spec §3.5-3.6)
Object.assign(L.it,{
vc_code_intro:"Questo è il tuo codice-voce: serve per usare la voce su altri dispositivi. Lo trovi anche nell'email.",
vc_code_note:"Non condividerlo con chi non vuoi che usi la tua voce.",
vc_wait:"Sto preparando le prove con la tua voce: ci vogliono da uno a quattro minuti. Puoi chiudere e riprendere più tardi.",
vc_demos_intro:"Ascolta le due prove lette con la tua voce:",
vc_demo_common:"Brano comune",vc_demo_extra:"Brano scelto",
vc_approve:"Approva",vc_regen:"Rigenera",
vc_regen_left:"rigenerazioni rimaste: {n}",
vc_reject:"Rifiuta e chiedi rimborso",
vc_reject_sure:"Sicuro? La voce sarà eliminata e il pagamento rimborsato.",
vc_yes:"Sì",vc_no:"No",
vc_demo_failed:"La preparazione delle prove non è riuscita. Riprova più tardi oppure chiedi il rimborso.",
vc_retry:"Riprova",
vc_done:"Voce approvata: la trovi nella combo delle voci sotto «Le tue voci».",
vc_refunded:"Voce eliminata. Se avevi pagato, il rimborso arriva secondo il metodo usato.",
vc_err_regen_exhausted:"Hai esaurito le rigenerazioni disponibili.",
vc_err_bad_state:"Operazione non consentita nello stato attuale."
});
Object.assign(L.en,{
vc_code_intro:"This is your voice code: use it to add the voice on other devices. It is also in the email.",
vc_code_note:"Do not share it with anyone you do not want using your voice.",
vc_wait:"Preparing the trials with your voice: it takes one to four minutes. You can close and come back later.",
vc_demos_intro:"Listen to the two trials read with your voice:",
vc_demo_common:"Common passage",vc_demo_extra:"Chosen passage",
vc_approve:"Approve",vc_regen:"Regenerate",
vc_regen_left:"regenerations left: {n}",
vc_reject:"Reject and request a refund",
vc_reject_sure:"Are you sure? The voice will be deleted and the payment refunded.",
vc_yes:"Yes",vc_no:"No",
vc_demo_failed:"Preparing the trials failed. Try again later or request a refund.",
vc_retry:"Try again",
vc_done:"Voice approved: you will find it in the voice list under “Your voices”.",
vc_refunded:"Voice deleted. If you had paid, the refund follows the method used.",
vc_err_regen_exhausted:"You have used up the available regenerations.",
vc_err_bad_state:"Operation not allowed in the current state."
});
```

- [ ] **Step 4: test statici**

```python
TASK5_KEYS = ["vc_code_intro", "vc_code_note", "vc_wait", "vc_demos_intro", "vc_demo_common", "vc_demo_extra",
              "vc_approve", "vc_regen", "vc_regen_left", "vc_reject", "vc_reject_sure", "vc_yes", "vc_no",
              "vc_demo_failed", "vc_retry", "vc_done", "vc_refunded", "vc_err_regen_exhausted", "vc_err_bad_state"]


def test_markup_pannello_4():
    p4 = HTML[HTML.index('id="vcP4"'):HTML.index('id="vcPMine"')]
    for i in ("vcCodeBox", "vcCode", "vcWait", "vcDemos", "vcDemoCommon", "vcDemoExtra", "vcApprove",
              "vcRegenSel", "vcRegen", "vcRegenLeft", "vcReject", "vcRejectConfirm", "vcRejectYes",
              "vcRejectNo", "vcFailed", "vcReject2", "vcRetry", "vcDone", "vcDoneClose", "vcRefunded"):
        assert f'id="{i}"' in p4, i


def test_avanzamento_via_sse_e_decisioni():
    assert "new EventSource('/api/voice_clone/progress/'" in VC
    for a in ("'approve'", "'regenerate'", "'retry'", "'reject'"):
        assert f"vcAction({a}" in VC, a
    assert "window._vcJustCreated = view.voice_id" in VC
    assert "confirm(" not in VC.replace("vcRejectConfirm", "").replace("vcConfirm", "").replace("confirm_code", ""), "mai confirm() del browser"


def test_chiavi_task5_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK5_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"
```

Run: `python -m pytest test/test_voice_clone_frontend.py test/test_i18n_completeness.py test/test_voxcpm_i18n.py -q` → verdi; `node --check static/js/voice_clone.js`.

- [ ] **Step 5: prova manuale**

Con il worker VoxCPM raggiungibile: dopo il commit il codice-voce compare una sola volta, il pannello attende, le due demo arrivano via SSE, «Rigenera» riporta in attesa e decrementa il contatore, «Approva» chiude sul messaggio di conferma e la combo mostra «Le tue voci» con la voce preselezionata; una generazione con quella voce parte. «Rifiuta» chiede conferma inline e porta al messaggio di rimborso.

- [ ] **Step 6: commit**

```
git add static/js/voice_clone.js templates/_fragments/html_head.html templates/_fragments/i18n_data.js test/test_voice_clone_frontend.py
git commit -m "feat(voice-clone): pannello delle prove con approvazione, rigenerazione e rifiuto"
```

---

### Task 6: ripresa, pannello «Le tue voci», errori di generazione

**Files:**
- Modify: `static/js/voice_clone.js` (ripresa da `?vc=`, pannello mine)
- Modify: `templates/_fragments/html_head.html` (`#vcPMine`)
- Modify: `static/js/app.js` (nuova `_handleVcGenerateError(gd)`; i due punti in cui la risposta di `/api/generate` non e' ok, ~3616-3652 e ~4037)
- Modify: `templates/_fragments/i18n_data.js`
- Test: `test/test_voice_clone_frontend.py`

**Interfaces:**
- Consumes: `S.resumeId` (Task 2), `S.mine`, `POST /api/voice_clone/claim|confirm`, `POST /api/voice_clone/<id>/forget|resend`, `vcResume(id)`, `vcShow`, `loadVoices()/updVoicesPremium()`.
- Produces: `_handleVcGenerateError(gd)` in `app.js` → `true` se ha gestito l'errore (`voice_gone`, `voice_not_authorized`, `voice_lang_mismatch`), altrimenti `false`.

- [ ] **Step 1: markup di `#vcPMine`**

```html
<section id="vcPMine" hidden>
  <ul id="vcMineList" class="vc-mine-list"></ul>
  <details class="vc-claim">
    <summary data-t="vc_claim_title"></summary>
    <p class="small" data-t="vc_claim_intro"></p>
    <div class="vc-claim-row">
      <input type="text" id="vcClaimCode" autocomplete="off" spellcheck="false" data-t-ph="vc_claim_ph">
      <button type="button" id="vcClaimBtn" class="btn-outline btn-sm" data-t="vc_claim_btn"></button>
    </div>
    <div id="vcConfirmRow" class="vc-claim-row" hidden>
      <span class="small" data-t="vc_confirm_intro"></span>
      <input type="text" id="vcConfirmCode" autocomplete="one-time-code" inputmode="numeric" data-t-ph="vc_confirm_ph">
      <button type="button" id="vcConfirmBtn" class="btn-outline btn-sm" data-t="vc_confirm_btn"></button>
    </div>
  </details>
  <div class="vc-footer">
    <button type="button" id="vcMineClose" class="btn-secondary" data-t="vc_close"></button>
    <button type="button" id="vcNewVoice" class="btn-primary" data-t="vc_new_voice"></button>
  </div>
</section>
```

- [ ] **Step 2: logica del pannello mine e della ripresa**

```js
  /* ---------- pannello «Le tue voci» ---------- */

  function vcStateLabel(m) {
    if (m.state === 'ready') return tt('vc_state_ready');
    if (m.state === 'sample_ok') return tt('vc_state_sample_ok');
    if (m.state === 'paid' || m.state === 'demos_generating') return tt('vc_state_generating');
    if (m.state === 'demos_ready') return tt('vc_state_demos_ready');
    if (m.state === 'demo_failed') return tt('vc_state_demo_failed');
    return m.state;
  }

  function vcRenderMine() {
    var ul = $('vcMineList'); if (!ul) return;
    ul.innerHTML = '';
    if (!S.mine.length) {
      var li0 = document.createElement('li'); li0.className = 'small'; li0.textContent = tt('vc_mine_empty'); ul.appendChild(li0); return;
    }
    S.mine.forEach(function (m) {
      var li = document.createElement('li'); li.className = 'vc-mine-item';
      var head = document.createElement('div');
      var lab = (typeof _voxcpmLocaleLabel === 'function') ? _voxcpmLocaleLabel(m.locale) : m.locale;
      head.textContent = (m.owner ? tt('vc_voice_own') : tt('vc_voice_shared')) + ' · ' + lab + ' · ' + tt(m.gender === 'f' ? 'vc_gender_f' : 'vc_gender_m') + ' — ' + vcStateLabel(m);
      li.appendChild(head);
      if (m.owner && m.voice_code) {
        var code = document.createElement('div'); code.className = 'vc-code'; code.textContent = m.voice_code; li.appendChild(code);
      }
      if (m.state === 'ready' && m.demo_urls && m.demo_urls.common) {
        var a = document.createElement('audio'); a.controls = true; a.preload = 'none'; a.src = m.demo_urls.common; li.appendChild(a);
      }
      var act = document.createElement('div'); act.className = 'vc-actions';
      var mk = function (key, fn) { var b = document.createElement('button'); b.type = 'button'; b.className = 'btn-outline btn-sm'; b.textContent = tt(key); b.onclick = fn; act.appendChild(b); return b; };
      if (m.pending) mk('vc_resume_btn', function () { vcResume(m.id); });
      if (!m.owner) mk('vc_forget', function () { vcAction2(m.id, 'forget').then(function (ok) { if (ok) vcOpen('mine'); }); });
      if (m.owner) mk('vc_resend', function () { vcAction2(m.id, 'resend').then(function (ok) { if (ok) vcErr(tt('vc_resend_ok')); }); });
      li.appendChild(act);
      ul.appendChild(li);
    });
  }

  function vcAction2(id, name) {
    vcErr('');
    return vcPost('/api/voice_clone/' + encodeURIComponent(id) + '/' + name, {}).then(function (r) {
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return false; }
      return true;
    }).catch(function () { vcErr(tt('vc_err_generic')); return false; });
  }

  function vcReloadCombo() {
    if (typeof loadVoices !== 'function') return;
    Promise.resolve(loadVoices()).then(function () {
      if (typeof updVoicesPremium === 'function') updVoicesPremium();
      vcSyncButton();
    });
  }

  function vcClaim() {
    var code = ($('vcClaimCode').value || '').trim().toUpperCase();
    if (!code) return;
    vcErr('');
    vcPost('/api/voice_clone/claim', {voice_code: code}).then(function (r) {
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return; }
      var row = $('vcConfirmRow');
      if (r.data.status === 'pending') { if (row) row.hidden = false; $('vcConfirmCode').value = ''; $('vcConfirmCode').focus(); return; }
      if (row) row.hidden = true;
      vcOpen('mine'); vcReloadCombo();
    }).catch(function () { vcErr(tt('vc_err_generic')); });
  }

  function vcConfirm() {
    var code = ($('vcClaimCode').value || '').trim().toUpperCase();
    var cc = ($('vcConfirmCode').value || '').trim();
    if (!code || !cc) return;
    vcErr('');
    vcPost('/api/voice_clone/confirm', {voice_code: code, confirm_code: cc}).then(function (r) {
      if (!r.ok) { vcErr(vcApiErrMsg(r.data)); return; }
      var row = $('vcConfirmRow'); if (row) row.hidden = true;
      $('vcClaimCode').value = ''; $('vcConfirmCode').value = '';
      vcOpen('mine'); vcReloadCombo();
    }).catch(function () { vcErr(tt('vc_err_generic')); });
  }

  function vcInitPanelMine() {
    vcRenderMine();
    var row = $('vcConfirmRow'); if (row) row.hidden = true;
    $('vcClaimBtn').onclick = vcClaim;
    $('vcConfirmBtn').onclick = vcConfirm;
    $('vcMineClose').onclick = vcClose;
    $('vcNewVoice').onclick = function () { vcShow(1); };
  }
```

`S.panelHooks.vcPMine = vcInitPanelMine;` in `vcInit`. Poi, sempre in `vcInit`, dopo aver salvato `S.resumeId`, esegui la ripresa: se `S.resumeId` e' presente in `S.mine`, `vcResume(S.resumeId)`, altrimenti `vcShow('mine')` con `vcErr(tt('vc_err_voice_gone'))`. La ripresa da `?vc=` deve avvenire DOPO che `app.js` ha popolato la pagina: avvolgi la chiamata in `setTimeout(..., 0)` se il test manuale mostra che `bookLangState` non e' ancora pronto; il pannello non dipende dalla combo.

Aggiorna `vcOpen(force)` cosi' che `vcOpen('mine')` mostri il pannello mine anche con voci in sospeso (gia' vero: `force` ha la precedenza).

- [ ] **Step 3: `_handleVcGenerateError` in `app.js`**

Aggiungi vicino a `_handlePremiumPaymentRequired`:

```js
// Errori di /api/generate dovuti a una voce campionata (spec §3.8): la voce
// non c'e' piu', il dispositivo non e' autorizzato o la lingua del libro non
// coincide. Messaggio dedicato e combo ricaricata: mai il testo del server.
function _handleVcGenerateError(gd){
  const code=gd&&gd.error_code;
  if(code!=='voice_gone'&&code!=='voice_not_authorized'&&code!=='voice_lang_mismatch')return false;
  showErr('s3err',t('vc_err_'+code));
  _voxcpmVoiceSel='';
  loadVoices().then(()=>{updVoicesPremium();if(typeof vcSyncButton==='function')vcSyncButton();});
  return true;
}
```

Nei due punti in cui la risposta di `/api/generate` non e' ok (dopo il `payment_required`/premium handling e prima dello `showErr` generico): `if(_handleVcGenerateError(gd)){/* stessa pulizia del ramo di errore: nascondi #generationProgress, mostra #panel4Footer, unlockUI(), generating=false */return;}` — copia esattamente le istruzioni di pulizia che il ramo generico esegue in quel punto, in modo che la UI torni allo stato pre-generazione. Se `s3err` non e' l'id giusto in uno dei due punti, usa l'id che usa il ramo generico li'.

- [ ] **Step 4: chiavi i18n del Task 6** (IT/EN vincolanti, le altre lingue native)

```js
// Voci campionate: «Le tue voci», codice-voce, errori di generazione (spec §3.7-3.8, §6.4)
Object.assign(L.it,{
vc_mine_empty:"Nessuna voce su questo dispositivo.",
vc_state_ready:"pronta",vc_state_sample_ok:"campione registrato, in attesa del pagamento",
vc_state_generating:"prove in preparazione",vc_state_demos_ready:"prove pronte, in attesa della tua decisione",
vc_state_demo_failed:"preparazione non riuscita",
vc_forget:"Rimuovi da questo dispositivo",vc_resend:"Rimanda l'email con il codice",
vc_resend_ok:"Email inviata.",
vc_claim_title:"Aggiungi con codice-voce",
vc_claim_intro:"Hai ricevuto un codice-voce? Inseriscilo qui: il proprietario riceverà un'email con un codice di conferma da darti.",
vc_claim_ph:"codice-voce",vc_claim_btn:"Aggiungi",
vc_confirm_intro:"Codice di conferma ricevuto dal proprietario:",
vc_confirm_ph:"codice di conferma",vc_confirm_btn:"Conferma",
vc_new_voice:"Campiona una nuova voce",
vc_err_code_unknown:"Codice-voce non riconosciuto.",
vc_err_code_locked:"Troppi tentativi: questo codice è bloccato per un po'.",
vc_err_confirm_wrong:"Codice di conferma errato.",
vc_err_confirm_expired:"Codice di conferma scaduto: richiedi di nuovo l'aggiunta.",
vc_err_confirm_none:"Nessuna conferma in corso per questo codice: richiedi prima l'aggiunta.",
vc_err_voice_not_authorized:"Questo dispositivo non è più autorizzato a usare quella voce.",
vc_err_voice_lang_mismatch:"La voce scelta è di una lingua diversa da quella del libro."
});
Object.assign(L.en,{
vc_mine_empty:"No voices on this device.",
vc_state_ready:"ready",vc_state_sample_ok:"sample recorded, awaiting payment",
vc_state_generating:"trials in preparation",vc_state_demos_ready:"trials ready, awaiting your decision",
vc_state_demo_failed:"preparation failed",
vc_forget:"Remove from this device",vc_resend:"Resend the email with the code",
vc_resend_ok:"Email sent.",
vc_claim_title:"Add with a voice code",
vc_claim_intro:"Got a voice code? Enter it here: the owner will receive an email with a confirmation code to give you.",
vc_claim_ph:"voice code",vc_claim_btn:"Add",
vc_confirm_intro:"Confirmation code received from the owner:",
vc_confirm_ph:"confirmation code",vc_confirm_btn:"Confirm",
vc_new_voice:"Sample a new voice",
vc_err_code_unknown:"Voice code not recognised.",
vc_err_code_locked:"Too many attempts: this code is locked for a while.",
vc_err_confirm_wrong:"Wrong confirmation code.",
vc_err_confirm_expired:"Confirmation code expired: request the addition again.",
vc_err_confirm_none:"No confirmation in progress for this code: request the addition first.",
vc_err_voice_not_authorized:"This device is no longer authorised to use that voice.",
vc_err_voice_lang_mismatch:"The chosen voice is in a different language from the book."
});
```

(`vc_err_voice_gone` esiste dal Task 4 ed e' riusata da `_handleVcGenerateError`.)

- [ ] **Step 5: test statici**

```python
TASK6_KEYS = ["vc_mine_empty", "vc_state_ready", "vc_state_sample_ok", "vc_state_generating",
              "vc_state_demos_ready", "vc_state_demo_failed", "vc_forget", "vc_resend", "vc_resend_ok",
              "vc_claim_title", "vc_claim_intro", "vc_claim_ph", "vc_claim_btn", "vc_confirm_intro",
              "vc_confirm_ph", "vc_confirm_btn", "vc_new_voice", "vc_err_code_unknown", "vc_err_code_locked",
              "vc_err_confirm_wrong", "vc_err_confirm_expired", "vc_err_confirm_none",
              "vc_err_voice_not_authorized", "vc_err_voice_lang_mismatch"]


def test_markup_pannello_mine():
    pm = HTML[HTML.index('id="vcPMine"'):]
    pm = pm[:pm.index("</section>")]
    for i in ("vcMineList", "vcClaimCode", "vcClaimBtn", "vcConfirmRow", "vcConfirmCode", "vcConfirmBtn",
              "vcMineClose", "vcNewVoice"):
        assert f'id="{i}"' in pm, i


def test_ripresa_e_gestione():
    assert "S.resumeId" in VC
    assert "/api/voice_clone/claim" in VC and "/api/voice_clone/confirm" in VC
    assert "'forget'" in VC and "'resend'" in VC
    assert "history.replaceState" in VC


def test_il_codice_voce_non_finisce_in_console():
    assert "console.log" not in VC


def test_app_gestisce_gli_errori_di_generazione_delle_voci_personali():
    corpo = _estrai_funzione(JS, "_handleVcGenerateError")
    for c in ("voice_gone", "voice_not_authorized", "voice_lang_mismatch"):
        assert c in corpo
    assert "t('vc_err_'+code)" in corpo
    assert JS.count("_handleVcGenerateError(gd)") >= 2, "va chiamata in entrambi i punti di errore di /api/generate"


def test_chiavi_task6_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK6_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"
```

Se il nome della variabile della risposta nei due punti di `app.js` non e' `gd`, adegua l'ultima asserzione al nome reale (una sola variante, la stessa nei due punti).

Run: `python -m pytest test/test_voice_clone_frontend.py test/test_i18n_completeness.py test/test_voxcpm_i18n.py test/test_voxcpm_frontend_assets.py -q` → verdi; `node --check` su entrambi i JS.

- [ ] **Step 6: prova manuale**

Aprire `/?vc=<clone_id>` con una voce in sospeso: il modal si apre sul pannello dello stato e la query sparisce dalla barra. «Le tue voci» elenca le voci con stato, codice (solo proprie), demo, «Rimuovi» solo sulle ricevute, «Rimanda l'email» solo sulle proprie. Claim di un codice da un secondo browser: `pending` → riga di conferma → codice ricevuto via email → la voce compare. Con una voce eliminata dal proprietario, generare dal secondo browser mostra il messaggio dedicato e la combo si aggiorna.

- [ ] **Step 7: commit**

```
git add static/js/voice_clone.js static/js/app.js templates/_fragments/html_head.html templates/_fragments/i18n_data.js test/test_voice_clone_frontend.py
git commit -m "feat(voice-clone): ripresa, pannello Le tue voci ed errori di generazione"
```

---

### Task 7: privacy, collaudo manuale, `accepted_ext()` e rilettura nativa delle stringhe

**Files:**
- Modify: `privacy_content.py` (`_LAST_UPDATED` riga 8; sezioni: inserisci la nuova `<h2>` prima di `cookie_h` «9.» IT ~19 / EN ~165, rinumera 9→10 e 10→11)
- Modify: `seo_content.py` (chiave `"privacy":` per lingua: it ~181, en ~345, fr ~511, es ~676, de ~843, zh ~996, hi ~1144)
- Modify: `voice_clone.py` (nuova `accepted_ext()` accanto a `max_upload_mb()` ~145), `audiobook_app.py` (~8969: `voice_clone._ACCEPTED_EXT` → `voice_clone.accepted_ext()`)
- Modify: `templates/_fragments/i18n_data.js` (rilettura nativa fr/es/de/zh/hi delle chiavi `vc_*`)
- Create: `docs/MANUAL_TESTS_VOCI_CAMPIONATE.md`
- Test: `test/test_privacy_voice_clone.py` (nuovo), `test/test_voice_clone_frontend.py`

**Interfaces:**
- Produces: `voice_clone.accepted_ext()` → `frozenset[str]` (le stesse estensioni di `_ACCEPTED_EXT`).

- [ ] **Step 1: test della privacy**

Crea `test/test_privacy_voice_clone.py`:

```python
"""La sezione privacy sulle voci campionate (spec §11): presente in IT ed EN,
numerazione delle sezioni coerente, data aggiornata, riga di riassunto SEO
in tutte le lingue."""
import re
import privacy_content
import seo_content


def _html(lang):
    fn = getattr(privacy_content, "render", None) or getattr(privacy_content, "privacy_html", None)
    assert fn, "privacy_content deve esporre render(lang) o privacy_html(lang)"
    return fn(lang)


def test_sezione_voci_campionate_it_en():
    it = _html("it"); en = _html("en")
    assert "Voci campionate" in it and "voce campion" in it.lower()
    assert "Sampled voices" in en and "voice sample" in en.lower()
    for h in (it, en):
        assert "voice_code" not in h
        for kw in ("15", "email", "codice" if h is it else "code"):
            assert kw in h


def test_numerazione_sezioni_coerente():
    for lang in ("it", "en"):
        nums = [int(n) for n in re.findall(r"<h2[^>]*>\s*(\d+)\.", _html(lang))]
        assert nums == list(range(1, len(nums) + 1)), nums
        assert len(nums) == 19


def test_data_aggiornata():
    assert privacy_content._LAST_UPDATED["it"].endswith("2026")
    assert "settembre" in privacy_content._LAST_UPDATED["it"]
    assert "September" in privacy_content._LAST_UPDATED["en"]


def test_riassunto_seo_in_tutte_le_lingue():
    for lang in ("it", "en", "fr", "es", "de", "zh", "hi"):
        blob = seo_content.CONTENT[lang]["privacy"] if hasattr(seo_content, "CONTENT") else None
        assert blob is not None, "adegua il test all'accessor reale di seo_content"
        testo = str(blob).lower()
        assert any(k in testo for k in ("voce", "voice", "voix", "voz", "stimme", "声音", "आवाज़")), lang
```

Prima di scrivere, leggi come `privacy_content.py` espone il render (grep `def `) e come `seo_content.py` struttura il dizionario (grep `"privacy":`), e adegua i due accessor del test ai nomi reali: il test deve leggere le strutture vere, non indovinarle.

Run: `python -m pytest test/test_privacy_voice_clone.py -q` → fallisce (sezione assente, 18 sezioni).

- [ ] **Step 2: sezione privacy IT/EN**

In `privacy_content.py`, nuova sezione inserita prima di quella dei cookie, con la numerazione «9.» e le due successive rinumerate «10.» e «11.» (aggiorna anche `_LAST_UPDATED` a `{"it": "10 settembre 2026", "en": "September 10, 2026"}`):

IT:
```html
<h2>9. Voci campionate</h2>
<p>Se scegli di campionare la tua voce, registri o carichi un breve campione audio (circa 15 secondi) leggendo una frase che ti proponiamo. Il campione viene analizzato automaticamente (livelli, pause, rumore) e trascritto da un servizio di riconoscimento vocale per verificare che tu abbia letto la frase; la trascrizione serve solo a questa verifica e non viene conservata oltre l'esito.</p>
<p>Conserviamo il campione normalizzato, i due brani di prova generati con la tua voce, la lingua e il genere dichiarati, l'email indicata, il consenso prestato («è la mia voce e ho il diritto di usarla») con data e ora, e l'elenco dei dispositivi autorizzati (identificati dal cookie tecnico di sessione). Il campione è inviato al fornitore che esegue la sintesi vocale esclusivamente per generare i brani di prova e gli audiolibri che richiedi.</p>
<p>La voce è utilizzabile solo dai dispositivi che autorizzi con il codice-voce, previa conferma via email al titolare. Puoi eliminare la voce in qualsiasi momento dal link di gestione contenuto nell'email: l'eliminazione cancella campione, brani di prova e riferimento nel catalogo. Una voce non utilizzata per un lungo periodo viene eliminata automaticamente; te lo ricordiamo via email prima della scadenza. I dati di pagamento seguono le regole della sezione dedicata.</p>
```

EN:
```html
<h2>9. Sampled voices</h2>
<p>If you choose to sample your voice, you record or upload a short audio sample (about 15 seconds) reading a sentence we propose. The sample is analysed automatically (levels, pauses, noise) and transcribed by a speech-recognition service to check that you read the sentence; the transcription serves only this check and is not kept beyond the result.</p>
<p>We keep the normalised sample, the two trial passages generated with your voice, the declared language and gender, the email you provide, the consent given (“this is my voice and I have the right to use it”) with date and time, and the list of authorised devices (identified by the technical session cookie). The sample is sent to the provider that performs speech synthesis solely to generate the trial passages and the audiobooks you request.</p>
<p>The voice can be used only by the devices you authorise with the voice code, after email confirmation by the owner. You can delete the voice at any time from the management link in the email: deletion removes the sample, the trial passages and the catalogue entry. A voice unused for a long period is deleted automatically; we remind you by email before it expires. Payment data follows the rules of the dedicated section.</p>
```

Verifica con grep che nessun'altra parte del file (indice, ancore, `data-t`) citi «9.» o «10.» per cookie/modifiche: aggiorna ogni riferimento.

- [ ] **Step 3: riga SEO privacy per lingua**

In `seo_content.py`, nel blocco `"privacy"` di ciascuna lingua aggiungi una voce (nel formato che il blocco usa, es. un item della lista) con questo contenuto:
- it: «Voci campionate: campione audio, brani di prova, email e consenso conservati finché la voce è attiva; eliminazione dal link nell'email.»
- en: «Sampled voices: audio sample, trial passages, email and consent kept while the voice is active; deletion from the link in the email.»
- fr: «Voix échantillonnées : échantillon audio, extraits d'essai, e-mail et consentement conservés tant que la voix est active ; suppression depuis le lien de l'e-mail.»
- es: «Voces muestreadas: muestra de audio, fragmentos de prueba, correo y consentimiento conservados mientras la voz esté activa; eliminación desde el enlace del correo.»
- de: «Stimmproben: Audioprobe, Probetexte, E-Mail und Einwilligung werden aufbewahrt, solange die Stimme aktiv ist; Löschung über den Link in der E-Mail.»
- zh: «声音采样：音频样本、试听片段、邮箱和同意记录在声音有效期内保留；可通过邮件中的链接删除。»
- hi: «नमूना आवाज़ें: ऑडियो नमूना, परीक्षण अंश, ईमेल और सहमति आवाज़ के सक्रिय रहने तक रखे जाते हैं; ईमेल के लिंक से हटाया जा सकता है।»

Run: `python -m pytest test/test_privacy_voice_clone.py test/test_seo*.py test/test_privacy*.py -q` → verdi.

- [ ] **Step 4: `accepted_ext()`**

In `voice_clone.py`, accanto a `max_upload_mb()`:

```python
def accepted_ext():
    """Estensioni accettate per il campione caricato (lette dall'app per il 400 `format`)."""
    return frozenset(_ACCEPTED_EXT)
```

In `audiobook_app.py` sostituisci l'unico uso di `voice_clone._ACCEPTED_EXT` con `voice_clone.accepted_ext()`. Test in `test/test_voice_clone_frontend.py`:

```python
def test_app_non_legge_privati_di_voice_clone():
    app_src = (ROOT / "audiobook_app.py").read_text(encoding="utf-8")
    assert "voice_clone._ACCEPTED_EXT" not in app_src
    assert "voice_clone.accepted_ext()" in app_src
    import voice_clone
    assert voice_clone.accepted_ext() == frozenset(voice_clone.ACCEPTED_EXT if hasattr(voice_clone, "ACCEPTED_EXT") else voice_clone._ACCEPTED_EXT)
    js_ext = re.search(r"ACCEPTED_EXT = \[([^\]]+)\]", VC).group(1)
    assert set(re.findall(r"'(\w+)'", js_ext)) == set(voice_clone.accepted_ext())
```

Run: `python -m pytest test/test_voice_clone_frontend.py test/test_voice_clone_api.py -q` → verdi (`test_voice_clone_api.py` e' il file del piano 2 che copre `/api/voice_clone/sample`; se il nome differisce, usa quello che contiene i test su `too_large`).

- [ ] **Step 5: rilettura nativa delle stringhe fr/es/de/zh/hi**

Rileggi tutte le chiavi `vc_*` delle cinque lingue non vincolate: ogni stringa deve suonare come scritta da un madrelingua (registro informale ma cortese come il resto della UI di quella lingua: verifica il «tu/vous», «du/Sie», «你/您» gia' usato dalle chiavi esistenti e mantienilo), stessi segnaposto `{p}`, `{n}`, `{mb}` degli originali, virgolette tipografiche coerenti con la lingua. Correggi in loco. Non toccare IT/EN.

Run: `python -m pytest test/test_voice_clone_frontend.py test/test_i18n_completeness.py test/test_voxcpm_i18n.py -q` → verdi.

- [ ] **Step 6: collaudo manuale**

Crea `docs/MANUAL_TESTS_VOCI_CAMPIONATE.md` sul modello di `docs/MANUAL_TESTS_VOXCPM.md` (stessa struttura: prerequisiti, tabella dei casi con id, passi, esito atteso, colonna esito). Casi minimi:

| Id | Caso |
|----|------|
| VC-01 | Bottone visibile solo con VoxCPM su scheda PREMIUM e lingua offerta; tooltip; feature spenta → assente |
| VC-02 | Condizioni: «Avanti» disabilitato senza spunta |
| VC-03 | Registrazione: pallino, livello, timer, stop automatico a 25 s |
| VC-04 | Scarto per ogni motivo raggiungibile (corto, lungo, rumore, testo sbagliato, formato) con messaggio nella lingua UI |
| VC-05 | Caricamento file: `.flac` rifiutato lato client; file > limite rifiutato lato client |
| VC-06 | Campione accettato: player, «Rifaccio», «Va bene, avanti» |
| VC-07 | Email non coincidenti / non valide |
| VC-08 | Pagamento PayPal sandbox → commit → codice-voce mostrato una volta |
| VC-09 | Pagamento voucher → commit |
| VC-10 | Prezzo gratis (`free`) → commit senza modal di pagamento |
| VC-11 | Attesa e arrivo demo via SSE; chiusura e ripresa dal bottone «Riprendi» |
| VC-12 | Rigenera: contatore decrementa; esaurite → bottone disabilitato |
| VC-13 | Approva → combo con «Le tue voci», voce preselezionata, generazione con la voce, tag `abm_voice` = «user-voice» |
| VC-14 | Rifiuta → conferma inline → rimborso; voce sparita da «Le tue voci» |
| VC-15 | Demo fallite → «Riprova» / «Rifiuta» |
| VC-16 | Link email `/vc/<token>/resume` → pagina → POST → `/?vc=` → modal sul pannello giusto, query rimossa |
| VC-17 | Claim da secondo browser → pending → conferma via email → voce ricevuta con etichetta generica; «Rimuovi» solo su questa |
| VC-18 | Proprietario elimina la voce → il secondo browser vede l'errore dedicato in generazione e la combo si aggiorna |
| VC-19 | Voce di lingua diversa dal libro → errore dedicato |
| VC-20 | «Rimanda l'email» proprietario: 3 ok, 4° → messaggio di limite |
| VC-21 | Cambio lingua UI a modal aperto: tutte le etichette cambiano (nessuna chiave grezza) |
| VC-22 | Flusso premium Gemini con voucher e PayPal invariato (regressione pay modal) |
| VC-23 | Sezione privacy visibile in IT/EN con numerazione 1..19 |

- [ ] **Step 7: suite completa**

Run: `python -m pytest test/ -q --deselect test/test_voxcpm_runpod.py::test_il_capitolo_inoltra_gli_avanzamenti --deselect test/test_voxcpm_runpod.py::test_l_interruttore_spegne_l_inoltro` → tutto verde (≈7 minuti). `git diff --stat` di ogni file CRLF: poche righe, nessuna riscrittura.

- [ ] **Step 8: commit**

```
git add privacy_content.py seo_content.py voice_clone.py audiobook_app.py templates/_fragments/i18n_data.js test/test_privacy_voice_clone.py test/test_voice_clone_frontend.py
git add -f docs/MANUAL_TESTS_VOCI_CAMPIONATE.md
git commit -m "feat(voice-clone): informativa privacy, accepted_ext e collaudo manuale"
```

---

## Self-review

**Copertura della spec.** §3.1 bottone e tooltip → T2; §3.2 condizioni e spunta → T2; §3.3 registrazione/caricamento con vincoli tecnici → T3; §3.4 email, brano extra, pagamento, codice-voce una volta → T4; §3.5 attesa «da uno a quattro minuti», demo, approva/rigenera/rifiuta con contatore → T5; §3.6 ripresa (banner + `?vc=`) → T2/T6; §3.7 «Le tue voci» con claim/conferma/rimuovi/rimanda → T6; §3.8 voce nella combo e errori di generazione → T1/T6; §5.3 motivi di scarto → T3 (chiavi `vc_gate_*` allineate ai `reason` del piano 2); §6.4 codice-voce mostrato solo al proprietario → T4/T6; §11 privacy → T7. Nessun requisito UI della spec resta scoperto. Le pagine server-rendered (`/vc/<token>/*`) sono del piano 2 e restano monolingua inglese.

**Segnaposto.** Nessun «TBD/TODO». I punti in cui il piano dice «verifica il nome reale» (id della scheda premium, funzione del nome lingua, variabile `gd`, classe `.spinner`, accessor di `privacy_content`/`seo_content`) riguardano nomi gia' presenti nel codice che l'implementatore deve leggere, non decisioni aperte; ogni test ha un'asserzione concreta.

**Coerenza dei tipi.** `vociMie` restituisce `gender:'Female'|'Male'` come le voci di catalogo (usato dagli optgroup ♀/♂ di `app.js`) e `demos:[{common,url}]` + `sample_url` come si aspetta `_loadVoxcpmSample`. `S.cur` ha sempre `{clone_id, view, voice_code}` (T3 lo crea, T4 lo aggiorna, T5/T6 lo leggono). `vcShow(n)` accetta `1..4|'mine'` ovunque. `_openPayModalCtx` riceve `titleKey/noticeKey/paypal.captureJobId` che T4 aggiunge in `app.js`. `vcAction` (per-voce, aggiorna P4) e `vcAction2` (per-voce, solo esito) sono distinte perche' i pannelli reagiscono in modo diverso. `TEST_ATTESI`: 22 → 26 (T1) → 35 (T2). Le chiavi i18n sono 3 (T1) + 24 (T2) + 28 (T3) + 17 (T4) + 19 (T5) + 24 (T6) = 115 per lingua.
