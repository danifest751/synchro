import asyncio
import base64
import json
import os
import re
import threading
import unittest
import unittest.mock

os.environ.setdefault('SYNCHRO_TOKEN', 'unit-test-owner-token-00000000000000')
os.environ.setdefault('SYNCHRO_ORIGIN', 'chrome-extension://' + 'a' * 32)

from synchro import relay


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


class FakeRelay:
    """Serves ranges of one media file the way the browser would."""

    def __init__(self, data):
        self.data = data
        self.loop = asyncio.get_running_loop()
        self.requests = []

    async def fetch(self, method, url, headers=None, body=None, timeout=30):
        self.requests.append((method, url, dict(headers or {})))
        if url.endswith('/missing'):
            return 404, url, {}, b'not found'
        start, end = map(int, re.fullmatch(r'bytes=(\d+)-(\d+)', headers['Range']).groups())
        part = self.data[start:end + 1]
        return 206, url, {'content-range': f'bytes {start}-{start + len(part) - 1}/{len(self.data)}'}, part


class RelayTests(unittest.IsolatedAsyncioTestCase):
    def test_only_youtube_hosts_are_relayed(self):
        for url in ['https://www.youtube.com/watch?v=x', 'https://rr1---sn-abc.googlevideo.com/videoplayback', 'https://i.ytimg.com/a.jpg']:
            self.assertTrue(relay.allowed(url), url)
        for url in ['http://www.youtube.com/', 'https://youtube.com.evil.org/', 'https://example.com/', 'https://www.youtube.com:8443/',
                    'https://127.0.0.1/', 'file:///etc/passwd']:
            self.assertFalse(relay.allowed(url), url)

    async def test_request_round_trip_and_rejected_host(self):
        socket = FakeSocket()
        current = relay.Relay(socket)
        task = asyncio.create_task(current.fetch('POST', 'https://www.youtube.com/youtubei/v1/player', {'X-A': '1'}, b'{}'))
        await asyncio.sleep(0)
        sent = socket.sent[0]
        self.assertEqual((sent['method'], sent['headers'], base64.b64decode(sent['body'])), ('POST', {'X-A': '1'}, b'{}'))
        current.resolve({'id': sent['id'], 'status': 200, 'url': sent['url'], 'headers': {'a': 'b'}, 'body': base64.b64encode(b'ok').decode()})
        self.assertEqual(await task, (200, sent['url'], {'a': 'b'}, b'ok'))
        with self.assertRaises(ValueError):
            await current.fetch('GET', 'https://example.com/')
        # A response redirected away from YouTube is refused.
        task = asyncio.create_task(current.fetch('GET', 'https://www.youtube.com/'))
        await asyncio.sleep(0)
        current.resolve({'id': socket.sent[-1]['id'], 'status': 200, 'url': 'https://example.com/', 'body': ''})
        with self.assertRaises(ConnectionError):
            await task
        task = asyncio.create_task(current.fetch('GET', 'https://www.youtube.com/'))
        await asyncio.sleep(0)
        current.close()
        with self.assertRaises(ConnectionError):
            await task

    async def test_yt_dlp_requests_go_through_the_browser(self):
        import yt_dlp
        from yt_dlp.networking.exceptions import HTTPError
        fake = FakeRelay(b'0123456789')
        results = {}

        def run():
            relay.current.relay = fake
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    results['body'] = ydl.urlopen(yt_dlp.networking.Request('https://www.youtube.com/v', headers={'Range': 'bytes=2-4'})).read()
                    try:
                        ydl.urlopen('https://www.youtube.com/missing')
                    except HTTPError as error:
                        results['status'] = error.status
            finally:
                relay.current.relay = None
        thread = threading.Thread(target=run)
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(.01)
        self.assertEqual(results, {'body': b'234', 'status': 404})

    def test_media_size_without_visible_content_range(self):
        self.assertEqual(relay.media_size('https://r.googlevideo.com/videoplayback?clen=1234&x=1', {}), 1234)
        self.assertEqual(relay.media_size('https://r.googlevideo.com/videoplayback', {'content-range': 'bytes 0-9/50'}), 50)
        self.assertIsNone(relay.media_size('https://r.googlevideo.com/videoplayback', {}))

    async def test_media_endpoint_streams_ranges_for_ffmpeg(self):
        data = bytes(range(256)) * 9000
        fake = FakeRelay(data)
        server = relay.MediaServer()
        token, local = await server.add(lambda: fake, 'https://rr1.googlevideo.com/videoplayback?id=1', 'TV agent')
        port = int(local.rsplit(':', 1)[1].split('/')[0])

        async def get(path, range_header=''):
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(f'GET /{path} HTTP/1.1\r\nHost: x\r\n{range_header}\r\n'.encode())
            await writer.drain()
            response = await reader.read()
            writer.close()
            head, _, body = response.partition(b'\r\n\r\n')
            return head.decode(), body

        with unittest.mock.patch.object(relay, 'CHUNK', 1000):
            head, body = await get(token, f'Range: bytes={len(data) - 2500}-\r\n')
        self.assertIn('206 Partial Content', head)
        self.assertIn(f'Content-Range: bytes {len(data) - 2500}-{len(data) - 1}/{len(data)}', head)
        self.assertEqual(body, data[-2500:])
        self.assertEqual(len(fake.requests), 3)
        self.assertTrue(all(headers['User-Agent'] == 'TV agent' for _, _, headers in fake.requests))
        head, _ = await get('unknown')
        self.assertIn('404', head)
        server.remove(token)
        head, _ = await get(token)
        self.assertIn('404', head)


class RelayEndpointTests(unittest.TestCase):
    def test_socket_requires_extension_origin_and_key(self):
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        from synchro import app as api
        with TestClient(api.app) as client:
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/relay', headers={'Origin': 'https://example.com'}) as socket:
                    socket.receive_text()
            with client.websocket_connect('/api/relay', headers={'Origin': api.ORIGIN}) as socket:
                socket.send_text(json.dumps({'token': 'wrong-token'}))
                with self.assertRaises(WebSocketDisconnect):
                    socket.receive_text()
            with client.websocket_connect('/api/relay', headers={'Origin': api.ORIGIN}) as socket:
                socket.send_text(json.dumps({'token': api.TOKEN}))
                self.assertEqual(json.loads(socket.receive_text()), {'type': 'ready'})
                self.assertIn('owner', api.relays)
        self.assertNotIn('owner', api.relays)

