"""Local acoustic cues for grammatical gender; uncertain voices stay unspecified."""
import hashlib
from pathlib import Path
import urllib.request
import threading

MODEL_REVISION = '8aedeb1a399945e52e6f3f61714abe07c1c48742'
MODEL_URL = ('https://huggingface.co/Alice-Sabrina-Ivy/voice-gender-classifier-onnx-q8-v2/resolve/'
             + MODEL_REVISION + '/onnx/model_quantized.onnx')
MODEL_SHA256 = 'fdc2dbdcf99b9217977f7472f7d677dd48219c4759ca3f38d0626b600d86c252'


def install_model(path):
    """Build-time download only. Never download models during playback."""
    path = Path(path)
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.part')
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            data = response.read(20 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            raise ValueError('Speaker model checksum mismatch')
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class SpeakerClassifier:
    def __init__(self, path):
        self.path = str(path)
        self.model = None
        self.lock = threading.Lock()

    def classify(self, pcm):
        with self.lock:
            return self._classify(pcm)

    def _classify(self, pcm):
        import numpy as np
        import onnxruntime as ort

        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        if len(samples) < 12000 or np.sqrt(np.mean(samples * samples)) < .008 or not has_voiced_audio(samples):
            return 'unknown'
        if self.model is None:
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.add_session_config_entry('session.intra_op.allow_spinning', '0')
            ort.disable_telemetry_events()
            self.model = ort.InferenceSession(self.path, sess_options=options, providers=['CPUExecutionProvider'])
        # Sample across the phrase; conflicting confident cues indicate mixed speakers.
        length = min(len(samples), 24000)
        starts = sorted({0, (len(samples) - length) // 2, len(samples) - length})
        probabilities = []
        for start in starts:
            audio = samples[start:start + length]
            if np.sqrt(np.mean(audio * audio)) < .008:
                continue
            logits = np.asarray(self.model.run(None, {self.model.get_inputs()[0].name: audio[None, :]})[0]).reshape(-1)
            if logits.size != 2 or not np.isfinite(logits).all():
                continue
            weights = np.exp(logits - logits.max())
            probabilities.append(float(weights[1] / weights.sum()))
        return decide(probabilities)


def decide(probabilities):
    if not probabilities:
        return 'unknown'
    if min(probabilities) <= .2 and max(probabilities) >= .8:
        return 'unknown'
    mean = sum(probabilities) / len(probabilities)
    return 'female' if mean >= .8 else 'male' if mean <= .2 else 'unknown'


def has_voiced_audio(samples):
    """Reject silence and unvoiced noise before asking a binary classifier."""
    import numpy as np
    if len(samples) < 512:
        return False
    frames = np.lib.stride_tricks.sliding_window_view(samples, 512)[::320]
    frames = frames - frames.mean(axis=1, keepdims=True)
    spectrum = np.fft.rfft(frames, n=1024, axis=1)
    correlation = np.fft.irfft(np.abs(spectrum) ** 2, n=1024, axis=1)
    periodicity = correlation[:, 40:300].max(axis=1) / np.maximum(correlation[:, 0], 1e-10)
    voiced = (periodicity > .35) & (np.mean(frames * frames, axis=1) >= .008 ** 2)
    return int(voiced.sum()) >= max(6, len(frames) * .15)
