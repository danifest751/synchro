export const LOCAL_API = 'http://127.0.0.1:8768';
export const HOST_API = 'http://127.0.0.1:8778';
export const PUBLIC_API = 'https://synchro.example.com';

export function serverBase(value = LOCAL_API) {
  const url = new URL(value || LOCAL_API);
  if (![LOCAL_API, HOST_API, PUBLIC_API].includes(url.origin) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Server URL is not in the Synchro endpoint allowlist');
  }
  return url.origin;
}
