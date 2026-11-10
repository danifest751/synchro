import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import httpx

os.environ.setdefault('SYNCHRO_TOKEN', 'unit-test-owner-token-00000000000000')
os.environ.setdefault('SYNCHRO_ORIGIN', 'chrome-extension://' + 'a' * 32)
from synchro import app as api


class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.tokens = Path(self.directory.name) / 'tokens.json'
        self.keys = {name: name + '-test-token-00000000000000000000' for name in ['alice', 'bob', 'carol']}
        self.tokens.write_text(json.dumps({name: {'token_sha256': hashlib.sha256(value.encode()).hexdigest()}
                                          for name, value in self.keys.items()}))
        self.previous_file = api.CLIENTS_FILE
        api.CLIENTS_FILE = str(self.tokens)
        api.sessions.clear()
        api.requests.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        api.sessions.clear()
        api.requests.clear()
        api.CLIENTS_FILE = self.previous_file
        self.directory.cleanup()

    def headers(self, name):
        return {'Authorization': 'Bearer ' + self.keys[name], 'Origin': api.ORIGIN}

    async def test_clients_cannot_read_or_stop_each_others_sessions(self):
        alice = await api.reserve('alice', 'female')
        bob = await api.reserve('bob', 'male')
        self.assertNotEqual(alice.id, bob.id)
        wrong_read = await self.client.get('/api/video/' + alice.id, headers=self.headers('bob'))
        wrong_stop = await self.client.delete('/api/session/' + alice.id, headers=self.headers('bob'))
        self.assertEqual(wrong_read.status_code, 404)
        self.assertEqual(wrong_stop.status_code, 404)
        own_read = await self.client.get('/api/video/' + alice.id, headers=self.headers('alice'))
        self.assertEqual(own_read.status_code, 200)
        self.assertIn(bob.id, api.sessions)

    async def test_revocation_takes_effect_without_restarting(self):
        before = await self.client.get('/api/check', headers=self.headers('alice'))
        self.assertEqual(before.status_code, 200)
        clients = json.loads(self.tokens.read_text())
        clients['alice']['disabled'] = True
        self.tokens.write_text(json.dumps(clients))
        after = await self.client.get('/api/check', headers=self.headers('alice'))
        self.assertEqual(after.status_code, 401)

    async def test_capacity_is_shared_but_one_key_cannot_take_two_places(self):
        await api.reserve('alice', 'female')
        with self.assertRaises(api.HTTPException) as duplicate:
            await api.reserve('alice', 'male')
        self.assertEqual(duplicate.exception.status_code, 409)
        await api.reserve('bob', 'male')
        await api.reserve('carol', 'female')
        with self.assertRaises(api.HTTPException) as full:
            await api.reserve('owner', 'male')
        self.assertEqual(full.exception.status_code, 503)

    async def test_valid_key_does_not_authorize_another_web_origin(self):
        headers = self.headers('alice')
        headers['Origin'] = 'https://example.com'
        response = await self.client.get('/api/check', headers=headers)
        self.assertEqual(response.status_code, 403)
