"""Fetch the original audio track without capturing the tab."""
import asyncio
import json
import logging
import math
import os
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit

from . import relay
from .pipeline import RATE

_metadata = {}
_resolution_lock = asyncio.Lock()


def youtube_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("An HTTPS YouTube URL is required")
    host = parsed.hostname
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        video_id = parse_qs(parsed.query).get("v", [""])[0] if parsed.path == "/watch" else parsed.path.rsplit("/", 1)[-1] if parsed.path.startswith(("/shorts/", "/live/")) else ""
    else:
        raise ValueError("Only YouTube URLs are supported")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Video ID not found")
    return "https://www.youtube.com/watch?v=" + video_id


async def discard_errors(reader):
    # Do not log signed URLs or video content.
    while await reader.read(4096):
        pass


def browser_clients():
    # Through a browser, TV clients fail and their media URLs are bound to other User-Agents; clients that need no
    # JavaScript challenge (yt-dlp's own list, currently visionos) return URLs the browser can download as itself.
    from yt_dlp.extractor.youtube import YoutubeIE
    return getattr(YoutubeIE, "_DEFAULT_JSLESS_CLIENTS", None) or ("visionos",)


class YoutubeAudio:
    def __init__(self, process, errors, duration, base, reopen=None):
        self.process, self.errors = process, errors
        self.duration, self.base = duration, base
        self.pending = b""
        self.eof = False
        self.received = 0
        self.step = 10 * RATE
        # Async callable(position) -> (process, errors) that resumes a dropped CDN stream.
        self.reopen = reopen
        self.restarts = 0
        self.routes = []

    @classmethod
    async def open(cls, url: str, position: float, language: str = 'en', relay_for=None):
        url = youtube_url(url)
        if not math.isfinite(position) or position < 0:
            raise ValueError("Invalid video position")
        args = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-warnings",
                "--js-runtimes", "node", "--socket-timeout", "15", "--retries", "1",
                # Prefer the original-language track: videos can carry automatic dubs in other languages.
                "-f", f"ba[language^={language}][ext=m4a]/ba[language^={language}]/ba[ext=m4a]/ba"]
        proxy = os.environ.get("YTDLP_PROXY", "")
        if proxy:
            args += ["--proxy", proxy]
        # With a connected browser, YouTube is reached from the viewer's network instead of the server's.
        browser = relay_for if relay_for and relay_for() else None
        key = (url, language, bool(browser))
        routes = []

        async def source(info, at):
            if not browser:
                return await cls.spawn(info, at, proxy)
            cls.check_media(info)
            # Media URLs can be bound to the User-Agent of the YouTube client yt-dlp used.
            token, local = await relay.media.add(browser, info["url"], info.get("http_headers", {}).get("User-Agent", ""))
            routes.append(token)
            return await cls.spawn({**info, "url": local}, at, "", local=True)

        async def reopen(at):
            # A signed media URL can expire during a long pause; resolve it again.
            _metadata.pop(key, None)
            return await source(await cls.cached_info(args, url, key, browser), at)

        info = await cls.cached_info(args, url, key, browser)
        try:
            audio = await cls.from_info(info, position, proxy, reopen, source)
        except Exception:
            _metadata.pop(key, None)
            for token in routes:
                relay.media.remove(token)
            raise
        audio.routes = routes
        return audio

    @classmethod
    async def cached_info(cls, args, url, key, browser=None):
        # Serialize YouTube JavaScript challenges.
        async with _resolution_lock:
            cached = _metadata.get(key)
            if cached and time.monotonic() - cached[0] < 600:
                return cached[1]
            info = await (cls.resolve_in_browser(browser, args, url) if browser else cls.resolve(args, url))
            if len(_metadata) >= 3:
                _metadata.pop(min(_metadata, key=lambda item: _metadata[item][0]))
            _metadata[key] = (time.monotonic(), info)
            return info

    @staticmethod
    async def resolve_in_browser(browser, args, url):
        current = browser()
        if not current:
            raise ValueError("The browser connection closed; restart translation")
        options = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True, "socket_timeout": 15,
                   "retries": 1, "js_runtimes": {"node": {}}, "format": args[args.index("-f") + 1],
                   "extractor_args": {"youtube": {"player_client": list(browser_clients())}}}
        try:
            return await asyncio.wait_for(asyncio.to_thread(relay.extract, current, url, options), 75)
        except (OSError, ValueError, TimeoutError) as error:
            raise ValueError("YouTube did not return audio through the browser. Check that YouTube opens in this browser") from error
        except Exception as error:
            # yt-dlp reports extractor failures with its own exception types.
            raise ValueError("YouTube did not return audio through the browser: " + str(error)[:160]) from error

    @staticmethod
    async def resolve(args, url):
        resolver = await asyncio.create_subprocess_exec(*args, "--skip-download", "-J", "--", url,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            raw, _ = await asyncio.wait_for(resolver.communicate(), 75)
        except BaseException:
            if resolver.returncode is None:
                resolver.kill()
            await resolver.communicate()
            raise
        if resolver.returncode:
            raise ValueError("YouTube did not return audio. Check connectivity; this video may require sign-in")
        return json.loads(raw)

    @staticmethod
    def check_media(info):
        media = urlsplit(info.get("url", ""))
        if media.scheme != "https" or not (media.hostname or "").endswith(".googlevideo.com") or media.port not in (None, 443) or media.username:
            raise ValueError("YouTube returned an unsupported audio source")

    @classmethod
    async def spawn(cls, info, position, proxy, local=False):
        if not local:
            cls.check_media(info)
        headers = info.get("http_headers", {})
        agent = headers.get("User-Agent", "Mozilla/5.0")
        if "\r" in agent or "\n" in agent:
            raise ValueError("Invalid source header")
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-rw_timeout", "30000000",
                   # The CDN drops idle connections while playback is paused; continue from the same byte range.
                   "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "4"]
        if proxy:
            command += ["-http_proxy", proxy]
        command += ["-user_agent", agent, "-ss", str(position), "-i", info["url"], "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"]
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        return process, asyncio.create_task(discard_errors(process.stderr))

    @classmethod
    async def from_info(cls, info, position, proxy, reopen=None, source=None):
        if info.get("is_live"):
            raise ValueError("This mode supports recorded videos; live streams are not supported yet")
        duration = float(info.get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0 or position >= duration:
            raise ValueError("Unknown duration or position beyond the end of the video")
        process, errors = await (source(info, position) if source else cls.spawn(info, position, proxy))
        audio = cls(process, errors, duration, position, reopen)
        try:
            # Check CDN access before opening a browser session.
            audio.pending = await asyncio.wait_for(process.stdout.readexactly(3200), 35)
            audio.received = len(audio.pending)
        except asyncio.CancelledError:
            await audio.close()
            raise
        except Exception:
            await audio.close()
            raise ValueError("Could not read the YouTube audio stream")
        return audio

    async def next(self):
        wanted = (self.step + RATE) * 2
        while len(self.pending) < wanted and not self.eof:
            try:
                block, ended = await asyncio.wait_for(self.process.stdout.readexactly(wanted - len(self.pending)), 40), False
            except asyncio.IncompleteReadError as error:
                block, ended = error.partial, True
            # Keep audio read before a failure so a retried window loses nothing.
            self.pending += block
            self.received += len(block)
            if ended:
                await self.resume()
        result = self.pending
        self.pending = b"" if self.eof else result[self.step * 2:]
        self.step = 20 * RATE
        self.restarts = 0
        return result, self.eof

    async def resume(self):
        await self.process.wait()
        position = self.base + self.received / (RATE * 2)
        if not self.process.returncode and position >= self.duration - 2:
            self.eof = True
            return
        if not self.reopen or self.restarts >= 3:
            raise ValueError("YouTube stream interrupted; restart translation" if self.process.returncode else
                             "Audio stream ended before the video. Check network access and any proxy or SSH tunnel")
        self.restarts += 1
        logging.getLogger("uvicorn.error").warning("youtube_audio outcome=resume position=%.1f attempt=%d", position, self.restarts)
        await self.errors
        self.process, self.errors = await self.reopen(position)

    async def close(self):
        if self.process.returncode is None:
            self.process.kill()
        # Drain stdout so asyncio.wait() can finish after kill().
        await self.process.stdout.read()
        await self.process.wait()
        await self.errors
        for token in self.routes:
            relay.media.remove(token)
