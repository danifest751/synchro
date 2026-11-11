import asyncio
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from synchro.youtube import YoutubeAudio, youtube_url, discard_errors


class YoutubeTests(unittest.IsolatedAsyncioTestCase):
    async def test_seek_keeps_the_exact_selected_position(self):
        from types import SimpleNamespace
        process = SimpleNamespace(stdout=SimpleNamespace(readexactly=AsyncMock(return_value=b'\0\1' * 1600)),
                                  stderr=asyncio.StreamReader())
        process.stderr.feed_eof()
        with patch('synchro.youtube.asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)) as create:
            audio = await YoutubeAudio.from_info({'url': 'https://test.googlevideo.com/audio', 'duration': 800}, 613.7, '')
            self.assertEqual(audio.base, 613.7)
            command = create.await_args.args
            self.assertEqual(command[command.index('-ss') + 1], '613.7')
            await audio.errors

    def test_only_canonical_video_urls_are_accepted(self):
        expected = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        for url in [expected + '&t=15', 'https://youtu.be/dQw4w9WgXcQ', 'https://www.youtube.com/shorts/dQw4w9WgXcQ']:
            self.assertEqual(youtube_url(url), expected)
        for url in ['http://youtube.com/watch?v=dQw4w9WgXcQ', 'https://youtube.com.evil.org/watch?v=dQw4w9WgXcQ', 'https://user@youtube.com/watch?v=dQw4w9WgXcQ', 'https://youtube.com:8888/watch?v=dQw4w9WgXcQ', 'https://127.0.0.1/', 'file:///etc/passwd', 'https://youtube.com/playlist?list=x']:
            with self.assertRaises(ValueError, msg=url):
                youtube_url(url)

    async def test_audio_windows_keep_overlap_and_flush_tail(self):
        class Process:
            returncode = 0
            stdout = asyncio.StreamReader()
            async def wait(self):
                return 0
        pcm = b'\0\1' * (35 * 16000)
        Process.stdout.feed_data(pcm)
        Process.stdout.feed_eof()
        audio = YoutubeAudio(Process(), asyncio.create_task(asyncio.sleep(0)), 35, 0)
        first, final = await audio.next()
        self.assertEqual(first, pcm[:11 * 32000])
        self.assertFalse(final)
        middle, final = await audio.next()
        self.assertEqual(middle, pcm[10 * 32000:31 * 32000])
        self.assertFalse(final)
        last, final = await audio.next()
        self.assertEqual(last, pcm[30 * 32000:])
        self.assertTrue(final)
        await audio.close()

    async def test_stopping_a_full_decoder_pipe_releases_the_session(self):
        process = await asyncio.create_subprocess_exec(sys.executable, '-c',
            'import os\nwhile True: os.write(1, b"x" * 65536)',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        errors = asyncio.create_task(discard_errors(process.stderr))
        audio = YoutubeAudio(process, errors, 100, 0)
        await asyncio.sleep(.15)
        await asyncio.wait_for(audio.close(), 3)
        self.assertIsNotNone(process.returncode)

    async def test_truncated_network_stream_is_not_a_successful_end(self):
        class Process:
            returncode = 0
            stdout = asyncio.StreamReader()
            async def wait(self):
                return 0
        Process.stdout.feed_data(b'\0\1' * 16000)
        Process.stdout.feed_eof()
        audio = YoutubeAudio(Process(), asyncio.create_task(asyncio.sleep(0)), 100, 0)
        with self.assertRaisesRegex(ValueError, 'before the video'):
            await audio.next()
        await audio.close()

    async def test_dropped_stream_resumes_at_the_exact_position(self):
        def process(data, code):
            stdout = asyncio.StreamReader()
            stdout.feed_data(data)
            stdout.feed_eof()
            async def wait():
                return code
            return SimpleNamespace(returncode=code, stdout=stdout, wait=wait)

        pcm = bytes(range(256)) * (24 * 32000 // 256)
        # The CDN connection drops after 4 seconds; the resumed decoder continues from there.
        reopen = AsyncMock(return_value=(process(pcm[4 * 32000:], 0), asyncio.create_task(asyncio.sleep(0))))
        audio = YoutubeAudio(process(pcm[:4 * 32000], 1), asyncio.create_task(asyncio.sleep(0)), 124, 100, reopen)
        first, final = await audio.next()
        self.assertEqual((first, final), (pcm[:11 * 32000], False))
        reopen.assert_awaited_once_with(104.0)
        last, final = await audio.next()
        self.assertEqual((last, final), (pcm[10 * 32000:], True))

    async def test_repeated_drops_end_with_an_error(self):
        def dropped(*args):
            stdout = asyncio.StreamReader()
            stdout.feed_eof()
            async def wait():
                return 1
            return SimpleNamespace(returncode=1, stdout=stdout, wait=wait), asyncio.create_task(asyncio.sleep(0))

        reopen = AsyncMock(side_effect=dropped)
        audio = YoutubeAudio(*dropped(), 100, 0, reopen)
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            await audio.next()
        self.assertEqual(reopen.await_count, 3)
