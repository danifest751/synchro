# Speech on the browser's own computer

The optional host worker runs GigaAM recognition and Silero speech on the CPU of the computer running the browser. With **Cloud: text translation only**, only recognized text and its speech preparation go to the selected cloud provider. No remote recognition or voice service is used. This is different from connecting the extension to a gateway on another machine.

The Windows prototype was prepared on a Ryzen 7 8745HS (8 cores / 16 threads), about 40 GB RAM, with Radeon 780M graphics. GPU acceleration is not required for this route. OmniVoice/VoiceStudio is a separate, heavier optional voice evaluation and is not silently substituted for Silero.

## Run from the repository

1. Create a Python 3.12 virtual environment. Install `server/requirements-host.txt`; a CPU PyTorch build is sufficient. Install FFmpeg and Node.js and make them available in PATH. These instructions are for a dedicated environment; avoid changing dependencies of other applications.
2. Obtain the GigaAM Multilingual CTC ONNX files, Silero v5.5 Russian package, and a faster-whisper large-v3-turbo CTranslate2 model. Review their licences separately. Keep the three model paths local. The worker loads only local files and does not download a missing model during playback.
3. Generate private gateway keys with `python tools/init_config.py --server-url http://127.0.0.1:8778` in a fresh checkout, or prepare a separate private environment file without overwriting an existing server's keys.
4. Add these paths to the private gateway environment file:

```dotenv
SYNCHRO_HOST_ASR_MODEL=C:/models/gigaam-multilingual
SYNCHRO_HOST_TTS_MODEL=C:/models/silero/v5_5_ru.pt
SYNCHRO_HOST_WHISPER_MODEL=C:/models/faster-whisper-large-v3-turbo
SYNCHRO_FFMPEG_DIR=C:/tools/ffmpeg/bin
SYNCHRO_MAX_SESSIONS=1
```

5. Start the loopback worker:

```powershell
python tools/run_host.py --env-file .local/gateway.env --port 8778
```

6. Import its private connection into the extension, select **Cloud: text translation only**, choose Kilo (or another supported provider), save, and start translation. The approved host endpoint is `http://127.0.0.1:8778`. Port 8768 can continue forwarding to an existing remote gateway.

The worker uses eight CPU threads for recognition and synthesis, serializes native inference, and preserves serialization even when an HTTP request times out. Empty audible GigaAM results or a Cyrillic alphabet on English speech are rechecked with the local int8 Whisper model. Normalization and tempo adjustment use local FFmpeg. Native YouTube video stays in the browser, and this worker retrieves the audio track directly.

## Cloud egress and local translation

If the computer cannot reach a cloud API directly, forward the provider's existing server-side tunnel to a free loopback port and configure its `SYNCHRO_KILO_TUNNEL_PORT`, `SYNCHRO_OPENROUTER_TUNNEL_PORT`, or `SYNCHRO_OPENAI_TUNNEL_PORT`. The same validated Host, TLS SNI, and certificate verification are retained. See [cloud routing](CLOUD.md). No local AI fallback is implicit in a cloud operation.

For **Local** mode, also provide the operator's own llama.cpp/Ollama endpoint. It can run on this computer or on a private server. The CPU host worker supplies recognition and voices; it does not install a local translation LLM.

Keep the private environment, model directories and connection files out of Git and extension archives. Closing the worker ends its sessions. This prototype's worker is started explicitly; Windows logon autostart is not installed by `run_host.py`.
