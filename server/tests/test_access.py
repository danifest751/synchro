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
        api.warm.clear()
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
        first = await api.reserve('alice', 'female')
        second = await api.reserve('alice', 'male')
        self.assertEqual(list(api.sessions), [second.id])
        self.assertTrue(first.closed)
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
        result = {'session_id': current.id, 'ready_until': 10, 'finished': False, 'segments': []}
        with patch.object(api.pipeline, 'process', new=AsyncMock(side_effect=[TimeoutError, result])) as process:
            response = await self.client.post('/api/video/' + current.id + '/next', headers=self.headers('alice'))
            self.assertEqual(response.status_code, 504)
            self.assertFalse(current.lock.locked())
            self.assertEqual(current.offset, 0)
            self.assertEqual(current.pending, (b'pcm', False, 160000))
            retry = await self.client.post('/api/video/' + current.id + '/next', headers=self.headers('alice'))
        self.assertEqual(retry.status_code, 200, retry.text)
        # The retry repeats the same audio instead of reading past it.
        current.audio.next.assert_awaited_once()
        self.assertEqual(process.await_args_list[1].args[1:], (b'pcm', 0, False))
        self.assertIsNone(current.pending)
        deleted = await self.client.delete('/api/session/' + current.id, headers=self.headers('alice'))
        self.assertEqual(deleted.status_code, 204)

    async def test_lost_window_response_is_sent_again(self):
        from types import SimpleNamespace
        current = await api.reserve('alice', 'female')
        current.audio = SimpleNamespace(step=160000, next=AsyncMock(return_value=(b'pcm', False)), close=AsyncMock())

        async def process(session, *args, **kwargs):
            session.offset += 160000
            return {'session_id': session.id, 'ready_until': session.offset / 16000, 'finished': False, 'segments': []}

        with patch.object(api.pipeline, 'process', new=AsyncMock(side_effect=process)) as mocked:
            first = await self.client.post('/api/video/' + current.id + '/next?ready=0', headers=self.headers('alice'))
            again = await self.client.post('/api/video/' + current.id + '/next?ready=0', headers=self.headers('alice'))
            following = await self.client.post('/api/video/' + current.id + '/next?ready=10', headers=self.headers('alice'))
        self.assertEqual(again.json(), first.json())
        self.assertEqual(following.json()['ready_until'], 20)
        self.assertEqual(mocked.await_count, 2)
        self.assertEqual(current.audio.next.await_count, 2)

    async def test_closing_cancels_a_window_in_progress(self):
        import asyncio
        from types import SimpleNamespace
        current = await api.reserve('alice', 'female')
        current.audio = SimpleNamespace(step=160000, next=AsyncMock(return_value=(b'pcm', False)), close=AsyncMock())
        started = asyncio.Event()

        async def stalled(*args, **kwargs):
            started.set()
            await asyncio.sleep(3600)

        with patch.object(api.pipeline, 'process', new=stalled):
            window = asyncio.create_task(self.client.post('/api/video/' + current.id + '/next', headers=self.headers('alice')))
            await started.wait()
            deleted = await asyncio.wait_for(self.client.delete('/api/session/' + current.id, headers=self.headers('alice')), 2)
            response = await asyncio.wait_for(window, 2)
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(current.id, api.sessions)

    async def test_recent_warmup_is_reused_by_the_next_session(self):
        with patch.object(api.pipeline, 'warmup', new=AsyncMock()) as warmup:
            for _ in range(2):
                response = await self.client.post('/api/session', headers=self.headers('alice'), json={'voice': 'roman'})
                self.assertEqual(response.status_code, 200, response.text)
            await self.client.post('/api/session', headers=self.headers('alice'), json={'voice': 'albina'})
        self.assertEqual([call.args[0] for call in warmup.await_args_list], ['roman', 'albina'])
