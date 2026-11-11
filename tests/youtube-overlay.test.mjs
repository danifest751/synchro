import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('a playback error can be dismissed and retried from the same position', async () => {
  const elements = new Map(), listeners = new Map(), sent = [];
  let receive, frame, ad = false, statusDestroyed = false, decodeResolve;
  const audioSources = [];
  const element = () => ({style: {setProperty() {}, removeProperty() {}}, dataset: {}, hidden: false,
    textContent: '', value: '', isConnected: true, firstElementChild: {textContent: ''},
    classList: {contains: () => false, toggle() {}}, setAttribute(name, value) { this[name] = value; },
    getAttribute(name) { return this[name]; }, removeAttribute() {}, append() {}, remove() {}, focus() {}});
  const root = {getElementById(id) {
    if (statusDestroyed && ['statusText', 'retry', 'dismiss', 'usageText'].includes(id)) return null;
    if (!elements.has(id)) {
      const created = element();
      if (id === 'voice') created.options = ['albina', 'alfia', 'roman', 'eduard', 'alexandr'].map(value => ({value}));
      if (id === 'status') Object.defineProperty(created, 'textContent', {get: () => '', set() { statusDestroyed = true; }});
      elements.set(id, created);
    }
    return elements.get(id);
  }, addEventListener() {}};
  const host = {...element(), attachShadow: () => root};
  const video = {...element(), duration: 1200, currentTime: 600, paused: true, readyState: 4, playbackRate: 1, volume: .5,
    closest: () => element(), pause() { this.paused = true; }, play() { this.paused = false; return Promise.resolve(); },
    addEventListener(name, handler) { listeners.set(name, handler); }, removeEventListener() {}};
  const player = {...element(), classList: {contains: name => name === 'ad-showing' && ad}, querySelector: query => query === 'video' ? video : null};
  class AudioContext {
    currentTime = 0;
    createGain() { return {gain: {value: 0}, connect() {}}; }
    resume() { return Promise.resolve(); }
    decodeAudioData() { return new Promise(resolve => { decodeResolve = resolve; }); }
    createBufferSource() {
      const source = {connect() {}, start(...args) { this.started = args; }, stop() { this.stopped = true; }};
      audioSources.push(source); return source;
    }
  }
  const context = vm.createContext({
    window: {addEventListener() {}}, document: {querySelector: () => player, createElement: name => name === 'div' ? host : element(), documentElement: element()},
    location: {href: 'https://www.youtube.com/watch?v=test'}, AudioContext, performance, console, atob,
    chrome: {runtime: {sendMessage: async message => { sent.push(message); return {ok: true}; },
      onMessage: {addListener: handler => { receive = handler; }}}, storage: {local: {get: async () => ({voice: 'male-eugene', translation: {mode: 'cloud_translation'}}), set: async () => {}}}},
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
  await Promise.resolve();
  assert.equal(elements.get('voice').value, 'eduard');
  assert.equal(elements.get('start').textContent, 'Retry translation');
  await elements.get('start').onclick();
  assert.equal(sent.at(-1).type, 'youtube-seek');
  assert.equal(sent.at(-1).position, 600);
  assert.equal(sent.at(-1).revision, 2);
  receive({type: 'youtube-event', event: {type: 'result', revision: 2, ready_until: 610, finished: false,
    segments: [{id: 1, start: 600, source_duration: 1, duration: 1, text: 'Привет', wav: 'AA=='}]}});
  await new Promise(resolve => setImmediate(resolve));
  frame();
  assert.equal(video.paused, true, 'video waits for decoded audio, so the beginning of speech is never skipped');
  decodeResolve({duration: 1});
  await new Promise(resolve => setImmediate(resolve));
  receive({type: 'youtube-event', event: {type: 'error', revision: 1, message: 'stale error'}});
  frame();
  assert.equal(video.paused, false, 'first ten seconds are enough to start playback');
  assert.doesNotMatch(elements.get('statusText').textContent, /error|Preparing|empty response/);
  assert.equal(audioSources[0].started[1], 0, 'the first voice starts at its beginning');
  video.currentTime = 609.1; frame();
  assert.equal(video.paused, true, 'wait for boundary words while a one-second lookback is still playable');
  receive({type: 'youtube-event', event: {type: 'result', revision: 2, ready_until: 630, finished: false,
    segments: [{id: 2, start: 601, source_duration: 2, duration: 1, text: 'Короткая фраза', wav: 'AA=='},
      {id: 3, start: 604, source_duration: 1, duration: 20, text: 'Очень длинная фраза', wav: 'AA=='}]}});
  await new Promise(resolve => setImmediate(resolve)); decodeResolve({duration: 1});
  await new Promise(resolve => setImmediate(resolve)); decodeResolve({duration: 20});
  await new Promise(resolve => setImmediate(resolve));
  video.currentTime = 601; frame();
  assert.equal(video.playbackRate, 2, 'shorter speech and its source phrase finish together');
  video.currentTime = 603; frame();
  assert.equal(video.playbackRate, 1, 'real source pauses keep their original speed');
  video.currentTime = 604; frame();
  assert.equal(video.playbackRate, .0625);
  const longSource = audioSources.at(-1);
  video.currentTime = 605; frame();
  assert.equal(video.paused, true, 'speech beyond Chromium minimum speed holds the picture at its end');
  assert.notEqual(longSource.stopped, true, 'the last words are not cut off');
  longSource.onended(); frame();
  assert.equal(video.paused, false, 'video resumes once the last words finish');
  ad = true; frame();
  assert.equal(statusDestroyed, false, 'ad status must preserve retry and message elements');
  ad = false; frame();
  assert.equal(sent.at(-1).type, 'youtube-seek');
});
