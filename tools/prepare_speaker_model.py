"""Download the pinned local speaker classifier for desktop development."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from synchro.speaker import install_model

if __name__ == '__main__':
    target = ROOT / '.local/host-models/speaker/model.onnx'
    install_model(target)
    print(f'Speaker model verified: {target}')
