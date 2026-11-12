"""Public priced model catalogs and per-request account balances."""
import asyncio
import math
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .cloud import PROVIDERS, TranslationSettings, api_route, provider_error

CATALOG_URLS = {'kilo': 'https://ai-gateway.kilo.ai/api/v1/models', 'openrouter': 'https://openrouter.ai/api/v1/models'}
BALANCE_URLS = {'kilo': 'https://api.kilo.ai/api/profile/balance', 'openrouter': 'https://openrouter.ai/api/v1/credits'}


class CatalogRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['local', 'openai', 'kilo', 'openrouter']


class BalanceRequest(TranslationSettings):
    management_key: SecretStr = Field(default_factory=lambda: SecretStr(''))

    @model_validator(mode='after')
    def validate_management_key(self):
        key = self.management_key.get_secret_value()
        if key and (self.provider != 'openrouter' or not 16 <= len(key) <= 4096
                    or any(not 33 <= ord(char) <= 126 for char in key)):
            raise ValueError('An OpenRouter management key is required for account balance')
        return self


def price(value, allow_negative=False):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and (allow_negative or number >= 0) else None
    except (ValueError, TypeError, OverflowError):
        return None


def model_entry(item):
    model_id = item.get('id', '')
    if not isinstance(model_id, str) or not re.fullmatch(r'[A-Za-z0-9_./:@+\-]{1,128}', model_id) or '://' in model_id:
        return None
    architecture = item.get('architecture') or {}
    if not isinstance(architecture, dict):
        return None
    outputs = architecture.get('output_modalities') or []
    inputs = architecture.get('input_modalities') or []
    parameters = item.get('supported_parameters') or []
    specialized = model_id.startswith('tencent/hy-mt2-')
    if 'text' not in inputs or outputs != ['text'] or (not specialized and 'structured_outputs' not in parameters):
        return None
    pricing = item.get('pricing') or {}
    if not isinstance(pricing, dict):
        pricing = {}
    name = item.get('name')
    return {'id': model_id, 'name': name[:160] if isinstance(name, str) else model_id,
            'input_price': price(pricing.get('prompt')), 'output_price': price(pricing.get('completion'))}


class ProviderCatalog:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.cache = {}
        self.lock = asyncio.Lock()

    async def get(self, provider, endpoint, key=''):
        port = self.pipeline.cloud_tunnels.get(provider, 0)
        client = self.pipeline.client if port else self.pipeline.cloud_client or self.pipeline.client
        url, headers, extensions = api_route(endpoint, port)
        if key:
            headers['Authorization'] = 'Bearer ' + key
        try:
            response = await client.get(url, headers=headers, extensions=extensions, timeout=20)
        except httpx.HTTPError:
            raise ValueError(f'{PROVIDERS[provider][0]} is unreachable or timed out') from None
        if response.status_code != 200:
            raise provider_error(provider, response.status_code)
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ValueError:
            raise ValueError('Provider returned invalid account or catalog data') from None

    async def models(self, provider):
        if provider not in CATALOG_URLS:
            return {'provider': provider, 'models': [], 'fetched_at': None}
        async with self.lock:
            cached = self.cache.get(provider)
            if cached and time.monotonic() - cached[0] < 300:
                return cached[1]
            data = await self.get(provider, CATALOG_URLS[provider])
            items = data.get('data')
            if not isinstance(items, list) or len(items) > 10000:
                raise ValueError('Provider returned an invalid model catalog')
            models = [entry for item in items if isinstance(item, dict) and (entry := model_entry(item))]
            if not models:
                raise ValueError('No compatible translation models found in the provider catalog')
            result = {'provider': provider, 'models': models, 'fetched_at': int(time.time())}
            self.cache[provider] = (time.monotonic(), result)
            return result

    async def balance(self, settings):
        if settings.provider not in BALANCE_URLS:
            raise ValueError('Balance is available for Kilo Gateway and OpenRouter')
        if settings.provider == 'openrouter':
            result = await self.get('openrouter', 'https://openrouter.ai/api/v1/key', settings.api_key.get_secret_value())
            data = result.get('data')
            if not isinstance(data, dict) or price(data.get('usage')) is None:
                raise ValueError('OpenRouter key usage is unavailable')
            response = {'provider': 'openrouter', 'balance_usd': None, 'total_spent_usd': None,
                        'key_spent_usd': price(data['usage']), 'key_limit_remaining_usd': price(data.get('limit_remaining')),
                        'balance_note': 'Account balance requires a separate management key. The key allowance is not the account balance.',
                        'fetched_at': int(time.time())}
            management = getattr(settings, 'management_key', SecretStr('')).get_secret_value()
            if not management:
                return response
            try:
                result = await self.get('openrouter', BALANCE_URLS['openrouter'], management)
            except ValueError as error:
                return {**response, 'balance_note': str(error)}
        else:
            result = await self.get(settings.provider, BALANCE_URLS[settings.provider], settings.api_key.get_secret_value())
        used = None
        if settings.provider == 'kilo':
            remaining = price(result.get('balance'), allow_negative=True)
        else:
            data = result.get('data') or {}
            if not isinstance(data, dict):
                raise ValueError('Provider balance is unavailable; no balance was assumed')
            total, used = price(data.get('total_credits')), price(data.get('total_usage'))
            remaining = total - used if total is not None and used is not None else None
        if remaining is None:
            raise ValueError('Provider balance is unavailable; no balance was assumed')
        # Account-specific data must never enter the shared model cache.
        if settings.provider == 'openrouter':
            return {**response, 'balance_usd': remaining, 'total_spent_usd': used, 'balance_note': None}
        return {'provider': settings.provider, 'balance_usd': remaining, 'total_spent_usd': used,
                'fetched_at': int(time.time())}
