import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('silero_server', Path(__file__).resolve().parents[2] / 'deploy/silero_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SileroTests(unittest.TestCase):
    def test_russian_text_and_selected_speaker_are_preserved(self):
        self.assertEqual(module.speech_input({'text': 'Восемьдесят лет. Ёлка.', 'voice': 'xenia'}), ('Восемьдесят лет. Ёлка.', 'xenia'))
        self.assertEqual(module.speech_input({'text': 'Два + три.', 'voice': 'eugene'}), ('Два  плюс  три.', 'eugene'))

    def test_unsupported_names_and_numbers_cannot_disappear_silently(self):
        for body in [{'voice': 'other', 'text': 'Привет'}, {'voice': 'xenia', 'text': 'ChatGPT'},
                     {'voice': 'aidar', 'text': '80 лет'}, {'voice': 'aidar', 'text': ''}]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                module.speech_input(body)
