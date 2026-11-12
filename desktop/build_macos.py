"""Build a self-contained Apple Silicon Synchro.app and drag-to-install DMG on macOS.

python3 desktop/build_macos.py [--skip-dmg]
Requires Rust, Xcode Command Line Tools and .local/host-models (same models as Windows).
Python, mpv and FFmpeg sources are downloaded with pinned SHA-256 checksums.
"""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib

from bundle_assets import ROOT, MODELS, copy, copy_engine_models

DIST = ROOT / 'desktop/dist/macos'
CACHE = ROOT / 'desktop/dist/cache'
APP = DIST / 'Synchro.app'
RESOURCES = APP / 'Contents/Resources'
PYTHON_URL = ('https://github.com/astral-sh/python-build-standalone/releases/download/20261110/'
              'cpython-3.12.16%2B20261110-aarch64-apple-darwin-install_only.tar.gz')
PYTHON_SHA = 'e956e60bc9465d577ef8062059aa05cd3a2665b4b8678a2ed24e432368330b8f'
MPV_URL = ('https://github.com/mpv-player/mpv/releases/download/git-release/'
           'mpv-v0.42.0-dev-gbcde6b93c-42858938464-macos-15-arm.zip')
MPV_SHA = '51617bf14b31f938bb4dc1e091cbeb1f8ffca1e546d45b424940991e9205ebc1'
FFMPEG_URL = 'https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz'
FFMPEG_SHA = '8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e'


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def download(name, url, checksum):
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
        return target
    temporary = target.with_suffix('.part')
    try:
        run('curl', '--fail', '--location', '--retry', '3', '--output', temporary, url)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != checksum:
            raise ValueError(f'Checksum mismatch: {name}')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def extract(archive, destination):
    """Also safe on the macOS system Python 3.9, which lacks tarfile's data filter."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as package:
        for member in package:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination) or member.isdev() or member.isfifo():
                raise ValueError('Unsafe archive member')
            if member.issym() or member.islnk():
                link = (target.parent if member.issym() else destination) / member.linkname
                if not link.resolve().is_relative_to(destination):
                    raise ValueError('Unsafe archive link')
            package.extract(member, destination, filter='data') if sys.version_info >= (3, 12) else package.extract(member, destination)


def runtime():
    python = RESOURCES / 'runtime/bin/python3'
    if not python.is_file():
        archive = download('python-macos-arm64.tar.gz', PYTHON_URL, PYTHON_SHA)
        with tempfile.TemporaryDirectory(dir=CACHE) as directory:
            extract(archive, directory)
            shutil.copytree(Path(directory) / 'python', RESOURCES / 'runtime', symlinks=True, dirs_exist_ok=True)
    run(python, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location',
        'torch>=2.8,<3', '-r', ROOT / 'desktop/requirements.txt')
    certs = RESOURCES / 'runtime/lib/python3.12/site-packages/pip/_vendor/certifi/cacert.pem'
    if certs.is_file():
        os.environ.setdefault('SSL_CERT_FILE', str(certs))
    package = Path(subprocess.check_output([str(python), '-c',
        'import ruaccent; from pathlib import Path; print(Path(ruaccent.__file__).parent)'], text=True).strip())
    copy(MODELS / 'ruaccent/koziev', package / 'koziev')


def media_tools():
    wrapper = download('mpv-macos-arm64.zip', MPV_URL, MPV_SHA)
    with tempfile.TemporaryDirectory(dir=CACHE) as directory:
        nested = Path(directory) / 'mpv.tar.gz'
        with zipfile.ZipFile(wrapper) as archive, archive.open('mpv.tar.gz') as source, nested.open('wb') as output:
            shutil.copyfileobj(source, output)
        extract(nested, Path(directory) / 'mpv')
        shutil.copytree(Path(directory) / 'mpv/mpv.app', RESOURCES / 'mpv/mpv.app', symlinks=True, dirs_exist_ok=True)
    source = download('ffmpeg-9.0.2.tar.xz', FFMPEG_URL, FFMPEG_SHA)
    tools = ROOT / '.local/host-tools'
    stamp = tools / '.ffmpeg-sha256'
    binary = tools / 'ffmpeg'
    if not binary.is_file() or not stamp.is_file() or stamp.read_text().strip() != FFMPEG_SHA:
        extract(source, CACHE)
        folder = CACHE / 'ffmpeg-9.0.2'
        run('./configure', '--disable-doc', '--disable-debug', '--disable-ffplay', '--disable-ffprobe',
            '--disable-shared', '--enable-static', '--disable-autodetect', '--enable-zlib',
            '--extra-cflags=-mmacosx-version-min=15.0', '--extra-ldflags=-mmacosx-version-min=15.0', cwd=folder)
        run('make', f'-j{min(os.cpu_count() or 2, 4)}', 'ffmpeg', cwd=folder)
        copy(folder / 'ffmpeg', binary)
        stamp.write_text(FFMPEG_SHA + '\n')
    copy(binary, RESOURCES / 'tools/ffmpeg')


def app_icon():
    size = 1024
    pixels = bytearray(bytes([22, 25, 28, 255]) * size * size)
    for index, height in enumerate([320, 704, 480, 224]):
        for y in range((size - height) // 2, (size + height) // 2):
            start = (y * size + 192 + index * 192) * 4
            pixels[start:start + 64 * 4] = bytes([137, 205, 177, 255]) * 64
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(b''.join(b'\0' + pixels[y * size * 4:(y + 1) * size * 4] for y in range(size))))
    png += chunk(b'IEND', b'')
    with tempfile.TemporaryDirectory(dir=CACHE) as directory:
        source = Path(directory) / 'source.png'
        source.write_bytes(png)
        iconset = Path(directory) / 'Synchro.iconset'
        iconset.mkdir()
        for base in [16, 32, 128, 256, 512]:
            for scale in [1, 2]:
                target = iconset / f'icon_{base}x{base}{"@2x" if scale == 2 else ""}.png'
                run('sips', '-z', base * scale, base * scale, source, '--out', target, stdout=subprocess.DEVNULL)
        run('iconutil', '-c', 'icns', iconset, '-o', RESOURCES / 'Synchro.icns')


def verify_links(root):
    """Reject a bundle that still needs Homebrew or files from the build machine."""
    magic = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}
    for path in Path(root).rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as source:
            if source.read(4) not in magic:
                continue
        report = subprocess.check_output(['otool', '-L', str(path)], text=True)
        identity = {line.strip() for line in subprocess.check_output(['otool', '-D', str(path)], text=True).splitlines()[1:]}
        for line in report.splitlines()[1:]:
            if not line.startswith((' ', '\t')):
                continue  # Universal binaries have an unindented header for each architecture.
            dependency = line.strip().split(' (', 1)[0]
            if dependency in identity:
                continue  # LC_ID_DYLIB identifies this file; it is not a loaded dependency.
            if dependency.startswith('/') and not dependency.startswith(('/usr/lib/', '/System/Library/')):
                raise ValueError(f'Non-portable library in {path}: {dependency}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skip-dmg', action='store_true', help='Build the .app without creating a disk image')
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        parser.error('Build on an Apple Silicon Mac; this bundle targets macOS 15 or later')
    DIST.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    RESOURCES.mkdir(parents=True, exist_ok=True)
    runtime()
    copy_engine_models(RESOURCES)
    media_tools()
    cargo = shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo')
    environment = {**os.environ, 'MACOSX_DEPLOYMENT_TARGET': '15.0'}
    run(cargo, 'build', '--release', '--manifest-path', ROOT / 'desktop/Cargo.toml', env=environment)
    copy(ROOT / 'desktop/target/release/synchro-desktop', APP / 'Contents/MacOS/Synchro')
    version = next(line.split('"')[1] for line in (ROOT / 'desktop/Cargo.toml').read_text().splitlines() if line.startswith('version'))
    plist = {'CFBundleName': 'Synchro', 'CFBundleDisplayName': 'Synchro', 'CFBundleExecutable': 'Synchro',
             'CFBundleIdentifier': 'app.synchro.desktop', 'CFBundlePackageType': 'APPL',
             'CFBundleShortVersionString': version, 'CFBundleVersion': version, 'CFBundleIconFile': 'Synchro',
             'CFBundleDevelopmentRegion': 'en', 'CFBundleLocalizations': ['en', 'ru'],
             'LSMinimumSystemVersion': '15.0', 'NSHighResolutionCapable': True}
    (APP / 'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
    app_icon()
    (RESOURCES / 'licenses/macos-tools.txt').write_text(
        f'mpv upstream CI build bcde6b93c: {MPV_URL}\nSource and dependencies: https://github.com/mpv-player/mpv/tree/bcde6b93c\n'
        f'FFmpeg 9.0.2 source: {FFMPEG_URL}\nSHA256: {FFMPEG_SHA}\n'
        'FFmpeg uses only Apple system libraries; configure flags are in desktop/build_macos.py.\n'
        'Runtime and library licenses remain applicable; see THIRD_PARTY_NOTICES.md and runtime/ package metadata.\n')
    for cache in RESOURCES.rglob('__pycache__'):
        shutil.rmtree(cache)
    for metadata in RESOURCES.rglob('._*'):
        if metadata.is_file():
            metadata.unlink()  # ditto merges AppleDouble sidecars, which would invalidate sealed resources.
    verify_links(APP)
    run('codesign', '--force', '--deep', '--sign', '-', APP)
    run('codesign', '--verify', '--deep', '--strict', APP)
    if not args.skip_dmg:
        image = DIST / f'Synchro-{version}-macos-arm64.dmg'
        with tempfile.TemporaryDirectory(dir=DIST) as directory:
            stage = Path(directory)
            run('ditto', APP, stage / 'Synchro.app')
            run('codesign', '--verify', '--deep', '--strict', stage / 'Synchro.app')
            (stage / 'Applications').symlink_to('/Applications', target_is_directory=True)
            run('hdiutil', 'create', '-volname', 'Synchro', '-srcfolder', stage, '-ov', '-format', 'UDZO', image)
        run('hdiutil', 'verify', image)
        print(f'Disk image: {image}', flush=True)
    print(f'Application: {APP}', flush=True)


if __name__ == '__main__':
    main()
