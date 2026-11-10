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
                    self.assertEqual(body['max_completion_tokens' if provider == 'openai' else 'max_tokens'], 512)
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

    async def test_hymt_prepares_unsafe_speech_with_the_same_cloud_provider(self):
        settings = TranslationSettings(provider='kilo', api_key='private-test-api-key-123')
        seen = []
        def respond(request):
            body = json.loads(request.content)
            seen.append(str(request.url))
            self.assertEqual(request.url.host, 'ai-gateway.kilo.ai')
            self.assertEqual(request.headers['Authorization'], 'Bearer private-test-api-key-123')
            if body['model'] == settings.model:
                self.assertNotIn('response_format', body)
                self.assertEqual(len(body['messages']), 1)
                self.assertNotIn('current_text', body['messages'][0]['content'])
                text = 'ChatGPT за 80 лет.'
            else:
                self.assertEqual(body['model'], 'google/gemma-4-26b-a4b-it')
                self.assertIn('response_format', body)
                text = json.dumps({'translation': 'Чат джипити за восемьдесят лет.'})
            return httpx.Response(200, json={'choices': [{'message': {'content': text}}]})
        pipeline = Pipeline('http://speech', 'http://local', api='llama', silero_url='http://silero')
        await pipeline.client.aclose()
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            result = await pipeline.translate('ChatGPT in 80 years.', [], 4, translation=settings)
            self.assertEqual(result, 'Чат джипити за восемьдесят лет.')
            self.assertEqual(seen, [PROVIDERS['kilo'][1], PROVIDERS['kilo'][1]])
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
                self.assertEqual(request.headers['Connection'], 'close')
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

    async def test_transient_failures_retry_without_retranscribing_or_changing_provider(self):
        settings = TranslationSettings(provider='kilo', api_key='private-test-api-key-123')
        failures = [httpx.RemoteProtocolError('private-test-api-key-123'),
                    httpx.Response(503), httpx.Response(200, json={'choices': [{'message': {'content': None}}]}),
                    httpx.Response(200, json={'error': 'private-test-api-key-123'})]
        for failure in failures:
            calls = []
            def respond(request):
                calls.append(request)
                if len(calls) == 1:
                    if isinstance(failure, Exception):
                        raise failure
                    return failure
                return httpx.Response(200, json={'choices': [{'message': {'content': 'Готово'}, 'finish_reason': 'stop'}]})
            with patch('synchro.cloud.asyncio.sleep', new=AsyncMock()):
                async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                    self.assertEqual(await complete(client, settings, []), 'Готово')
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0].url, calls[1].url)

    async def test_output_limit_retries_with_more_tokens_and_logs_no_private_content(self):
        settings = TranslationSettings(provider='kilo', api_key='private-test-api-key-123')
        budgets = []
        def respond(request):
            budgets.append(json.loads(request.content)['max_tokens'])
            return httpx.Response(200, json={'choices': [{'message': {'content': '', 'reasoning': 'private-reasoning'}, 'finish_reason': 'length'}],
                'usage': {'completion_tokens': 512, 'completion_tokens_details': {'reasoning_tokens': 512}}})
        with self.assertLogs('uvicorn.error', level='INFO') as logs, patch('synchro.cloud.asyncio.sleep', new=AsyncMock()):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with self.assertRaisesRegex(ValueError, 'output token limit.*Reference:'):
                    await complete(client, settings, [{'role': 'user', 'content': 'private-transcript'}])
        self.assertEqual(budgets, [512, 1024])
        logged = '\n'.join(logs.output)
        self.assertIn('outcome=output_limit', logged)
        self.assertIn('reasoning_tokens=512', logged)
        for private in ['private-test-api-key-123', 'private-reasoning', 'private-transcript']:
            self.assertNotIn(private, logged)

    async def test_permanent_errors_and_content_filter_are_not_retried(self):
        settings = TranslationSettings(provider='kilo', api_key='private-test-api-key-123')
        for response in [httpx.Response(status) for status in [400, 401, 402, 403, 429]] + [
            httpx.Response(200, json={'choices': [{'message': {'content': ''}, 'finish_reason': 'content_filter'}]})]:
            respond = AsyncMock(return_value=response)
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with self.assertRaises(ValueError):
                    await complete(client, settings, [])
            self.assertEqual(respond.await_count, 1)
