import {serverBase} from './connection.mjs';
const token = document.querySelector('#token'), delay = document.querySelector('#delay'), status = document.querySelector('#status');
const config = await chrome.storage.local.get(['token', 'delay', 'autoUpdate', 'voice', 'apiBase']);
const server = document.querySelector('#server'); server.value = serverBase(config.apiBase);
const voice = document.querySelector('#voice'); voice.value = ['female', 'male', 'male-eugene'].includes(config.voice) ? config.voice : 'female';
voice.onchange = () => chrome.storage.local.set({voice: voice.value});
document.querySelector('#version').textContent = `Version ${chrome.runtime.getManifest().version}`;
const autoUpdate = document.querySelector('#autoUpdate'); autoUpdate.checked = config.autoUpdate !== false;
autoUpdate.onchange = () => chrome.storage.local.set({autoUpdate: autoUpdate.checked});
document.querySelector('#checkUpdate').onclick = async () => {
  const result = await chrome.runtime.sendMessage({type: 'check-update'});
  document.querySelector('#updateStatus').textContent = result.error || ({none: 'The installed version is up to date.', defer: 'The update will apply after playback ends.', disabled: 'Automatic updates are disabled.'}[result.action] || 'Applying update…');
};
token.value = ''; token.placeholder = config.token ? 'Token saved' : 'Import a connection'; delay.value = config.delay || 20;
document.querySelector('#origin').textContent = `Extension: ${chrome.runtime.id}`;
document.querySelector('#import').onchange = async (event) => {
  try {
    const data = JSON.parse(await event.target.files[0].text());
    if (typeof data.token !== 'string' || data.token.length < 24) throw new Error('Invalid connection file');
    server.value = serverBase(data.server_url);
    token.value = data.token; status.textContent = 'Connection imported. Click Save and test.';
  } catch (error) { status.textContent = error.message; }
};
document.querySelector('#save').onclick = async () => {
  try {
    const seconds = Number(delay.value);
    const savedToken = token.value.trim() || config.token;
    if (!savedToken || !Number.isFinite(seconds) || seconds < 10 || seconds > 40) throw new Error('Check the token and translation buffer');
    const apiBase = serverBase(server.value);
    const response = await fetch(apiBase + '/api/check', {headers: {Authorization: `Bearer ${savedToken}`}, signal: AbortSignal.timeout(10000)});
    if (!response.ok || !(await response.json()).ok) throw new Error('Invalid token or server');
    await chrome.storage.local.set({token: savedToken, delay: seconds, voice: voice.value, apiBase});
    config.token = savedToken; token.value = ''; token.placeholder = 'Token saved';
    status.textContent = 'Saved. Server is available.';
  } catch (error) { status.textContent = `Connection failed: ${error.message}. Check the server URL and access key.`; }
};
