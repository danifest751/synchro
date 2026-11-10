import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from synchro.cloud import TranslationSettings
from synchro.pipeline import Pipeline, wav_bytes
from synchro.voices import StudioVoices, STUDIO_VOICES


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_six_private_profiles_and_accent_marks_reach_only_studio(self):
        profiles = {voice: 'private-profile-' + str(index) for index, voice in enumerate(STUDIO_VOICES)}
        env = {'SYNCHRO_VOICESTUDIO_URL': 'http://studio', 'SYNCHRO_VOICESTUDIO_TOKEN': 'private-studio-key',
               'SYNCHRO_VOICESTUDIO_VOICES': json.dumps(profiles), 'SYNCHRO_VOICESTUDIO_SHARED_GPU': '1'}
        with patch.dict(os.environ, env):
            pipeline = Pipeline('http://speech', 'http://llm', accent_url='http://accent')
        await pipeline.client.aclose()
        seen = []
        def respond(request):
            body = json.loads(request.content)
            if request.url.host == 'accent':
                self.assertNotIn('Authorization', request.headers)
                return httpx.Response(200, json={'text': 'В+осемьдесят л+ёт. На двер+и зам+ок, ст+арый з+амок.'})
            self.assertEqual(request.url.host, 'studio')
            self.assertEqual(request.headers['Authorization'], 'Bearer private-studio-key')
            seen.append(body)
            return httpx.Response(200, content=wav_bytes(b'\xff\x1f' * 16000))
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            catalog = pipeline.studio.available('cloud_translation')
            self.assertEqual(len(catalog), 9)
            self.assertNotIn('private', json.dumps(catalog))
            self.assertEqual(len(pipeline.studio.available('local')), 3)
            self.assertEqual(len(pipeline.studio.available('cloud_all')), 3)
            with self.assertRaises(ValueError):
                pipeline.studio.validate('studio-female-1', 'local')
            with patch('synchro.pipeline.normalize_wav', new=AsyncMock(side_effect=lambda data: data)):
                for voice in profiles:
                    await pipeline.synthesize('Восемьдесят лет. На двери замок, старый замок.', voice,
                                              TranslationSettings(provider='kilo', api_key='test-api-key-1234567890'))
            self.assertEqual([body['voice'] for body in seen], list(profiles.values()))
            self.assertTrue(all(body['input'] == 'Во́семьдесят ле́т. На двери́ замо́к, ста́рый за́мок.' for body in seen))
            pipeline.accentuate = AsyncMock(side_effect=ValueError('Annotation changed the words'))
            with patch('synchro.pipeline.normalize_wav', new=AsyncMock(side_effect=lambda data: data)):
                await pipeline.synthesize('Исходные слова.', 'studio-female-1',
                    TranslationSettings(provider='kilo', api_key='test-api-key-1234567890'))
            self.assertEqual(seen[-1]['input'], 'Исходные слова.', 'invalid stress annotation must not interrupt or rewrite speech')
        finally:
            await pipeline.client.aclose()

    async def test_provider_errors_do_not_expose_the_private_response(self):
        studio = StudioVoices()
        studio.url, studio.token, studio.profiles = 'http://studio', 'private-token', {'studio-male-1': 'secret-profile'}
        for status, content in [(500, b'private-server-details'), (200, b'not-a-wave')]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, content=content))) as client:
                with self.assertRaises(ValueError) as caught:
                    await studio.speak(client, 'Привет', 'studio-male-1')
                self.assertNotIn('private-server-details', str(caught.exception))

    def test_invalid_profile_configuration_is_rejected(self):
        for profiles in [['not-a-map'], {'female': 'abc'}, {'studio-male-1': '../private'}]:
            with patch.dict(os.environ, {'SYNCHRO_VOICESTUDIO_VOICES': json.dumps(profiles)}), self.assertRaises(ValueError):
                StudioVoices()
