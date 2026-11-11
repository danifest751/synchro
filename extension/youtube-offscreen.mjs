import {serverBase} from './connection.mjs';
import {translationSettings} from './translation.mjs';
let current, lifecycle = Promise.resolve();

async function request(state, path, method = 'GET', body, cancel = true, timeout = 120000) {
  const response = await fetch(serverBase(state.config.apiBase) + path, {method,
    headers: {Authorization: `Bearer ${state.config.token}`, 'Content-Type': 'application/json'},
    ...(body ? {body: JSON.stringify(body)} : {}),
    signal: cancel ? AbortSignal.any([state.abort.signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout)});
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : `Server: ${response.status}`), {status: response.status});
  }
  return response.status === 204 ? null : response.json();
}

// Network, gateway and model hiccups are retried; the server keeps a failed window and repeats it.
export async function retried(call, signal, delays = [2000, 4000, 6000]) {
  for (let attempt = 0; ; attempt++) {
    try { return await call(); }
    catch (error) {
      const transient = error.status === undefined || [409, 502, 503, 504].includes(error.status);
      if (signal?.aborted || attempt >= delays.length || !transient) throw error;
      await new Promise(resolve => {
        const timer = setTimeout(resolve, delays[attempt]);
        signal?.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, {once: true});
      });
    }
  }
}

function emit(state, event) {
  if (state.stopped) return;
  void chrome.runtime.sendMessage({type: 'youtube-event', event: {...event, revision: state.revision}}).catch(() => {});
}

async function run(state) {
  try {
    emit(state, {type: 'loading'});
    // The initial request must return its ID even after cancellation so the session can be deleted.
    const opened = await request(state, '/api/video', 'POST', {url: state.url, position: state.position, voice: state.config.voice || 'female', translation: translationSettings(state.config.translation)}, false);
    state.id = opened.session_id;
    if (state.stopped) return;
    emit(state, {type: 'opened', ...opened});
    let ready = opened.base, finished = false, heartbeat = Date.now();
    while (!state.stopped) {
      if (!finished && ready < state.position + Math.max(14, Number(state.config.delay) || 20) + 14) {
        // ready lets the server resend a response that was lost in transit instead of skipping a window.
        const result = await retried(() => request(state, `/api/video/${state.id}/next?ready=${ready}`, 'POST'), state.abort.signal);
        ready = result.ready_until; finished = result.finished; heartbeat = Date.now();
        emit(state, {type: 'result', ...result});
      } else {
        if (Date.now() - heartbeat > 15000) {
          await retried(() => request(state, `/api/video/${state.id}`), state.abort.signal); heartbeat = Date.now();
        }
        await new Promise(resolve => setTimeout(resolve, 250));
      }
    }
  } catch (error) {
    if (!state.stopped) {
      const status = state.id ? await request(state, `/api/video/${state.id}`, 'GET', null, true, 5000).catch(() => null) : null;
      emit(state, {type: 'error', message: error.message, cloud_usage: status?.cloud_usage});
    }
  } finally {
    if (state.id) await request(state, `/api/session/${state.id}`, 'DELETE', null, false, 10000).catch(() => {});
    if (current === state) {
      current = null;
      void chrome.runtime.sendMessage({type: 'youtube-ended'}).catch(() => {});
    }
  }
}

export function youtubeControl(message) {
  if (message.type === 'youtube-position') {
    if (current && message.revision === current.revision && Number.isFinite(message.position)) current.position = Math.max(0, message.position);
    return Promise.resolve();
  }
  if (current) { current.stopped = true; current.abort.abort(); }
  if (message.type === 'youtube-stop') return lifecycle.catch(() => {});
  const state = {...message, abort: new AbortController(), stopped: false};
  current = state;
  lifecycle = lifecycle.catch(() => {}).then(() => state.stopped ? undefined : run(state));
  return Promise.resolve();
}
