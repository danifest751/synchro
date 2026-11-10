import {serverBase} from './connection.mjs';
import {PROVIDERS, translationSettings} from './translation.mjs';
const token = document.querySelector('#token'), delay = document.querySelector('#delay'), status = document.querySelector('#status');
const config = await chrome.storage.local.get(['token', 'delay', 'autoUpdate', 'voice', 'apiBase', 'translation', 'cloudProfiles']);
const provider = document.querySelector('#provider'), cloudModel = document.querySelector('#cloudModel'), cloudKey = document.querySelector('#cloudKey');
const profiles = config.cloudProfiles || {};
let selected = Object.hasOwn(PROVIDERS, config.translation?.provider) ? config.translation.provider : 'local';
provider.value = selected;
function rememberProvider() {
  if (selected !== 'local') profiles[selected] = {model: cloudModel.value.trim(), api_key: cloudKey.value.trim() || profiles[selected]?.api_key || ''};
}
function showProvider() {
  selected = provider.value;
  document.querySelector('#cloudSettings').hidden = selected === 'local';
  cloudModel.value = profiles[selected]?.model || PROVIDERS[selected].model;
  cloudKey.value = '';
  cloudKey.placeholder = profiles[selected]?.api_key ? 'API key saved' : 'Enter provider API key';
  document.querySelector('#hyNote').hidden = !cloudModel.value.startsWith('tencent/hy-mt2-');
}
provider.onchange = () => { rememberProvider(); showProvider(); };
cloudModel.oninput = () => { document.querySelector('#hyNote').hidden = !cloudModel.value.startsWith('tencent/hy-mt2-'); };
showProvider();
function translation() { rememberProvider(); return translationSettings({provider: selected, ...profiles[selected]}); }
document.querySelector('#clearCloudKey').onclick = async () => {
  if (profiles[selected]) delete profiles[selected].api_key;
  cloudKey.value = ''; cloudKey.placeholder = 'Enter provider API key';
  if (config.translation?.provider === selected) {
    config.translation = {provider: 'local'};
    await chrome.storage.local.set({translation: config.translation});
  }
  await chrome.storage.local.set({cloudProfiles: profiles});
  document.querySelector('#translationStatus').textContent = 'Provider key removed. Save a valid provider before starting cloud translation.';
};
document.querySelector('#testTranslation').onclick = async (event) => {
  const button = event.target, resultText = document.querySelector('#translationStatus');
  button.disabled = true; resultText.textContent = 'Testing translator…';
  try {
    const response = await fetch(serverBase(server.value) + '/api/translation/check', {method: 'POST',
      headers: {Authorization: `Bearer ${token.value.trim() || config.token}`, 'Content-Type': 'application/json'},
      body: JSON.stringify(translation()), signal: AbortSignal.timeout(90000)});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `Server: ${response.status}`);
    resultText.textContent = `${PROVIDERS[result.provider].name} · ${result.seconds} s · ${result.translation}`;
  } catch (error) { resultText.textContent = error.message; }
  finally { button.disabled = false; }
};
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
    const selectedTranslation = translation();
    await chrome.storage.local.set({token: savedToken, delay: seconds, voice: voice.value, apiBase, translation: selectedTranslation, cloudProfiles: profiles});
    config.translation = selectedTranslation;
    cloudKey.value = ''; cloudKey.placeholder = selected === 'local' ? '' : 'API key saved';
    config.token = savedToken; token.value = ''; token.placeholder = 'Token saved';
    status.textContent = 'Saved. Server is available.';
  } catch (error) { status.textContent = `Connection failed: ${error.message}. Check the server URL and access key.`; }
};
