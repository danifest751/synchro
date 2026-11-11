"""Optional CPU recognition and voices on the computer running the browser."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import re
import time

from .pipeline import Pipeline, RATE, SILERO_VOICES, normalize_wav, wav_bytes
from .stress import FOREIGN, preserve_stress, silero_marks, spoken_text


def load_host_accent():
    import onnxruntime as ort
    import ruaccent
    from ruaccent import accent_model, omograph_model, stress_usage_model, yo_homograph_model

    path = Path(os.environ['SYNCHRO_HOST_ACCENT_MODEL']).resolve(strict=True)
    package = Path(ruaccent.__file__).parent
    for folder in (path / 'dictionary', path / 'nn/nn_omograph/turbo3.1', package / 'koziev'):
        if not folder.is_dir():
            raise ValueError('Install the local RUAccent assets before starting playback')

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')

    # RUAccent 1.5.8.3 does not expose ONNX session options.
    def cpu_session(path, *, providers):
        return ort.InferenceSession(path, sess_options=options, providers=['CPUExecutionProvider'])

    for module in (accent_model, omograph_model, stress_usage_model, yo_homograph_model):
        module.InferenceSession = cpu_session
    accent = ruaccent.RUAccent()
    accent.load(omograph_model_size='turbo3.1', use_dictionary=True, device='CPU', workdir=str(path))
    # Transformers 5 omits token_type_ids by default for the tokenizer used on unknown words.
    unknown_word_model = accent.accent_model
    unknown_word_model.tokenizer.model_input_names = [item.name for item in unknown_word_model.session.get_inputs()]
    return accent


class HostPipeline(Pipeline):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.russian_speech = True
        self.host_lock = asyncio.Lock()
        # Cancelling an HTTP request cannot cancel native CPU inference.
        self.host_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='synchro-cpu')
        self.host_asr = self.host_tts = self.host_whisper = self.host_accent = None

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
        # Whisper is an optional install (the desktop app ships without it).
        if os.environ.get('SYNCHRO_HOST_WHISPER_MODEL') and (re.search(r'[А-Яа-яЁё]', result.text) or not result.text.strip() and np.any(samples)):
            logging.getLogger('uvicorn.error').info('host_asr engine=whisper device=cpu reason=empty_or_alphabet')
            return self.whisper_cpu(pcm, 'en')
        # Reuse the worker's CTC decoder; run_host.py adds the repository to sys.path.
        from deploy.gigaam_server import word_timestamps
        return {'text': result.text, 'words': word_timestamps(result.tokens, result.timestamps, len(pcm) / (RATE * 2))}

    def whisper_cpu(self, pcm, language):
        import numpy as np
        if self.host_whisper is None:
            from faster_whisper import WhisperModel
            self.host_whisper = WhisperModel(os.environ['SYNCHRO_HOST_WHISPER_MODEL'], device='cpu',
                compute_type='int8', cpu_threads=8, num_workers=1, local_files_only=True)
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        segments, _ = self.host_whisper.transcribe(samples, language=language, beam_size=1, word_timestamps=True,
            condition_on_previous_text=False, vad_filter=True)
        words = [{'word': word.word, 'start': word.start, 'end': word.end} for segment in segments for word in segment.words or []]
        return {'text': ''.join(word['word'] for word in words), 'words': words}

    async def whisper(self, pcm, language):
        async with self.host_lock:
            return await asyncio.get_running_loop().run_in_executor(self.host_executor, self.whisper_cpu, pcm, language)

    async def transcribe(self, pcm):
        started = time.monotonic()
        async with self.host_lock:
            result = await asyncio.get_running_loop().run_in_executor(self.host_executor, self.recognize_cpu, pcm)
        logging.getLogger('uvicorn.error').info('host_asr device=cpu seconds=%.3f source_seconds=%.1f', time.monotonic() - started, len(pcm) / 32000)
        return result

    def synthesize_cpu(self, text, voice):
        import torch
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 2000 or FOREIGN.search(text):
            raise ValueError('Russian speech needs Cyrillic names and numbers written as words')
        if self.host_tts is None:
            torch.set_num_threads(2)
            path = Path(os.environ['SYNCHRO_HOST_TTS_MODEL']).resolve(strict=True)
            model = torch.package.PackageImporter(str(path)).load_pickle('tts_models', 'model')
            if not set(SILERO_VOICES.values()) <= set(model.speakers):
                raise ValueError('Configure the Silero V5 CIS model for the selected voices')
            model.to(torch.device('cpu'))
            self.host_tts = model
        if self.host_accent is None:
            self.host_accent = load_host_accent()
        spoken = spoken_text(text)
        try:
            marked = silero_marks(preserve_stress(spoken, self.host_accent.process_all(spoken)))
        except Exception:
            # Unmarked words are still spoken; an unusual phrase must not stop playback.
            logging.getLogger('uvicorn.error').warning('host_stress outcome=unmarked_fallback')
            marked = spoken
        audio = self.host_tts.apply_tts(text=marked, speaker=SILERO_VOICES[voice], sample_rate=48000,
            put_accent=False, put_yo=False)
        pcm = (audio.detach().cpu().clamp(-1, 1).numpy() * 32767).astype('<i2').tobytes()
        return wav_bytes(pcm, 48000)

    async def speak(self, text, voice='female'):
        started = time.monotonic()
        async with self.host_lock:
            audio = await asyncio.get_running_loop().run_in_executor(self.host_executor, self.synthesize_cpu, text, voice)
        result = await normalize_wav(audio)
        logging.getLogger('uvicorn.error').info('host_tts device=cpu seconds=%.3f', time.monotonic() - started)
        return result
