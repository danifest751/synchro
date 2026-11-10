import test from 'node:test';
import assert from 'node:assert/strict';
import {canStart, playableUntil, scheduleCue, cueRate, cueAt} from '../extension/timeline.mjs';
import {updateAction} from '../extension/updates.mjs';
import {serverBase, PUBLIC_API, LOCAL_API} from '../extension/connection.mjs';
import {translationSettings} from '../extension/translation.mjs';

test('video cannot outrun a missing translation', () => {
  assert.equal(playableUntil(40, 7), 7);
  assert.equal(canStart(40, 2, 0, 20, false), false);
  assert.equal(canStart(20, 7, 0, 20, false), true);
});
test('short final video can start without a full delay buffer', () => {
  assert.equal(canStart(5, 5, 0, 20, true), true);
});
test('seeking into a cue resumes the remaining audio', () => {
  assert.deepEqual(scheduleCue({start: 10, duration: 4}, 12), {delay: 0, offset: 2});
  assert.equal(scheduleCue({start: 10, duration: 4}, 14), null);
});

test('long narration slows its own video interval and maps seeks to audio time', () => {
  const cue = {start: 10, source_duration: 4, duration: 8};
  assert.equal(cueRate(cue), .5);
  assert.deepEqual(scheduleCue(cue, 12), {delay: 0, offset: 4});
  assert.equal(cueAt([cue], 14), undefined);
  assert.equal(scheduleCue(cue, 14), null);
});

test('updating never interrupts capture or an open player', () => {
  assert.equal(updateAction('0.1.0', '0.2.0', true, false), 'defer');
  assert.equal(updateAction('0.1.0', '0.2.0', false, true), 'defer');
  assert.equal(updateAction('0.1.0', '0.2.0', false, false), 'reload');
  assert.equal(updateAction('0.2.0', '0.2.0', false, false), 'none');
  assert.equal(updateAction('0.2.0', undefined, false, false), 'none');
});

test('connection tokens can only be sent to the two Synchro endpoints', () => {
  assert.equal(serverBase(), LOCAL_API);
  assert.equal(serverBase(PUBLIC_API + '/'), PUBLIC_API);
  for (const url of ['https://evil.example', PUBLIC_API + '.evil.example', PUBLIC_API.replace('://', '://token@'), PUBLIC_API + '/other', PUBLIC_API.replace('https:', 'http:')]) {
    assert.throws(() => serverBase(url));
  }
});

test('local mode discards cloud keys and cloud settings validate provider and credentials', () => {
  assert.deepEqual(translationSettings({provider: 'local', api_key: 'private-cloud-api-key-123'}), {provider: 'local'});
  assert.equal(translationSettings({provider: 'kilo', api_key: 'private-cloud-api-key-123'}).model, 'tencent/hy-mt2-1.8b');
  for (const value of [{provider: 'unknown'}, {provider: 'openai', api_key: 'short'}, {provider: 'kilo', model: 'bad model', api_key: 'private-cloud-api-key-123'}]) {
    assert.throws(() => translationSettings(value));
  }
});
