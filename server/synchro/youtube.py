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

    @classmethod
    async def open(cls, url: str, position: float, language: str = 'en'):
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

        async def reopen(at):
            # A signed media URL can expire during a long pause; resolve it again.
            _metadata.pop((url, language), None)
            return await cls.spawn(await cls.cached_info(args, url, language), at, proxy)

        info = await cls.cached_info(args, url, language)
        try:
            return await cls.from_info(info, position, proxy, reopen)
        except Exception:
            _metadata.pop((url, language), None)
            raise

    @classmethod
    async def cached_info(cls, args, url, language):
        # Serialize YouTube JavaScript challenges.
        async with _resolution_lock:
            cached = _metadata.get((url, language))
            if cached and time.monotonic() - cached[0] < 600:
                return cached[1]
            info = await cls.resolve(args, url)
            if len(_metadata) >= 3:
                _metadata.pop(min(_metadata, key=lambda item: _metadata[item][0]))
            _metadata[url, language] = (time.monotonic(), info)
            return info

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
    async def spawn(info, position, proxy):
        media = urlsplit(info.get("url", ""))
        if media.scheme != "https" or not (media.hostname or "").endswith(".googlevideo.com") or media.port not in (None, 443) or media.username:
            raise ValueError("YouTube returned an unsupported audio source")
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
    async def from_info(cls, info, position, proxy, reopen=None):
        if info.get("is_live"):
            raise ValueError("This mode supports recorded videos; live streams are not supported yet")
        duration = float(info.get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0 or position >= duration:
            raise ValueError("Unknown duration or position beyond the end of the video")
        process, errors = await cls.spawn(info, position, proxy)
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
