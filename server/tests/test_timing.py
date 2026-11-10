import base64
import json
import unittest
from unittest.mock import AsyncMock, patch

from synchro.cloud import TranslationSettings
from synchro.pipeline import Pipeline, Session, RATE, trim_wav, wav_bytes, wav_info
from synchro.timing import source_phrases, split_translation


class TimingTests(unittest.IsolatedAsyncioTestCase):
    def test_source_pauses_and_last_word_end_are_preserved(self):
        words = [{'word': ' Hello.', 'start': .4, 'end': 1.8},
                 {'word': ' Welcome', 'start': 3, 'end': 3.5}, {'word': ' back.', 'start': 3.6, 'end': 4.2}]
        phrases = source_phrases(words, 20)
        self.assertEqual([p['start'] for p in phrases], [.4, 3])
        self.assertAlmostEqual(phrases[0]['end'], 1.88)
        self.assertAlmostEqual(phrases[1]['end'], 4.28)
        text = 'Привет. Добро пожаловать обратно.'
        self.assertEqual(split_translation(text, [1, 4], 2), ['Привет.', 'Добро пожаловать обратно.'])
        self.assertEqual(split_translation(text, [0, 4], 2), ['', text])
        for ends in [[1, 3], [-1, 4], [2, 2], [True, 4], [4], [1, 5]]:
            with self.assertRaises(ValueError):
                split_translation(text, ends, 2)

    def test_outer_tts_padding_is_removed_without_cutting_internal_pauses(self):
        original = wav_bytes(b'\0\0' * RATE + b'\xff\x1f' * RATE + b'\0\0' * RATE + b'\xff\x1f' * RATE + b'\0\0' * RATE)
        self.assertAlmostEqual(wav_info(trim_wav(original))[1], 3.1)
        silence = wav_bytes(b'\0\0' * RATE)
        self.assertEqual(trim_wav(silence), silence)

    async def test_word_straddling_chunk_boundary_is_recognized_once_with_left_context(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        try:
            pipeline.recognize = AsyncMock(side_effect=[
                {'words': [{'word': ' First', 'start': .2, 'end': .6}, {'word': ' boundary', 'start': 6.8, 'end': 7.6}]},
                {'words': [{'word': ' boundary', 'start': .8, 'end': 1.6}, {'word': ' next', 'start': 1.9, 'end': 2.6}]}])
            pipeline.translate = AsyncMock(return_value='Все слова.')
            pipeline.synthesize = AsyncMock(return_value=wav_bytes(b'\xff\x1f' * RATE))
            pipeline.align_phrases = AsyncMock(return_value=None)
            session = Session('boundary')
            with patch('synchro.pipeline.fit_wav', new=AsyncMock(side_effect=lambda data, seconds: data)):
                first = await pipeline.process(session, b'\0\1' * 8 * RATE, 0, False)
                second = await pipeline.process(session, b'\0\2' * 8 * RATE, 7 * RATE, False)
            self.assertEqual(first['segments'][0]['source'], 'First')
            self.assertEqual(second['segments'][0]['source'], 'boundary next')
            self.assertAlmostEqual(second['segments'][0]['start'], 6.8)
            self.assertEqual(pipeline.recognize.await_args_list[1].args[0], b'\0\1' * RATE + b'\0\2' * 8 * RATE)
            self.assertLessEqual(first['segments'][0]['start'] + first['segments'][0]['source_duration'], second['segments'][0]['start'])
        finally:
            await pipeline.client.aclose()

    async def test_two_phrases_share_one_translation_and_commit_only_after_all_speech(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        try:
            pipeline.recognize = AsyncMock(return_value={'words': [
                {'word': ' Hello.', 'start': .3, 'end': 2}, {'word': ' Welcome.', 'start': 4, 'end': 6}]})
            pipeline.translate = AsyncMock(return_value='Привет. Добро пожаловать.')
            pipeline.completion = AsyncMock(return_value=json.dumps({'ends': [1, 3]}))
            pipeline.synthesize = AsyncMock(side_effect=[wav_bytes(b'\xff\x1f' * RATE), ValueError('TTS failed')])
            session = Session('atomic')
            with patch('synchro.pipeline.fit_wav', new=AsyncMock(side_effect=lambda data, seconds: data)):
                with self.assertRaisesRegex(ValueError, 'TTS failed'):
                    await pipeline.process(session, b'\0\1' * 8 * RATE, 0, False)
                self.assertEqual((session.offset, session.sequence, session.history, session.asr_tail, session.speech_end), (0, 0, [], b'', 0))
                pipeline.synthesize.side_effect = None
                pipeline.synthesize.return_value = wav_bytes(b'\xff\x1f' * RATE)
                result = await pipeline.process(session, b'\0\1' * 8 * RATE, 0, False)
            self.assertEqual([c['text'] for c in result['segments']], ['Привет.', 'Добро пожаловать.'])
            self.assertEqual([c['start'] for c in result['segments']], [.3, 4])
            self.assertAlmostEqual(result['segments'][-1]['source_duration'], 2.08)
            self.assertEqual([c['id'] for c in result['segments']], [1, 2])
            self.assertEqual(pipeline.translate.await_count, 2, 'one complete-context translation per attempt')
            pipeline.completion.return_value = '{"ends":[1,2]}'
            self.assertIsNone(await pipeline.align_phrases([{}, {}], 'Все три слова', TranslationSettings()))
        finally:
            await pipeline.client.aclose()

    async def test_condensed_neighboring_phrases_merge_without_discarding_words(self):
        pipeline = Pipeline('http://speech', 'http://llm')
        try:
            pipeline.recognize = AsyncMock(return_value={'words': [
                {'word': ' Right?', 'start': .3, 'end': 1}, {'word': ' Correct.', 'start': 2, 'end': 2.4},
                {'word': ' Welcome.', 'start': 4, 'end': 6}]})
            pipeline.translate = AsyncMock(return_value='Верно. Добро пожаловать.')
            pipeline.completion = AsyncMock(return_value='{"ends":[1,1,3]}')
            pipeline.synthesize = AsyncMock(return_value=wav_bytes(b'\xff\x1f' * RATE))
            with patch('synchro.pipeline.fit_wav', new=AsyncMock(side_effect=lambda data, seconds: data)):
                result = await pipeline.process(Session('condensed'), b'\0\1' * 8 * RATE, 0, False)
            self.assertEqual([c['text'] for c in result['segments']], ['Верно.', 'Добро пожаловать.'])
            self.assertEqual(result['segments'][0]['source'], 'Right? Correct.')
            self.assertAlmostEqual(result['segments'][0]['source_duration'], 2.18)
            self.assertEqual(result['segments'][1]['start'], 4)
        finally:
            await pipeline.client.aclose()
