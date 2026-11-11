import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('silero_server', Path(__file__).resolve().parents[2] / 'deploy/silero_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SileroTests(unittest.TestCase):
    def test_russian_text_and_selected_speaker_are_preserved(self):
        self.assertEqual(module.speech_input({'text': 'Восемьдесят лет. Ёлка.', 'voice': 'ru_albina'}), ('Восемьдесят лет. Ёлка.', 'ru_albina'))
        self.assertEqual(module.speech_input({'text': 'Дв+а пл+юс тр+и.', 'voice': 'ru_roman'}), ('Дв+а пл+юс тр+и.', 'ru_roman'))

    def test_unsupported_names_and_numbers_cannot_disappear_silently(self):
        for body in [{'voice': 'other', 'text': 'Привет'}, {'voice': 'ru_albina', 'text': 'ChatGPT'},
                     {'voice': 'ru_eduard', 'text': '80 лет'}, {'voice': 'ru_eduard', 'text': ''}]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                module.speech_input(body)
