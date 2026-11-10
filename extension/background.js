import {updateAction} from './updates.mjs';
import {serverBase} from './connection.mjs';
let lifecycle = Promise.resolve();
const offscreenUrl = chrome.runtime.getURL('offscreen.html');

async function checkUpdate() {
  const {autoUpdate} = await chrome.storage.local.get('autoUpdate');
  if (autoUpdate === false) return 'disabled';
  const disk = await fetch(chrome.runtime.getURL('manifest.json') + `?check=${Date.now()}`, {cache: 'no-store'}).then(response => response.json());
  const {captureActive} = await chrome.storage.session.get('captureActive');
  const players = await chrome.tabs.query({url: chrome.runtime.getURL('player.html')});
  const action = updateAction(chrome.runtime.getManifest().version, disk.version, captureActive, players.length > 0);
  if (action === 'defer') {
    await chrome.action.setBadgeText({text: '↑'});
    await chrome.action.setTitle({title: 'Synchro will update after playback is closed'});
  }
  if (action === 'none') {
    await chrome.action.setBadgeText({text: ''});
    await chrome.action.setTitle({title: 'Synchro — Local Video Dubbing'});
  }
  if (action === 'reload') chrome.runtime.reload();
  return action;
}

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'synchro-update') lifecycle = lifecycle.catch(() => {}).then(checkUpdate).catch(() => {});
});
void chrome.alarms.get('synchro-update').then(alarm => {
  if (!alarm) return chrome.alarms.create('synchro-update', {periodInMinutes: 1});
});

async function ensureOffscreen() {
  const contexts = await chrome.runtime.getContexts({contextTypes: ['OFFSCREEN_DOCUMENT'], documentUrls: [offscreenUrl]});
  if (!contexts.length) await chrome.offscreen.createDocument({
    url: 'offscreen.html', reasons: ['USER_MEDIA', 'WORKERS'], justification: 'Capture a video tab for local translation',
  });
}

async function start(tabId) {
  if ((await chrome.storage.session.get('captureActive')).captureActive) throw new Error('Finish the current translation first');
  const players = await chrome.tabs.query({url: chrome.runtime.getURL('player.html')});
  if (players.length) throw new Error('Close the previous Synchro player before starting another translation');
  const config = await chrome.storage.local.get(['token', 'delay', 'voice', 'apiBase', 'translation']);
  config.apiBase = serverBase(config.apiBase);
  if (!config.token) throw new Error('Import a connection in the extension settings');
  const tab = await chrome.tabs.get(tabId);
  if (tab.url && !/^https?:/.test(tab.url)) throw new Error('Open a tab with a video');
  await ensureOffscreen();
  if (/^https:\/\/(www\.|m\.)?youtube\.com\/(watch\?|shorts\/|live\/)/.test(tab.url || '')) {
    await chrome.storage.session.set({captureActive: true, sourceTab: tabId, sourceMode: 'youtube'});
    try {
      const [{result}] = await chrome.scripting.executeScript({target: {tabId}, files: ['youtube.js']});
      if (!result?.ok) throw new Error(result?.error || 'YouTube player not found');
      const response = await chrome.runtime.sendMessage({target: 'offscreen', type: 'youtube-start', config, url: tab.url, position: result.position, revision: 1});
      if (!response?.ok) throw new Error(response?.error || 'Could not start translation');
      return;
    } catch (error) {
      await chrome.storage.session.set({captureActive: false});
      await chrome.tabs.sendMessage(tabId, {type: 'youtube-event', event: {type: 'error', revision: 1, message: error.message}}).catch(() => {});
      throw error;
    }
  }
  await chrome.storage.session.set({sourceMode: 'capture'});
  const prepared = await chrome.runtime.sendMessage({target: 'offscreen', type: 'prepare', config});
  if (!prepared?.ok) throw new Error(prepared?.error || 'Models are not ready');
  try {
    const streamId = await chrome.tabCapture.getMediaStreamId({targetTabId: tabId});
    const result = await chrome.runtime.sendMessage({target: 'offscreen', type: 'start', streamId, config, tabId});
    if (!result?.ok) throw new Error(result?.error || 'Could not start capture');
    await chrome.storage.session.set({captureActive: true, sourceTab: tabId});
    await chrome.scripting.executeScript({target: {tabId}, files: ['source-bridge.js']}).catch(() => {});
    await chrome.tabs.create({url: chrome.runtime.getURL('player.html')});
  } catch (error) {
    await chrome.runtime.sendMessage({target: 'offscreen', type: 'abort'}).catch(() => {});
    await chrome.storage.session.set({captureActive: false});
    throw error;
  }
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target === 'offscreen') return;
  if (sender.id !== chrome.runtime.id) return;
  if (message.type === 'youtube-event' || message.type === 'youtube-ended') {
    if (sender.tab || sender.url !== offscreenUrl) return;
    void chrome.storage.session.get(['sourceTab', 'sourceMode']).then(async state => {
      if (state.sourceMode !== 'youtube') return;
      if (message.type === 'youtube-ended') await chrome.storage.session.set({captureActive: false});
      else if (state.sourceTab) await chrome.tabs.sendMessage(state.sourceTab, message).catch(() => {});
    });
    return;
  }
  if (['youtube-position', 'youtube-seek', 'youtube-stop', 'youtube-voices'].includes(message.type)) {
    void chrome.storage.session.get(['sourceTab', 'sourceMode']).then(async state => {
      if (state.sourceMode !== 'youtube' || sender.tab?.id !== state.sourceTab || sender.frameId !== 0) return respond({ok: false});
      if (!Number.isFinite(message.position) && message.type !== 'youtube-stop') return respond({ok: false});
      const config = await chrome.storage.local.get(['token', 'delay', 'voice', 'apiBase', 'translation']);
      config.apiBase = serverBase(config.apiBase);
      if (message.type === 'youtube-voices') {
        const mode = config.translation?.mode || (config.translation?.provider && config.translation.provider !== 'local' ? 'cloud_translation' : 'local');
        const response = await fetch(config.apiBase + '/api/voices?mode=' + encodeURIComponent(mode), {
          headers: {Authorization: `Bearer ${config.token}`}, signal: AbortSignal.timeout(10000)});
        if (!response.ok) throw new Error('Could not load the server voice list');
        const catalog = await response.json();
        return respond({ok: true, voices: catalog.voices, note: catalog.note});
      }
      const tab = await chrome.tabs.get(state.sourceTab);
      if (message.type === 'youtube-seek') await chrome.storage.session.set({captureActive: true});
      const result = await chrome.runtime.sendMessage({target: 'offscreen', type: message.type === 'youtube-seek' ? 'youtube-start' : message.type,
        config, url: tab.url, position: message.position, revision: message.revision});
      if (message.type === 'youtube-stop') await chrome.storage.session.set({captureActive: false});
      respond(result);
    }).catch(error => respond({ok: false, error: error.message}));
    return true;
  }
  if (message.type === 'state') {
    chrome.storage.session.get(['captureActive', 'sourceTab']).then(respond); return true;
  }
  if (message.type === 'check-update') {
    lifecycle = lifecycle.catch(() => {}).then(checkUpdate).then(action => respond({action})).catch(error => respond({error: error.message}));
    return true;
  }
  if (!['start', 'stop', 'source-ended', 'source-changed', 'capture-ended'].includes(message.type)) return;
  if (message.type.startsWith('source-')) {
    // Only the captured tab may end the producer.
    lifecycle = lifecycle.then(async () => {
      const {sourceTab} = await chrome.storage.session.get('sourceTab');
      if (sourceTab !== sender.tab?.id) return;
      await chrome.runtime.sendMessage({target: 'offscreen', type: message.type === 'source-ended' ? 'stop' : 'source-changed'});
      await chrome.storage.session.set({captureActive: false});
    }).catch(() => {});
    return;
  }
  lifecycle = lifecycle.catch(() => {}).then(async () => {
    try {
      if (message.type === 'start') await start(message.tabId);
      else {
        if (message.type === 'stop') await chrome.runtime.sendMessage({target: 'offscreen', type: 'stop'});
        await chrome.storage.session.set({captureActive: false});
      }
      respond({ok: true});
    } catch (error) { respond({ok: false, error: error.message}); }
  });
  return true;
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const {sourceTab, captureActive, sourceMode} = await chrome.storage.session.get(['sourceTab', 'captureActive', 'sourceMode']);
  if (captureActive && sourceTab === tabId) chrome.runtime.sendMessage({target: 'offscreen', type: sourceMode === 'youtube' ? 'youtube-stop' : 'stop'}).catch(() => {});
  lifecycle = lifecycle.catch(() => {}).then(checkUpdate).catch(() => {});
});

chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status !== 'loading' && !change.url) return;
  void chrome.storage.session.get(['sourceTab', 'sourceMode', 'captureActive']).then(state => {
    if (state.captureActive && state.sourceMode === 'youtube' && state.sourceTab === tabId) {
      return chrome.runtime.sendMessage({target: 'offscreen', type: 'youtube-stop'});
    }
  }).catch(() => {});
});
