import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('a playback error can be dismissed and retried from the same position', async () => {
  const elements = new Map(), listeners = new Map(), sent = [];
  let receive, frame;
  const element = () => ({style: {setProperty() {}, removeProperty() {}}, dataset: {}, hidden: false,
    textContent: '', value: '', isConnected: true, firstElementChild: {textContent: ''},
    classList: {contains: () => false, toggle() {}}, setAttribute(name, value) { this[name] = value; },
    getAttribute(name) { return this[name]; }, removeAttribute() {}, append() {}, remove() {}, focus() {}});
  const root = {getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }, addEventListener() {}};
  const host = {...element(), attachShadow: () => root};
  const video = {...element(), duration: 1200, currentTime: 600, paused: true, readyState: 4, playbackRate: 1, volume: .5,
    closest: () => element(), pause() { this.paused = true; }, play() { this.paused = false; return Promise.resolve(); },
    addEventListener(name, handler) { listeners.set(name, handler); }, removeEventListener() {}};
  const player = {...element(), querySelector: query => query === 'video' ? video : null};
  class AudioContext {
    currentTime = 0;
    createGain() { return {gain: {value: 0}, connect() {}}; }
    resume() { return Promise.resolve(); }
  }
  const context = vm.createContext({
    window: {addEventListener() {}}, document: {querySelector: () => player, createElement: name => name === 'div' ? host : element(), documentElement: element()},
    location: {href: 'https://www.youtube.com/watch?v=test'}, AudioContext, performance, console,
    chrome: {runtime: {sendMessage: async message => { sent.push(message); return {ok: true}; },
      onMessage: {addListener: handler => { receive = handler; }}}, storage: {local: {get: async () => ({}), set: async () => {}}}},
    requestAnimationFrame: handler => { frame = handler; }, setInterval() {}, setTimeout, clearTimeout,
  });
  const result = vm.runInContext(fs.readFileSync(new URL('../extension/youtube.js', import.meta.url), 'utf8'), context);
  assert.equal(result.ok, true);
  receive({type: 'youtube-event', event: {type: 'error', revision: 1, message: 'Kilo returned an empty response'}});
  frame();
  assert.match(elements.get('statusText').textContent, /empty response/);
  assert.equal(elements.get('retry').hidden, false);
  elements.get('dismiss').onclick();
  frame();
  assert.doesNotMatch(elements.get('statusText').textContent, /empty response/);
  assert.equal(elements.get('dismiss').hidden, true);
  assert.equal(elements.get('start').textContent, 'Retry translation');
  await elements.get('start').onclick();
  assert.equal(sent.at(-1).type, 'youtube-seek');
  assert.equal(sent.at(-1).position, 600);
  assert.equal(sent.at(-1).revision, 2);
  receive({type: 'youtube-event', event: {type: 'result', revision: 2, ready_until: 610, finished: false, segments: []}});
  receive({type: 'youtube-event', event: {type: 'error', revision: 1, message: 'stale error'}});
  frame();
  assert.equal(video.paused, false, 'first ten seconds are enough to start playback');
  assert.doesNotMatch(elements.get('statusText').textContent, /error|Preparing|empty response/);
});
