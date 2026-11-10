import importlib.util
from pathlib import Path
import unittest
from http.client import HTTPConnection
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('gigaam_server', Path(__file__).resolve().parents[2] / 'deploy/gigaam_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GigaamTests(unittest.TestCase):
    def test_larger_youtube_windows_are_accepted_by_the_worker(self):
        with module.Server(('127.0.0.1', 0), module.Handler) as server:
            server.authorization = b'Bearer test-worker-key'
            server.model = SimpleNamespace(recognize=lambda *args, **kwargs: SimpleNamespace(text='Hello', tokens=list('hello'), timestamps=[.1, .2, .3, .4, .5]))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                with patch.dict('sys.modules', {'numpy': MagicMock()}):
                    client.request('POST', '/transcribe', body=b'\0\0' * 21 * 16000, headers={'Authorization': 'Bearer test-worker-key'})
                    response = client.getresponse()
                    response_body = response.read()
                self.assertEqual(response.status, 200, response_body)
                client.close()
            finally:
                server.shutdown()
                thread.join()

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
