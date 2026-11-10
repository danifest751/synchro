"""Smoke-test original YouTube audio and translation against a running gateway."""
import base64
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
connection = json.loads((ROOT / '.local/connection.json').read_text())
headers = {'Authorization': 'Bearer ' + connection['token'],
           'Origin': 'chrome-extension://' + connection['extension_id'], 'Content-Type': 'application/json'}


def request(path, method='GET', data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(connection['server_url'] + path, headers=headers, method=method, data=body)
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response) if response.status != 204 else None


url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.youtube.com/watch?v=YmLp8qe87A0'
position = float(sys.argv[2]) if len(sys.argv) > 2 else 0
started = time.monotonic()
opened = request('/api/video', 'POST', {'url': url, 'position': position, 'voice': 'male'})
sid = opened['session_id']
print(json.dumps({'warmup_seconds': round(time.monotonic() - started, 2), 'duration': opened['duration']}), flush=True)
try:
    for index in range(2):
        started = time.monotonic()
        result = request('/api/video/' + sid + '/next', 'POST')
        for cue in result['segments']:
            assert cue['text'] and cue['source_duration'] > 0
            (ROOT / 'output').mkdir(exist_ok=True)
            (ROOT / 'output' / f'youtube-smoke-{cue["id"]}.wav').write_bytes(base64.b64decode(cue['wav']))
        assert result['ready_until'] > opened['base']
        print(json.dumps({'seconds': round(time.monotonic() - started, 2), 'ready_until': result['ready_until'],
                          'texts': [cue['text'] for cue in result['segments']]}, ensure_ascii=False), flush=True)
finally:
    request('/api/session/' + sid, 'DELETE')
