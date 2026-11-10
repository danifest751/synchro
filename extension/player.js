import {canStart, playableUntil, scheduleCue, cueRate, cueAt} from './timeline.mjs';
import {installView} from './view.mjs';
const video = document.querySelector('#video'), play = document.querySelector('#play'), seek = document.querySelector('#seek');
const status = document.querySelector('#status'), subtitle = document.querySelector('#subtitle');
const channel = new BroadcastChannel('synchro-player');
let mediaSource, sourceBuffer, nextChunk = 0, mediaQueue = new Map(), initialized = false;
let mimeType, mediaUrl, replayTarget = null, recordedEnd = 0, mediaRevision = 0;
const directory = navigator.storage.getDirectory().then(root => root.getDirectoryHandle('synchro-current'));
let readyUntil = 0, delay = 20, finished = false, mediaEnded = false, failed = false;
let wanted = false, started = false, rebuffering = false, audioContext, gain, cueList = [], sources = new Map();
let audioRevision = 0;
let lastVideoTime = 0, lastAudioTime = 0, appendBusy = false, rendering = false;
const format = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
const videoEnd = () => video.buffered.length ? video.buffered.end(video.buffered.length - 1) : 0;

function fail(message) {
  failed = true; wanted = false; video.pause(); stopAudio();
  document.querySelector('#error').textContent = message;
  status.textContent = 'Translation stopped'; play.disabled = true;
}

function stopAudio() {
  for (const source of sources.values()) { try { source.stop(); } catch {} }
  sources.clear(); lastAudioTime = 0; audioRevision++;
}

async function append() {
  if (failed || appendBusy || !sourceBuffer || sourceBuffer.updating || !mediaQueue.has(nextChunk)) return;
  appendBusy = true;
  const target = sourceBuffer, revision = mediaRevision;
  try {
    const focus = replayTarget ?? video.currentTime;
    if (target.buffered.length && target.buffered.start(0) < focus - 60) {
      const removeUntil = Math.min(focus - 30, videoEnd() - 1);
      if (removeUntil > target.buffered.start(0)) { target.remove(target.buffered.start(0), removeUntil); return; }
    }
    if (replayTarget === null && videoEnd() > video.currentTime + 90) return;
    const entry = mediaQueue.get(nextChunk);
    const file = await (await (await directory).getFileHandle('video.webm')).getFile();
    const bytes = await file.slice(entry.offset, entry.offset + entry.size).arrayBuffer();
    if (revision !== mediaRevision) return;
    target.appendBuffer(bytes); nextChunk++;
  } catch (error) { if (revision === mediaRevision) fail(`Could not play recording: ${error.message}`); }
  finally { appendBusy = false; }
}

function initialize(type, position = null) {
  if (initialized && position === null) return;
  stopAudio(); video.pause();
  mimeType = type; replayTarget = position; nextChunk = 0; sourceBuffer = null; mediaRevision++;
  initialized = true; const current = mediaSource = new MediaSource();
  if (mediaUrl) URL.revokeObjectURL(mediaUrl);
  video.src = mediaUrl = URL.createObjectURL(current);
  current.addEventListener('sourceopen', () => {
    if (current !== mediaSource) return;
    try {
      sourceBuffer = current.addSourceBuffer(type);
      sourceBuffer.addEventListener('updateend', () => {
        if (current !== mediaSource) return;
        recordedEnd = Math.max(recordedEnd, videoEnd());
        if (replayTarget !== null && bufferedAt(replayTarget)) {
          const target = replayTarget; replayTarget = null; video.currentTime = target;
          if (wanted) void resume();
        }
        void append(); void render();
      });
      sourceBuffer.addEventListener('error', () => fail('Recording decode failed'));
      void append();
    } catch (error) { fail(error.message); }
  }, {once: true});
}

function bufferedAt(position) {
  for (let index = 0; index < video.buffered.length; index++) {
    if (position >= video.buffered.start(index) && position < video.buffered.end(index)) return true;
  }
  return false;
}

async function schedule() {
  if (!audioContext || video.paused || video.seeking || replayTarget !== null || rebuffering || !wanted || failed) return;
  const position = video.currentTime;
  const activeCue = cueAt(cueList, position), rate = cueRate(activeCue);
  if (Math.abs(video.playbackRate - rate) > .0001) { stopAudio(); video.playbackRate = rate; }
  if (lastAudioTime && Math.abs((position - lastVideoTime) / rate - (audioContext.currentTime - lastAudioTime)) > .15) stopAudio();
  if (!lastAudioTime) { lastVideoTime = position; lastAudioTime = audioContext.currentTime; }
  for (const cue of activeCue ? [activeCue] : []) {
    if (sources.has(cue.id)) continue;
    const timing = scheduleCue(cue, position);
    if (!timing) continue;
    if (!cue.buffer) {
      if (cue.decoding) continue;
      cue.decoding = true;
      const revision = audioRevision;
      try {
        const file = await (await (await directory).getFileHandle(cue.fileName)).getFile();
        cue.buffer = await audioContext.decodeAudioData(await file.arrayBuffer());
        if (revision !== audioRevision) return;
      } catch (error) { fail(`Speech playback failed: ${error.message}`); return; }
      finally { cue.decoding = false; }
    }
    if (video.paused || video.seeking || !wanted || failed || sources.has(cue.id)) return;
    const now = scheduleCue(cue, video.currentTime);
    if (!now || now.offset >= cue.buffer.duration) continue;
    const source = audioContext.createBufferSource(); source.buffer = cue.buffer; source.connect(gain);
    sources.set(cue.id, source);
    source.start(audioContext.currentTime + now.delay, now.offset);
    // Keep completed IDs until pause/seek so a clock tick cannot schedule the same cue twice.
  }
}

async function resume() {
  if (!wanted || failed || replayTarget !== null) return;
  await audioContext?.resume(); rebuffering = false;
  try { await video.play(); void schedule(); } catch (error) { wanted = false; status.textContent = 'Click Play to enable audio'; }
}

async function render() {
  if (rendering) return;
  rendering = true;
  try {
    const end = videoEnd(), position = video.currentTime, available = playableUntil(end, readyUntil) - position;
    const ready = canStart(end, readyUntil, position, delay, finished);
    seek.max = String(Math.max(0, Math.min(recordedEnd, readyUntil) - .05));
    if (document.activeElement !== seek) seek.value = String(position);
    document.querySelector('#position').textContent = `${format(position)} / ${format(Math.min(recordedEnd, readyUntil))}`;
    const cue = cueAt(cueList, position);
    subtitle.textContent = cue?.text || ''; document.querySelector('#source').textContent = cue?.source || '';
    const tempo = document.querySelector('#tempo');
    tempo.hidden = video.playbackRate >= .99 || video.paused;
    tempo.textContent = `Speech sync · video ${video.playbackRate.toFixed(2)}×`;
    for (const item of cueList) if (item !== cue && (item.start < position - 15 || item.start > position + 15)) item.buffer = null;
    if (!failed) {
      play.disabled = !started && !ready;
      play.textContent = wanted && !rebuffering ? 'Pause' : ready || started ? 'Play' : 'Preparing…';
      status.textContent = replayTarget !== null ? 'Restoring the selected position…' : finished ? 'Recording finished' : `Translated ${format(readyUntil)} · Buffer ${Math.max(0, available).toFixed(0)} s`;
      if (wanted && !video.paused && !finished && available < .25) {
        rebuffering = true; video.pause(); stopAudio();
      }
      if (wanted && rebuffering && (available >= 3 || finished && available > .1)) await resume();
      if (wanted && finished && position >= Math.min(recordedEnd, readyUntil) - .08) { wanted = false; video.pause(); stopAudio(); play.textContent = 'Play'; }
    }
    if (mediaEnded && nextChunk === mediaQueue.size && !appendBusy && sourceBuffer && !sourceBuffer.updating && mediaSource.readyState === 'open') mediaSource.endOfStream();
    void append();
    void schedule();
  } finally { rendering = false; }
}

channel.onmessage = ({data}) => {
  if (data.type === 'init') { delay = data.delay; initialize(data.mimeType); }
  if (data.type === 'media') { mediaQueue.set(data.sequence, data.entry); recordedEnd = Math.max(recordedEnd, data.entry.end || 0); void append(); }
  if (data.type === 'cue' && !cueList.some(cue => cue.id === data.cue.id)) cueList.push(data.cue);
  if (data.type === 'state') {
    readyUntil = data.readyUntil || 0; finished = data.finished; mediaEnded = data.mediaEnded;
    if (data.failure) fail(data.failure);
  }
  void render();
};

play.onclick = async () => {
  if (!audioContext) {
    audioContext = new AudioContext(); gain = audioContext.createGain(); gain.connect(audioContext.destination);
    gain.gain.value = Number(document.querySelector('#volume').value) / 100;
  }
  if (wanted) { wanted = false; video.pause(); stopAudio(); }
  else { wanted = true; started = true; await resume(); }
  void render();
};
seek.oninput = () => {
  stopAudio(); const target = Math.max(0, Math.min(Number(seek.value), readyUntil - .05));
  if (bufferedAt(target)) video.currentTime = target;
  else initialize(mimeType, target);
};
video.onseeking = () => { stopAudio(); };
video.onseeked = () => { void schedule(); };
video.onpause = stopAudio;
function crossSmallGap() {
  if (!wanted || failed) return;
  const position = video.currentTime;
  for (let index = 0; index < video.buffered.length; index++) {
    const next = video.buffered.start(index);
    if (next > position && next - position <= .75 && next < readyUntil) {
      stopAudio(); video.currentTime = next + .005;
      void video.play().catch(() => {}); return;
    }
  }
}
video.addEventListener('waiting', crossSmallGap);
video.addEventListener('seeked', crossSmallGap);
video.onended = () => { wanted = false; stopAudio(); void render(); };
document.querySelector('#original').onchange = event => { video.muted = !event.target.checked; video.volume = event.target.checked ? .12 : 0; };
video.muted = true;
document.querySelector('#fullscreen').onclick = () => document.querySelector('#stage').requestFullscreen();
installView(video, value => { if (gain) gain.gain.value = value; });
document.querySelector('#stop').onclick = async event => {
  event.target.disabled = true; status.textContent = 'Finishing recording and remaining phrases…';
  const result = await chrome.runtime.sendMessage({type: 'stop'});
  if (!result?.ok) fail(result?.error || 'Could not finish recording');
};
window.addEventListener('beforeunload', () => { void chrome.runtime.sendMessage({type: 'stop'}); });
channel.postMessage({type: 'hello'});
const helloTimer = setInterval(() => { if (initialized) clearInterval(helloTimer); else channel.postMessage({type: 'hello'}); }, 1000);
setInterval(() => { void render(); }, 100);
