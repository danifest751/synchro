# Architecture

## Browser components

| File | Responsibility |
| --- | --- |
| `extension/background.js` | Session startup, active-tab access, offscreen lifecycle, local updates |
| `extension/youtube.js` | Native-player overlay, synchronization, seeking, audio ducking |
| `extension/youtube-offscreen.mjs` | YouTube gateway requests and session cancellation |
| `extension/connection.mjs` | Exact server-origin allowlist; credentials are never sent to arbitrary URLs |
| `extension/offscreen.js` | Tab audio capture, PCM windows, MediaRecorder, gateway transport |
| `extension/pcm-worklet.js` | Mono PCM resampling to 16 kHz |
| `extension/store-worker.js` | OPFS recording and cue storage |
| `extension/player.js` | Separate capture player, replay, seeking, buffer cleanup |
| `extension/timeline.mjs` | Cue timing, playable boundary, speech/video rate mapping |
| `extension/view.mjs` | Picture controls |
| `extension/updates.mjs` | Defer extension reload while playback is active |

The extension uses Manifest V3, activeTab, tabCapture, offscreen, storage, scripting, and alarms. It contains no model weights or private server-to-server credentials. Its manifest public key stabilizes the extension ID; that public key is not a signing secret.

## Server components

`server/synchro/app.py` is a FastAPI gateway. It authenticates each request, enforces exact browser Origin, limits sessions, tracks ownership, and expires inactive sessions. Sessions and rate-limit counters live in process memory, so run one Uvicorn worker. Restarting the gateway ends active sessions.

`server/synchro/youtube.py` accepts validated YouTube URLs, resolves audio with yt-dlp, checks CDN access, and decodes audio with FFmpeg. Source URLs and video contents are not logged by its helper. No browser cookies are imported. A working server-side route to YouTube is required independently of the browser's ability to play video.

`server/synchro/pipeline.py` recognizes speech, translates text, synthesizes speech, joins WAV parts, normalizes loudness, and adjusts tempo. The translation API supports llama.cpp's OpenAI-compatible endpoint or Ollama's native endpoint; it requires structured JSON output.

`deploy/gigaam_server.py` and `deploy/silero_server.py` are separate authenticated loopback services. Both serialize inference instead of creating a CPU thread pool for every viewer. The reference configuration uses eight intra-op CPU threads.

## Audio windows and timing

Input is mono, little-endian PCM16 at 16 kHz. Recognition uses eight-second windows with one second of overlap. A non-final window commits seven seconds; the final window commits its actual length. Word ownership is determined by the midpoint of each word's timestamps, preventing duplicate overlap words.

GigaAM character timestamps are grouped into words. If GigaAM fails or returns Cyrillic in an English transcription, the gateway rechecks that window with Whisper. This check does not detect every recognition error.

Each translated segment starts at the first recognized word. The last two translated windows provide context to the next text request. Silence advances the ready boundary without generating a phrase. Currently a window produces at most one translated cue; sentence-boundary stabilization is future work.

Speech is synthesized as mono WAV. Concatenated RIFF files from sentence-based synthesis are validated and merged, avoiding playback of only the first sentence. FFmpeg measures loudness, then applies constant gain toward −18 LUFS, limited by −1.5 dBTP and a maximum 12 dB boost. Silence is unchanged. Tempo correction is limited to 0.9–1.35×; the browser maps longer audio to a slower video interval.

## Privacy and storage

For YouTube, the browser sends the video URL, selected position, voice, session requests, and access key to the gateway. The gateway sends audio, transcript text, and translated text only to the operator-configured inference services. Video stays with YouTube. For tab capture, tab audio is sent to the gateway and captured video stays in browser storage.

The backend retains session context in memory until deletion, expiry, or restart. Generated audio is sent as base64 inside JSON responses. Operators control their own service logs, proxies, and model runtimes; this repository cannot guarantee their retention settings.

## Deployment topologies

A single Linux inference host can run everything on loopback, accessed from a browser through SSH port forwarding. A remote-user installation adds HTTPS through Caddy. The optional two-host example keeps the public reverse proxy on a gateway host and forwards only the private API port over SSH to the inference host; its ASR service can be forwarded in the opposite direction.

See [deployment](DEPLOYMENT.md) for ports, configuration, and model setup.
