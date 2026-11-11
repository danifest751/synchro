import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from synchro.cloud import TranslationSettings
from synchro.pipeline import Pipeline
from synchro.sensevoice import token_words
from synchro.stress import cyrillic_spelling
from synchro.timing import source_phrases


class LanguageTests(unittest.IsolatedAsyncioTestCase):
    def test_sensevoice_tokens_become_timed_words(self):
        # Token shapes as SenseVoice returns them through sherpa-onnx.
        chinese = token_words(['开', '饭', '时', '间', '。'], [0.72, 0.96, 1.26, 1.5, 2.6], 3)
        self.assertEqual([word['word'] for word in chinese], ['开', '饭', '时', '间。'])
        self.assertEqual(chinese[0], {'word': '开', 'start': 0.72, 'end': 0.96})
        self.assertAlmostEqual(chinese[-1]['end'], 2.9)
        korean = token_words(['조', '금', '만', ' 생각을', ' 하면서', '.'], [0.84, 0.96, 1.14, 1.38, 2.04, 4.56], 4.6)
        self.assertEqual(''.join(word['word'] for word in korean), '조금만 생각을 하면서.')
        self.assertEqual([word['word'] for word in korean], ['조금만', ' 생각을', ' 하면서.'])
        japanese = token_words(['は', '5', '0', '円'], [1.0, 1.2, 1.4, 1.6], 2)
        self.assertEqual([word['word'] for word in japanese], ['は', '50', '円'])
        with self.assertRaises(ValueError):
            token_words(['开'], [], 1)

    def test_chinese_sentence_end_and_pause_split_phrases(self):
        words = token_words(list('今天很好。我们走吧'), [0, .25, .5, .75, 1.0, 1.3, 1.55, 2.6, 2.85], 4)
        self.assertEqual([phrase['source'] for phrase in source_phrases(words, 4)], ['今天很好。', '我们', '走吧'])

    async def test_language_selects_recognizer_with_whisper_fallback(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        try:
            pipeline.transcribe = AsyncMock(return_value={'words': []})
            pipeline.whisper = AsyncMock(return_value={'text': '你好', 'words': []})
            with patch.object(pipeline.sensevoice, 'recognize', return_value={'text': '你好', 'words': []}) as sensevoice:
                await pipeline.recognize(b'\0\0', language='zh')
                await pipeline.recognize(b'\0\0')
            sensevoice.assert_called_once_with(b'\0\0', 'zh')
            pipeline.transcribe.assert_awaited_once()
            pipeline.whisper.assert_not_awaited()
            # SenseVoice not configured: Whisper recognizes the language instead.
            await pipeline.recognize(b'\0\0', language='ko')
            pipeline.whisper.assert_awaited_once_with(b'\0\0', 'ko')
        finally:
            await pipeline.client.aclose()

    async def test_translation_prompt_names_the_source_language(self):
        pipeline = Pipeline('http://speech', 'http://llama', api='llama', silero_url='http://silero')
        await pipeline.client.aclose()
        prompts = []

        def respond(request):
            prompts.append(json.loads(request.content)['messages'][0]['content'])
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'translation': 'Привет, Сеул.'})}}]})
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            self.assertEqual(await pipeline.translate('안녕, 서울.', [], 3, translation=TranslationSettings(), language='ko'), 'Привет, Сеул.')
            self.assertIn('Translate the Korean speech', prompts[0])
        finally:
            await pipeline.client.aclose()

    def test_untranslated_source_script_is_not_sent_to_russian_speech(self):
        self.assertEqual(cyrillic_spelling('Город 首尔 и 서울'), 'Город и')


class LanguageApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_language_is_validated_and_used(self):
        import os
        os.environ.setdefault('SYNCHRO_TOKEN', 'unit-test-owner-token-00000000000000')
        os.environ.setdefault('SYNCHRO_ORIGIN', 'chrome-extension://' + 'a' * 32)
        from synchro import app as api
        api.sessions.clear()
        api.warm.clear()
        headers = {'Authorization': 'Bearer ' + api.TOKEN}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test') as client:
            with patch.object(api.pipeline, 'warmup', new=AsyncMock()) as warmup:
                rejected = await client.post('/api/session', headers=headers, json={'language': 'fr'})
                accepted = await client.post('/api/session', headers=headers, json={'language': 'ja', 'voice': 'roman'})
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(api.sessions[accepted.json()['session_id']].language, 'ja')
            self.assertEqual(warmup.await_args.args[2], 'ja')
        api.sessions.clear()

    async def test_original_language_audio_track_is_requested(self):
        from synchro.youtube import YoutubeAudio, _metadata
        _metadata.clear()
        info = {'url': 'https://example.googlevideo.com/audio', 'duration': 100}
        with patch.object(YoutubeAudio, 'resolve', new=AsyncMock(return_value=info)) as resolve, \
                patch.object(YoutubeAudio, 'from_info', new=AsyncMock(return_value='audio')):
            await YoutubeAudio.open('https://youtu.be/dQw4w9WgXcQ', 0, 'ko')
        selector = resolve.await_args.args[0][resolve.await_args.args[0].index('-f') + 1]
        self.assertTrue(selector.startswith('ba[language^=ko]'))
        _metadata.clear()
