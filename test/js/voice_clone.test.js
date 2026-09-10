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
