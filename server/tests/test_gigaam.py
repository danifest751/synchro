import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('gigaam_server', Path(__file__).resolve().parents[2] / 'deploy/gigaam_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GigaamTests(unittest.TestCase):
    def test_ctc_characters_become_timed_words_without_filling_silence(self):
        words = module.word_timestamps(list('hi all'), [0.1, 0.2, 0.3, 2, 2.1, 2.2], 3)
        self.assertEqual([word['word'] for word in words], [' hi', ' all'])
        self.assertAlmostEqual(words[0]['end'], 0.24)
        self.assertEqual(words[1]['start'], 2)
        self.assertEqual(module.word_timestamps([], [], 1), [])

    def test_invalid_ctc_timestamps_are_rejected(self):
        for tokens, times in [('hi', [0.1]), ('hi', [0.2, 0.1]), ('a', [float('nan')]), ('a', [2])]:
            with self.subTest(times=times), self.assertRaises(ValueError):
                module.word_timestamps(tokens, times, 1)
