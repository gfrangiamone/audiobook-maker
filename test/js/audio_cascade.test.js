const test = require('node:test');
const assert = require('node:assert');
const {resolveAudioSelection} = require('../../static/js/audio_cascade.js');

/* Catalogo minimo, nella forma di /api/voices. Volutamente piccolo: i numeri
   veri (75 lingue, 1.957 voci) non rendono un test piu' vero, solo piu' lento
   da leggere quando fallisce. */
const CATALOGO = {
  _voxcpm: {available: true, model_label: 'VoxCPM2', personas: []},
  _premium_status: {capability_ok: true, admin_disabled: false},
  _translate_available: false,
  it: {name: 'Italian', voices: [
    {id: 'it-IT-IsabellaNeural', name: 'Isabella', gender: 'Female', locale: 'it-IT', engine: 'edge'},
    {id: 'it-IT-DiegoNeural', name: 'Diego', gender: 'Male', locale: 'it-IT', engine: 'edge'},
    {id: 'gemini:flash25:Achernar', name: 'Achernar', gender: 'Female', locale: 'it-IT', engine: 'gemini'},
    {id: 'voxcpm:v2:it-IT/Bianca', name: 'Bianca', gender: 'Female', locale: 'it-IT', engine: 'voxcpm'},
  ]},
  en: {name: 'English', voices: [
    {id: 'en-US-AvaNeural', name: 'Ava', gender: 'Female', locale: 'en-US', engine: 'edge'},
    {id: 'en-GB-SoniaNeural', name: 'Sonia', gender: 'Female', locale: 'en-GB', engine: 'edge'},
    {id: 'gemini:flash25:Puck', name: 'Puck', gender: 'Male', locale: 'en-US', engine: 'gemini', model_key: 'flash25'},
    {id: 'gemini:flash31:Puck', name: 'Puck', gender: 'Male', locale: 'en-US', engine: 'gemini', model_key: 'flash31'},
    {id: 'voxcpm:v2:en-US/Grace', name: 'Grace', gender: 'Female', locale: 'en-US', engine: 'voxcpm'},
    {id: 'speechify:simba-3.2:beatrice_32', name: 'Beatrice', gender: 'Female', locale: 'en-GB', engine: 'speechify'},
  ]},
  fr: {name: 'French', voices: [
    {id: 'fr-FR-DeniseNeural', name: 'Denise', gender: 'Female', locale: 'fr-FR', engine: 'edge'},
    {id: 'gemini:flash25:Kore', name: 'Kore', gender: 'Female', locale: 'fr-FR', engine: 'gemini'},
  ]},
  sv: {name: 'Swedish', voices: [
    {id: 'sv-SE-SofieNeural', name: 'Sofie', gender: 'Female', locale: 'sv-SE', engine: 'edge'},
  ]},
  es: {name: 'Spanish', voices: [
    {id: 'es-ES-ElviraNeural', name: 'Elvira', gender: 'Female', locale: 'es-ES', engine: 'edge'},
    {id: 'es-MX-DaliaNeural', name: 'Dalia', gender: 'Female', locale: 'es-MX', engine: 'edge'},
    {id: 'es-AR-ElenaNeural', name: 'Elena', gender: 'Female', locale: 'es-AR', engine: 'edge'},
    {id: 'gemini:flash25:Lyra', name: 'Lyra', gender: 'Female', locale: 'es-ES', engine: 'gemini'},
  ]},
};

test('italiano: premium attivo, tre modelli, VOXCPM2 di default', () => {
  const r = resolveAudioSelection({lang: 'it', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.premiumEnabled, true);
  assert.deepStrictEqual(r.premium.models, ['voxcpm', 'flash25', 'flash31']);
  assert.strictEqual(r.premium.model, 'voxcpm');
});

test('italiano: un solo locale, niente riga accento in Standard', () => {
  const r = resolveAudioSelection({lang: 'it', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.standard.accents.length, 1);
});

test('inglese: quattro modelli, Simba incluso', () => {
  const r = resolveAudioSelection({lang: 'en', catalog: CATALOGO, current: {}});
  assert.deepStrictEqual(r.premium.models,
    ['voxcpm', 'flash25', 'flash31', 'simba-3.2']);
});

test('i due modelli Gemini non condividono le voci', () => {
  /* Condividono il prefisso `gemini:` ma non l'id completo. Se il filtro
     tornasse al solo prefisso corto, ogni modello mostrerebbe anche le voci
     dell'altro e l'utente sceglierebbe una voce che il suo modello non ha. */
  const std = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO, current: {tab: 'premium', model: 'flash25'}});
  const avz = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO, current: {tab: 'premium', model: 'flash31'}});
  assert.deepStrictEqual(std.premium.voices.map(v => v.id), ['gemini:flash25:Puck']);
  assert.deepStrictEqual(avz.premium.voices.map(v => v.id), ['gemini:flash31:Puck']);
});

test('inglese con modello Avanzato: quattro varianti di accento', () => {
  const r = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO, current: {tab: 'premium', model: 'flash31'}});
  assert.strictEqual(r.premium.model, 'flash31');
  assert.strictEqual(r.premium.accents.length, 4);
});

test('svedese: premium spento, col motivo', () => {
  /* Parte da un `current` che sta davvero sul tab premium: solo cosi`
     l'assert sul tab tornato a 'standard' significa qualcosa (con
     `current: {}` il tab parte gia` da 'standard' e l'assert e` tautologico). */
  const r = resolveAudioSelection({
    lang: 'sv', catalog: CATALOGO, current: {tab: 'premium', model: 'flash25'}});
  assert.strictEqual(r.premiumEnabled, false);
  assert.strictEqual(r.premiumReason, 'no_premium_voices');
  assert.strictEqual(r.tab, 'standard');
  assert.ok(r.changes.some(c => c.what === 'tab' && c.to === 'standard'),
    'il downgrade forzato dal tab premium non e` segnalato in changes');
});

test('spagnolo: tre locali, riga accento visibile in Standard', () => {
  const r = resolveAudioSelection({lang: 'es', catalog: CATALOGO, current: {}});
  assert.deepStrictEqual(r.standard.accents.sort(),
    ['es-AR', 'es-ES', 'es-MX']);
});

test('catalogo senza Speechify: Simba assente anche in inglese', () => {
  const senzaSimba = JSON.parse(JSON.stringify(CATALOGO));
  senzaSimba.en.voices = senzaSimba.en.voices.filter(
    v => !v.id.startsWith('speechify:'));
  const r = resolveAudioSelection({lang: 'en', catalog: senzaSimba, current: {}});
  assert.ok(!r.premium.models.includes('simba-3.2'));
});

test('catalogo senza VoxCPM: il modello non compare', () => {
  const senzaVox = JSON.parse(JSON.stringify(CATALOGO));
  senzaVox._voxcpm = {available: false, model_label: '', personas: []};
  const r = resolveAudioSelection({lang: 'it', catalog: senzaVox, current: {}});
  assert.ok(!r.premium.models.includes('voxcpm'));
  assert.strictEqual(r.premium.model, 'flash25');
});

test('it -> sv con VOXCPM2 attivo: si scende a Standard e lo si dice', () => {
  const r = resolveAudioSelection({
    lang: 'sv', catalog: CATALOGO,
    current: {tab: 'premium', model: 'voxcpm', premiumVoice: 'voxcpm:v2:it-IT/Bianca'}});
  assert.strictEqual(r.tab, 'standard');
  const cambiati = r.changes.map(c => c.what);
  assert.ok(cambiati.includes('tab'), 'il cambio di tab non e` segnalato');
  assert.ok(cambiati.includes('model'), 'il cambio di modello non e` segnalato');
});

test('it -> fr con Avanzato attivo: il modello si preserva', () => {
  const r = resolveAudioSelection({
    lang: 'fr', catalog: CATALOGO,
    current: {tab: 'premium', model: 'flash31'}});
  assert.strictEqual(r.premium.model, 'flash31');
  assert.ok(!r.changes.some(c => c.what === 'model'),
    'un modello preservato non deve comparire fra i cambiamenti');
});

test('en -> it con Simba attivo: il modello non e` preservabile', () => {
  const r = resolveAudioSelection({
    lang: 'it', catalog: CATALOGO,
    current: {tab: 'premium', model: 'simba-3.2'}});
  assert.strictEqual(r.premium.model, 'voxcpm');
  assert.ok(r.changes.some(c => c.what === 'model'));
});

test('la cascata e` idempotente', () => {
  const primo = resolveAudioSelection({lang: 'en', catalog: CATALOGO, current: {}});
  const stato = {
    tab: primo.tab,
    standardAccent: primo.standard.accent,
    standardVoice: primo.standard.voice,
    model: primo.premium.model,
    premiumAccent: primo.premium.accent,
    premiumVoice: primo.premium.voice,
  };
  const secondo = resolveAudioSelection({lang: 'en', catalog: CATALOGO, current: stato});
  assert.deepStrictEqual(secondo.changes, [],
    'la seconda applicazione non deve cambiare nulla');
  assert.strictEqual(secondo.premium.model, primo.premium.model);
  assert.strictEqual(secondo.standard.voice, primo.standard.voice);
});

test('lingua sconosciuta al catalogo: non esplode', () => {
  const r = resolveAudioSelection({lang: 'xx', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.premiumEnabled, false);
  assert.deepStrictEqual(r.standard.voices, []);
});

test('voce Speechify senza `engine`: niente fuga nel tab Standard', () => {
  /* L'invariante e` sul prefisso dell'id, mai sul campo vetrina `engine`. Se
     un domani `engine` mancasse o fosse sbagliato su una voce a pagamento,
     vociStandard non deve comunque lasciarla passare nel tab gratuito:
     l'utente la sceglierebbe pensando sia gratis e si beccherebbe un 402. */
  const senzaEngine = JSON.parse(JSON.stringify(CATALOGO));
  const simba = senzaEngine.en.voices.find(v => v.id.indexOf('speechify:') === 0);
  delete simba.engine;
  /* L'accento forzato a quello del Simba (en-GB) evita che il filtro per
     locale nasconda per caso la fuga: se non fosse per _ePremium, questa
     e` proprio la richiesta che la farebbe comparire in Standard. */
  const r = resolveAudioSelection({
    lang: 'en', catalog: senzaEngine, current: {standardAccent: simba.locale}});
  assert.ok(!r.standard.voices.some(v => v.id === simba.id),
    'una voce Speechify senza `engine` e` finita nel tab Standard');
});

test('premium.accents e` una copia: mutarlo non tocca le chiamate successive', () => {
  const primo = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO, current: {tab: 'premium', model: 'flash31'}});
  const codiciOriginali = primo.premium.accents.map(c => c[0]);
  primo.premium.accents.reverse();
  primo.premium.accents.forEach(c => c.reverse());
  const secondo = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO, current: {tab: 'premium', model: 'flash31'}});
  assert.deepStrictEqual(secondo.premium.accents.map(c => c[0]), codiciOriginali,
    'la tabella ACCENT_CATALOG condivisa e` stata corrotta da chi consuma il risultato');
});

test('it -> sv: una standardVoice non disponibile ricade con il motivo giusto', () => {
  const r = resolveAudioSelection({
    lang: 'sv', catalog: CATALOGO,
    current: {standardVoice: 'it-IT-IsabellaNeural'}});
  assert.strictEqual(r.standard.voice, 'sv-SE-SofieNeural');
  assert.deepStrictEqual(
    r.changes.find(c => c.what === 'voice'),
    {what: 'voice', from: 'it-IT-IsabellaNeural', to: 'sv-SE-SofieNeural',
     reason: 'voice_unavailable_in_lang'});
});

test('spagnolo: scegliere un accento riduce davvero le voci Standard', () => {
  const r = resolveAudioSelection({
    lang: 'es', catalog: CATALOGO, current: {standardAccent: 'es-ES'}});
  assert.deepStrictEqual(r.standard.voices.map(v => v.id), ['es-ES-ElviraNeural']);
});

test('italiano: un solo locale, il filtro accento e` saltato', () => {
  /* Contraltare del test spagnolo: con un solo locale in gioco vociStandard
     riceve locale='' e non deve scartare nessuna voce gratuita. */
  const r = resolveAudioSelection({lang: 'it', catalog: CATALOGO, current: {}});
  assert.deepStrictEqual(r.standard.voices.map(v => v.id).sort(),
    ['it-IT-DiegoNeural', 'it-IT-IsabellaNeural']);
});
