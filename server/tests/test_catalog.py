import asyncio
from types import SimpleNamespace
import unittest

import httpx

from synchro.catalog import ProviderCatalog, model_entry, price
from synchro.cloud import TranslationSettings


def model(model_id='tencent/hy-mt2-7b', **values):
    return {'id':model_id, 'name':'Translation model', 'architecture':{'input_modalities':['text'], 'output_modalities':['text']},
            'pricing':{'prompt':'0.000000074','completion':'0.000000295'}, **values}


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_catalog_uses_tunnel_without_viewer_key_and_is_cached(self):
        calls = []
        def respond(request):
            calls.append(request)
            self.assertEqual(str(request.url), 'https://127.0.0.1:8443/api/v1/models')
            self.assertEqual(request.headers['Host'], 'ai-gateway.kilo.ai')
            self.assertEqual(request.extensions['sni_hostname'], 'ai-gateway.kilo.ai')
            self.assertNotIn('Authorization',request.headers)
            return httpx.Response(200,json={'data':[model(),model('embedding',architecture={'input_modalities':['text'],'output_modalities':['embedding']})]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            catalog=ProviderCatalog(SimpleNamespace(client=client,cloud_client=None,cloud_tunnels={'kilo':8443}))
            first, second=await asyncio.gather(catalog.models('kilo'),catalog.models('kilo'))
            self.assertEqual(len(calls),1)
            self.assertEqual(first,second)
            self.assertEqual(len(first['models']),1)
            self.assertAlmostEqual(first['models'][0]['input_price'],.000000074)

    async def test_personal_balances_are_not_shared_or_cached_and_zero_is_valid(self):
        keys=['first-personal-api-key','second-personal-api-key']
        calls=[]
        def respond(request):
            calls.append(request)
            self.assertEqual(str(request.url),'https://127.0.0.1:8443/api/profile/balance')
            self.assertEqual(request.headers['Host'],'api.kilo.ai')
            return httpx.Response(200,json={'balance':0 if request.headers['Authorization'].endswith(keys[0]) else 12.3456})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            catalog=ProviderCatalog(SimpleNamespace(client=client,cloud_client=None,cloud_tunnels={'kilo':8443}))
            first,second=await asyncio.gather(*(catalog.balance(TranslationSettings(provider='kilo',api_key=key)) for key in keys))
            self.assertEqual(first['balance_usd'],0)
            self.assertEqual(second['balance_usd'],12.3456)
            self.assertEqual(catalog.cache,{})
            self.assertEqual(len(calls),2)
            self.assertNotIn(keys[0],str(first))

    async def test_missing_or_malformed_balance_is_never_assumed_zero(self):
        for payload in [{}, {'balance':None}, {'balance':'NaN'}, {'balance':True}]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload))) as client:
                catalog=ProviderCatalog(SimpleNamespace(client=client,cloud_client=None,cloud_tunnels={}))
                with self.assertRaises(ValueError):
                    await catalog.balance(TranslationSettings(provider='kilo',api_key='private-test-api-key-123'))

    async def test_openrouter_remaining_credit_and_provider_errors(self):
        settings=TranslationSettings(provider='openrouter',api_key='private-test-api-key-123')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':{'total_credits':20,'total_usage':3.25}}))) as client:
            catalog=ProviderCatalog(SimpleNamespace(client=client,cloud_client=None,cloud_tunnels={}))
            self.assertEqual((await catalog.balance(settings))['balance_usd'],16.75)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(401,json={'error':settings.api_key.get_secret_value()}))) as client:
            catalog=ProviderCatalog(SimpleNamespace(client=client,cloud_client=None,cloud_tunnels={}))
            with self.assertRaises(ValueError) as error:
                await catalog.balance(settings)
            self.assertNotIn(settings.api_key.get_secret_value(),str(error.exception))

    def test_catalog_filtering_and_price_validation(self):
        self.assertIsNotNone(model_entry(model()))
        self.assertIsNotNone(model_entry(model('google/gemma-4-26b-a4b-it',supported_parameters=['structured_outputs'])))
        self.assertIsNone(model_entry(model('unstructured-chat')))
        self.assertIsNone(model_entry(model('https://evil.example')))
        self.assertIsNone(model_entry(model(architecture='invalid')))
        self.assertIsNone(model_entry(model('image-model',architecture={'input_modalities':['text'],'output_modalities':['text','image']})))
        unknown=model_entry(model(pricing={'prompt':'-1'}))
        self.assertIsNone(unknown['input_price'])
        self.assertIsNone(unknown['output_price'])
        self.assertEqual(price('0'),0)
        for value in [None,True,'NaN','Infinity',-1]:
            self.assertIsNone(price(value))
