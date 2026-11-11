# Architecture

## Browser components

| File | Responsibility |
| --- | --- |
| `extension/background.js` | Session startup, active-tab access, offscreen lifecycle, local updates |
| `extension/youtube.js` | Native-player overlay, synchronization, seeking, audio ducking |
| `extension/youtube-offscreen.mjs` | YouTube gateway requests and session cancellation |
| `extension/connection.mjs` | Exact server-origin allowlist; credentials are never sent to arbitrary URLs |
| `extension/translation.mjs` | Cloud provider defaults and browser-side translation settings validation |
| `extension/model-picker.mjs` | Translation-first model search, selection, account balance, and explicit cost estimates |
| `extension/offscreen.js` | Tab audio capture, PCM windows, MediaRecorder, gateway transport |
| `extension/pcm-worklet.js` | Mono PCM resampling to 16 kHz |
| `extension/store-worker.js` | OPFS recording and cue storage |
| `extension/player.js` | Separate capture player, replay, seeking, buffer cleanup |
| `extension/timeline.mjs` | Cue timing, playable boundary, speech/video rate mapping |
| `extension/view.mjs` | Picture controls |
| `extension/updates.mjs` | Defer extension reload while playback is active |

The extension uses Manifest V3, activeTab, tabCapture, offscreen, storage, scripting, and alarms. It contains no model weights or bundled private keys. Optional user-entered cloud API keys stay in local extension storage and are sent to the trusted gateway for one session. Its manifest public key stabilizes the extension ID; that public key is not a signing secret.

## Server components

`server/synchro/app.py` is a FastAPI gateway. It authenticates each request, enforces exact browser Origin, limits sessions, tracks ownership, and expires inactive sessions. Sessions and rate-limit counters live in process memory, so run one Uvicorn worker. Restarting the gateway ends active sessions.

Failures are contained to one window. Processing changes the session only after every stage succeeds, so a failed window stays pending and a repeated request processes the same audio; a repeated request after a lost response receives the stored result. The YouTube decoder reconnects inside FFmpeg and, if the stream still ends early, is restarted at the exact received position with a freshly resolved media URL. A missing stress mark speaks unmarked text, and Latin letters or digits that survive the translation retry are transliterated and spelled out in Russian instead of stopping playback. Closing or replacing a session cancels its work immediately.

`server/synchro/youtube.py` accepts validated YouTube URLs, resolves audio with yt-dlp, checks CDN access, and decodes audio with FFmpeg. Source URLs and video contents are not logged by its helper. No browser cookies are imported.

`server/synchro/relay.py` lets YouTube see the viewer's network instead of the server's. Before opening a video the extension connects to `/api/relay` (exact extension Origin, then its access key as the first message). yt-dlp then runs in-process with a request handler that sends every HTTP request over that WebSocket, and FFmpeg reads the media through a loopback endpoint that turns its Range requests into relayed 1 MB requests, so seeking works. The extension (`extension/relay.mjs`) performs only HTTPS GET/POST/HEAD requests to youtube.com, googlevideo.com, ytimg.com and youtubei.googleapis.com, without cookies, and refuses redirects elsewhere; the server refuses other hosts too. A session rule gives the extension's own youtube.com requests YouTube's Origin and Referer, and its googlevideo requests the User-Agent that yt-dlp chose. Through a browser, yt-dlp's clients that need no JavaScript challenge (currently `visionos`) return media URLs the browser can download as itself. Without a connected browser, the server uses its own network and `YTDLP_PROXY`, as before.

`server/synchro/pipeline.py` recognizes speech, translates text, synthesizes speech, joins WAV parts, normalizes loudness, and adjusts tempo. The translation API supports llama.cpp's OpenAI-compatible endpoint or Ollama's native endpoint; it requires structured JSON output.

`server/synchro/cloud.py` adds fixed-endpoint OpenAI, Kilo Gateway, and OpenRouter calls. Credentials and model selections belong to a session, not global pipeline state. HY-MT2 uses plain-text translation and optional cloud speech preparation through the same provider; general instruction models use validated structured output. See [cloud behavior](CLOUD.md).

`server/synchro/cloud_speech.py` handles full-cloud ASR and speech using the same provider key and server tunnel, without local AI fallback. Router speech streams are bounded, assembled into PCM/WAV and checked against the requested text. `server/synchro/usage.py` aggregates request-local, per-stage provider-reported costs and missing-price counts; it retains no content. Cloud ASR without timestamps uses committed audio only and window-level alignment.

`server/synchro/catalog.py` fetches compatible public model catalogs and per-token prices through the same configured server routes, caching only that public metadata for five minutes. Personal balance requests are authenticated separately with the submitted key and never placed in the shared cache. Responses contain only the remaining USD balance and fetch time, with `Cache-Control: no-store`.

`deploy/gigaam_server.py` and `deploy/silero_server.py` are separate authenticated loopback services. Both serialize inference instead of creating a CPU thread pool for every viewer. The reference configuration uses eight intra-op CPU threads.

## Audio windows and timing

Input is mono, little-endian PCM16 at 16 kHz. YouTube audio starts with an 11-second recognition window committing ten seconds, then uses 21-second windows committing twenty seconds. All windows overlap by one second. The player starts once ten seconds are translated (or the shorter remaining video finishes). Capture mode retains eight-second windows committing seven seconds. A final window commits its actual length. Word ownership is determined by the midpoint of each word's timestamps, preventing duplicate overlap words. Longer YouTube windows provide more translation context and fewer API round trips, but individual requests and voiceover intervals are longer.

The session language selects recognition: GigaAM for English, SenseVoice-Small (sherpa-onnx, CPU) for Chinese, Korean, and Japanese, and Whisper with that language if SenseVoice is missing or fails. SenseVoice token start times become timing units: every Han or kana character is its own unit, Korean words start at a space, and punctuation joins the preceding unit. Sentence ends `。！？` also split phrases. GigaAM character timestamps are grouped into words. A one-second lookback from the last committed window also provides left context to recover boundary words without duplicating them; the private recognition worker accepts up to 22 seconds including both margins. If GigaAM fails or returns Cyrillic in an English transcription, the gateway rechecks that window with Whisper. This check does not detect every recognition error.

The whole window is translated once, retaining the last two translated windows as context. Source word timestamps define smaller speech phrases using pauses, punctuation and a six-second soft limit. A structured alignment request assigns the existing Russian words to those phrases in order, preserving every translated word. HY-MT2 alignment uses cloud Gemma through the same provider. Invalid alignment falls back to one complete translation at the actual speech boundaries. Alignment usage is reported separately. This is phrase alignment, not word-for-word lip synchronization, and depends on recognition and model quality.

Each cue starts at the first recognized word and ends near the last word, rather than filling the whole chunk. Actual pauses remain separate intervals. Adjacent cue intervals cannot overlap. Silence advances the ready boundary without generating a phrase. Session history and sequence advance only after all speech in the window succeeds. YouTube audio seeking uses the exact selected position. The overlay waits for every cue in a result to decode before advancing its playable boundary.

Speech is synthesized as mono WAV. Concatenated RIFF files from sentence-based synthesis are validated and merged, avoiding playback of only the first sentence. FFmpeg measures loudness, then applies constant gain toward −18 LUFS, limited by −1.5 dBTP and a maximum 12 dB boost. Quiet outer padding is trimmed with short margins; pauses inside a phrase survive. Silence is unchanged. Tempo correction is limited to 0.9–1.35×. The browser maps speech duration to its source interval by slowing or speeding video, returning to normal speed during source pauses. If exceptionally long speech reaches Chromium's minimum video speed, the YouTube overlay holds the picture until the last words finish.

## Privacy and storage

For YouTube, the browser sends the video URL, selected position, voice, session requests, and access key to the gateway. In Local mode the gateway sends audio/text only to operator-configured inference services. Cloud mode additionally sends recognized text and applicable translation context to the selected provider using the submitted key. Video stays with YouTube. For tab capture, tab audio is sent to the gateway and captured video stays in browser storage.

The backend retains session context in memory until deletion, expiry, or restart. Generated audio is sent as base64 inside JSON responses. Operators control their own service logs, proxies, and model runtimes; this repository cannot guarantee their retention settings.

## Deployment topologies

A single Linux inference host can run everything on loopback, accessed from a browser through SSH port forwarding. A remote-user installation adds HTTPS through Caddy. The optional two-host example keeps the public reverse proxy on a gateway host and forwards only the private API port over SSH to the inference host; its ASR service can be forwarded in the opposite direction.

See [deployment](DEPLOYMENT.md) for ports, configuration, and model setup.
