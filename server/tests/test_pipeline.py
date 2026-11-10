import asyncio
import base64
import unittest
import json
import httpx
import shutil
from unittest.mock import AsyncMock, patch

from synchro.pipeline import Pipeline, Session, fit_wav, select_words, wav_bytes, wav_info, join_wav, normalize_wav


class FakePipeline(Pipeline):
    def __init__(self):
        pass

    async def transcribe(self, pcm):
        return {"words": [{"word": " Hello", "start": 0.2, "end": 1.0}, {"word": " world", "start": 7.4, "end": 7.8}]}

    async def translate(self, *args, **kwargs):
        return "Привет"

    async def speak(self, text, voice='female'):
        return wav_bytes(b"\0\0" * 22050, 22050)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg must be installed')
    async def test_short_narration_gently_fills_its_interval(self):
        data = wav_bytes(b'\0\1' * 16000 * 3)
        result = await fit_wav(data, 6)
        rate, seconds = wav_info(result)
        self.assertEqual(rate, 16000)
        self.assertGreater(seconds, 3.15)
        self.assertLess(seconds, 3.4)

    async def test_silero_receives_selected_voice_and_original_spelling(self):
        pipeline = Pipeline('http://speech', 'http://llama', silero_url='http://silero', silero_token='internal-tts-key')
        await pipeline.client.aclose()
        seen = []
        def respond(request):
            self.assertEqual(str(request.url), 'http://silero/speech')
            self.assertEqual(request.headers['Authorization'], 'Bearer internal-tts-key')
            seen.append(json.loads(request.content))
            return httpx.Response(200, content=wav_bytes(b'\0\1' * 48000, 48000))
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with patch('synchro.pipeline.normalize_wav', new=AsyncMock(side_effect=lambda data: data)):
                for voice in ['female', 'male', 'male-eugene']:
                    await pipeline.speak('Восемьдесят лет исследований.', voice)
            self.assertEqual([item['voice'] for item in seen], ['xenia', 'aidar', 'eugene'])
            self.assertTrue(all(item['text'] == 'Восемьдесят лет исследований.' for item in seen))
        finally:
            await pipeline.client.aclose()

    async def test_silero_translation_retries_latin_names_and_digits(self):
        pipeline = Pipeline('http://speech', 'http://llama', api='llama', silero_url='http://silero')
        await pipeline.client.aclose()
        replies = iter(['ChatGPT за 80 лет.', 'Чат Джи Пи Ти за восемьдесят лет.'])
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json={'choices': [{'message': {'content': json.dumps({'translation': next(replies)})}}]})))
        try:
            self.assertEqual(await pipeline.translate('ChatGPT in 80 years', [], 5), 'Чат Джи Пи Ти за восемьдесят лет.')
        finally:
            await pipeline.client.aclose()

    async def test_accent_service_cannot_change_e_to_yo(self):
        pipeline = Pipeline('http://speech', 'http://llama')
        await pipeline.client.aclose()
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'text': 'в+осемьдесят л+ёт'})))
        try:
            self.assertEqual(await pipeline.accentuate('восемьдесят лет'), 'во\u0301семьдесят ле\u0301т')
        finally:
            await pipeline.client.aclose()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg must be installed')
    async def test_phrase_loudness_is_equalized_without_changing_duration(self):
        import io, math, wave
        from array import array
        levels = []
        for amplitude in [2000, 8000]:
            pcm = array('h', (round(amplitude * math.sin(2 * math.pi * 440 * i / 22050)) for i in range(22050 * 3))).tobytes()
            result = await normalize_wav(wav_bytes(pcm, 22050))
            self.assertEqual(wav_info(result), (22050, 3))
            with wave.open(io.BytesIO(result)) as audio:
                values = array('h', audio.readframes(audio.getnframes()))
                self.assertLess(max(abs(x) for x in values), 32767)
                levels.append(math.sqrt(sum(x*x for x in values)/len(values)))
        self.assertLess(abs(levels[0]/levels[1] - 1), .03)
        silence = wav_bytes(b'\0\0' * 22050, 22050)
        self.assertEqual(await normalize_wav(silence), silence)

    def test_all_piper_sentences_are_preserved_in_one_wav(self):
        first = wav_bytes(b'\1\0' * 22050, 22050)
        second = wav_bytes(b'\2\0' * 44100, 22050)
        joined = join_wav(first + second)
        self.assertEqual(wav_info(joined), (22050, 3))
        import io, wave
        with wave.open(io.BytesIO(joined)) as audio:
            self.assertEqual(audio.readframes(audio.getnframes()), b'\1\0' * 22050 + b'\2\0' * 44100)
        for broken in [first + second[:-2], first + b'broken', first + wav_bytes(b'\0\1' * 16000, 16000), b'']:
            with self.subTest(size=len(broken)), self.assertRaises(ValueError):
                join_wav(broken)

    async def test_private_gigaam_receives_pcm_and_its_own_key(self):
        pipeline = Pipeline('http://speech', 'http://llama', asr_url='http://gigaam', asr_token='private-asr-key')
        await pipeline.client.aclose()
        def respond(request):
            self.assertEqual(str(request.url), 'http://gigaam/transcribe')
            self.assertEqual(request.headers['Authorization'], 'Bearer private-asr-key')
            self.assertEqual(request.content, b'\0\1' * 16000)
            return httpx.Response(200, json={'text': 'hi', 'words': [{'word': ' hi', 'start': 0.1, 'end': 0.3}]})
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            result = await pipeline.transcribe(b'\0\1' * 16000)
            self.assertEqual(result['words'][0]['word'], ' hi')
        finally:
            await pipeline.client.aclose()

    async def test_gigaam_wrong_alphabet_or_outage_rechecks_with_whisper(self):
        for status, text in [(200, 'w е н та ром'), (503, '')]:
            with self.subTest(status=status):
                pipeline = Pipeline('http://speech', 'http://llama', asr_url='http://gigaam', asr_token='private-asr-key')
                await pipeline.client.aclose()
                paths = []
                def respond(request):
                    paths.append(request.url.path)
                    if request.url.host == 'gigaam':
                        return httpx.Response(status, json={'text': text})
                    self.assertNotIn('Authorization', request.headers)
                    return httpx.Response(200, json={'text': 'What happens when you type a prompt', 'words': []})
                pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                try:
                    result = await pipeline.transcribe(b'\0\1' * 16000)
                    self.assertTrue(result['text'].startswith('What happens'))
                    self.assertEqual(paths, ['/transcribe', '/v1/audio/transcriptions'])
                finally:
                    await pipeline.client.aclose()

    async def test_llama_translation_uses_schema_and_rejects_invalid_text(self):
        pipeline = Pipeline('http://speech', 'http://llama', model='gemma4-26b', api='llama')
        await pipeline.client.aclose()
        response_text = '  Привет  '
        def respond(request):
            body = json.loads(request.content)
            self.assertEqual(request.url.path, '/v1/chat/completions')
            self.assertEqual(body['model'], 'gemma4-26b')
            self.assertEqual(body['response_format']['json_schema']['schema']['required'], ['translation'])
            self.assertFalse(body['stream'])
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'translation': response_text})}}]})
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            self.assertEqual(await pipeline.translate('Hello', [], 3), 'Привет')
            response_text = ''
            with self.assertRaises(ValueError):
                await pipeline.translate('Hello', [], 3)
        finally:
            await pipeline.client.aclose()

    async def test_overlap_and_final_flush(self):
        pipeline = FakePipeline()
        session = Session("test")
        result = await pipeline.process(session, b"\0\1" * 128000, 0, False)
        self.assertEqual(result["ready_until"], 7)
        self.assertEqual(result["segments"][0]["source"], "Hello")
        self.assertEqual(wav_info(base64.b64decode(result["segments"][0]["wav"]))[0], 22050)
        result = await pipeline.process(session, b"\0\1" * 64000, 112000, True)
        self.assertTrue(result["finished"])
        self.assertEqual(result["ready_until"], 11)

    async def test_gap_does_not_advance_frontier(self):
        session = Session("test")
        with self.assertRaises(ValueError):
            await FakePipeline().process(session, b"\0\0" * 128000, 10, False)
        self.assertEqual(session.offset, 0)

    async def test_inference_failure_does_not_commit(self):
        pipeline = FakePipeline()
        async def broken(*args, **kwargs):
            raise RuntimeError("unavailable")
        pipeline.speak = broken
        session = Session("test")
        with self.assertRaises(RuntimeError):
            await pipeline.process(session, b"\0\1" * 128000, 0, False)
        self.assertEqual(session.offset, 0)

    async def test_silence_advances_without_hallucinated_speech(self):
        result = await FakePipeline().process(Session('quiet'), b'\0\0' * 128000, 0, False)
        self.assertEqual(result['segments'], [])
        self.assertEqual(result['ready_until'], 7)

    async def test_invalid_source_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            await fit_wav(wav_bytes(b'\0\1' * 16000 * 4), 0)

    async def test_long_voiceover_does_not_fail_the_session(self):
        pipeline = FakePipeline()
        async def long_speech(text, voice='female'):
            return wav_bytes(b'\0\1' * 16000 * 20)
        pipeline.speak = long_speech
        # Check the protocol here; integration tests exercise real FFmpeg.
        from unittest.mock import AsyncMock, patch
        with patch('synchro.pipeline.fit_wav', new=AsyncMock(side_effect=lambda audio, seconds: audio)):
            result = await pipeline.process(Session('long'), b'\0\1' * 128000, 0, False)
        cue = result['segments'][0]
        self.assertEqual(cue['duration'], 20)
        self.assertAlmostEqual(cue['source_duration'], 6.8)
        self.assertEqual(result['ready_until'], 7)

    async def test_session_gender_is_used_for_synthesis(self):
        pipeline = FakePipeline()
        voices = []
        async def record_voice(text, voice):
            voices.append(voice)
            return wav_bytes(b'\0\1' * 16000)
        pipeline.speak = record_voice
        await pipeline.process(Session('male', voice='male'), b'\0\1' * 128000, 0, False)
        self.assertEqual(voices, ['male'])

    async def test_stress_marks_reach_piper(self):
        pipeline = Pipeline('http://speech', 'http://ollama', accent_url='http://accent')
        await pipeline.client.aclose()
        sent = []
        def respond(request):
            body = json.loads(request.content)
            if request.url.path == '/accent':
                return httpx.Response(200, json={'text': 'На двер+и вис+ит зам+ок.'})
            sent.append(body)
            return httpx.Response(200, content=wav_bytes(b'\0\1' * 16000))
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            original = 'На двери висит замок.'
            with patch('synchro.pipeline.normalize_wav', new=AsyncMock(side_effect=lambda audio: audio)):
                await pipeline.speak(original, 'male')
            self.assertEqual(sent[0]['input'], 'На двери\u0301 виси\u0301т замо\u0301к.')
        finally:
            await pipeline.client.aclose()

    async def test_accent_service_cannot_change_translation_words(self):
        pipeline = Pipeline('http://speech', 'http://ollama')
        await pipeline.client.aclose()
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'text': 'Друг+ие слов+а'})))
        try:
            with self.assertRaises(ValueError):
                await pipeline.accentuate('Исходный текст')
        finally:
            await pipeline.client.aclose()

    def test_midpoint_ownership(self):
        words = [{"word": "a", "start": 6.6, "end": 7.2}, {"word": "b", "start": 7.2, "end": 7.8}]
        self.assertEqual(select_words({"words": words}, 0, 7), words[:1])


if __name__ == "__main__":
    unittest.main()
