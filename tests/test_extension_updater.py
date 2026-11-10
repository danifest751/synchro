import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('updater', Path(__file__).resolve().parents[1] / 'tools/update_extension.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class UpdaterTests(unittest.TestCase):
    def archive(self, entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, value in entries.items():
                archive.writestr(name, value)
        return output.getvalue()

    def test_release_preserves_private_endpoints_identity_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'extension'
            target.mkdir()
            old = {'name': 'Synchro', 'version': '1.0', 'permissions': ['storage'], 'key': 'installed-public-key', 'host_permissions': ['https://own.example/*'], 'content_security_policy': {'extension_pages': "script-src 'self'; connect-src 'self' https://own.example"}}
            (target / 'manifest.json').write_text(json.dumps(old))
            (target / 'connection.mjs').write_text("export const PUBLIC_API = 'https://own.example';\nexport const LOCAL_API = 'http://127.0.0.1:8768';")
            entries = {'extension/manifest.json': json.dumps({**old, 'version': '1.1', 'key': 'other-key', 'host_permissions': ['http://127.0.0.1:8778/*']}),
                       'extension/connection.mjs': "export const PUBLIC_API = 'https://placeholder.example';\nexport const LOCAL_API = 'http://127.0.0.1:8768';", 'extension/background.js': 'new code'}
            backup = updater.install(self.archive(entries), target, '1.1')
            self.assertEqual(json.loads((backup / 'manifest.json').read_text())['version'], '1.0')
            installed = json.loads((target / 'manifest.json').read_text())
            self.assertEqual(installed['key'], old['key'])
            self.assertEqual(installed['host_permissions'], old['host_permissions'] + ['http://127.0.0.1:8778/*'])
            self.assertIn('http://127.0.0.1:8778', installed['content_security_policy']['extension_pages'])
            self.assertIn('https://own.example', (target / 'connection.mjs').read_text())
            for malicious in ['../outside.js', 'extension/../../outside.js', 'extension/evil.exe']:
                with self.assertRaises(ValueError):
                    updater.install(self.archive({**entries, malicious: 'bad'}), target, '1.1')
