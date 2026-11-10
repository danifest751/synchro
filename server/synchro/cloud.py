"""Fixed-endpoint cloud translation; credentials belong to one playback session."""
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

PROVIDERS = {
    'openai': ('OpenAI', 'https://api.openai.com/v1/chat/completions', 'gpt-4.1-mini'),
    'kilo': ('Kilo Gateway', 'https://ai-gateway.kilo.ai/api/v1/chat/completions', 'tencent/hy-mt2-1.8b'),
    'openrouter': ('OpenRouter', 'https://openrouter.ai/api/v1/chat/completions', 'google/gemma-4-26b-a4b-it'),
}


class TranslationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['local', 'openai', 'kilo', 'openrouter'] = 'local'
    model: str = Field(default='', max_length=128, pattern=r'^[A-Za-z0-9_./:@+\-]*$')
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(''))

    @model_validator(mode='after')
    def validate_key(self):
        if '://' in self.model:
            raise ValueError('Use a model ID, not a URL')
        if self.provider != 'local':
            key = self.api_key.get_secret_value()
            if not 16 <= len(key) <= 4096 or any(not 33 <= ord(char) <= 126 for char in key):
                raise ValueError('A valid cloud API key is required')
            self.model = self.model or PROVIDERS[self.provider][2]
        else:
            self.api_key = SecretStr('')
            self.model = ''
        return self

    @property
    def is_hymt(self):
        return self.provider in ('kilo', 'openrouter') and self.model.startswith('tencent/hy-mt2-')


def api_route(endpoint, tunnel_port=0):
    headers = {}
    extensions = {}
    if tunnel_port:
        target = urlsplit(endpoint)
        endpoint = f'https://127.0.0.1:{tunnel_port}{target.path}'
        headers['Host'] = target.hostname
        extensions['sni_hostname'] = target.hostname
    return endpoint, headers, extensions


def provider_error(provider, status):
    name = PROVIDERS[provider][0]
    hint = {401: 'check the API key', 402: 'check account credits', 403: 'check account access and the server outbound network route',
            429: 'request limit reached', 400: 'check the model and structured-output support'}.get(status, 'try again later')
    return ValueError(f'{name}: HTTP {status}; {hint}')


async def complete(client, settings, messages, schema=None, tunnel_port=0):
    name, endpoint, _ = PROVIDERS[settings.provider]
    endpoint, headers, extensions = api_route(endpoint, tunnel_port)
    headers['Authorization'] = 'Bearer ' + settings.api_key.get_secret_value()
    body = {'model': settings.model, 'messages': messages, 'stream': False, 'temperature': 0}
    body['max_completion_tokens' if settings.provider == 'openai' else 'max_tokens'] = 256
    if settings.provider == 'openai':
        body['store'] = False
    if schema is not None:
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'translation', 'strict': True, 'schema': schema}}
    try:
        response = await client.post(endpoint, json=body, headers=headers, extensions=extensions, timeout=60)
    except httpx.HTTPError:
        raise ValueError(f'{name} is unreachable or timed out') from None
    if response.status_code != 200:
        raise provider_error(settings.provider, response.status_code)
    try:
        data = response.json()
        choice = data['choices'][0]
        result = choice['message']['content']
        if not isinstance(result, str) or not result.strip() or choice.get('finish_reason') in ('length', 'content_filter'):
            raise ValueError()
        return result.strip()
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError(f'{name} returned an empty, truncated, or invalid translation') from None
