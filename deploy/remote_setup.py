"""Build and run Linux Docker services using .local/gateway.env."""
import os
from pathlib import Path
import subprocess
import json

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
env_path = ROOT / '.local/gateway.env'
if not env_path.is_file():
    raise SystemExit('Run tools/init_config.py first; see docs/DEPLOYMENT.md')
clients = ROOT / '.local/clients'
if not (clients / 'tokens.json').is_file():
    raise SystemExit('The private client registry is missing')
for name in ['synchro-speech', 'synchro-gateway']:
    result = subprocess.run(['docker', 'inspect', name], capture_output=True)
    if result.returncode == 0 and json.loads(result.stdout)[0]['Config'].get('Labels', {}).get('app') != 'synchro':
        raise RuntimeError(f'Container name already in use: {name}')

def run(*args):
    subprocess.run(args, check=True)

run('docker', 'build', '-t', 'synchro-speech:prototype', '-f', 'deploy/speech.Dockerfile', 'deploy')
run('docker', 'build', '-t', 'synchro-gateway:prototype', '-f', 'deploy/gateway.Dockerfile', '.')
for name in ['synchro-speech', 'synchro-gateway']:
    if subprocess.run(['docker', 'inspect', name], capture_output=True).returncode == 0:
        run('docker', 'rm', '-f', name)
run('docker', 'run', '-d', '--name', 'synchro-speech', '--label', 'app=synchro', '--restart', 'unless-stopped',
    '--gpus', 'device=' + os.environ.get('SYNCHRO_SPEECH_GPU', '0'), '-p', '127.0.0.1:8002:8000',
    '-e', 'HF_HUB_DISABLE_TELEMETRY=1',
    '--mount', 'type=volume,source=synchro-hf-cache,target=/home/ubuntu/.cache/huggingface/hub',
    'synchro-speech:prototype')
run('docker', 'run', '-d', '--name', 'synchro-gateway', '--label', 'app=synchro', '--restart', 'unless-stopped',
    '--network', 'host', '--env-file', str(env_path),
    '-e', 'SYNCHRO_CLIENTS_FILE=/run/synchro-clients/tokens.json',
    '--mount', f'type=bind,src={clients},dst=/run/synchro-clients,readonly', 'synchro-gateway:prototype')
print('Docker services started. Translation, GigaAM and Silero must run separately.')
