"""Private PCM16/16k ASR endpoint; run separately from the shared Russian service."""
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import math
import os


def word_timestamps(tokens, timestamps, duration):
    if tokens is None or timestamps is None or len(tokens) != len(timestamps):
        raise ValueError('Missing CTC timestamps')
    words, current = [], None
    previous = 0.0
    for token, timestamp in zip(tokens, timestamps):
        if not isinstance(token, str) or not math.isfinite(timestamp) or not previous <= timestamp <= duration:
            raise ValueError('Invalid CTC timestamp')
        previous = timestamp
        for character in token:
            if character.isspace():
                if current:
                    words.append(current)
                    current = None
            else:
                if current is None:
                    current = {'word': ' ', 'start': timestamp, 'end': timestamp}
                current['word'] += character
                current['end'] = min(duration, timestamp + 0.04)
    if current:
        words.append(current)
    return words


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        valid = hmac.compare_digest(self.headers.get('Authorization', '').encode(), self.server.authorization)
        if not valid:
            self.respond(401, {'error': 'Unauthorized'})
        return valid

    def do_GET(self):
        if self.authorized():
            self.respond(200 if self.path == '/health' else 404, {'engine': 'gigaam-multilingual-ctc', 'threads': 8})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != '/transcribe':
            self.respond(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if not 0 < length <= 21 * 32000 or length % 2 or self.headers.get('Transfer-Encoding'):
            self.respond(400, {'error': 'Expected up to 21 seconds of PCM16 mono 16kHz'})
            return
        pcm = self.rfile.read(length)
        if len(pcm) != length:
            self.respond(400, {'error': 'Incomplete PCM'})
            return
        try:
            import numpy as np
            result = self.server.model.recognize(np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768, sample_rate=16000)
            words = word_timestamps(result.tokens, result.timestamps, length / 32000)
            self.respond(200, {'text': result.text, 'words': words, 'language': 'en'})
        except Exception:
            logging.exception('GigaAM inference failed')
            self.respond(503, {'error': 'Recognition failed'})


class Server(HTTPServer):
    # One inference at a time; three viewers queue without multiplying CPU thread pools.
    request_queue_size = 3

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address


if __name__ == '__main__':
    import onnx_asr
    import onnxruntime as ort
    ort.disable_telemetry_events()
    token = os.environ.get('SYNCHRO_ASR_TOKEN', '')
    if len(token) < 32:
        raise SystemExit('SYNCHRO_ASR_TOKEN must be configured')
    options = ort.SessionOptions()
    options.intra_op_num_threads = 8
    options.inter_op_num_threads = 1
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    model = onnx_asr.load_model('gigaam-multilingual-ctc', path=os.environ.get('SYNCHRO_ASR_MODEL', 'models/gigaam'),
                               sess_options=options, providers=['CPUExecutionProvider']).with_timestamps()
    server = Server(('127.0.0.1', 3008), Handler)
    server.authorization = ('Bearer ' + token).encode()
    server.model = model
    logging.warning('GigaAM Multilingual ready on loopback:3008, CPU threads=8')
    server.serve_forever()
