import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx

os.environ.setdefault('SYNCHRO_TOKEN', 'unit-test-owner-token-00000000000000')
os.environ.setdefault('SYNCHRO_ORIGIN', 'chrome-extension://' + 'a' * 32)

from synchro.cloud import TranslationSettings, complete
from synchro.youtube import YoutubeAudio


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_files_are_closed_to_the_shared_gateway(self):
        from synchro import app as api
        self.assertFalse(api.DESKTOP)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test') as client:
            response = await client.post('/api/file', headers={'Authorization': 'Bearer ' + api.TOKEN}, json={'path': 'C:/Windows/win.ini'})
        self.assertEqual(response.status_code, 404)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg must be installed')
    async def test_local_file_is_read_in_windows_from_a_position(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'clip with spaces.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=40', '-ac', '2', '-ar', '44100',
                            '-c:a', 'aac', str(path)], check=True)
            audio = await YoutubeAudio.open_file(str(path), 5)
            try:
                self.assertAlmostEqual(audio.duration, 40, delta=.2)
                first, final = await audio.next()
                self.assertEqual((len(first) / 32000, final), (11, False))
                windows = []
                while not final:
                    pcm, final = await audio.next()
                    windows.append(len(pcm) / 32000)
                # 35 s from position 5: 10 s committed first, then 20 s steps; the final window commits all it has.
                self.assertEqual(windows[0], 21)
                self.assertAlmostEqual(10 + 20 * (len(windows) - 1) + windows[-1], 35, delta=.2)
            finally:
                await audio.close()
            with self.assertRaisesRegex(ValueError, 'not found'):
                await YoutubeAudio.open_file(str(path) + '.missing', 0)
            with self.assertRaisesRegex(ValueError, 'beyond'):
                await YoutubeAudio.open_file(str(path), 50)

    async def test_custom_endpoint_is_desktop_only_and_keyless_capable(self):
        custom = {'provider': 'custom', 'base_url': 'http://127.0.0.1:1234/v1', 'model': 'qwen2.5:7b'}
        with self.assertRaises(ValueError):
            TranslationSettings(**custom)
        with self.assertRaises(ValueError):
            TranslationSettings(provider='kilo', api_key='private-test-api-key-123', base_url='http://example.com')
        with patch.dict(os.environ, {'SYNCHRO_DESKTOP': '1'}):
            settings = TranslationSettings(**custom)
            with self.assertRaises(ValueError):
                TranslationSettings(**{**custom, 'base_url': 'file:///etc/passwd'})
            with self.assertRaises(ValueError):
                TranslationSettings(**{**custom, 'mode': 'cloud_all'})
        seen = []

        def respond(request):
            seen.append((str(request.url), request.headers.get('authorization'), json.loads(request.content)['model']))
            return httpx.Response(200, json={'choices': [{'message': {'content': 'Привет'}, 'finish_reason': 'stop'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(await complete(client, settings, [{'role': 'user', 'content': 'Hi'}]), 'Привет')
        self.assertEqual(seen, [('http://127.0.0.1:1234/v1/chat/completions', None, 'qwen2.5:7b')])
