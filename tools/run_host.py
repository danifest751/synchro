"""Run Synchro with optional CPU speech models on this browser's computer."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--port', type=int, default=8778)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged loopback port')
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'server'), str(root)]
    for line in Path(args.env_file).read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            os.environ[key.strip()] = value.strip()
    os.environ['SYNCHRO_HOST_MODE'] = '1'
    if os.environ.get('SYNCHRO_FFMPEG_DIR'):
        os.environ['PATH'] = os.environ['SYNCHRO_FFMPEG_DIR'] + os.pathsep + os.environ.get('PATH', '')
    import uvicorn
    uvicorn.run('synchro.app:app', host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
