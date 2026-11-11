"""CPU recognition of Chinese, Japanese and Korean with SenseVoice-Small through sherpa-onnx."""
from pathlib import Path
import threading
import unicodedata

# CTC gives token start frames only; a token ends at the next start, but never later than this.
TOKEN_SECONDS = .3


def is_cjk(char):
    # Han and kana are written without spaces: every character is its own timing unit.
    return '぀' <= char <= 'ヿ' or '㐀' <= char <= '鿿' or '豈' <= char <= '﫿'


def token_words(tokens, timestamps, duration):
    """Group SenseVoice tokens into the word timing units used by the pipeline."""
    if len(tokens) != len(timestamps):
        raise ValueError('Missing SenseVoice timestamps')
    words = []
    for index, (token, start) in enumerate(zip(tokens, timestamps)):
        following = timestamps[index + 1] if index + 1 < len(timestamps) else duration
        end = min(duration, following, start + TOKEN_SECONDS)
        if not token.strip():
            continue
        punctuation = all(unicodedata.category(char).startswith('P') for char in token)
        if words and not token[0].isspace() and (punctuation or not is_cjk(token[0]) and not is_cjk(words[-1]['word'][-1])):
            # A subword or punctuation continues the previous word.
            words[-1]['word'] += token
            words[-1]['end'] = max(words[-1]['end'], end)
        else:
            words.append({'word': token, 'start': float(start), 'end': float(max(start, end))})
    return words


class SenseVoice:
    def __init__(self, path, threads=8):
        self.path = Path(path) if path else None
        self.threads = threads
        self.recognizers = {}
        # One inference at a time keeps CPU threads bounded with several viewers.
        self.lock = threading.Lock()

    def recognize(self, pcm, language):
        if not self.path:
            raise ValueError('SenseVoice is not configured')
        import numpy as np
        import sherpa_onnx
        with self.lock:
            recognizer = self.recognizers.get(language)
            if recognizer is None:
                recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(self.path / 'model.int8.onnx'), tokens=str(self.path / 'tokens.txt'),
                    num_threads=self.threads, language=language, use_itn=True)
                self.recognizers[language] = recognizer
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768)
            recognizer.decode_stream(stream)
            result = stream.result
        return {'text': result.text, 'words': token_words(list(result.tokens), list(result.timestamps), len(pcm) / 32000),
                'language': language}
