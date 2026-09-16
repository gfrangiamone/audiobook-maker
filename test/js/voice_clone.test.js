'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {vociMie} = require('../../static/js/audio_cascade.js');

const CAT = {
  it: {voices: [{id: 'voxcpm:it-IT/Elena', locale: 'it-IT', gender: 'Female'}]},
  _voxcpm: {available: true, model_label: 'VoxCPM2', personas: {}},
  _mine: [
    {id: 'vc_a1', state: 'ready', voice_id: 'voxcpm:mine:TOKA', lang: 'it', locale: 'it-IT',
     gender: 'f', owner: true, pending: false, name: 'Nonna Pina',
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
  assert.equal(out[0].name, 'Nonna Pina');
  assert.equal(out[0].sample_url, '/api/voice_clone/vc_a1/sample.wav');
  assert.deepEqual(out[0].demos, [
    {common: true, url: '/api/voice_clone/vc_a1/demo/common'},
    {common: false, url: '/api/voice_clone/vc_a1/demo/extra'},
  ]);
});

test('vociMie: senza locale filtra solo per lingua', () => {
  assert.deepEqual(vociMie(CAT, 'it', '').map(v => v.id), ['voxcpm:mine:TOKA', 'voxcpm:mine:TOKB']);
  assert.equal(vociMie(CAT, 'it', '')[1].gender, 'Male');
  // voce senza nome: stringa vuota, la combo usa l'etichetta generica
  assert.equal(vociMie(CAT, 'it', '')[1].name, '');
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
  assert.equal(VcCore.vcGateKey(null), 'vc_gate_generic');
});

test('vcGateKey: dal server la chiave arriva col prefisso vc_gate_', () => {
  // Il motivo arriva cosi' dall'API: se il prefisso non viene tolto prima del
  // confronto, ogni scarto degrada a vc_gate_generic (il «Campione non
  // accettato. Riprova» che non dice niente a chi registra).
  assert.equal(VcCore.vcGateKey('vc_gate_short'), 'vc_gate_short');
  assert.equal(VcCore.vcGateKey('vc_gate_transcript'), 'vc_gate_transcript');
  assert.equal(VcCore.vcGateKey('vc_gate_boh'), 'vc_gate_generic');
});

test('vcGateKeys: tutti i motivi dello scarto, senza doppioni', () => {
  const d = {reason: 'vc_gate_short', metrics: {reasons: ['vc_gate_short', 'vc_gate_noise', 'vc_gate_pauses']}};
  assert.deepEqual(VcCore.vcGateKeys(d), ['vc_gate_short', 'vc_gate_noise', 'vc_gate_pauses']);
  // senza metrics resta il solo `reason` (e' il caso del controllo del testo)
  assert.deepEqual(VcCore.vcGateKeys({reason: 'vc_gate_transcript'}), ['vc_gate_transcript']);
  // motivi ignoti o risposta vuota: una riga sola, quella generica
  assert.deepEqual(VcCore.vcGateKeys({reason: 'boh'}), ['vc_gate_generic']);
  assert.deepEqual(VcCore.vcGateKeys({}), ['vc_gate_generic']);
  assert.deepEqual(VcCore.vcGateKeys(null), ['vc_gate_generic']);
  assert.deepEqual(VcCore.vcGateKeys({metrics: {reasons: ['vc_gate_band', 'vc_gate_band']}}), ['vc_gate_band']);
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

test('vcHasReadyFor: una voce pronta nella lingua', () => {
  const mine = [{state: 'ready', lang: 'it', voice_id: 'x'}, {state: 'paid', lang: 'en'}];
  assert.equal(VcCore.vcHasReadyFor(mine, 'it'), true);
  assert.equal(VcCore.vcHasReadyFor(mine, 'en'), false);
});

/* ---------- durata dei WebM registrati ---------- */

/* Finto <audio>: tiene i listener e permette di far scattare gli eventi a
   mano, nell'ordine in cui li manda il browser. */
function fintoAudio(durataIniziale) {
  return {
    duration: durataIniziale, currentTime: 0, paused: true, _l: {},
    addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); },
    removeEventListener(t, f) {
      const a = this._l[t] || []; const i = a.indexOf(f); if (i >= 0) a.splice(i, 1);
    },
    scatta(t) { (this._l[t] || []).slice().forEach(f => f()); },
    listener() { return Object.keys(this._l).reduce((n, t) => n + this._l[t].length, 0); },
  };
}

test('vcFixDurata: registrazione a durata ignota -> cercata in fondo e ritorno a zero', () => {
  const a = fintoAudio(Infinity);
  VcCore.vcFixDurata(a);
  a.scatta('durationchange');            // Infinity: non e' ancora la durata vera
  a.scatta('loadedmetadata');
  assert.equal(a.currentTime, 1e101, 'senza la cercata il parser non legge fino in fondo');
  // il parser arriva in fondo: durata vera, ma il cursore e' rimasto alla fine
  a.duration = 19.001; a.currentTime = 19.001;
  a.scatta('durationchange');
  assert.equal(a.currentTime, 0, 'la barra deve tornare a inizio, non restare al 100%');
  assert.equal(a.listener(), 0, 'a durata nota i listener vanno staccati');
});

test('vcFixDurata: file con durata gia nell header -> non si tocca niente', () => {
  const a = fintoAudio(12.5);
  VcCore.vcFixDurata(a);
  a.scatta('loadedmetadata');
  assert.equal(a.currentTime, 0);
  assert.equal(a.listener(), 0);
});

test('vcFixDurata: a lettore avviato nessuna cercata (spezzerebbe l ascolto)', () => {
  const a = fintoAudio(Infinity);
  a.paused = false;
  VcCore.vcFixDurata(a);
  a.scatta('loadedmetadata');
  assert.equal(a.currentTime, 0);
  a.duration = 19.001; a.currentTime = 4;
  a.scatta('durationchange');
  assert.equal(a.currentTime, 4, 'non si riporta a zero chi sta ascoltando');
});

test('vcFixDurata: lo stacco restituito ripulisce al cambio di sorgente', () => {
  const a = fintoAudio(Infinity);
  const stacca = VcCore.vcFixDurata(a);
  stacca();
  assert.equal(a.listener(), 0);
  a.scatta('loadedmetadata');
  assert.equal(a.currentTime, 0, 'staccato non deve piu' + ' cercare');
});

test('vcFixDurata: elemento assente non fa esplodere il chiamante', () => {
  assert.equal(typeof VcCore.vcFixDurata(null), 'function');
  VcCore.vcFixDurata(null)();
});
