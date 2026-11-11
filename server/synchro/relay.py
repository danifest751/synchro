"""Browser network relay: YouTube requests run in the viewer's browser, so YouTube sees the viewer's address.

The extension keeps a WebSocket open; yt-dlp (in-process) and FFmpeg (through a loopback HTTP endpoint with
Range support) send their requests over it. Only YouTube hosts are allowed, on both sides.
"""
import asyncio
import base64
import io
import itertools
import json
import logging
import re
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

from yt_dlp.networking.common import RequestHandler, Response, register_preference, register_rh
from yt_dlp.networking.exceptions import HTTPError, TransportError, UnsupportedRequest

ALLOWED_HOST = re.compile(r'(?:[a-z0-9-]+\.)*(?:youtube\.com|googlevideo\.com|ytimg\.com|youtubei\.googleapis\.com)')
MAX_BODY = 16_000_000
CHUNK = 1_000_000


def allowed(url):
    parts = urlsplit(url)
    return parts.scheme == 'https' and parts.port in (None, 443) and bool(ALLOWED_HOST.fullmatch(parts.hostname or ''))


class Relay:
    def __init__(self, socket):
        self.socket = socket
        self.pending = {}
        self.ids = itertools.count(1)
        self.loop = asyncio.get_running_loop()

    async def fetch(self, method, url, headers=None, body=None, timeout=30):
        if not allowed(url):
            raise ValueError('The browser relay only reaches YouTube')
        request_id = next(self.ids)
        future = self.pending[request_id] = self.loop.create_future()
        try:
            await self.socket.send_text(json.dumps({'id': request_id, 'method': method, 'url': url, 'headers': headers or {},
                                                    'body': base64.b64encode(body).decode() if body else None}))
            answer = await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(request_id, None)
        if 'error' in answer:
            raise ConnectionError('Browser request failed: ' + str(answer['error'])[:200])
        content = base64.b64decode(answer.get('body') or '')
        if len(content) > MAX_BODY or not allowed(answer.get('url', '')):
            raise ConnectionError('Invalid browser relay response')
        return int(answer['status']), answer['url'], dict(answer.get('headers') or {}), content

    def resolve(self, answer):
        future = self.pending.get(answer.get('id'))
        if future and not future.done():
            future.set_result(answer)

    def close(self):
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError('The browser relay disconnected'))


# yt-dlp runs in a worker thread; the relay of the session that resolves a video is set for that thread.
current = threading.local()


@register_rh
class BrowserRH(RequestHandler):
    RH_KEY = 'SynchroBrowser'
    _SUPPORTED_URL_SCHEMES = ('http', 'https')
    _SUPPORTED_PROXY_SCHEMES = ('http', 'https')

    def _check_extensions(self, extensions):
        for key in ('cookiejar', 'timeout', 'legacy_ssl', 'keep_header_casing', 'impersonate'):
            extensions.pop(key, None)

    def _validate(self, request):
        if getattr(current, 'relay', None) is None:
            raise UnsupportedRequest('No browser relay for this thread')
        super()._validate(request)

    def _send(self, request):
        relay = current.relay
        current.requests = getattr(current, 'requests', 0) + 1
        data = request.data
        body = data if isinstance(data, (bytes, type(None))) else data.read() if hasattr(data, 'read') else b''.join(data)
        try:
            status, url, headers, content = asyncio.run_coroutine_threadsafe(
                relay.fetch(request.method, request.url, dict(request.headers), body), relay.loop).result(40)
        except (ConnectionError, ValueError, TimeoutError) as error:
            raise TransportError(cause=error) from error
        response = Response(io.BytesIO(content), url, headers, status)
        if not 200 <= status < 300:
            raise HTTPError(response)
        return response


@register_preference(BrowserRH)
def prefer_browser(handler, request):
    return 1000


def extract(relay, url, options):
    import yt_dlp
    current.relay, current.requests = relay, 0
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
        client = parse_qs(urlsplit(info.get('url', '')).query).get('c', ['?'])[0]
        logging.getLogger('uvicorn.error').info('youtube_resolve via=browser requests=%d client=%s format=%s', current.requests, client, info.get('format_id'))
        return info
    finally:
        current.relay = None


class MediaServer:
    """Loopback HTTP endpoint so FFmpeg can read and seek a relayed media URL with Range requests."""

    def __init__(self):
        self.routes = {}
        self.port = None
        self.lock = asyncio.Lock()

    async def add(self, relay_for, url, agent=''):
        async with self.lock:
            if self.port is None:
                server = await asyncio.start_server(self.handle, '127.0.0.1', 0, limit=8192)
                self.port = server.sockets[0].getsockname()[1]
        token = secrets.token_urlsafe(18)
        self.routes[token] = (relay_for, url, {'User-Agent': agent} if agent else {})
        return token, f'http://127.0.0.1:{self.port}/{token}'

    def remove(self, token):
        self.routes.pop(token, None)

    async def handle(self, reader, writer):
        try:
            head = (await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)).decode('latin-1')
            method, path = head.split(' ', 2)[:2]
            route = self.routes.get(path.lstrip('/'))
            relay = route and route[0]()
            if method != 'GET' or not relay:
                writer.write(b'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                return
            match = re.search(r'(?im)^range:\s*bytes=(\d+)-', head)
            start = int(match[1]) if match else 0
            status, _, headers, content = await relay.fetch('GET', route[1], {**route[2], 'Range': f'bytes={start}-{start + CHUNK - 1}'})
            total = media_size(route[1], headers)
            if status != 206 or not total or start >= total:
                logging.getLogger('uvicorn.error').warning('relay_media outcome=bad_response status=%s size_known=%s', status, bool(total))
                writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                return
            writer.write((f'HTTP/1.1 206 Partial Content\r\nContent-Type: application/octet-stream\r\nAccept-Ranges: bytes\r\n'
                          f'Content-Range: bytes {start}-{total - 1}/{total}\r\nContent-Length: {total - start}\r\n'
                          'Connection: close\r\n\r\n').encode())
            position = start
            while content:
                writer.write(content)
                await writer.drain()
                position += len(content)
                if position >= total:
                    break
                # FFmpeg reads sequentially; each chunk is fetched only when the previous one was consumed.
                _, _, _, content = await relay.fetch('GET', route[1], {**route[2], 'Range': f'bytes={position}-{min(total, position + CHUNK) - 1}'})
        except (OSError, ValueError, ConnectionError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
            # FFmpeg closes the connection on every seek; only relay failures are worth a line.
            if not isinstance(error, (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError)):
                logging.getLogger('uvicorn.error').warning('relay_media outcome=failed error_type=%s', type(error).__name__)
        finally:
            writer.close()


def media_size(url, headers):
    # Browsers hide Content-Range from cross-origin googlevideo responses; the signed URL carries the length.
    total = re.search(r'/(\d+)$', headers.get('content-range', ''))
    length = parse_qs(urlsplit(url).query).get('clen', [''])[0]
    return int(total[1]) if total else int(length) if length.isdigit() else None


media = MediaServer()
