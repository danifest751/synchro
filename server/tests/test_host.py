import asyncio
import importlib.util
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from synchro.host import HostPipeline
from synchro.pipeline import wav_bytes


class HostTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'numpy is part of the desktop inference runtime')
    async def test_english_alphabet_fallback_uses_bundled_sensevoice_without_whisper(self):
        pipeline = HostPipeline('http://unused', 'http://unused')
        result = SimpleNamespace(text='ай эм рэди', tokens=[], timestamps=[])
        pipeline.host_asr = Mock()
        pipeline.host_asr.recognize.return_value = result
        pipeline.sensevoice = SimpleNamespace(path='bundled', recognize=Mock(return_value={'text': 'I am ready', 'words': []}))
        pipeline.whisper_cpu = Mock(return_value={'text': 'Whisper result', 'words': []})
        pcm = b'\1\0' * 16000
        try:
            with patch.dict('os.environ', {'SYNCHRO_HOST_WHISPER_MODEL': ''}):
                self.assertEqual(pipeline.recognize_cpu(pcm)['text'], 'I am ready')
                pipeline.sensevoice.recognize.assert_called_once_with(pcm, 'en')
                pipeline.sensevoice.recognize.reset_mock()
                result.text = ''
                pipeline.recognize_cpu(pcm)
                pipeline.sensevoice.recognize.assert_called_once()
                pipeline.sensevoice.recognize.reset_mock()
                pipeline.recognize_cpu(b'\0\0' * 16000)
                result.text = 'Hello world'
                self.assertEqual(pipeline.recognize_cpu(pcm)['text'], 'Hello world')
                pipeline.sensevoice.recognize.assert_not_called()
                pipeline.whisper_cpu.assert_not_called()
            with patch.dict('os.environ', {'SYNCHRO_HOST_WHISPER_MODEL': 'installed'}):
                result.text = 'ай эм рэди'
                self.assertEqual(pipeline.recognize_cpu(pcm)['text'], 'Whisper result')
                pipeline.whisper_cpu.assert_called_once_with(pcm, 'en')
        finally:
            pipeline.host_executor.shutdown(wait=True)
            await pipeline.client.aclose()

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
