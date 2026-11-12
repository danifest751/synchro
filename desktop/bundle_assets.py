"""Engine and model payload shared by the Windows and macOS bundles."""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / '.local/host-models'


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.cache'))
    else:
        shutil.copy2(source, target)


def copy_engine_models(bundle):
    sys.path.insert(0, str(ROOT / 'server'))
    from synchro.speaker import install_model
    install_model(MODELS / 'speaker/model.onnx')
    copy(MODELS / 'speaker/model.onnx', bundle / 'models/speaker/model.onnx')
    copy(ROOT / 'desktop/licenses', bundle / 'licenses')
    copy(ROOT / 'server/synchro', bundle / 'engine/synchro')
    copy(ROOT / 'deploy/gigaam_server.py', bundle / 'engine/deploy/gigaam_server.py')
    for name in ['config.json', 'multilingual_ctc.onnx', 'multilingual_vocab.txt']:
        copy(MODELS / 'gigaam' / name, bundle / 'models/gigaam' / name)
    for name in ['model.int8.onnx', 'tokens.txt']:
        copy(MODELS / 'sensevoice' / name, bundle / 'models/sensevoice' / name)
    for name in ['dictionary', 'nn']:
        copy(MODELS / 'ruaccent' / name, bundle / 'models/ruaccent' / name)
    copy(MODELS / 'silero-cis.pt', bundle / 'models/silero/v5_cis_base_nostress.pt')
    for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
        copy(ROOT / name, bundle / name)
    copy(ROOT / 'desktop/README.md', bundle / 'README.md')
    copy(ROOT / 'desktop/MACOS.md', bundle / 'MACOS.md')
