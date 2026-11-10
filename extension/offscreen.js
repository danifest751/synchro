import {youtubeControl} from './youtube-offscreen.mjs';
import {serverBase} from './connection.mjs';
import {translationSettings} from './translation.mjs';
const channel = new BroadcastChannel('synchro-player');
let stream, context, recorder, worker, sessionId, config;
let mediaIndex = [], cues = [], pcm = new Int16Array(), offset = 0;
let active = false, draining = false, readyUntil = 0, finished = false, failure = '', mediaEnded = false;
let bytesWritten = 0, storeQueue = Promise.resolve(), requestId = 0, pending = new Map(), stopping;
let recorderDone;
let inputPeak = 0;
const post = (data) => channel.postMessage(data);

function store(type, data = {}, transfer = []) {
  return new Promise((resolve, reject) => {
    const id = ++requestId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('Storage is not responding')); }, 10000);
    pending.set(id, {resolve, reject, timer}); worker.postMessage({type, id, ...data}, transfer);
  });
}

async function api(path, options = {}) {
  const response = await fetch(serverBase(config.apiBase) + path, {...options,
    headers: {Authorization: `Bearer ${config.token}`, ...options.headers}, signal: AbortSignal.timeout(120000)});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Server: ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

function state() {
  post({type: 'state', readyUntil, finished, mediaEnded, failure, active, inputPeak});
}

async function fail(error) {
  failure = error.message || String(error); state();
  await stop(true).catch(() => {});
}

async function drain(final = false) {
  if (draining) return;
  draining = true;
  try {
    while (!failure && (pcm.length >= 128000 || final && pcm.length)) {
      const isFinal = final && pcm.length <= 128000;
      const count = Math.min(128000, pcm.length);
      const input = pcm.slice(0, count);
      const result = await api(`/api/session/${sessionId}/chunk`, {method: 'POST', body: input.buffer,
        headers: {'Content-Type': 'application/octet-stream', 'X-Offset': String(offset), 'X-Final': isFinal ? '1' : '0'}});
      if (result.session_id !== sessionId) throw new Error('Response belongs to another session');
      for (const {wav, ...cue} of result.segments) {
        const bytes = Uint8Array.from(atob(wav), char => char.charCodeAt(0));
        cue.fileName = `cue-${cue.id}.wav`;
        await store('cue', {fileName: cue.fileName, bytes: bytes.buffer}, [bytes.buffer]);
        cues.push(cue); post({type: 'cue', cue});
      }
      readyUntil = result.ready_until;
      const consumed = isFinal ? count : 112000;
      pcm = pcm.slice(consumed); offset += consumed;
      if (isFinal) finished = true;
      state();
    }
  } catch (error) { failure = error.message; state(); void stop(true); }
  finally { draining = false; }
}

async function begin(streamId, nextConfig) {
  if (active) throw new Error('Capture is already running');
  if (stopping) await stopping;
  config = nextConfig;
  if (!sessionId) throw new Error('Models have not been prepared');
  mediaIndex = []; cues = []; pcm = new Int16Array(); offset = 0;
  readyUntil = 0; finished = false; failure = ''; mediaEnded = false; bytesWritten = 0; storeQueue = Promise.resolve();
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio: {mandatory: {chromeMediaSource: 'tab', chromeMediaSourceId: streamId}},
      video: {mandatory: {chromeMediaSource: 'tab', chromeMediaSourceId: streamId, maxWidth: 1280, maxHeight: 720, maxFrameRate: 30}}});
    worker = new Worker('store-worker.js');
    worker.onmessage = ({data}) => { const item = pending.get(data.id); if (!item) return; pending.delete(data.id); clearTimeout(item.timer); data.error ? item.reject(new Error(data.error)) : item.resolve(); };
    worker.onerror = () => void fail(new Error('Local storage failed'));
    await store('open');
    const mimeType = ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp9,opus'].find(type => MediaRecorder.isTypeSupported(type) && MediaSource.isTypeSupported(type));
    if (!mimeType) throw new Error('This browser does not support recording and delayed playback');
    recorder = new MediaRecorder(stream, {mimeType, videoBitsPerSecond: 2500000, audioBitsPerSecond: 96000});
    recorderDone = new Promise(resolve => { recorder.onstop = resolve; });
    recorder.onerror = () => void fail(new Error('Video recording failed'));
    recorder.ondataavailable = ({data, timecode}) => {
      if (!data.size) return;
      storeQueue = storeQueue.then(async () => {
        const bytes = await data.arrayBuffer(), at = bytesWritten;
        await store('append', {bytes, offset: at}, [bytes]);
        const sequence = mediaIndex.length;
        bytesWritten += data.size; mediaIndex.push({offset: at, size: data.size, end: Number(timecode) / 1000 || 0});
        post({type: 'media', sequence, entry: mediaIndex[sequence]});
      }).catch(error => { void fail(error); });
    };
    context = new AudioContext();
    await context.audioWorklet.addModule('pcm-worklet.js');
    const source = context.createMediaStreamSource(stream);
    const capture = new AudioWorkletNode(context, 'synchro-capture');
    capture.port.onmessage = ({data}) => {
      if (!active) return;
      const incoming = new Int16Array(data), merged = new Int16Array(pcm.length + incoming.length);
      inputPeak = incoming.reduce((peak, sample) => Math.max(peak, Math.abs(sample)), 0);
      merged.set(pcm); merged.set(incoming, pcm.length); pcm = merged;
      if (pcm.length > 480000) { void fail(new Error('The server is more than 30 seconds behind')); return; }
      void drain();
    };
    source.connect(capture).connect(context.destination);
    active = true;
    // Both clocks start at capture initialization; verify the remaining offset on real video.
    recorder.start(500); await context.resume();
    for (const track of stream.getVideoTracks()) track.onended = () => void stop();
  } catch (error) { await stop(true); throw error; }
}

async function performStop(abort) {
  active = false;
  if (recorder?.state === 'recording') { recorder.stop(); await recorderDone; }
  await context?.close().catch(() => {});
  stream?.getTracks().forEach(track => track.stop());
  await storeQueue;
  mediaEnded = true; state();
  while (draining) await new Promise(resolve => setTimeout(resolve, 50));
  if (!abort && !failure) {
    await drain(true);
    if (!pcm.length && !failure) { finished = true; state(); }
  }
  if (worker) { await store('close').catch(() => {}); worker.terminate(); worker = null; }
  if (sessionId) await api(`/api/session/${sessionId}`, {method: 'DELETE'}).catch(() => {});
  await chrome.runtime.sendMessage({type: 'capture-ended'}).catch(() => {});
}

function stop(abort = false) {
  if (!stopping) stopping = performStop(abort).finally(() => { stopping = null; });
  return stopping;
}

channel.onmessage = async ({data}) => {
  if (data.type !== 'hello') return;
  const snapshot = mediaIndex.slice();
  post({type: 'init', mimeType: recorder?.mimeType, delay: Number(config?.delay) || 20});
  try {
    for (const [sequence, entry] of snapshot.entries()) post({type: 'media', sequence, entry});
    for (const cue of cues) post({type: 'cue', cue});
    state();
  } catch (error) { post({type: 'state', failure: error.message}); }
};

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== 'offscreen' || sender.id !== chrome.runtime.id) return;
  if (message.type.startsWith('youtube-')) {
    youtubeControl(message).then(() => respond({ok: true})).catch(error => respond({ok: false, error: error.message}));
    return true;
  }
  if (message.type === 'prepare') {
    config = message.config;
    Promise.resolve().then(() => api('/api/session', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({voice: config.voice || 'female', translation: translationSettings(config.translation)})}))
      .then(result => { sessionId = result.session_id; respond({ok: true}); }).catch(error => respond({ok: false, error: error.message}));
  }
  else if (message.type === 'start') begin(message.streamId, message.config).then(() => respond({ok: true})).catch(error => respond({ok: false, error: error.message}));
  else if (message.type === 'source-changed') fail(new Error('Source video changed. Start a new translation')).then(() => respond({ok: true}));
  else stop(message.type === 'abort').then(() => respond({ok: true})).catch(error => respond({ok: false, error: error.message}));
  return true;
});
