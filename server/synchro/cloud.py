"""Fixed-endpoint cloud translation; credentials belong to one playback session."""
import asyncio
import logging
import os
import time
import uuid
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from .usage import record_usage

logger = logging.getLogger('uvicorn.error')

PROVIDERS = {
    'openai': ('OpenAI', 'https://api.openai.com/v1/chat/completions', 'gpt-4.1-mini'),
    'kilo': ('Kilo Gateway', 'https://ai-gateway.kilo.ai/api/v1/chat/completions', 'tencent/hy-mt2-1.8b'),
    'openrouter': ('OpenRouter', 'https://openrouter.ai/api/v1/chat/completions', 'google/gemma-4-26b-a4b-it'),
}


class TranslationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['local', 'openai', 'kilo', 'openrouter', 'custom'] = 'local'
    mode: Literal['local', 'cloud_translation', 'cloud_all'] | None = None
    model: str = Field(default='', max_length=128, pattern=r'^[A-Za-z0-9_./:@+\-]*$')
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(''))
    # Any OpenAI-compatible chat endpoint (local LM Studio, Ollama, a proxy); desktop app only.
    base_url: str = Field(default='', max_length=512)

    @model_validator(mode='after')
    def validate_key(self):
        self.mode = self.mode or ('local' if self.provider == 'local' else 'cloud_translation')
        if self.provider == 'custom':
            return self.validate_custom()
        if self.base_url:
            raise ValueError('A server address is only used by a custom OpenAI-compatible provider')
        if (self.mode == 'local') != (self.provider == 'local'):
            raise ValueError('Select a cloud provider for a cloud mode, or Local server for local mode')
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

    def validate_custom(self):
        # A shared gateway must not be pointed at arbitrary addresses; the desktop engine serves one local user.
        if os.environ.get('SYNCHRO_DESKTOP') != '1':
            raise ValueError('Custom OpenAI-compatible endpoints are available in the desktop app only')
        address = urlsplit(self.base_url)
        if address.scheme not in ('http', 'https') or not address.hostname or address.username or address.password:
            raise ValueError('Enter an http(s) address such as https://example.com/v1')
        if self.mode != 'cloud_translation' or not self.model or '://' in self.model:
            raise ValueError('A custom endpoint needs a model ID and translates text only')
        key = self.api_key.get_secret_value()
        if len(key) > 4096 or any(not 33 <= ord(char) <= 126 for char in key):
            raise ValueError('Invalid API key')
        return self

    @property
    def is_hymt(self):
        return self.provider in ('kilo', 'openrouter') and self.model.startswith('tencent/hy-mt2-')


class EmptyTranslationError(ValueError):
    pass


def api_route(endpoint, tunnel_port=0):
    headers = {}
    extensions = {}
    if tunnel_port:
        target = urlsplit(endpoint)
        endpoint = f'https://127.0.0.1:{tunnel_port}{target.path}' + ('?' + target.query if target.query else '')
        headers['Host'] = target.hostname
        # Different TLS hosts can share a tunnel port; httpx pools by loopback origin.
        headers['Connection'] = 'close'
        extensions['sni_hostname'] = target.hostname
    return endpoint, headers, extensions


def provider_route(settings):
    if settings.provider == 'custom':
        return 'Custom endpoint', settings.base_url.rstrip('/') + '/chat/completions'
    return PROVIDERS[settings.provider][:2]


def provider_error(provider, status):
    name = PROVIDERS[provider][0] if provider in PROVIDERS else 'Custom endpoint'
    hint = {401: 'check the API key', 402: 'check account credits', 403: 'check account access and the server outbound network route',
            429: 'request limit reached', 400: 'check the model and structured-output support'}.get(status, 'try again later')
    return ValueError(f'{name}: HTTP {status}; {hint}')


async def complete(client, settings, messages, schema=None, tunnel_port=0, stage='translation'):
    name, endpoint = provider_route(settings)
    endpoint, headers, extensions = api_route(endpoint, tunnel_port)
    if settings.api_key.get_secret_value():
        headers['Authorization'] = 'Bearer ' + settings.api_key.get_secret_value()
    body = {'model': settings.model, 'messages': messages, 'stream': False, 'temperature': 0}
    token_field = 'max_completion_tokens' if settings.provider == 'openai' else 'max_tokens'
    body[token_field] = 512
    if settings.provider == 'openai':
        body['store'] = False
    if schema is not None:
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'translation', 'strict': True, 'schema': schema}}
    reference = uuid.uuid4().hex[:12]
    failure = f'{name} is unreachable or timed out'
    outcome = 'network_error'
    fast_kilo = settings.provider == 'kilo' and (settings.is_hymt or settings.model == 'google/gemma-4-26b-a4b-it')
    try:
        async with asyncio.timeout(60):
            for attempt in range(2):
                started = time.monotonic()
                status, finish, tokens, reasoning = None, None, None, None
                retry = True
                outcome = 'network_error'
                try:
                    timeout = (8, 15)[attempt] if fast_kilo else 30
                    response = await client.post(endpoint, json=body, headers=headers, extensions=extensions, timeout=timeout)
                    try:
                        record_usage(stage, response.json().get('usage'))
                    except (ValueError, AttributeError):
                        record_usage(stage)
                    status = response.status_code
                    if status != 200:
                        failure = str(provider_error(settings.provider, status))
                        outcome = 'http_error'
                        retry = status in (502, 503, 504)
                    else:
                        outcome = 'invalid_response'
                        try:
                            data = response.json()
                            choice = data['choices'][0]
                            result = choice['message']['content']
                            reason = choice.get('finish_reason')
                            finish = reason if reason in ('stop', 'length', 'content_filter', 'tool_calls', 'error') else 'other'
                            usage = data.get('usage') or {}
                            tokens = usage.get('completion_tokens')
                            reasoning = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
                            tokens = tokens if type(tokens) is int else None
                            reasoning = reasoning if type(reasoning) is int else None
                            if reason == 'length':
                                outcome = 'output_limit'
                                body[token_field] = 1024
                            elif reason == 'content_filter':
                                outcome, retry = 'content_filter', False
                            elif not isinstance(result, str) or not result.strip():
                                outcome = 'empty_response'
                            elif reason in (None, 'stop'):
                                outcome = 'ok'
                        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                            pass
                        failure = f'{name}: ' + {
                            'output_limit': 'translation exceeded the output token limit',
                            'content_filter': 'translation was blocked by the provider content filter',
                            'empty_response': 'provider returned an empty translation',
                        }.get(outcome, 'provider returned an invalid translation')
                except httpx.HTTPError as error:
                    record_usage(stage)
                    failure = f'{name} is unreachable or timed out'
                    outcome = type(error).__name__
                # Never log credentials, response bodies, transcripts, or reasoning text.
                logger.info('cloud_translation ref=%s provider=%s model=%s stage=%s attempt=%d status=%s outcome=%s finish=%s tokens=%s reasoning_tokens=%s seconds=%.3f',
                            reference, settings.provider, settings.model, stage, attempt + 1, status, outcome, finish, tokens, reasoning, time.monotonic() - started)
                if outcome == 'ok':
                    return result.strip()
                if not retry or attempt == 1:
                    break
                await asyncio.sleep(.5)
    except TimeoutError:
        outcome = 'deadline'
        failure = f'{name}: translation timed out after 60 seconds'
        logger.warning('cloud_translation ref=%s provider=%s model=%s outcome=deadline', reference, settings.provider, settings.model)
    error_type = EmptyTranslationError if outcome == 'empty_response' else ValueError
    raise error_type(f'{failure}. Retry translation. Reference: {reference}') from None
