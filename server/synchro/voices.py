"""Stable voice IDs; private VoiceStudio profile IDs stay on the gateway."""
import json
import os
import re
from typing import Literal

Voice = Literal['female', 'male', 'male-eugene', 'studio-female-1', 'studio-female-2', 'studio-female-3',
                'studio-male-1', 'studio-male-2', 'studio-male-3']
BASE_VOICES = {'female': 'Xenia · female', 'male': 'Aidar · male', 'male-eugene': 'Eugene · male'}
CLOUD_VOICES = {'female': 'Nova · cloud female', 'male': 'Onyx · cloud male', 'male-eugene': 'Echo · cloud male'}
STUDIO_VOICES = {f'studio-{gender}-{index}': f'{gender.title()} {index} · VoiceStudio · server'
                 for gender in ['female', 'male'] for index in range(1, 4)}


class StudioVoices:
    def __init__(self):
        self.url = os.environ.get('SYNCHRO_VOICESTUDIO_URL', '').rstrip('/')
        self.token = os.environ.get('SYNCHRO_VOICESTUDIO_TOKEN', '')
        self.shared_gpu = os.environ.get('SYNCHRO_VOICESTUDIO_SHARED_GPU') == '1'
        self.profiles = json.loads(os.environ.get('SYNCHRO_VOICESTUDIO_VOICES', '{}'))
        if not isinstance(self.profiles, dict) or any(key not in STUDIO_VOICES or not isinstance(value, str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) for key, value in self.profiles.items()):
            raise ValueError('Invalid VoiceStudio profile mapping')

    def available(self, mode):
        if mode == 'cloud_all':
            return [{'id': key, 'name': name} for key, name in CLOUD_VOICES.items()]
        voices = dict(BASE_VOICES)
        if self.url and self.token and not (mode == 'local' and self.shared_gpu):
            voices.update({key: STUDIO_VOICES[key] for key in self.profiles})
        return [{'id': key, 'name': name} for key, name in voices.items()]

    def validate(self, voice, mode):
        if voice not in {item['id'] for item in self.available(mode)}:
            raise ValueError('This voice is unavailable in the selected processing mode. Choose another voice in settings')

    async def speak(self, client, text, voice):
        import httpx
        try:
            response = await client.post(self.url + '/v1/audio/speech',
                headers={'Authorization': 'Bearer ' + self.token},
                json={'model': 'tts-1', 'voice': self.profiles[voice], 'input': text, 'response_format': 'wav'}, timeout=75)
        except httpx.HTTPError:
            raise ValueError('VoiceStudio is unreachable or timed out; check its private server') from None
        if response.status_code != 200:
            raise ValueError(f'VoiceStudio: HTTP {response.status_code}; check its model, GPU memory and saved voice')
        if not response.content.startswith(b'RIFF') or len(response.content) > 20_000_000:
            raise ValueError('VoiceStudio returned invalid or oversized speech audio')
        return response.content
