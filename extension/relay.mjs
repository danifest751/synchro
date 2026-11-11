// Lends this browser's network to the Synchro server for YouTube only, so YouTube sees the viewer's address
// instead of a data-centre address. The server sends HTTP requests over a WebSocket; this page performs them.
import {serverBase} from './connection.mjs';

const HOSTS = /(^|\.)(youtube\.com|googlevideo\.com|ytimg\.com|youtubei\.googleapis\.com)$/;
// The browser sets these itself; Origin and Referer for youtube.com come from the rule in background.js.
const DROPPED = new Set(['cookie', 'origin', 'referer', 'host', 'connection', 'content-length', 'accept-encoding',
  'user-agent', 'keep-alive', 'transfer-encoding']);
const MAX_BODY = 16_000_000;
let relay;

export function relayAllowed(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.port && HOSTS.test(url.hostname);
  } catch { return false; }
}

function base64(buffer) {
  const bytes = new Uint8Array(buffer);
  let text = '';
  for (let index = 0; index < bytes.length; index += 32768) text += String.fromCharCode(...bytes.subarray(index, index + 32768));
  return btoa(text);
}

let agent = '';
// Offscreen documents cannot change request headers; background.js owns the declarativeNetRequest rule.
const setAgent = value => chrome.runtime.sendMessage({type: 'relay-agent', agent: value});

export async function answer(request, fetcher = fetch, applyAgent = setAgent) {
  const {id, method, url} = request;
  if (!relayAllowed(url) || !['GET', 'POST', 'HEAD'].includes(method)) return {id, error: 'Request not allowed'};
  const headers = Object.fromEntries(Object.entries(request.headers || {}).filter(([name]) => !DROPPED.has(name.toLowerCase())));
  // googlevideo URLs can be bound to the User-Agent of the YouTube client the server used; one viewer plays one video.
  const wanted = Object.entries(request.headers || {}).find(([name]) => name.toLowerCase() === 'user-agent')?.[1];
  if (wanted && wanted !== agent && new URL(url).hostname.endsWith('googlevideo.com')) { await applyAgent(wanted); agent = wanted; }
  // No cookies: the viewer's YouTube account is never used.
  const response = await fetcher(url, {method, headers, credentials: 'omit', cache: 'no-store', redirect: 'follow',
    body: request.body ? Uint8Array.from(atob(request.body), char => char.charCodeAt(0)) : undefined, signal: AbortSignal.timeout(30000)});
  if (!relayAllowed(response.url)) return {id, error: 'Redirected outside YouTube'};
  const body = await response.arrayBuffer();
  if (body.byteLength > MAX_BODY) return {id, error: 'Response too large'};
  return {id, status: response.status, url: response.url, headers: Object.fromEntries(response.headers), body: base64(body)};
}

export function connectRelay(config) {
  const base = serverBase(config.apiBase);
  if (relay && relay.base === base && relay.token === config.token && relay.socket.readyState <= WebSocket.OPEN) return relay.ready;
  relay?.socket.close();
  const socket = new WebSocket(base.replace(/^http/, 'ws') + '/api/relay');
  const current = relay = {socket, base, token: config.token};
  current.ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => { reject(new Error('The browser relay did not connect')); socket.close(); }, 10000);
    socket.onopen = () => socket.send(JSON.stringify({token: config.token}));
    socket.onmessage = ({data}) => {
      const message = JSON.parse(data);
      if (message.type === 'ready') { clearTimeout(timer); resolve(); return; }
      void answer(message).catch(error => ({id: message.id, error: String(error)})).then(reply => {
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(reply));
      });
    };
    socket.onclose = () => {
      clearTimeout(timer); reject(new Error('The browser relay closed'));
      if (relay === current) relay = null;
    };
  });
  return current.ready;
}
