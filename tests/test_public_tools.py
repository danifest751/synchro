"""Verify private setup, key lifecycle, and safe ZIP contents in an isolated copy."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PublicToolsTests(unittest.TestCase):
    def test_private_configuration_and_guest_archive_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ['tools', 'extension', 'docs']:
                shutil.copytree(ROOT / folder, root / folder)
            for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
                shutil.copyfile(ROOT / name, root / name)

            def run(script, *args, success=True):
                result = subprocess.run([sys.executable, str(root / 'tools' / script), *args], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                return result

            run('init_config.py', '--server-url', 'http://untrusted.example', success=False)
            run('init_config.py')
            owner_file = root / '.local/connection.json'
            owner = json.loads(owner_file.read_text())
            self.assertGreaterEqual(len(owner['token']), 32)
            run('init_config.py', success=False)
            self.assertEqual(json.loads(owner_file.read_text()), owner)
            run('client_keys.py', 'add', '../escape', success=False)
            result = run('client_keys.py', 'add', 'guest-1')
            guest = json.loads((root / '.local/connections/guest-1/connection.json').read_text())
            self.assertNotIn(guest['token'], result.stdout)
            self.assertNotEqual(guest['token'], owner['token'])
            self.assertEqual(guest['server_url'], owner['server_url'])
            registry = json.loads((root / '.local/clients/tokens.json').read_text())
            self.assertNotIn(guest['token'], json.dumps(registry))
            run('package.py')
            run('package.py', '--client', 'guest-1')
            for name, personal in [('Synchro-extension.zip', False), ('Synchro-guest-1.zip', True)]:
                with zipfile.ZipFile(root / 'output' / name) as zipped:
                    self.assertEqual('connection.json' in zipped.namelist(), personal)
                    self.assertIn('LICENSE', zipped.namelist())
                    for member in zipped.namelist():
                        self.assertNotIn(owner['token'].encode(), zipped.read(member))
                        if not personal:
                            self.assertNotIn(guest['token'].encode(), zipped.read(member))
            run('client_keys.py', 'revoke', 'guest-1')
            run('package.py', '--client', 'guest-1', success=False)


if __name__ == '__main__':
    unittest.main()
