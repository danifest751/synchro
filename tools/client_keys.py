"""Create or revoke personal connections without printing access keys."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['add', 'revoke'])
parser.add_argument('name')
parser.add_argument('--connection', type=Path, default=ROOT / '.local/connection.json', help='Owner connection used for server URL and extension ID')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', args.name) or args.name == 'owner':
    parser.error('Use a name such as guest-1; owner is reserved')
store = ROOT / '.local/clients/tokens.json'
store.parent.mkdir(parents=True, exist_ok=True)
clients = json.loads(store.read_text()) if store.exists() else {}
if args.action == 'revoke':
    if args.name not in clients:
        parser.error('Key not found')
    clients[args.name]['disabled'] = True
else:
    if args.name in clients and not clients[args.name].get('disabled'):
        parser.error('Key already exists; revoke it before replacing it')
    owner = json.loads(args.connection.read_text())
    token = secrets.token_urlsafe(32)
    clients[args.name] = {'token_sha256': hashlib.sha256(token.encode()).hexdigest(), 'disabled': False}
    connection = ROOT / '.local/connections' / args.name / 'connection.json'
    connection.parent.mkdir(parents=True, exist_ok=True)
    connection.parent.chmod(0o700)
    connection.write_text(json.dumps({'server_url': owner['server_url'], 'token': token,
                                      'client': args.name, 'extension_id': owner['extension_id']}, indent=2))
    connection.chmod(0o600)
    print('Connection saved:', connection)
store.write_text(json.dumps(clients, indent=2))
print('Registry updated:', store)
