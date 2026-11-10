"""Optional CPU recognition and voices on the computer running the browser."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import re
import time

from .pipeline import Pipeline, RATE, SILERO_VOICES, normalize_wav, wav_bytes


class HostPipeline(Pipeline):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.russian_speech = True
        self.host_lock = asyncio.Lock()
        # Cancelling an HTTP request cannot cancel native CPU inference.
        self.host_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='synchro-cpu')
        self.host_asr = self.host_tts = self.host_whisper = None

    def recognize_cpu(self, pcm):
        import numpy as np
        if self.host_asr is None:
            import onnx_asr
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options = ort.SessionOptions()
            options.intra_op_num_threads = 8
            options.inter_op_num_threads = 1
            options.add_session_config_entry('session.intra_op.allow_spinning', '0')
            self.host_asr = onnx_asr.load_model('gigaam-multilingual-ctc', path=os.environ['SYNCHRO_HOST_ASR_MODEL'],
                sess_options=options, providers=['CPUExecutionProvider']).with_timestamps()
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        result = self.host_asr.recognize(samples, sample_rate=RATE)
        if re.search(r'[А-Яа-яЁё]', result.text) or not result.text.strip() and np.any(samples):
            if self.host_whisper is None:
                from faster_whisper import WhisperModel
                self.host_whisper = WhisperModel(os.environ['SYNCHRO_HOST_WHISPER_MODEL'], device='cpu',
                    compute_type='int8', cpu_threads=8, num_workers=1, local_files_only=True)
            logging.getLogger('uvicorn.error').info('host_asr engine=whisper device=cpu reason=empty_or_alphabet')
            segments, _ = self.host_whisper.transcribe(samples, language='en', beam_size=1, word_timestamps=True,
                condition_on_previous_text=False, vad_filter=True)
            words = [{'word': word.word, 'start': word.start, 'end': word.end} for segment in segments for word in segment.words or []]
            return {'text': ''.join(word['word'] for word in words), 'words': words}
        # Reuse the worker's CTC decoder; run_host.py adds the repository to sys.path.
        from deploy.gigaam_server import word_timestamps
        return {'text': result.text, 'words': word_timestamps(result.tokens, result.timestamps, len(pcm) / (RATE * 2))}

    async def transcribe(self, pcm):
        started = time.monotonic()
        async with self.host_lock:
            result = await asyncio.get_running_loop().run_in_executor(self.host_executor, self.recognize_cpu, pcm)
        logging.getLogger('uvicorn.error').info('host_asr device=cpu seconds=%.3f source_seconds=%.1f', time.monotonic() - started, len(pcm) / 32000)
        return result

    def synthesize_cpu(self, text, voice):
        import torch
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 2000 or re.search(r'[A-Za-z0-9]', text):
            raise ValueError('Russian speech needs Cyrillic names and numbers written as words')
        if self.host_tts is None:
            torch.set_num_threads(8)
            path = Path(os.environ['SYNCHRO_HOST_TTS_MODEL']).resolve(strict=True)
            self.host_tts = torch.package.PackageImporter(str(path)).load_pickle('tts_models', 'model')
            self.host_tts.to(torch.device('cpu'))
        audio = self.host_tts.apply_tts(text=text.replace('+', ' плюс '), speaker=SILERO_VOICES[voice], sample_rate=48000,
            put_accent=True, put_stress_homo=True, put_yo=False, put_yo_homo=False)
        pcm = (audio.detach().cpu().clamp(-1, 1).numpy() * 32767).astype('<i2').tobytes()
        return wav_bytes(pcm, 48000)

    async def speak(self, text, voice='female'):
        started = time.monotonic()
        async with self.host_lock:
            audio = await asyncio.get_running_loop().run_in_executor(self.host_executor, self.synthesize_cpu, text, voice)
        result = await normalize_wav(audio)
        logging.getLogger('uvicorn.error').info('host_tts device=cpu seconds=%.3f', time.monotonic() - started)
        return result
