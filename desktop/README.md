# Synchro desktop (Windows)

A player for local video files with Russian voiceover. mpv shows the video; the bundled Synchro engine (the
server code in host mode) recognizes speech, marks stress and speaks on this computer's CPU. Only text
translation goes to the provider set in the window: OpenRouter, Kilo Gateway, OpenAI, or any OpenAI-compatible
address (for example a local LM Studio or Ollama server).

Status: player logic, engine start-up and the engine's `/api/file` work end to end (`--self-test`); playback with
mpv and the installer that bundles Python, models, FFmpeg and mpv are next.

## Development

The debug build finds the repository's `server/` code and `.local/host-env`, `.local/host-models` and
`.local/host-tools` (FFmpeg, and `mpv/mpv.exe` or the `SYNCHRO_MPV` path).

```powershell
cargo run --manifest-path desktop/Cargo.toml                      # window
cargo run --manifest-path desktop/Cargo.toml -- --self-test a.mp4 # engine + two translated windows, no mpv
cargo test --manifest-path desktop/Cargo.toml
```

Settings are stored in `%APPDATA%\Synchro\settings.json`; the engine log in `%LOCALAPPDATA%\Synchro\engine.log`.
The engine runs on loopback with a random key and ends with the player (Windows job object). Builds target
x86-64-v3 (AVX2).
