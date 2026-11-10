import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

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

    async def test_voice_catalog_is_authenticated_and_contains_no_private_profiles(self):
        from synchro.voices import StudioVoices, STUDIO_VOICES
        with patch.dict(os.environ, {'SYNCHRO_VOICESTUDIO_URL': 'http://private-studio',
            'SYNCHRO_VOICESTUDIO_TOKEN': 'private-studio-key',
            'SYNCHRO_VOICESTUDIO_VOICES': json.dumps({key: 'private-profile-' + str(index) for index, key in enumerate(STUDIO_VOICES)})}):
            studio = StudioVoices()
        with patch.object(api.pipeline, 'studio', studio):
            anonymous = await self.client.get('/api/voices?mode=cloud_translation')
            self.assertEqual(anonymous.status_code, 401)
            response = await self.client.get('/api/voices?mode=cloud_translation', headers=self.headers('alice'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()['voices']), 9)
            self.assertNotIn('private', response.text)

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

    async def test_cloud_configuration_is_per_session_and_cleared_on_delete(self):
        first = {'provider': 'kilo', 'api_key': 'alice-private-cloud-key-123'}
        second = {'provider': 'openrouter', 'api_key': 'bob-private-cloud-key-123'}
        with patch.object(api.pipeline, 'warmup', new=AsyncMock()) as warmup:
            alice = await self.client.post('/api/session', headers=self.headers('alice'), json={'voice': 'female', 'translation': first})
            bob = await self.client.post('/api/session', headers=self.headers('bob'), json={'voice': 'male', 'translation': second})
        self.assertEqual(alice.status_code, 200, alice.text)
        self.assertEqual(bob.status_code, 200, bob.text)
        current = api.sessions[alice.json()['session_id']]
        self.assertEqual(current.translation.provider, 'kilo')
        self.assertEqual(api.sessions[bob.json()['session_id']].translation.provider, 'openrouter')
        self.assertEqual(warmup.await_args_list[0].args[1].api_key.get_secret_value(), first['api_key'])
        self.assertNotIn(first['api_key'], alice.text)
        await self.client.delete('/api/session/' + current.id, headers=self.headers('alice'))
        self.assertEqual(current.translation.api_key.get_secret_value(), '')

    async def test_invalid_cloud_config_never_echoes_the_key(self):
        secret = 'private-api-key-must-not-appear'
        response = await self.client.post('/api/translation/check', headers=self.headers('alice'),
            json={'provider': 'unknown', 'api_key': secret})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)

    async def test_legacy_capture_request_still_uses_local_translation(self):
        with patch.object(api.pipeline, 'warmup', new=AsyncMock()):
            response = await self.client.post('/api/session?voice=male', headers=self.headers('alice'))
        self.assertEqual(response.status_code, 200)
        current = api.sessions[response.json()['session_id']]
        self.assertEqual(current.voice, 'male')
        self.assertEqual(current.translation.provider, 'local')

    async def test_account_metadata_still_requires_synchro_authentication(self):
        for path in ['models','balance']:
            body={'provider':'kilo'}
            if path=='balance': body['api_key']='private-provider-key-123'
            response=await self.client.post('/api/translation/'+path,json=body)
            self.assertEqual(response.status_code,401)
            wrong=self.headers('alice')
            wrong['Origin']='https://untrusted.example'
            response=await self.client.post('/api/translation/'+path,json=body,headers=wrong)
            self.assertEqual(response.status_code,403)

    async def test_video_deadline_releases_lock_and_keeps_frontier(self):
        from types import SimpleNamespace
        current = await api.reserve('alice', 'female')
        current.audio = SimpleNamespace(step=160000, next=AsyncMock(return_value=(b'pcm', False)), close=AsyncMock())
        with patch.object(api.pipeline, 'process', new=AsyncMock(side_effect=TimeoutError)):
            response = await self.client.post('/api/video/' + current.id + '/next', headers=self.headers('alice'))
        self.assertEqual(response.status_code, 504)
        self.assertTrue(current.failed)
        self.assertFalse(current.lock.locked())
        self.assertEqual(current.offset, 0)
        deleted = await self.client.delete('/api/session/' + current.id, headers=self.headers('alice'))
        self.assertEqual(deleted.status_code, 204)
