import importlib.util
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from synchro.cloud import TranslationSettings
from synchro.pipeline import Pipeline, Session, RATE, wav_bytes
from synchro.speaker import SpeakerClassifier, decide
from synchro.usage import collect_usage, usage_summary


class SpeakerTests(unittest.TestCase):
    def test_kilo_microdollars_and_unknown_costs_are_distinguished(self):
        from synchro.usage import record_usage
        usage = {}
        with collect_usage(usage):
            record_usage('translation', {'cost_microdollars': 24})
            record_usage('translation', {'cost_microdollars': 0})
            record_usage('translation', {'cost_microdollars': True})
            record_usage('translation', {'cost_microdollars': -3})
        self.assertAlmostEqual(usage_summary(usage)['reported_cost_usd'], .000024)
        self.assertEqual(usage_summary(usage)['unpriced_requests'], 2)

    def test_uncertain_or_mixed_cues_do_not_force_a_gender(self):
        self.assertEqual(decide([]), 'unknown')
        self.assertEqual(decide([.4, .6]), 'unknown')
        self.assertEqual(decide([.01, .99]), 'unknown')
        self.assertEqual(decide([.02, .1, .15]), 'male')
        self.assertEqual(decide([.9, .98, .95]), 'female')

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'numpy is part of the desktop inference runtime')
    def test_silence_noise_and_short_clips_do_not_load_the_model(self):
        import numpy as np
        classifier = SpeakerClassifier('must-not-be-loaded.onnx')
        self.assertEqual(classifier.classify(b'\0\0' * 24000), 'unknown')
        self.assertEqual(classifier.classify(b'\xff\x3f' * 4000), 'unknown')
        noise = np.random.default_rng(42).normal(0, .03, 24000)
        self.assertEqual(classifier.classify((noise * 32767).astype('<i2').tobytes()), 'unknown')
        self.assertIsNone(classifier.model)


class SpeakerPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_assigned_voices_and_single_voice_work_independently_of_grammar(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        try:
            pipeline.recognize = AsyncMock(return_value={'words': [
                {'word': ' First.', 'start': .1, 'end': 1.5},
                {'word': ' Second.', 'start': 2, 'end': 3.5},
                {'word': ' Third.', 'start': 4, 'end': 5.5}]})
            pipeline.align_phrases = AsyncMock(return_value=['Первая.', 'Вторая.', 'Третья.'])
            for matching, grammar in [(True, 'auto'), (True, 'off'), (False, 'auto'), (False, 'off')]:
                with self.subTest(matching=matching, grammar=grammar):
                    pipeline.speaker_classifier = SimpleNamespace(classify=Mock(side_effect=['female', 'male', 'unknown']))
                    pipeline.translate = AsyncMock(return_value='Первая. Вторая. Третья.')
                    pipeline.synthesize = AsyncMock(return_value=wav_bytes(b'\xff\x1f' * RATE))
                    session = Session('assigned', voice='alexandr', speaker_gender=grammar,
                        match_voice=matching, female_voice='alfia', male_voice='eduard')
                    with patch('synchro.pipeline.fit_wav', new=AsyncMock(side_effect=lambda data, seconds: data)):
                        await pipeline.process(session, b'\0\1' * 8 * RATE, 0, False)
                    expected = ['alfia', 'eduard', 'alexandr'] if matching else ['alexandr'] * 3
                    self.assertEqual([call.args[1] for call in pipeline.synthesize.await_args_list], expected)
                    self.assertEqual('speakers' in pipeline.translate.await_args.kwargs, grammar == 'auto')
                    self.assertEqual(pipeline.speaker_classifier.classify.call_count, 3 if matching or grammar == 'auto' else 0)
        finally:
            await pipeline.client.aclose()

    async def test_voice_assignment_validation_and_session_mapping(self):
        import os
        os.environ.setdefault('SYNCHRO_TOKEN', 'unit-test-owner-token-00000000000000')
        os.environ.setdefault('SYNCHRO_ORIGIN', 'chrome-extension://' + 'a' * 32)
        from synchro import app as api
        for invalid in [{'female_voice':'roman'}, {'male_voice':'alfia'}, {'male_voice':'unknown'}]:
            with self.assertRaises(ValueError):
                api.SessionRequest(**invalid)
        request = api.SessionRequest(match_voice=True, female_voice='alfia', male_voice='eduard')
        current = await api.reserve('voice-assignment-test', request.voice, request.translation,
            request.language, request.speaker_gender, request.match_voice, request.female_voice, request.male_voice)
        try:
            self.assertEqual((current.female_voice, current.male_voice), ('alfia', 'eduard'))
        finally:
            await api.discard(current)

    async def test_failed_connection_check_keeps_confirmed_cost(self):
        import os
        from synchro.usage import record_usage
        os.environ.setdefault('SYNCHRO_TOKEN', 'unit-test-owner-token-00000000000000')
        os.environ.setdefault('SYNCHRO_ORIGIN', 'chrome-extension://' + 'a' * 32)
        from synchro import app as api
        async def fail(*args):
            record_usage('translation', {'cost': .0012})
            raise ValueError('Expected test failure after translation')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test') as client:
            with patch.object(api.pipeline, 'warmup', new=fail):
                response = await client.post('/api/pipeline/check', headers={'Authorization':'Bearer ' + api.TOKEN}, json={})
        self.assertEqual(response.status_code, 502)
        self.assertAlmostEqual(response.json()['cloud_usage']['reported_cost_usd'], .0012)

    async def test_interrupted_provider_request_is_marked_as_unpriced(self):
        import asyncio
        from synchro.cloud import complete
        async def reply(request):
            await asyncio.sleep(10)
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            usage = {}
            with collect_usage(usage):
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(complete(client,
                        TranslationSettings(provider='kilo', api_key='private-test-key-123'), []), .01)
            self.assertEqual(usage_summary(usage)['unpriced_requests'], 1)

    async def test_each_phrase_supplies_grammar_cues_and_uses_a_matching_voice(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        try:
            pipeline.speaker_classifier = SimpleNamespace(classify=Mock(side_effect=['female', 'male']))
            pipeline.recognize = AsyncMock(return_value={'words': [
                {'word': ' I was ready.', 'start': .1, 'end': 2.5},
                {'word': ' I was ready.', 'start': 4, 'end': 6}]})
            pipeline.translate = AsyncMock(return_value='Я была готова. Я был готов.')
            pipeline.align_phrases = AsyncMock(return_value=['Я была готова.', 'Я был готов.'])
            pipeline.synthesize = AsyncMock(return_value=wav_bytes(b'\xff\x1f' * RATE))
            session = Session('speakers', voice='alfia', speaker_gender='auto', match_voice=True)
            with patch('synchro.pipeline.fit_wav', new=AsyncMock(side_effect=lambda data, seconds: data)):
                result = await pipeline.process(session, b'\0\1' * 8 * RATE, 0, False)
            self.assertEqual([cue['speaker_gender'] for cue in result['segments']], ['female', 'male'])
            self.assertEqual([call.args[1] for call in pipeline.synthesize.await_args_list], ['alfia', 'roman'])
            self.assertEqual([hint['gender'] for hint in pipeline.translate.await_args.kwargs['speakers']], ['female', 'male'])
            self.assertEqual(pipeline.speaker_classifier.classify.call_count, 2)
        finally:
            await pipeline.client.aclose()

    async def test_manual_grammar_and_uncertain_voice_keep_the_selected_voice(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        try:
            pipeline.speaker_classifier = SimpleNamespace(classify=Mock(return_value='unknown'))
            phrases = [{'start': 0, 'end': 2, 'source': 'I was ready.'}]
            session = Session('manual', speaker_gender='female')
            hints = await pipeline.speaker_hints(session, b'\0\1' * 2 * RATE, phrases)
            self.assertEqual(hints[0]['gender'], 'female')
            pipeline.speaker_classifier.classify.assert_not_called()
            session.speaker_gender = 'auto'
            self.assertIsNone(await pipeline.speaker_hints(session, b'\0\1' * 2 * RATE, phrases))
            self.assertEqual(phrases[0]['speaker_gender'], 'unknown')
        finally:
            await pipeline.client.aclose()

    async def test_instruction_models_receive_first_person_grammar_context(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        try:
            pipeline.completion = AsyncMock(return_value='{"translation":"Я была готова."}')
            hints = [{'source': 'I was ready.', 'gender': 'female'}]
            translated = await pipeline.translate('I was ready.', [], 3, speakers=hints)
            self.assertEqual(translated, 'Я была готова.')
            messages = pipeline.completion.await_args.args[0]
            self.assertIn('third-person', messages[0]['content'])
            self.assertEqual(json.loads(messages[1]['content'])['speakers'], hints)
        finally:
            await pipeline.client.aclose()

    async def test_hymt_grammar_revision_is_billed_as_a_separate_stage(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        await pipeline.client.aclose()
        def reply(request):
            return httpx.Response(200, json={'choices': [{'message': {'content': 'Я был готов.'}, 'finish_reason': 'stop'}],
                                            'usage': {'cost': .001}})
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        try:
            async def completion(messages, translation, stage):
                from synchro.usage import record_usage
                record_usage(stage, {'cost': .002})
                self.assertEqual(stage, 'speaker_grammar')
                return '{"translation":"Я была готова."}'
            pipeline.completion = completion
            usage = {}
            with collect_usage(usage):
                result = await pipeline.translate('I was ready.', [], 3,
                    translation=TranslationSettings(provider='kilo', api_key='private-test-key-123'),
                    speakers=[{'source': 'I was ready.', 'gender': 'female'}])
            self.assertEqual(result, 'Я была готова.')
            self.assertAlmostEqual(usage_summary(usage)['reported_cost_usd'], .003)
            self.assertEqual(set(usage), {'translation', 'speaker_grammar'})
        finally:
            await pipeline.client.aclose()
