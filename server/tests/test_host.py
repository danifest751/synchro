import asyncio
from threading import Event
import unittest
from unittest.mock import AsyncMock, patch

from synchro.host import HostPipeline
from synchro.pipeline import wav_bytes


class HostTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_cpu_inference_cannot_overlap_the_next_model_call(self):
        pipeline = HostPipeline('http://unused', 'http://unused')
        started, release, speech_started = Event(), Event(), Event()
        def recognize(pcm):
            started.set()
            release.wait(5)
            return {'text': 'hello', 'words': []}
        def speech(text, voice):
            speech_started.set()
            return wav_bytes(b'\0\0' * 16000)
        pipeline.recognize_cpu = recognize
        pipeline.synthesize_cpu = speech
        try:
            first = asyncio.create_task(pipeline.transcribe(b'pcm'))
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            with patch('synchro.host.normalize_wav', new=AsyncMock(side_effect=lambda audio: audio)):
                second = asyncio.create_task(pipeline.speak('Привет', 'female'))
                await asyncio.sleep(.02)
                self.assertFalse(speech_started.is_set())
                release.set()
                self.assertTrue((await second).startswith(b'RIFF'))
            self.assertTrue(pipeline.russian_speech)
        finally:
            release.set()
            pipeline.host_executor.shutdown(wait=True)
            await pipeline.client.aclose()
