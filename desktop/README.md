# Synchro desktop (Windows)

A player for local video files with Russian voiceover. mpv shows the video; the bundled Synchro engine (the
server code in host mode) recognizes speech, marks stress and speaks on this computer's CPU. Only text
translation goes to the provider set in the window: OpenRouter, Kilo Gateway, OpenAI, or any OpenAI-compatible
address (for example a local LM Studio or Ollama server).

Video languages: English (GigaAM), Chinese, Korean and Japanese (SenseVoice). Voices: five Silero V5 CIS voices.
Requires a 64-bit CPU with AVX2 (Intel 2013+, AMD 2015+); about 4 GB of disk space.

## Use

Install, start Synchro, choose a provider and paste its key, then **Open video…** (or *Open with → Synchro* in
Explorer). Playback waits until the first ten seconds are translated and keeps about half a minute ahead.
mpv's own controls work as usual: Space pauses, arrows seek, F toggles full screen. A seek translates again from
the new position.

Files: settings `%APPDATA%\Synchro\settings.json`; logs `%LOCALAPPDATA%\Synchro\engine.log` and `player.log`.

## Development

The debug build finds the repository's `server/` code and `.local/host-env`, `.local/host-models` and
`.local/host-tools` (FFmpeg, and `mpv/mpv.exe` or the `SYNCHRO_MPV` path).

```powershell
cargo run --manifest-path desktop/Cargo.toml                      # window
cargo run --manifest-path desktop/Cargo.toml -- --self-test a.mp4 # engine + two translated windows, no mpv
cargo test --manifest-path desktop/Cargo.toml
```

## Building the installer

```powershell
python desktop/build_bundle.py --test-video a.mp4
```

The script downloads the portable CPython 3.12 runtime (SHA-256 pinned), installs the CPU build of PyTorch and
`desktop/requirements.txt` into it, copies the engine code, the models from `.local/host-models`, FFmpeg and mpv
(the shinchiro x86_64-v3 build) from `.local/host-tools`, builds `Synchro.exe`, runs `--self-test` on the finished
folder and compiles `installer.iss` with Inno Setup 6. Output: `desktop/dist/Synchro` (the installed layout) and
`desktop/dist/installer` (setup plus `.bin` parts, because the payload exceeds 2 GB). The installer is per-user
and needs no administrator rights.

The engine runs on loopback with a random key; the engine and mpv end with the player (Windows job object).
