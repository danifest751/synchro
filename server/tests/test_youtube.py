import asyncio
import unittest
import sys

from synchro.youtube import YoutubeAudio, youtube_url, discard_errors


class YoutubeTests(unittest.IsolatedAsyncioTestCase):
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
        pcm = b'\0\1' * (11 * 16000)
        Process.stdout.feed_data(pcm)
        Process.stdout.feed_eof()
        audio = YoutubeAudio(Process(), asyncio.create_task(asyncio.sleep(0)), 11, 0)
        first, final = await audio.next()
        self.assertEqual(first, pcm[:256000])
        self.assertFalse(final)
        last, final = await audio.next()
        self.assertEqual(last, pcm[224000:])
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
