import test from 'node:test';
import assert from 'node:assert/strict';
import {answer, relayAllowed} from '../extension/relay.mjs';

test('the browser relay reaches YouTube hosts only', () => {
  for (const url of ['https://www.youtube.com/watch?v=x', 'https://rr2---sn-x.googlevideo.com/videoplayback', 'https://youtubei.googleapis.com/x']) assert.ok(relayAllowed(url), url);
  for (const url of ['http://www.youtube.com/', 'https://youtube.com.evil.org/', 'https://www.youtube.com:444/', 'https://192.168.0.1/', 'not a url']) assert.ok(!relayAllowed(url), url);
});

test('relayed requests carry no cookies and refuse other destinations', async () => {
  const seen = [];
  const fetcher = async (url, options) => {
    seen.push({url, options});
    return {url: url.includes('redirect') ? 'https://example.com/' : url, status: 206, headers: new Map([['content-range', 'bytes 0-1/2']]),
      arrayBuffer: async () => new Uint8Array([104, 105]).buffer};
  };
  const ok = await answer({id: 1, method: 'POST', url: 'https://www.youtube.com/youtubei/v1/player',
    headers: {Cookie: 'SID=secret', 'User-Agent': 'x', 'X-YouTube-Client-Name': '1'}, body: btoa('{}')}, fetcher);
  assert.deepEqual({...ok, headers: undefined}, {id: 1, status: 206, url: 'https://www.youtube.com/youtubei/v1/player', headers: undefined, body: btoa('hi')});
  assert.deepEqual(seen[0].options.headers, {'X-YouTube-Client-Name': '1'});
  assert.equal(seen[0].options.credentials, 'omit');
  assert.equal(new TextDecoder().decode(seen[0].options.body), '{}');
  assert.equal((await answer({id: 2, method: 'GET', url: 'https://example.com/'}, fetcher)).error, 'Request not allowed');
  assert.equal((await answer({id: 3, method: 'DELETE', url: 'https://www.youtube.com/'}, fetcher)).error, 'Request not allowed');
  assert.equal((await answer({id: 4, method: 'GET', url: 'https://www.youtube.com/redirect'}, fetcher)).error, 'Redirected outside YouTube');
  assert.equal(seen.length, 2);
});

test('googlevideo requests take the User-Agent of the YouTube client once', async () => {
  const agents = [];
  const fetcher = async url => ({url, status: 206, headers: new Map(), arrayBuffer: async () => new ArrayBuffer(0)});
  const request = id => ({id, method: 'GET', url: 'https://rr1.googlevideo.com/videoplayback?id=1', headers: {'User-Agent': 'TV agent', Range: 'bytes=0-1'}});
  await answer(request(1), fetcher, async value => agents.push(value));
  await answer(request(2), fetcher, async value => agents.push(value));
  await answer({id: 3, method: 'GET', url: 'https://www.youtube.com/', headers: {'User-Agent': 'other'}}, fetcher, async value => agents.push(value));
  assert.deepEqual(agents, ['TV agent']);
});
