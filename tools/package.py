"""Build an extension ZIP; personal keys are included only with --client."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--client', help='Name of an existing personal connection, such as guest-1')
args = parser.parse_args()
connection = None
if args.client:
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', args.client) or args.client == 'owner':
        parser.error('Use an existing guest name; owner archives are not supported')
    registry = json.loads((ROOT / '.local/clients/tokens.json').read_text())
    connection = json.loads((ROOT / '.local/connections' / args.client / 'connection.json').read_text())
    record = registry[args.client]
    if record.get('disabled') or hashlib.sha256(connection['token'].encode()).hexdigest() != record['token_sha256']:
        parser.error('The personal connection is revoked or does not match the registry')

output = ROOT / 'output'
output.mkdir(exist_ok=True)
archive = output / ('Synchro-' + (args.client or 'extension') + '.zip')
files = sorted(path for path in (ROOT / 'extension').rglob('*') if path.is_file())
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
    for path in files:
        if path.is_symlink() or path.suffix not in {'.js', '.mjs', '.json', '.html', '.css'}:
            raise ValueError(f'Unexpected extension file: {path.name}')
        zipped.write(path, path.relative_to(ROOT).as_posix())
    for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
        zipped.write(ROOT / name, name)
    zipped.write(ROOT / 'docs/USER_GUIDE.md', 'USER_GUIDE.md')
    if connection:
        zipped.writestr('connection.json', json.dumps(connection, indent=2))
with zipfile.ZipFile(archive) as zipped:
    assert zipped.testzip() is None
    assert ('connection.json' in zipped.namelist()) == bool(connection)
    assert json.loads(zipped.read('extension/manifest.json'))['name'].startswith('Synchro')
    owner = ROOT / '.local/connection.json'
    owner_token = json.loads(owner.read_text())['token'].encode() if owner.exists() else None
    for name in zipped.namelist():
        data = zipped.read(name)
        assert b'PRIVATE KEY-----' not in data
        assert not owner_token or owner_token not in data
        assert name.startswith('extension/') or name in {'LICENSE', 'THIRD_PARTY_NOTICES.md', 'USER_GUIDE.md', 'connection.json'}
print(archive)
