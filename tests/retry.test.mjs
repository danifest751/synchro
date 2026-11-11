import test from 'node:test';
import assert from 'node:assert/strict';
import {retried} from '../extension/youtube-offscreen.mjs';

const failure = status => Object.assign(new Error('failed'), {status});

test('transient gateway and network failures are retried', async () => {
  const errors = [failure(504), new TypeError('network'), failure(409)];
  let calls = 0;
  const result = await retried(async () => { calls++; if (errors.length) throw errors.shift(); return 'window'; }, undefined, [0, 0, 0]);
  assert.equal(result, 'window');
  assert.equal(calls, 4);
});

test('permanent errors, exhausted retries and stopping are not retried', async () => {
  let calls = 0;
  await assert.rejects(retried(async () => { calls++; throw failure(404); }, undefined, [0, 0]), /failed/);
  assert.equal(calls, 1);
  calls = 0;
  await assert.rejects(retried(async () => { calls++; throw failure(502); }, undefined, [0, 0]));
  assert.equal(calls, 3);
  const stop = new AbortController();
  calls = 0;
  const pending = retried(async () => { calls++; stop.abort(); throw failure(502); }, stop.signal, [60000]);
  await assert.rejects(pending);
  assert.equal(calls, 1);
});
