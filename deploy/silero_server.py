"""Private Synchro CPU speech endpoint using locally installed Silero weights."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import os
import re
import threading
import wave

SPEAKERS = {'ru_roman', 'ru_eduard', 'ru_albina', 'ru_alexandr', 'ru_alfia'}


def speech_input(body):
    text, voice = body.get('text'), body.get('voice')
    if voice not in SPEAKERS or not isinstance(text, str) or not 0 < len(text.strip()) <= 2000:
        raise ValueError('Invalid voice or text')
    if re.search(r'[A-Za-z0-9]', text):
        raise ValueError('Names and numbers must be written as Russian words')
    return text, voice


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, content_type='application/json'):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if hmac.compare_digest(self.headers.get('Authorization', '').encode(), self.server.authorization):
            return True
        self.reply(401, {'error': 'Unauthorized'})
        return False

    def do_GET(self):
        if self.authorized():
            self.reply(200 if self.path == '/health' else 404, {'engine': 'silero-v5-cis', 'voices': sorted(SPEAKERS)})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != '/speech':
            self.reply(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16000 or self.headers.get('Transfer-Encoding'):
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object')
            text, voice = speech_input(body)
        except (ValueError, TypeError):
            self.reply(400, {'error': 'Invalid voice or request text'})
            return
        try:
            # Preserve the translated spelling; automatic yo substitution can change word meanings.
            with self.server.inference:
                audio = self.server.model.apply_tts(text=text, speaker=voice, sample_rate=48000,
                    put_accent=False, put_yo=False)
            pcm = (audio.detach().cpu().clamp(-1, 1).numpy() * 32767).astype('<i2').tobytes()
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(48000); wav.writeframes(pcm)
            self.reply(200, output.getvalue(), 'audio/wav')
        except Exception:
            logging.exception('Silero synthesis failed')
            self.reply(503, {'error': 'Synthesis failed'})


class Server(ThreadingHTTPServer):
    # Viewers queue on the lock in the process, not in the kernel accept backlog.
    daemon_threads = True
    request_queue_size = 16
    inference = threading.Lock()

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address


if __name__ == '__main__':
    import torch
    token = os.environ.get('SYNCHRO_SILERO_TOKEN', '')
    if len(token) < 32:
        raise SystemExit('SYNCHRO_SILERO_TOKEN must be configured')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    model_path = os.environ.get('SYNCHRO_SILERO_MODEL', 'models/silero/v5_cis_base_nostress.pt')
    model = torch.package.PackageImporter(model_path).load_pickle('tts_models', 'model')
    model.to(torch.device('cpu'))
    if not SPEAKERS <= set(model.speakers):
        raise SystemExit('The configured Silero model is missing selected voices')
    port = int(os.environ.get('SYNCHRO_SILERO_PORT', '8776'))
    server = Server(('127.0.0.1', port), Handler)
    server.authorization = ('Bearer ' + token).encode()
    server.model = model
    logging.warning('Silero V5 CIS ready on loopback:%s, CPU only', port)
    server.serve_forever()
