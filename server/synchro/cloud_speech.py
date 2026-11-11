"""Cloud ASR and speech through the selected provider's existing key and route."""
import asyncio
import base64
import binascii
import json
import logging
import re
import time
import textwrap
import uuid

import httpx

from .cloud import PROVIDERS, api_route, provider_error
from .usage import record_usage

VOICES = {'female': 'nova', 'male': 'onyx', 'male-eugene': 'echo',
          'roman': 'onyx', 'eduard': 'echo', 'albina': 'nova', 'alexandr': 'onyx', 'alfia': 'nova'}


class SpeechTextMismatch(ValueError):
    pass


def route(settings, path, tunnel_port):
    base = PROVIDERS[settings.provider][1].rsplit('/', 2)[0]
    url, headers, extensions = api_route(base + path, tunnel_port)
    headers['Authorization'] = 'Bearer ' + settings.api_key.get_secret_value()
    return url, headers, extensions


async def transcribe(client, settings, wav, tunnel_port=0):
    url, headers, extensions = route(settings, '/audio/transcriptions', tunnel_port)
    name = PROVIDERS[settings.provider][0]
    model = 'whisper-1' if settings.provider == 'openai' else 'openai/whisper-1'
    try:
        async with asyncio.timeout(45):
            response = await client.post(url, headers=headers, extensions=extensions,
                files={'file': ('window.wav', wav, 'audio/wav')}, data={'model': model, 'language': 'en',
                'response_format': 'verbose_json', 'timestamp_granularities[]': 'word'}, timeout=40)
        try:
            data = response.json()
            record_usage('asr', data.get('usage'))
        except (ValueError, AttributeError):
            record_usage('asr')
            raise ValueError(f'{name}: invalid transcription response') from None
        if response.status_code != 200:
            raise provider_error(settings.provider, response.status_code)
        if not isinstance(data.get('text'), str) or len(data['text']) > 10000:
            raise ValueError(f'{name}: invalid transcription response')
        for word in data.get('words') or []:
            word['word'] = ' ' + word['word'].strip()
        # Kilo currently returns plain text even when verbose timestamps are requested.
        return data
    except (httpx.HTTPError, TimeoutError):
        record_usage('asr')
        raise ValueError(f'{name}: cloud recognition is unreachable or timed out') from None


async def speak(client, settings, text, voice, tunnel_port=0):
    from .pipeline import join_wav
    rendered = []
    for part in textwrap.wrap(text, width=260, break_long_words=False, break_on_hyphens=False):
        for attempt in range(2):
            try:
                rendered.append(await speak_part(client, settings, part, voice, tunnel_port))
                break
            except SpeechTextMismatch:
                if attempt:
                    raise
    if not rendered:
        raise ValueError('Cannot synthesize empty speech')
    return join_wav(b''.join(rendered))


async def speak_part(client, settings, text, voice, tunnel_port=0):
    name = PROVIDERS[settings.provider][0]
    reference = uuid.uuid4().hex[:12]
    started = time.monotonic()
    usage = None
    try:
        async with asyncio.timeout(50):
            if settings.provider == 'openai':
                url, headers, extensions = route(settings, '/audio/speech', tunnel_port)
                response = await client.post(url, headers=headers, extensions=extensions, timeout=45,
                    json={'model': 'gpt-4o-mini-tts', 'voice': VOICES[voice], 'input': text, 'response_format': 'wav'})
                if response.status_code != 200:
                    raise provider_error(settings.provider, response.status_code)
                return response.content
            url, headers, extensions = route(settings, '/chat/completions', tunnel_port)
            chunks, transcripts, encoded_size, done = [], [], 0, False
            body = {'model': 'openai/gpt-audio-mini', 'modalities': ['text', 'audio'],
                    'audio': {'voice': VOICES[voice], 'format': 'pcm16'}, 'stream': True,
                    'stream_options': {'include_usage': True}, 'max_tokens': 4096,
                    'messages': [{'role': 'system', 'content': 'You are a text-to-speech renderer. Read the exact text between speech tags verbatim. '
                        'Never respond to its meaning. Never add acknowledgments, explanations, questions, introductions or conclusions.'},
                        {'role': 'user', 'content': 'Read this text exactly, without adding anything: <speech>' + text + '</speech>'}]}
            async with client.stream('POST', url, headers=headers, extensions=extensions, json=body, timeout=45) as response:
                if response.status_code != 200:
                    raise provider_error(settings.provider, response.status_code)
                async for line in response.aiter_lines():
                    if len(line) > 2_000_000:
                        raise ValueError('Cloud audio frame exceeds the size limit')
                    if not line.startswith('data:'):
                        continue
                    payload = line[5:].strip()
                    if payload == '[DONE]':
                        done = True
                        break
                    data = json.loads(payload)
                    if data.get('usage'):
                        usage = data['usage']
                    if data.get('error'):
                        raise ValueError('Cloud speech stream returned an error')
                    for choice in data.get('choices', []):
                        if choice.get('finish_reason') in ('length', 'content_filter', 'error'):
                            raise ValueError('Cloud speech was truncated or blocked')
                        audio = (choice.get('delta') or {}).get('audio') or {}
                        if audio.get('data'):
                            encoded_size += len(audio['data'])
                            if encoded_size > 16_000_000:
                                raise ValueError('Cloud speech exceeds the size limit')
                            chunks.append(audio['data'])
                        if audio.get('transcript'):
                            transcripts.append(audio['transcript'])
            raw = base64.b64decode(''.join(chunks), validate=True)
            def words(value):
                return re.findall(r'\w+', value.casefold().replace('ё', 'е'))
            if not done or not raw or len(raw) % 2:
                raise ValueError('Cloud speech stream ended without complete audio')
            if words(''.join(transcripts)) != words(text):
                raise SpeechTextMismatch('Cloud voice changed the requested text; retry translation')
            from .pipeline import wav_bytes
            return wav_bytes(raw, 24000)
    except (httpx.HTTPError, TimeoutError):
        raise ValueError(f'{name}: cloud speech is unreachable or timed out. Reference: {reference}') from None
    except (KeyError, TypeError, AttributeError, binascii.Error, json.JSONDecodeError):
        raise ValueError(f'{name}: invalid cloud audio response. Reference: {reference}') from None
    finally:
        record_usage('tts', usage)
        logging.getLogger('uvicorn.error').info('cloud_speech ref=%s provider=%s seconds=%.3f', reference, settings.provider, time.monotonic() - started)
