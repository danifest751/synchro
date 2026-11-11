import {serverBase} from './connection.mjs';
import {PROVIDERS, translationSettings} from './translation.mjs';
import {createModelPicker} from './model-picker.mjs';
const token = document.querySelector('#token'), delay = document.querySelector('#delay'), status = document.querySelector('#status');
const config = await chrome.storage.local.get(['token', 'delay', 'autoUpdate', 'voice', 'apiBase', 'translation', 'cloudProfiles']);
const provider = document.querySelector('#provider'), cloudModel = document.querySelector('#cloudModel'), cloudKey = document.querySelector('#cloudKey');
const profiles = config.cloudProfiles || {};
const voice = document.querySelector('#voice');
const localVoiceOptions = voice.innerHTML;
const localVoiceAliases = {female: 'albina', male: 'roman', 'male-eugene': 'eduard'};
const cloudVoiceAliases = {albina: 'female', alfia: 'female', roman: 'male', alexandr: 'male', eduard: 'male-eugene'};
let displayedCloudVoices;
const processingMode = document.querySelector('#processingMode');
processingMode.value = config.translation?.mode || (config.translation?.provider && config.translation.provider !== 'local' ? 'cloud_translation' : 'local');
function showMode() {
  const allCloud = processingMode.value === 'cloud_all';
  document.querySelector('#modeNote').textContent = allCloud ? 'One provider key for cloud ASR, translation and speech. No local AI models are used. Audio is uploaded. FFmpeg and the Synchro gateway still run on your server. Cloud speech is AI-generated. Speech charges are additional to the text estimate.' : processingMode.value === 'cloud_translation' ? 'All text processing uses the selected cloud provider. Recognition and voices use your own server.' : 'Recognition, text translation and voices use your own computer or server.';
  if (displayedCloudVoices !== allCloud) {
    const previous = displayedCloudVoices === undefined ? config.voice : voice.value;
    const aliases = allCloud ? cloudVoiceAliases : localVoiceAliases;
    voice.innerHTML = allCloud ? '<option value="female">Nova · cloud female</option><option value="male">Onyx · cloud male</option><option value="male-eugene">Echo · cloud male</option>' : localVoiceOptions;
    const selectedVoice = aliases[previous] || previous;
    if ([...voice.options].some(option => option.value === selectedVoice)) voice.value = selectedVoice;
    displayedCloudVoices = allCloud;
  }
  document.querySelector('#testTranslation').textContent = allCloud ? 'Test full cloud pipeline' : processingMode.value === 'cloud_translation' ? 'Test translation and local speech' : 'Test translator';
}
let modelPicker;
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
  void modelPicker?.setProvider();
}
provider.onchange = () => { rememberProvider(); if (provider.value === 'local') processingMode.value = 'local'; else if (processingMode.value === 'local') processingMode.value = 'cloud_translation'; showProvider(); showMode(); };
processingMode.onchange = () => {
  rememberProvider();
  if (processingMode.value === 'local') provider.value = 'local';
  else if (provider.value === 'local') provider.value = 'kilo';
  showProvider(); showMode();
};
cloudModel.oninput = () => { document.querySelector('#hyNote').hidden = !cloudModel.value.startsWith('tencent/hy-mt2-'); modelPicker?.renderSelection(); };
cloudKey.onchange = () => modelPicker?.loadBalance();
cloudKey.oninput = () => modelPicker?.invalidateBalance();
showProvider();
showMode();
function translation() { rememberProvider(); return translationSettings({provider: selected, ...profiles[selected], mode: processingMode.value}); }
document.querySelector('#clearCloudKey').onclick = async () => {
  if (profiles[selected]) delete profiles[selected].api_key;
  cloudKey.value = ''; cloudKey.placeholder = 'Enter provider API key';
  if (config.translation?.provider === selected) {
    config.translation = {provider: 'local'};
    await chrome.storage.local.set({translation: config.translation});
  }
  await chrome.storage.local.set({cloudProfiles: profiles});
  modelPicker.invalidateBalance();
  document.querySelector('#translationStatus').textContent = 'Provider key removed. Save a valid provider before starting cloud translation.';
};
document.querySelector('#testTranslation').onclick = async (event) => {
  const button = event.target, resultText = document.querySelector('#translationStatus');
  button.disabled = true; resultText.textContent = 'Testing translator…';
  try {
    const selectedTranslation = translation(), full = selectedTranslation.mode !== 'local';
    const response = await fetch(serverBase(server.value) + (full ? '/api/pipeline/check' : '/api/translation/check'), {method: 'POST',
      headers: {Authorization: `Bearer ${token.value.trim() || config.token}`, 'Content-Type': 'application/json'},
      body: JSON.stringify(full ? {voice: document.querySelector('#voice').value, translation: selectedTranslation} : selectedTranslation), signal: AbortSignal.timeout(115000)});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `Server: ${response.status}`);
    const usage = result.cloud_usage;
    resultText.textContent = `${PROVIDERS[result.provider].name} · ${result.seconds} s · ${result.translation}` + (usage && Object.keys(usage.stages).length ? ` · Provider-reported ${usage.unpriced_requests ? '≥' : ''}$${usage.reported_cost_usd.toFixed(6)}${usage.unpriced_requests ? ' (incomplete price data)' : ''}` : '');
  } catch (error) { resultText.textContent = error.message; }
  finally { button.disabled = false; void modelPicker.loadBalance(); }
};
const server = document.querySelector('#server'); server.value = serverBase(config.apiBase);
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
    void modelPicker.setProvider();
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
    void modelPicker.setProvider();
  } catch (error) { status.textContent = `Connection failed: ${error.message}. Check the server URL and access key.`; }
};

async function accountRequest(path, body, signal) {
  const savedToken = token.value.trim() || config.token;
  if (!savedToken) throw new Error('Import your Synchro connection first');
  const response = await fetch(serverBase(server.value) + path, {method:'POST', cache:'no-store',
    headers:{Authorization:`Bearer ${savedToken}`,'Content-Type':'application/json'}, body:JSON.stringify(body),
    signal: AbortSignal.any([signal, AbortSignal.timeout(30000)])});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `Server: ${response.status}`);
  return result;
}
modelPicker = createModelPicker({provider:()=>selected, model:cloudModel, settings:translation, request:accountRequest});
void modelPicker.setProvider();
