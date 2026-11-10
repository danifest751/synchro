"""Install compatible eSpeak data: Piper 1.2 ignores U+0301 stress marks."""
import hashlib
import io
from pathlib import Path
import sys
import urllib.request
import zipfile

URL = 'https://files.pythonhosted.org/packages/84/81/0112a7d510911f33018dc24023d1655bb772f84a4e95fe7f0180f66bbd17/piper_tts-1.8.0-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.manylinux_2_28_x86_64.whl'
SHA256 = '25b4d3f31ff70c8fa7151908e00aaa5650cbdf16bca8fcf21299f3941b89a7d3'
with urllib.request.urlopen(URL, timeout=120) as response:
    data = response.read()
if hashlib.sha256(data).hexdigest() != SHA256:
    raise RuntimeError('Piper package checksum mismatch')
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    names = [name for name in archive.namelist() if name.endswith('/espeak-ng-data/ru_dict')]
    if len(names) != 1:
        raise RuntimeError('Expected exactly one Russian dictionary')
    prefix = names[0][:-len('ru_dict')]
    destination = Path(sys.argv[1])
    for name in archive.namelist():
        if not name.startswith(prefix) or name.endswith('/'):
            continue
        relative = Path(name[len(prefix):])
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Invalid path in the eSpeak archive')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(name))
print('eSpeak data extracted from the verified Piper 1.8.0 package')
