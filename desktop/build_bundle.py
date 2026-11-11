"""Assemble the Synchro desktop bundle and its Windows installer.

python desktop/build_bundle.py [--skip-installer] [--test-video clip.mp4]

Inputs: the portable Python runtime (downloaded, SHA-256 pinned), engine packages from PyPI and the PyTorch CPU
index, this repository's engine code, and local files: models in .local/host-models, FFmpeg in .local/host-tools and
mpv in .local/host-tools/mpv. Output: desktop/dist/Synchro (the installed layout) and desktop/dist/installer.
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'desktop' / 'dist'
BUNDLE = DIST / 'Synchro'
PYTHON = ('https://github.com/astral-sh/python-build-standalone/releases/download/20261110/'
          'cpython-3.12.16+20261110-x86_64-pc-windows-msvc-install_only.tar.gz')
PYTHON_SHA256 = 'e23fe5b16926de1d81661b1a97352e89fb167549c55a6825796ccd0f32ec7f1b'
MODELS = ROOT / '.local' / 'host-models'
TOOLS = ROOT / '.local' / 'host-tools'
INNO = [Path(r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'), Path.home() / r'AppData\Local\Programs\Inno Setup 6\ISCC.exe']


def step(text):
    print('==', text, flush=True)


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.cache'))
    else:
        shutil.copy2(source, target)


def runtime():
    cache = DIST / 'cache' / PYTHON.rsplit('/', 1)[1]
    if not cache.is_file():
        step('download portable Python')
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(PYTHON, timeout=120) as response, open(cache.with_suffix('.part'), 'wb') as out:
            shutil.copyfileobj(response, out)
        cache.with_suffix('.part').replace(cache)
    if hashlib.sha256(cache.read_bytes()).hexdigest() != PYTHON_SHA256:
        cache.unlink()
        sys.exit('Portable Python checksum mismatch; download removed')
    step('unpack Python and install engine packages')
    with tempfile.TemporaryDirectory(dir=DIST) as temp, tarfile.open(cache) as archive:
        archive.extractall(temp, filter='data')
        shutil.move(Path(temp) / 'python', BUNDLE / 'runtime')
    python = BUNDLE / 'runtime' / 'python.exe'
    run(python, '-m', 'pip', 'install', '--no-cache-dir', '--disable-pip-version-check', '--no-warn-script-location',
        '--index-url', 'https://download.pytorch.org/whl/cpu', 'torch>=2.8,<3')
    run(python, '-m', 'pip', 'install', '--no-cache-dir', '--disable-pip-version-check', '--no-warn-script-location',
        '-r', ROOT / 'desktop' / 'requirements.txt')
    # RUAccent looks for its morphology data inside the installed package.
    package = Path(subprocess.check_output([python, '-c', 'import ruaccent, os; print(os.path.dirname(ruaccent.__file__))'], text=True).strip())
    copy(MODELS / 'ruaccent' / 'koziev', package / 'koziev')


def payload():
    step('engine code, models, FFmpeg and mpv')
    copy(ROOT / 'server' / 'synchro', BUNDLE / 'engine' / 'synchro')
    copy(ROOT / 'deploy' / 'gigaam_server.py', BUNDLE / 'engine' / 'deploy' / 'gigaam_server.py')
    for name in ['config.json', 'multilingual_ctc.onnx', 'multilingual_vocab.txt']:
        copy(MODELS / 'gigaam' / name, BUNDLE / 'models' / 'gigaam' / name)
    for name in ['model.int8.onnx', 'tokens.txt']:
        copy(MODELS / 'sensevoice' / name, BUNDLE / 'models' / 'sensevoice' / name)
    for name in ['dictionary', 'nn']:
        copy(MODELS / 'ruaccent' / name, BUNDLE / 'models' / 'ruaccent' / name)
    copy(MODELS / 'silero-cis.pt', BUNDLE / 'models' / 'silero' / 'v5_cis_base_nostress.pt')
    copy(TOOLS / 'ffmpeg.exe', BUNDLE / 'tools' / 'ffmpeg.exe')
    for name in ['mpv.exe', 'd3dcompiler_43.dll', 'mpv']:
        copy(TOOLS / 'mpv' / name, BUNDLE / 'mpv' / name)
    for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
        copy(ROOT / name, BUNDLE / name)
    copy(ROOT / 'desktop' / 'README.md', BUNDLE / 'README.md')


def player():
    step('build Synchro.exe')
    run('cargo', 'build', '--release', '--manifest-path', ROOT / 'desktop' / 'Cargo.toml')
    copy(ROOT / 'desktop' / 'target' / 'release' / 'synchro-desktop.exe', BUNDLE / 'Synchro.exe')


def self_test(video):
    step('self-test the bundle')
    report = Path.home() / 'AppData' / 'Local' / 'Synchro' / 'self-test.txt'
    report.unlink(missing_ok=True)
    subprocess.run([str(BUNDLE / 'Synchro.exe'), '--self-test', str(video)], timeout=600)
    text = report.read_text(encoding='utf-8') if report.exists() else 'FAILED: no report'
    print(text)
    if text.startswith('FAILED'):
        sys.exit('The bundle failed its self-test')


def installer():
    compiler = next((path for path in INNO if path.is_file()), None)
    if not compiler:
        sys.exit('Inno Setup 6 (ISCC.exe) is required for the installer')
    step('build the installer')
    version = next(line.split('"')[1] for line in (ROOT / 'desktop' / 'Cargo.toml').read_text().splitlines() if line.startswith('version'))
    run(compiler, f'/DAppVersion={version}', f'/DBundle={BUNDLE}', f'/DOutput={DIST / "installer"}', ROOT / 'desktop' / 'installer.iss')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skip-installer', action='store_true')
    parser.add_argument('--test-video', type=Path, help='Translate two windows of this video with the finished bundle')
    parser.add_argument('--installer-only', action='store_true', help='Package an already built desktop/dist/Synchro')
    args = parser.parse_args()
    if args.installer_only:
        return installer()
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    BUNDLE.mkdir(parents=True)
    runtime()
    payload()
    player()
    if args.test_video:
        self_test(args.test_video)
    if not args.skip_installer:
        installer()
    step(f'done: {BUNDLE}')


if __name__ == '__main__':
    main()
