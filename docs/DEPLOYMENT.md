# Server deployment

These instructions describe a self-hosted prototype, not a one-command appliance. Install model weights and inference runtimes separately. Examples target Linux with systemd and Docker; the browser may run on Windows, Linux, or macOS.

## Prerequisites

- Python 3.11 or newer; the reference inference host uses Python 3.12.
- Node.js 22 or newer for yt-dlp's YouTube JavaScript challenges.
- FFmpeg in PATH, including `atempo` and `loudnorm` filters.
- An NVIDIA driver and NVIDIA Container Toolkit for the provided GPU speech container.
- A CUDA-enabled llama.cpp build compatible with the selected GPU and model.
- Sufficient RAM, disk, and VRAM for all selected models. The reference Gemma 26B-A4B setup uses nearly all of a 16 GB card; put Whisper on another card or choose smaller models when needed.

Clone into `~/synchro` if using the supplied user-service templates. The public examples contain no access credentials or working public endpoint.

## 1. Generate private configuration

From the repository root:

```bash
python3 tools/init_config.py
chmod 700 .local .local/clients
```

This creates `.local/connection.json`, `gateway.env`, `asr.env`, `silero.env`, and an empty client registry. The owner, ASR, and TTS keys are independent random values. The command refuses to overwrite existing configuration. These files are ignored by Git and must remain private. On Windows, restrict their ACLs to the operator; Unix chmod permissions are not a Windows ACL substitute.

For a public endpoint, use `--server-url https://your-synchro-host.example`. For a different extension identity, pass `--extension-id` and use that same ID in the gateway Origin. The included manifest produces `ngidmicmdihpmmafpelcfmllcefokieg`; verify the actual browser ID after installation.

## 2. Start local text translation

Obtain a supported instruction-tuned GGUF model from its publisher and review its license. Put it at `models/translation.gguf`, or change the service path. The reference model is Gemma 4 26B-A4B. Benchmark alternatives are not automatically integrated: models that cannot obey the structured-output translation contract need an adapter.

Build [llama.cpp](https://github.com/ggml-org/llama.cpp) with CUDA for your GPU. The sample unit expects `~/llama.cpp/build/bin/llama-server`:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/llama.service ~/.config/systemd/user/synchro-llama.service
systemctl --user daemon-reload
systemctl --user enable --now synchro-llama
```

Edit `CUDA_VISIBLE_DEVICES=0` to the intended GPU index or UUID. The alias `synchro-translator` must match `SYNCHRO_MODEL` in `.local/gateway.env`. The service listens on loopback port 11436. Context and slot counts affect VRAM; test capacity before increasing them.

The reference installation also used an MTP draft model and a compatible custom llama.cpp build: `-md /path/to/draft.gguf --spec-type draft-mtp --spec-draft-n-max 4 -ngld 999`. Those optional flags are deliberately absent from the generic unit. Verify support in your build and model before enabling them.

## 3. Start GigaAM recognition on CPU

Use a dedicated environment and download the [ONNX export](https://huggingface.co/istupakov/gigaam-multilingual-ctc-onnx) of [GigaAM Multilingual](https://huggingface.co/ai-sage/GigaAM-Multilingual):

```bash
python3 -m venv .venv-asr
.venv-asr/bin/pip install 'onnx-asr[cpu,hub]' huggingface-hub
.venv-asr/bin/hf download istupakov/gigaam-multilingual-ctc-onnx --local-dir models/gigaam
set -a
. .local/asr.env
set +a
export SYNCHRO_ASR_MODEL="$PWD/models/gigaam"
.venv-asr/bin/python deploy/gigaam_server.py
```

Keep that process running in its own terminal or service. The default is loopback:3008 and eight CPU threads. The model directory must contain the complete ONNX model, configuration, and vocabulary expected by onnx-asr. For reproducible deployments, pin downloaded revisions and runtime versions after validating them on your hardware.

For a separate system-level ASR host, `deploy/gigaam.service` is a template using `/opt/synchro-asr/.venv`, `/opt/synchro-asr/gigaam_server.py`, and `/etc/synchro-asr.env`. Set an absolute `SYNCHRO_ASR_MODEL` there and make weights readable by the dynamic service user. Copy only the ASR key, never an owner connection. Point the gateway at an SSH-forwarded loopback port if ASR runs elsewhere.

## 4. Start Silero synthesis on CPU

Install a CPU PyTorch build appropriate for your platform in `.venv-speech`. Obtain the Russian **v5.5** `v5_5_ru.pt` package from the [Silero project](https://github.com/snakers4/silero-models). Put it in `models/silero/v5_5_ru.pt`, or set `SYNCHRO_SILERO_MODEL` in `.local/silero.env`. Obtain files only from a trusted source: PyTorch packages contain executable model code.

```bash
python3 -m venv .venv-speech
.venv-speech/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
cp deploy/silero.service ~/.config/systemd/user/synchro-silero.service
systemctl --user daemon-reload
systemctl --user enable --now synchro-silero
```

The service uses eight threads and loopback:8776. Supported speakers are `xenia`, `aidar`, and `eugene`. Built-in stress handling is enabled; automatic yo substitution is disabled to preserve spelling. Consult [license notes](MODELS.md) before commercial use of model weights.

## 5. Start the gateway and Whisper fallback

Check `.local/gateway.env` against your actual endpoints, then run:

```bash
python3 deploy/remote_setup.py
```

This builds the two Docker images and replaces only containers named `synchro-gateway` and `synchro-speech` carrying the `app=synchro` label. Replacement ends active sessions. It does not start or modify systemd inference services. The speech container downloads model files into its own `synchro-hf-cache` volume on demand; the first request may need a long download. Preload `deepdml/faster-whisper-large-v3-turbo-ct2` using the Speaches model-management API for your image before serving users.

To assign the fallback speech container to a different GPU:

```bash
SYNCHRO_SPEECH_GPU=1 python3 deploy/remote_setup.py
```

Use Linux host networking for the gateway: inference services remain on loopback. Do not run multiple gateway workers; sessions are in memory. Confirm `curl http://127.0.0.1:8768/health`, then test the authenticated connection using the extension.

For development without Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
set -a
. .local/gateway.env
set +a
cd server
../.venv/bin/python -m uvicorn synchro.app:app --host 127.0.0.1 --port 8768 --no-access-log
```

Whisper still needs an external Speaches service at `SPEECH_URL`. FFmpeg and Node must be available in the gateway environment. The optional Piper TTS path additionally requires an operator-provided `/accent` service at loopback:8775 that returns `{"text":"..."}` with plus-before-vowel stress markers; it is not included here. Silero does not use this service.

## Gateway environment reference

| Variable | Purpose |
| --- | --- |
| `SYNCHRO_TOKEN` | Private owner bearer key; required |
| `SYNCHRO_ORIGIN` | Exact `chrome-extension://<id>`; required |
| `SYNCHRO_CLIENTS_FILE` | JSON registry of hashed guest keys |
| `SYNCHRO_MAX_SESSIONS` | Shared session limit; generated default 3 |
| `SPEECH_URL` | Speaches base URL; default loopback:8002 |
| `SYNCHRO_LLM_API` | `llama` or `ollama` |
| `OLLAMA_URL` | Translation base URL for either backend; generated llama default loopback:11436 |
| `SYNCHRO_MODEL` | Translation model alias or Ollama model name |
| `SYNCHRO_ASR_URL`, `SYNCHRO_ASR_TOKEN` | Optional GigaAM endpoint and its private key; empty URL uses Whisper |
| `SYNCHRO_SILERO_URL`, `SYNCHRO_SILERO_TOKEN` | Silero endpoint and private key; empty URL selects legacy Piper |
| `YTDLP_PROXY` | Optional proxy for server-side YouTube access |
| `SYNCHRO_CLOUD_PROXY` | Optional HTTPS CONNECT proxy route for cloud API calls only |
| `SYNCHRO_KILO_TUNNEL_PORT`, `SYNCHRO_OPENROUTER_TUNNEL_PORT`, `SYNCHRO_OPENAI_TUNNEL_PORT` | Optional existing loopback TCP forwards to provider HTTPS; 0 means unset; TLS Host/SNI are preserved |

The app's bare defaults retain the older Ollama endpoint (11435) and model name; `init_config.py` generates the recommended llama.cpp configuration explicitly.

## Remote browser access and HTTPS

For a personal browser, an SSH forward avoids exposing the backend: `ssh -N -L 8768:127.0.0.1:8768 user@inference-host`. The extension can then use its default loopback URL.

For other viewers, configure HTTPS and explicitly allow your endpoint in all three places:

1. `PUBLIC_API` in `extension/connection.mjs`.
2. `host_permissions` and `content_security_policy.extension_pages` in `extension/manifest.json`.
3. The site address in `deploy/Caddyfile`.

Replace `https://synchro.example.com` with your actual HTTPS origin. Keep exact-origin validation; do not replace it with unrestricted credential forwarding. Repackage the extension after changes. Ensure generated connection files use the same URL.

On a single host, change Caddy's upstream from 18768 to 8768. On a separate public gateway, adapt `deploy/public_tunnel.service` to forward gateway loopback:18768 to inference loopback:8768. Its reverse-direction ASR forward is optional. Restrict the SSH account to the necessary `PermitListen`/`PermitOpen` ports, disable interactive shell access, and provision trusted host keys before startup. Keep model ports private.

The Caddy example disables upstream keepalive because Uvicorn or an SSH tunnel may close idle HTTP/1 connections before Caddy, causing a subsequent POST to fail with 502. Validate the adapted configuration before reloading Caddy. DNS, TLS certificates, firewall rules, and public-host provisioning are operator responsibilities.

## YouTube network access

If server egress can access YouTube, no extra proxy is needed. Otherwise, the optional Windows helper forwards a restricted local CONNECT proxy:

```powershell
powershell -File tools/connect.ps1 -Server user@inference-host -IdentityFile C:/path/to/private-key
```

Set `YTDLP_PROXY=http://127.0.0.1:18770` in the gateway environment and restart it. To route cloud API calls through the same tunnel, also set `SYNCHRO_CLOUD_PROXY=http://127.0.0.1:18770`. The helper requires Python, OpenSSH, and the operator's working network route to the permitted services. It forwards the local proxy on 18769 and the gateway on 8768 when that port is free. `-ProxyPort` and `-RemoteProxyPort` can select another local/remote port pair. If the operator's computer or tunnel stops, new audio fetches and proxied cloud requests fail. Recipients need only the extension and HTTPS access.

## Issue and revoke guest keys

```bash
python3 tools/client_keys.py add guest-1
python3 tools/package.py --client guest-1
python3 tools/client_keys.py revoke guest-1
```

Give one private ZIP to one person. Upload the updated `.local/clients/tokens.json` to the inference host's mounted registry directory when generating keys on another machine. Replace registry files atomically while preserving permissions. Changes take effect on the next request without restarting the gateway. Revocation cannot erase audio already downloaded by a client. Generic `python3 tools/package.py` produces a public-safe archive without a connection file.
