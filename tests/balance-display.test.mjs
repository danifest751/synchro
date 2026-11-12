import assert from 'node:assert/strict';
import test from 'node:test';
import {createModelPicker} from '../extension/model-picker.mjs';

test('key allowance is described separately and never shown as account balance', async () => {
  const previous = globalThis.document;
  const elements = new Map();
  globalThis.document = {getElementById(id) {
    if (!elements.has(id)) elements.set(id, {textContent:'', disabled:false});
    return elements.get(id);
  }};
  try {
    const picker = createModelPicker({provider:() => 'openrouter', model:{value:''}, settings:() => ({}),
      request:async () => ({balance_usd:null, key_spent_usd:4.25, key_limit_remaining_usd:15.75,
        balance_note:'The key allowance is not the account balance.'})});
    await picker.loadBalance();
    assert.equal(elements.get('cloudBalance').textContent, '—');
    assert.match(elements.get('balanceStatus').textContent, /Key spent/);
    assert.match(elements.get('balanceStatus').textContent, /Key allowance remaining/);
    assert.match(elements.get('balanceStatus').textContent, /not the account balance/);
  } finally { globalThis.document = previous; }
});
