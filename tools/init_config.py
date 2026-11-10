"""Generate a new private configuration without overwriting existing files."""
import argparse
import json
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--server-url', default='http://127.0.0.1:8768')
parser.add_argument('--extension-id', default='ngidmicmdihpmmafpelcfmllcefokieg')
args = parser.parse_args()
url = urlsplit(args.server_url)
if (not re.fullmatch(r'[a-p]{32}', args.extension_id) or not url.hostname
        or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment
        or (url.scheme != 'https' and args.server_url != 'http://127.0.0.1:8768')
        or any(char.isspace() for char in args.server_url)):
    parser.error('Use an HTTPS origin (or the default loopback URL) and a 32-letter extension ID')
local = ROOT / '.local'
destinations = [local / name for name in ['connection.json', 'gateway.env', 'asr.env', 'silero.env', 'clients/tokens.json']]
if any(path.exists() for path in destinations):
    parser.error('Private configuration already exists; edit it manually instead of overwriting keys')
owner, asr, silero = [secrets.token_urlsafe(32) for _ in range(3)]
connection = {'server_url': args.server_url.rstrip('/'), 'token': owner, 'extension_id': args.extension_id}
gateway = {
    'SYNCHRO_TOKEN': owner, 'SYNCHRO_ORIGIN': 'chrome-extension://' + args.extension_id,
    'SYNCHRO_CLIENTS_FILE': str(local / 'clients/tokens.json'), 'SYNCHRO_MAX_SESSIONS': '3',
    'SPEECH_URL': 'http://127.0.0.1:8002', 'SYNCHRO_LLM_API': 'llama',
    'OLLAMA_URL': 'http://127.0.0.1:11436', 'SYNCHRO_MODEL': 'synchro-translator',
    'SYNCHRO_ASR_URL': 'http://127.0.0.1:3008', 'SYNCHRO_ASR_TOKEN': asr,
    'SYNCHRO_SILERO_URL': 'http://127.0.0.1:8776', 'SYNCHRO_SILERO_TOKEN': silero,
}
contents = [json.dumps(connection, indent=2), ''.join(f'{key}={value}\n' for key, value in gateway.items()),
            'SYNCHRO_ASR_TOKEN=' + asr + '\n', 'SYNCHRO_SILERO_TOKEN=' + silero + '\n', '{}\n']
for path, content in zip(destinations, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    with path.open('x', encoding='utf-8') as stream:
        path.chmod(0o600)
        stream.write(content)
print('Private configuration created in .local/. Import connection.json into the extension; do not publish it.')
