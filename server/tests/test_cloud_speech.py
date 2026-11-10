import base64
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from synchro.cloud import TranslationSettings
from synchro.cloud_speech import speak
from synchro.pipeline import Pipeline, Session, wav_bytes
from synchro.usage import collect_usage, record_usage, usage_summary


def speech_stream(text, done=True, error=None):
    frames = [{'choices': [{'delta': {'audio': {'transcript': text, 'data': base64.b64encode(b'\0\1' * 24000).decode()}}}]}]
    frames.append({'usage': {'cost': .001, 'completion_tokens': 30}, 'choices': []})
    if error:
        frames.append({'error': error})
    return ''.join('data: ' + json.dumps(frame) + '\n\n' for frame in frames) + ('data: [DONE]\n\n' if done else '')


class CloudSpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_cloud_pipeline_never_calls_local_ai_and_uses_one_key(self):
        settings = TranslationSettings(provider='kilo', mode='cloud_all', api_key='private-test-api-key-123')
        pipeline = Pipeline('http://local-speech', 'http://local-llm', silero_url='http://local-tts', cloud_tunnels={'kilo': 8443})
        await pipeline.client.aclose()
        paths = []
        def respond(request):
            self.assertEqual(request.url.host, '127.0.0.1')
            self.assertEqual(request.url.port, 8443)
            self.assertEqual(request.headers['Host'], 'ai-gateway.kilo.ai')
            self.assertEqual(request.headers['Authorization'], 'Bearer private-test-api-key-123')
            paths.append(request.url.path)
            if request.url.path.endswith('/audio/transcriptions'):
                return httpx.Response(200, json={'text': 'Hello world.', 'usage': {'cost': .002}})
            body = json.loads(request.content)
            if body.get('stream'):
                return httpx.Response(200, text=speech_stream('Привет, мир.'), headers={'Content-Type': 'text/event-stream'})
            return httpx.Response(200, json={'choices': [{'message': {'content': 'Привет, мир.'}}], 'usage': {'cost': .0001}})
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        session = Session('cloud', translation=settings)
        try:
            with patch.object(pipeline, 'transcribe', side_effect=AssertionError('local ASR called')), \
                 patch.object(pipeline, 'speak', side_effect=AssertionError('local TTS called')), \
                 patch('synchro.pipeline.normalize_wav', new=AsyncMock(side_effect=lambda audio: audio)), \
                 patch('synchro.pipeline.fit_wav', new=AsyncMock(side_effect=lambda audio, seconds: audio)), collect_usage(session.usage):
                result = await pipeline.process(session, b'\0\1' * 176000, 0, False, step=160000)
            self.assertEqual(result['ready_until'], 10)
            self.assertEqual(result['segments'][0]['source'], 'Hello world.')
            self.assertEqual(len(paths), 3)
            self.assertAlmostEqual(usage_summary(session.usage)['reported_cost_usd'], .0031)
            self.assertEqual(usage_summary(session.usage)['unpriced_requests'], 0)
        finally:
            await pipeline.client.aclose()

    async def test_stream_must_finish_and_repeat_the_text_exactly(self):
        settings = TranslationSettings(provider='openrouter', mode='cloud_all', api_key='private-test-api-key-123')
        for body in [speech_stream('Добавленные слова. Привет.'), speech_stream('Привет.', done=False), speech_stream('Привет.', error={'message': 'private-test-api-key-123'})]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))) as client:
                with self.assertRaises(ValueError) as error:
                    await speak(client, settings, 'Привет.', 'female')
                self.assertNotIn('private-test-api-key-123', str(error.exception))

    async def test_usage_is_isolated_and_missing_cost_is_not_zero(self):
        first, second = {}, {}
        with collect_usage(first):
            record_usage('translation', {'cost': .01})
            with collect_usage(second):
                record_usage('tts', {'cost': 0})
            record_usage('translation', {'cost': float('nan')})
        record_usage('asr', {'cost': 1})
        self.assertEqual(usage_summary(first)['unpriced_requests'], 1)
        self.assertEqual(usage_summary(first)['reported_cost_usd'], .01)
        self.assertEqual(usage_summary(second)['reported_cost_usd'], 0)
        self.assertEqual(set(first), {'translation'})

    def test_modes_are_explicit_and_legacy_configs_keep_their_behavior(self):
        self.assertEqual(TranslationSettings().mode, 'local')
        self.assertEqual(TranslationSettings(provider='kilo', api_key='private-test-api-key-123').mode, 'cloud_translation')
        for fields in [{'provider': 'local', 'mode': 'cloud_all'}, {'provider': 'kilo', 'mode': 'local', 'api_key': 'private-test-api-key-123'}]:
            with self.assertRaises(ValueError):
                TranslationSettings(**fields)
