import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from synchro.cloud import PROVIDERS, TranslationSettings, complete
from synchro.pipeline import Pipeline


class CloudTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_endpoints_auth_and_json_contract(self):
        for provider, (_, endpoint, model) in PROVIDERS.items():
            with self.subTest(provider=provider):
                settings = TranslationSettings(provider=provider, model='test-model', api_key='private-test-api-key-123')
                def respond(request):
                    self.assertEqual(str(request.url), endpoint)
                    self.assertEqual(request.headers['Authorization'], 'Bearer private-test-api-key-123')
                    body = json.loads(request.content)
                    self.assertEqual(body['model'], 'test-model')
                    self.assertEqual(body['response_format']['type'], 'json_schema')
                    self.assertEqual(body['max_completion_tokens' if provider == 'openai' else 'max_tokens'], 256)
                    if provider == 'openai':
                        self.assertIs(body['store'], False)
                    return httpx.Response(200, json={'choices': [{'message': {'content': '{"translation":"Привет"}'}, 'finish_reason': 'stop'}]})
                pipeline = Pipeline('http://speech', 'http://local', api='llama')
                await pipeline.client.aclose()
                pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                try:
                    self.assertEqual(await pipeline.translate('Hello', [], 3, translation=settings), 'Привет')
                finally:
                    await pipeline.client.aclose()

    async def test_hymt_uses_plain_text_and_prepares_only_unsafe_speech_locally(self):
        settings = TranslationSettings(provider='kilo', api_key='private-test-api-key-123')
        seen = []
        def respond(request):
            body = json.loads(request.content)
            seen.append(str(request.url))
            if request.url.host == 'ai-gateway.kilo.ai':
                self.assertNotIn('response_format', body)
                self.assertEqual(len(body['messages']), 1)
                self.assertNotIn('current_text', body['messages'][0]['content'])
                text = 'ChatGPT за 80 лет.'
            else:
                self.assertNotIn('Authorization', request.headers)
                text = json.dumps({'translation': 'Чат джипити за восемьдесят лет.'})
            return httpx.Response(200, json={'choices': [{'message': {'content': text}}]})
        pipeline = Pipeline('http://speech', 'http://local', api='llama', silero_url='http://silero')
        await pipeline.client.aclose()
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            result = await pipeline.translate('ChatGPT in 80 years.', [], 4, translation=settings)
            self.assertEqual(result, 'Чат джипити за восемьдесят лет.')
            self.assertEqual(seen, [PROVIDERS['kilo'][1], 'http://local/v1/chat/completions'])
        finally:
            await pipeline.client.aclose()

    async def test_errors_never_echo_provider_secrets_or_error_bodies(self):
        key = 'private-test-api-key-123'
        settings = TranslationSettings(provider='kilo', api_key=key)
        for status in [400, 401, 402, 429, 500]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, json={'error': key}))) as client:
                with self.assertRaises(ValueError) as error:
                    await complete(client, settings, [])
                self.assertNotIn(key, str(error.exception))
                self.assertIn(str(status), str(error.exception))
        for payload in [{}, {'choices': []}, {'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}]}]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
                with self.assertRaises(ValueError):
                    await complete(client, settings, [])
        self.assertNotIn(key, repr(settings))

    async def test_existing_ssh_tunnels_preserve_host_and_tls_verification_name(self):
        for provider, port in [('kilo', 8443), ('openrouter', 8444), ('openai', 8445)]:
            settings = TranslationSettings(provider=provider, api_key='private-test-api-key-123')
            def respond(request):
                from urllib.parse import urlsplit
                target = urlsplit(PROVIDERS[provider][1])
                self.assertEqual(str(request.url), f'https://127.0.0.1:{port}{target.path}')
                self.assertEqual(request.headers['Host'], target.hostname)
                self.assertEqual(request.extensions['sni_hostname'], target.hostname)
                return httpx.Response(200, json={'choices': [{'message': {'content': 'translation'}}]})
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                self.assertEqual(await complete(client, settings, [], tunnel_port=port), 'translation')

    def test_invalid_endpoints_and_keys_are_rejected(self):
        for data in [{'provider': 'https://evil.example', 'api_key': 'private-test-api-key-123'},
                     {'provider': 'kilo', 'model': 'https://evil.example', 'api_key': 'private-test-api-key-123'},
                     {'provider': 'openai', 'api_key': 'short'}, {'provider': 'kilo', 'api_key': 'private-test-api-key\nheader'}]:
            with self.assertRaises(ValueError):
                TranslationSettings(**data)
        self.assertEqual(TranslationSettings(api_key='should-be-discarded').api_key.get_secret_value(), '')
