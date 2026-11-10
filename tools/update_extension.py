"""Update an existing unpacked Synchro extension from verified GitHub release assets."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.request
import zipfile

REPOSITORY = 'danifest751/synchro'
RELEASE_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'


def download(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'Synchro-extension-updater', 'Accept': 'application/vnd.github+json' if url == RELEASE_URL else 'application/octet-stream'})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError('Release exceeds the download size limit')
    return content


def version(value):
    if not re.fullmatch(r'\d+(?:\.\d+){0,3}', value or ''):
        raise ValueError('Invalid extension version')
    parts = tuple(int(part) for part in value.split('.'))
    return parts + (0,) * (4 - len(parts))


def install(content, target, expected_version):
    target = Path(target).resolve(strict=True)
    current = json.loads((target / 'manifest.json').read_text(encoding='utf-8-sig'))
    if not current.get('name', '').startswith('Synchro'):
        raise ValueError('Target is not a Synchro extension')
    files = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if len(archive.infolist()) > 200 or sum(item.file_size for item in archive.infolist()) > 20_000_000:
            raise ValueError('Unexpected release archive size')
        for item in archive.infolist():
            path = Path(item.filename)
            if '\\' in item.filename or path.is_absolute() or '..' in path.parts or item.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError('Unsafe release archive path')
            if item.filename.startswith('extension/') and not item.is_dir():
                relative = path.relative_to('extension').as_posix()
                if path.suffix not in {'.js', '.mjs', '.json', '.html', '.css'} or relative in files:
                    raise ValueError('Unexpected or duplicate extension file')
                files[relative] = archive.read(item)
    manifest = json.loads(files['manifest.json'])
    if manifest.get('version') != expected_version or not manifest.get('name', '').startswith('Synchro'):
        raise ValueError('Release version or application does not match its manifest')
    if set(manifest.get('permissions', [])) - set(current.get('permissions', [])):
        raise ValueError('New extension permissions require a manual update')
    for key in ['host_permissions', 'content_security_policy', 'key']:
        if key in current:
            manifest[key] = current[key]
    files['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    # Private deployments keep their configured API allowlist across public updates.
    connection = (target / 'connection.mjs').read_text(encoding='utf-8')
    updated = files['connection.mjs'].decode('utf-8')
    for constant in ['PUBLIC_API', 'LOCAL_API']:
        pattern = r"(export const " + constant + r" = )('[^'\r\n]*'|\"[^\"\r\n]*\");"
        match = re.search(pattern, connection)
        if not match or len(re.findall(pattern, updated)) != 1:
            raise ValueError('Cannot preserve the installed server allowlist')
        updated = re.sub(pattern, lambda new: new[1] + match[2] + ';', updated)
    files['connection.mjs'] = updated.encode('utf-8')
    for name in files:
        if not (target / name).resolve().is_relative_to(target) or (target / name).is_symlink():
            raise ValueError('Extension target contains an unsafe link')
    backup = target.parent / '.synchro-update-backups' / f'{current["version"]}-{time.time_ns()}'
    shutil.copytree(target, backup)
    try:
        # The extension notices the version change only after all scripts are in place.
        for name in [name for name in files if name != 'manifest.json'] + ['manifest.json']:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix='.synchro-update') as temporary:
                temporary.write(files[name])
                temporary_path = Path(temporary.name)
            temporary_path.replace(path)
    except BaseException:
        shutil.copytree(backup, target, dirs_exist_ok=True)
        raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, help='Existing unpacked extension folder')
    parser.add_argument('--check', action='store_true', help='Check without changing files')
    args = parser.parse_args()
    target = Path(args.target).resolve(strict=True)
    current = json.loads((target / 'manifest.json').read_text(encoding='utf-8-sig'))
    release = json.loads(download(RELEASE_URL, 2_000_000))
    tag = release['tag_name']
    latest = tag.removeprefix('v')
    if release.get('draft') or release.get('prerelease') or version(latest) <= version(current['version']):
        print('Synchro is up to date')
        return
    asset = next(item for item in release['assets'] if item['name'] == 'Synchro-extension.zip')
    url = asset['browser_download_url']
    if url != f'https://github.com/{REPOSITORY}/releases/download/{tag}/Synchro-extension.zip':
        raise ValueError('Release asset is outside the configured repository')
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('GitHub did not provide a verified asset digest')
    if args.check:
        print('Synchro update available: ' + latest)
        return
    content = download(url, 5_000_000)
    if hashlib.sha256(content).hexdigest() != digest[7:]:
        raise ValueError('Release checksum does not match GitHub metadata')
    backup = install(content, target, latest)
    print(f'Synchro {latest} installed. Chrome will reload after playback. Backup: {backup}')


if __name__ == '__main__':
    main()
