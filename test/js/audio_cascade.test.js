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
    {id: 'gemini:flash31:Achernar', name: 'Achernar', gender: 'Female', locale: 'it-IT', engine: 'gemini'},
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
    {id: 'gemini:flash31:Kore', name: 'Kore', gender: 'Female', locale: 'fr-FR', engine: 'gemini'},
  ]},
  sv: {name: 'Swedish', voices: [
    {id: 'sv-SE-SofieNeural', name: 'Sofie', gender: 'Female', locale: 'sv-SE', engine: 'edge'},
  ]},
  es: {name: 'Spanish', voices: [
    {id: 'es-ES-ElviraNeural', name: 'Elvira', gender: 'Female', locale: 'es-ES', engine: 'edge'},
    {id: 'es-MX-DaliaNeural', name: 'Dalia', gender: 'Female', locale: 'es-MX', engine: 'edge'},
    {id: 'es-AR-ElenaNeural', name: 'Elena', gender: 'Female', locale: 'es-AR', engine: 'edge'},
    {id: 'gemini:flash25:Lyra', name: 'Lyra', gender: 'Female', locale: 'es-ES', engine: 'gemini'},
    {id: 'gemini:flash31:Lyra', name: 'Lyra', gender: 'Female', locale: 'es-ES', engine: 'gemini'},
  ]},
};

test('italiano: premium attivo, tre modelli, VOXCPM2 di default', () => {
  const r = resolveAudioSelection({lang: 'it', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.premiumEnabled, true);
  assert.deepStrictEqual(r.premium.models, ['voxcpm', 'flash25', 'flash31']);
  assert.strictEqual(r.premium.model, 'voxcpm');
});

test('italiano: un modello Gemini spento sul server sparisce dal selettore', () => {
  /* L interruttore ABM_<MODELLO>_ENABLE toglie le voci di quel modello dal
     catalogo: la cascata non deve reinventarlo a partire dall altro. */
  const senzaFlash31 = JSON.parse(JSON.stringify(CATALOGO));
  senzaFlash31.it.voices = senzaFlash31.it.voices.filter(v => v.id.indexOf('gemini:flash31:') !== 0);
  const r = resolveAudioSelection({lang: 'it', catalog: senzaFlash31, current: {tab: 'premium', model: 'flash31'}});
  assert.deepStrictEqual(r.premium.models, ['voxcpm', 'flash25']);
  assert.notStrictEqual(r.premium.model, 'flash31');
});

test('italiano: un solo locale, niente riga accento in Standard', () => {
  const r = resolveAudioSelection({lang: 'it', catalog: CATALOGO, current: {}});
  assert.strictEqual(r.standard.accents.length, 1);
});

test('inglese: quattro modelli, nell ordine mostrato', () => {
  /* L ordine non e cosmetico: il primo della lista e anche il modello
     predefinito. */
  const r = resolveAudioSelection({lang: 'en', catalog: CATALOGO, current: {}});
  assert.deepStrictEqual(r.premium.models,
    ['voxcpm', 'simba-3.2', 'flash25', 'flash31']);
});

test('inglese senza VoxCPM: il predefinito e Simba, non Gemini', () => {
  /* Conseguenza voluta dell ordine: quando VOXCPM2 non c e, sull inglese
     resta Simba in testa. */
  const senzaVox = JSON.parse(JSON.stringify(CATALOGO));
  senzaVox._voxcpm = {available: false, model_label: '', personas: []};
  const r = resolveAudioSelection({lang: 'en', catalog: senzaVox, current: {}});
  assert.deepStrictEqual(r.premium.models, ['simba-3.2', 'flash25', 'flash31']);
  assert.strictEqual(r.premium.model, 'simba-3.2');
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

test('svedese: premium spento, col motivo', () => {
  /* Parte da un `current` che sta davvero sul tab premium: solo cosi`
     l'assert sul tab tornato a 'standard' significa qualcosa (con
     `current: {}` il tab parte gia` da 'standard' e l'assert e` tautologico). */
  const r = resolveAudioSelection({
    lang: 'sv', catalog: CATALOGO, current: {tab: 'premium', model: 'flash25'}});
  assert.strictEqual(r.premiumEnabled, false);
  assert.ok(r.changes.some(c => c.what === 'tab' && c.to === 'standard'
                             && c.reason === 'no_premium_voices'),
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
    tab: 'premium',
    standardAccent: primo.standard.accent,
    standardVoice: primo.standard.voice,
    model: primo.premium.model,
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

test('it -> sv: una standardVoice non disponibile ricade con il motivo giusto', () => {
  const r = resolveAudioSelection({
    lang: 'sv', catalog: CATALOGO,
    current: {standardVoice: 'it-IT-IsabellaNeural'}});
  assert.strictEqual(r.standard.voice, 'sv-SE-SofieNeural');
  assert.deepStrictEqual(
    r.changes.find(c => c.what === 'voice'),
    {what: 'voice', from: 'it-IT-IsabellaNeural', to: 'sv-SE-SofieNeural',
     reason: 'voice_unavailable_in_lang', dove: 'standard'});
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

/* Catalogo inglese nell'ordine vero di /api/voices: le voci Edge arrivano
   alfabetiche per ShortName, quindi en-AU precede en-US. Con `accents[0]` e
   `ids[0]` un libro inglese si aprirebbe su due voci australiane. */
const CATALOGO_EN_ALFABETICO = {
  en: {name: 'English', voices: [
    {id: 'en-AU-NatashaNeural', name: 'Natasha', gender: 'Female', locale: 'en-AU', engine: 'edge'},
    {id: 'en-AU-WilliamNeural', name: 'William', gender: 'Male', locale: 'en-AU', engine: 'edge'},
    {id: 'en-GB-SoniaNeural', name: 'Sonia', gender: 'Female', locale: 'en-GB', engine: 'edge'},
    {id: 'en-US-AvaNeural', name: 'Ava', gender: 'Female', locale: 'en-US', engine: 'edge'},
    {id: 'en-US-DavisNeural', name: 'Davis', gender: 'Male', locale: 'en-US', engine: 'edge'},
  ]},
  sv: {name: 'Swedish', voices: [
    {id: 'sv-SE-HilleviNeural', name: 'Hillevi', gender: 'Female', locale: 'sv-SE', engine: 'edge'},
    {id: 'sv-SE-MattiasNeural', name: 'Mattias', gender: 'Male', locale: 'sv-SE', engine: 'edge'},
    {id: 'sv-FI-SelmaNeural', name: 'Selma', gender: 'Female', locale: 'sv-FI', engine: 'edge'},
  ]},
};

test('inglese: la voce preferita decide voce E accento, non l`ordine del catalogo', () => {
  const r = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO_EN_ALFABETICO, current: {}});
  assert.strictEqual(r.standard.voice, 'en-US-DavisNeural',
    'la voce predefinita deve essere quella preferita, non la prima del catalogo');
  assert.strictEqual(r.standard.accent, 'en-US',
    'l`accento predefinito deve essere il locale della voce preferita');
  assert.ok(r.standard.voices.some(v => v.id === 'en-US-DavisNeural'),
    'la lista filtrata deve contenere la voce predefinita');
});

test('lingua senza voci preferite: resta la prima del catalogo', () => {
  const r = resolveAudioSelection({
    lang: 'sv', catalog: CATALOGO_EN_ALFABETICO, current: {}});
  assert.strictEqual(r.standard.accent, 'sv-SE');
  assert.strictEqual(r.standard.voice, 'sv-SE-HilleviNeural');
});

test('inglese: un accento gia` scelto vince sulla voce preferita', () => {
  /* La preferenza vale come DEFAULT, non come correzione: chi ha appena
     scelto en-GB non deve essere riportato su en-US. */
  const r = resolveAudioSelection({
    lang: 'en', catalog: CATALOGO_EN_ALFABETICO,
    current: {standardAccent: 'en-GB', standardVoice: 'en-US-DavisNeural'}});
  assert.strictEqual(r.standard.accent, 'en-GB');
  assert.strictEqual(r.standard.voice, 'en-GB-SoniaNeural');
});

test('la voce premium scelta dall`utente sopravvive alla cascata', () => {
  /* B1: `applyI18n()` -> `applyBookLanguage()` gira anche in mezzo alla
     sequenza di generazione a pagamento, e ricostruisce #vvPremium. La
     cascata e` la fonte di verita` che app.js riversa nel select dopo il
     rebuild: se smettesse di preservare la voce in ingresso, l'audiolibro
     pagato uscirebbe con una voce che l'utente non ha scelto. */
  /* Catalogo esteso con una SECONDA voce flash31: con una sola voce per
     modello «preservare la scelta» e «ripiegare sulla prima» danno lo stesso
     risultato, e il test passerebbe anche su una cascata che la scelta la
     butta via. La voce dell'utente e` la seconda, non la prima. */
  const catalogo = {...CATALOGO, en: {...CATALOGO.en, voices: [
    ...CATALOGO.en.voices,
    {id: 'gemini:flash31:Kore', name: 'Kore', gender: 'Female',
     locale: 'en-US', engine: 'gemini', model_key: 'flash31'},
  ]}};
  const r = resolveAudioSelection({
    lang: 'en', catalog: catalogo,
    current: {tab: 'premium', model: 'flash31',
              premiumVoice: 'gemini:flash31:Kore'}});
  assert.deepStrictEqual(r.premium.voices.map(v => v.id),
    ['gemini:flash31:Puck', 'gemini:flash31:Kore']);
  assert.strictEqual(r.premium.voice, 'gemini:flash31:Kore');
  assert.ok(!r.changes.some(c => c.what === 'voice'),
    'una voce premium ancora valida non deve comparire fra i cambiamenti');
});

test('il reset di una voce dice a quale tab appartiene', () => {
  /* D3: la nota che l'utente legge parla del tab che ha davanti. Senza
     `dove` chi sta sul tab PREMIUM leggerebbe l'annuncio del reset della
     voce Standard, che non e` nemmeno sullo schermo. */
  const r = resolveAudioSelection({
    lang: 'it', catalog: CATALOGO,
    current: {tab: 'premium', model: 'flash25',
              standardVoice: 'en-US-AvaNeural',
              premiumVoice: 'gemini:flash25:Puck'}});
  const perTab = {};
  for (const c of r.changes) if (c.what === 'voice') perTab[c.dove] = c.to;
  assert.strictEqual(perTab.standard, 'it-IT-IsabellaNeural');
  assert.strictEqual(perTab.premium, 'gemini:flash25:Achernar');
});
