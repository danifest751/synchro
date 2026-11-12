# Synchro Desktop for Windows

Watch your own video files with a synchronized Russian voiceover. Synchro Desktop is a video player (built on
[mpv](https://mpv.io)) with a speech engine that runs entirely on your computer's CPU: it recognizes the original
speech, marks Russian word stress and speaks the translation. Only the recognized **text** is sent for
translation, to the provider you choose: OpenRouter, Kilo Gateway, OpenAI, or any OpenAI-compatible address —
including a model running on your own machine.

- English, Chinese, Korean and Japanese videos.
- Five Russian voices (Silero V5 CIS): Albina, Alfia, Roman, Eduard, Alexander.
- Local speaker cues guide masculine/feminine first-person grammar, with optional automatic voice matching.
- Searchable Kilo/OpenRouter model catalogs, balances and provider-reported spending.
- The original track stays audible between phrases and is lowered while the voice speaks.
- Long Russian phrases slow the picture slightly so speech and video stay together; pauses play at normal speed.
- Optional on-screen captions with the translation.
- Plays practically any file mpv can play: MP4, MKV, AVI, MOV, WebM, HEVC, AV1, and more.

**Status: 0.1.0, first public build.** Tested on Windows 10 with English clips; Chinese, Korean and Japanese use
the same engine as the [Synchro server](../README.md), where they were tested end to end.

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [First start](#first-start)
- [Choosing a translation provider](#choosing-a-translation-provider)
- [Watching a video](#watching-a-video)
- [What leaves your computer](#what-leaves-your-computer)
- [Performance](#performance)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [How it works](#how-it-works)
- [Building from source](#building-from-source)
- [Licenses](#licenses)

## Requirements

| | Minimum | Notes |
| --- | --- | --- |
| Windows | 10 or 11, 64-bit | Per-user install, no administrator rights |
| CPU | x86-64 with AVX2 | Intel Haswell (2013) or newer, AMD Excavator/Zen (2015) or newer; 4+ cores recommended |
| Memory | 8 GB RAM | The engine peaks at about 3.5 GB while playing |
| Disk | 4 GB free | 3.2 GB installed |
| Network | For translation only | Not needed with a local OpenAI-compatible model |
| Account | A translation provider key | OpenRouter, Kilo Gateway, OpenAI, or none for a local server |

No GPU is used. Speech recognition, stress marking and voices run on the CPU.

## Install

1. Download both files of the release into the same folder:
   `Synchro-Setup-<version>.exe` and `Synchro-Setup-<version>-1.bin`. The installer is split into two files because
   the bundled models exceed 2 GB.
2. Run `Synchro-Setup-<version>.exe`. Windows SmartScreen may warn about an unsigned program; choose
   **More info → Run anyway** if you trust the download (compare its SHA-256 with `SHA256SUMS` from the release).
3. The program installs to `%LOCALAPPDATA%\Programs\Synchro` and adds:
   - a Start menu shortcut (and optionally a desktop shortcut);
   - **Open with → Synchro** for `.mp4 .mkv .avi .mov .webm .m4v .wmv .ts` files. Your default video player is not
     changed.

Everything the program needs is inside the install folder: a private Python runtime, the speech engine, the
models, FFmpeg and mpv. Nothing is installed system-wide.

## First start

1. Start **Synchro**. The header shows *Engine starting*, then *Engine ready*.
2. Open the **Translation** tab, choose a **translation provider** and paste its **API key** (see below).
   For a local model, choose **OpenAI-compatible address** and enter the server address. Settings save automatically;
   a save failure is shown in the footer with a **Retry** action.
3. In **Watch**, pick a **Russian voice** and the **video language** in the voiceover panel.
4. Optionally press **Check connection** on the **Translation** tab. The first check loads the speech models
   (about 20–30 s on a typical laptop); afterwards models are loaded automatically at every start, so videos open in seconds.

| Setting | Meaning |
| --- | --- |
| Translation provider | Where the recognized text is translated |
| Server address | Only for *OpenAI-compatible address*: the API base URL, e.g. `http://127.0.0.1:1234/v1` |
| Model | Search the Kilo/OpenRouter catalog or enter an ID manually; leave empty for the provider default |
| API key | Required for cloud providers; optional for a local server |
| Russian voice | The single voice used in One voice mode, also the fallback for uncertain speakers |
| Voice mode | One voice for all speech, or By speaker with separate assigned voices |
| Female speaker / Male speaker | Your chosen voices for each detected speaker type in By speaker mode |
| Video language | The language spoken in the video: English, Chinese, Korean or Japanese |
| Voiceover volume | Loudness of the Russian voice |
| Original audio | Linear volume of the original track; slider changes apply immediately |
| Lower original during voiceover | Keep half the selected original volume during translated speech; turn off for full selected volume |
| Speaker grammar | Auto from voice, forced Feminine/Masculine, or text only |
| Show translated captions | Show each translated phrase on screen |

The layout stacks vertically in a smaller window; scroll to reach the remaining controls.

Changing translation settings, the voice, language or speaker grammar while a video plays translates again from
the current position after a short pause in editing. Volumes and captions apply immediately. Provider keys and
selected models are remembered separately; switching providers does not send the previous provider's key.

**Speaker grammar.** The bundled ECAPA-TDNN classifier runs locally on CPU for each speech phrase. It guides
first-person forms such as “я сделал / я сделала”; the selected synthesis voice is not used as evidence about
the original speaker. Voice mode and speaker grammar are independent: One voice can still use the correct
masculine/feminine wording, and By speaker can change voices even with grammar set to Use text only.
Short, noisy, ambiguous or mixed-speaker phrases can remain unspecified. This is a
probabilistic voice cue, and errors remain possible; use the manual Feminine/Masculine override for a single
speaker when needed. Choose **One voice** to keep one synthesis voice throughout the video (the default for older settings without an
explicit voice mode). Choose **By speaker** to assign a **Female speaker** voice (Albina or Alfia) and a **Male
speaker** voice (Roman, Eduard or Alexander). The assignments are saved and retained when switching modes.
Uncertain speakers use the voice selected in One voice mode.
With HY-MT2, grammar correction uses an additional Gemma request to the same provider because HY-MT2 does not
follow grammar instructions. The spending total includes this stage.

## Choosing a translation provider

| Provider | Default model | Get a key |
| --- | --- | --- |
| OpenRouter | `google/gemma-4-26b-a4b-it` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| Kilo Gateway | `tencent/hy-mt2-1.8b` | [kilo.ai](https://kilo.ai) |
| OpenAI | `gpt-4.1-mini` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| OpenAI-compatible address | (enter one) | Your own server or another provider |

Translation is cheap: text of a one-hour video is typically a few cents with the default models. Synchro asks for
structured JSON answers; choose a model that supports structured output (most current instruction models do).

**Using a model on your own computer.** Any server with an OpenAI-compatible `/v1/chat/completions` endpoint
works. Choose *OpenAI-compatible address* and enter, for example:

| Server | Address | Model example |
| --- | --- | --- |
| [LM Studio](https://lmstudio.ai) | `http://127.0.0.1:1234/v1` | the model ID shown in LM Studio |
| [Ollama](https://ollama.com) | `http://127.0.0.1:11434/v1` | `gemma3:12b` |
| [llama.cpp server](https://github.com/ggml-org/llama.cpp) | `http://127.0.0.1:8080/v1` | the `--alias` you started it with |

The key can stay empty for local servers. With a local model nothing leaves your computer at all.

## Balances and spending

The **Translation** tab loads the provider's compatible model catalog with search and input/output prices per
million tokens. A manual model ID remains available if the catalog cannot be reached.

**Account & spending** refreshes every minute, or when you press **Refresh account & models**:

- **Kilo:** account balance from the service.
- **OpenRouter:** key usage and remaining key allowance from a normal translation key. This allowance is not the
  account balance. The optional **Account balance key** field accepts a separate OpenRouter management key to
  retrieve account credits and total account spending. This key stays in memory for the app run and is sent only
  to the balance endpoint; it is never used for translation or saved to disk.
- **This provider · app run:** confirmed request costs since the app started, including connection checks, retries,
  translation, grammar correction and phrase alignment. The Watch screen also shows the cost of the current video,
  including seeks and changes of settings. These counters reset when the app closes.

Missing provider prices are reported as unpriced requests, rather than assumed to be free. A partial total may be
lower than the final charge. Account-wide spending may include activity from other applications; the app-run and
video totals count Synchro requests only. OpenAI/custom endpoints have no balance integration.

## Watching a video

1. Click **Open video** in **Watch**, press **Ctrl+O**, drag a video onto Synchro, or right-click a file in Explorer
   → **Open with → Synchro**. If translation still needs setup, the selected file is kept on the **Translation** tab;
   finish the settings and click **Continue to video**.
2. The mpv window opens paused and shows *Synchro: Translating ahead…*. Playback starts by itself once the first
   ten seconds are translated (a few seconds after the models are loaded).
3. Synchro keeps about half a minute of translation ahead of the picture. If translation falls behind (a slow
   provider, a long burst of speech), the video pauses briefly and continues automatically.

mpv's controls work as usual (Synchro manages the volume mix itself; use the sliders in its window):

| Key / action | Effect |
| --- | --- |
| Space, click | Pause / play |
| ← → | Seek 5 s; ↑ ↓ seek 1 min |
| Drag the seek bar | Seek; translation restarts from the new position |
| F, double-click | Full screen |
| Q | Close the video |

**Stop video** in the Synchro window ends the current video. The filename and any playback error remain visible
afterwards. Closing the Synchro window closes the video and the engine.

## What leaves your computer

| Data | Where it goes |
| --- | --- |
| Video and audio | Nowhere. Decoded and recognized locally |
| Recognized text (and the two previous phrases for context) | Your translation provider |
| API key | Your translation provider, for each request |
| Generated speech | Nowhere. Synthesized locally |

The speech engine listens only on `127.0.0.1` with a random per-start key and stops when Synchro closes. The API
key is stored in `%APPDATA%\Synchro\settings.json` in your Windows profile, like any application setting; use a
key with a spending limit.

## Performance

Measured on a Ryzen 7 8745HS laptop (8 cores) with Kilo Gateway translation:

| Stage | Time |
| --- | --- |
| Engine start | 1–2 s |
| Loading models (once per start, in the background) | 20–30 s |
| Translating 20 s of speech (recognition + translation + alignment + voice) | 3–4 s |
| Recognition alone, 21 s window | 0.4–0.9 s (English), about 0.4 s (Chinese/Korean/Japanese) |

Playback is comfortably faster than real time on any recent 4-core CPU; most of the time is the translation
provider's response.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| *Engine unavailable* in the header | Open `%LOCALAPPDATA%\Synchro\engine.log` |
| *Connection check failed … HTTP 401* | The API key is wrong or revoked |
| *… HTTP 402* / *credits* | Top up the provider account |
| *Custom endpoint is unreachable* | Check that your local server is running and the address ends with `/v1` |
| The video waits a lot | The provider is slow; try a faster model, or check your network |
| *This file has no readable audio track* | The file has no audio, or a codec FFmpeg cannot read |
| Wrong recognition | Set **Video language** to the language actually spoken |
| No voice, video plays | Check the Windows output device; Synchro uses the default device |

`%LOCALAPPDATA%\Synchro\player.log` records what the player did (start, seeks, waits, each phrase start), without
any text or audio. To test the engine without the player window, run from a terminal:

```powershell
& "$env:LOCALAPPDATA\Programs\Synchro\Synchro.exe" --self-test "C:\path\to\video.mp4"
Get-Content "$env:LOCALAPPDATA\Synchro\self-test.txt"
```

It starts the engine, translates the first two windows of the video and writes the result.

## Uninstall

*Settings → Apps → Synchro → Uninstall*, or *Uninstall Synchro* from the Start menu. This removes the program, the
models and the *Open with* entries. Your settings and logs stay in `%APPDATA%\Synchro` and
`%LOCALAPPDATA%\Synchro`; delete those folders to remove them too.

## How it works

```mermaid
flowchart LR
    File[Video file] --> MPV[mpv: picture and original sound]
    File --> FFmpeg[FFmpeg: 16 kHz audio windows]
    FFmpeg --> ASR[GigaAM / SenseVoice]
    ASR --> Provider[Translation provider]
    Provider --> Stress[RUAccent stress]
    Stress --> Voice[Silero voice]
    Voice --> Player[Synchro player]
    Player -->|speed, volume, pause| MPV
    Player --> Speakers[Voice output]
```

- `Synchro.exe` (Rust, this folder) is the window and the player. It starts the engine and mpv as helper processes
  in a Windows job object, so both end with Synchro even after a crash.
- The engine is the [Synchro server](../server) in its desktop host mode, running in a private Python 3.12. It
  reads the file with FFmpeg in windows of 10 s, then 20 s (one second overlap), and returns phrases with their
  timing and WAV speech.
- The player asks for windows ahead of the picture, then plays each phrase when the picture reaches it: it sets
  mpv's speed so the phrase fits its source interval (0.06–16×, normally 0.75–1.0×), lowers the original track
  while the voice speaks, pauses when translation is not ready, and restarts translation after a seek.
- English is recognized by GigaAM Multilingual; Chinese, Korean and Japanese by SenseVoice-Small. Phrases are split
  by pauses and sentence ends, translated as a whole window and then aligned back to the phrases.

## Building from source

Requirements: Rust (stable), Python 3.11+, Git, and [Inno Setup 6](https://jrsoftware.org/isinfo.php). The bundle
script takes models and tools from the repository's private `.local` folder:

| Path | Contents |
| --- | --- |
| `.local/host-models/gigaam` | `config.json`, `multilingual_ctc.onnx`, `multilingual_vocab.txt` (GigaAM Multilingual CTC ONNX) |
| `.local/host-models/sensevoice` | `model.int8.onnx`, `tokens.txt` from the [sherpa-onnx SenseVoice package](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2) |
| `.local/host-models/speaker/model.onnx` | Pinned 16 MB ECAPA-TDNN voice cue classifier; run `python tools/prepare_speaker_model.py` (also downloaded and verified by the bundle builder) |
| `.local/host-models/silero-cis.pt` | Silero `v5_cis_base_nostress.pt` |
| `.local/host-models/ruaccent` | RUAccent `dictionary`, `nn` and `koziev` folders (see [HOST.md](../docs/HOST.md)) |
| `.local/host-tools/ffmpeg.exe` | FFmpeg for Windows |
| `.local/host-tools/mpv` | mpv x86_64-v3 build from [shinchiro](https://github.com/shinchiro/mpv-winbuild-cmake/releases) |

```powershell
cargo test --manifest-path desktop/Cargo.toml
python desktop/build_bundle.py --test-video C:\path\to\clip.mp4   # bundle, self-test, installer
python desktop/build_bundle.py --installer-only                    # repackage desktop/dist/Synchro
```

`build_bundle.py` downloads the portable CPython 3.12 build (SHA-256 pinned), installs the CPU build of PyTorch and
[`requirements.txt`](requirements.txt) into it, copies the engine code and the files above into
`desktop/dist/Synchro` (the installed layout), builds `Synchro.exe` for x86-64-v3, runs `--self-test` on the
finished folder when a test video is given, and compiles [`installer.iss`](installer.iss) into
`desktop/dist/installer`.

For development, first run `python tools/prepare_speaker_model.py`. Then `cargo run --manifest-path desktop/Cargo.toml` uses the repository directly: the engine code in
`server/`, the Python environment in `.local/host-env` (`server/requirements-host.txt`), models in
`.local/host-models`, tools in `.local/host-tools` (or mpv from the `SYNCHRO_MPV` path). Debug builds keep a
console; `-- --self-test clip.mp4` prints the report there.

| Source file | Responsibility |
| --- | --- |
| `src/main.rs` | App state, file opening, settings, self-test |
| `src/ui.rs` | Theme, Watch and Translation screens, playback preferences |
| `src/provider.rs`, `src/billing.rs` | Background catalog/balance refresh, account isolation and usage totals |
| `src/engine.rs` | Engine start on loopback, job object |
| `src/api.rs` | Engine HTTP client |
| `src/player.rs` | Window fetching ahead, voice/picture synchronization |
| `src/mpv.rs` | mpv JSON IPC |
| `src/config.rs`, `src/wav.rs` | Settings file, WAV decoding |

## Licenses

Synchro's code is MIT-licensed. The installer bundles third-party software and models under their own terms,
listed in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and [models and licenses](../docs/MODELS.md):

| Component | License |
| --- | --- |
| mpv (shinchiro build) | GPL-2.0-or-later |
| FFmpeg (gyan.dev build) | GPL-3.0 |
| CPython (python-build-standalone) | PSF and bundled library licenses |
| PyTorch, ONNX Runtime, sherpa-onnx | BSD-3-Clause, MIT, Apache-2.0 |
| GigaAM Multilingual | MIT |
| SenseVoice-Small | FunASR Model Open Source License (attribution required) |
| Silero V5 CIS Base (`v5_cis_base_nostress`) | MIT |
| RUAccent | MIT |
| [ECAPA-TDNN speaker classifier](https://huggingface.co/Alice-Sabrina-Ivy/voice-gender-classifier-onnx-q8-v2) | MIT; full notice in `licenses/speaker-model-LICENSE.txt` |

mpv and FFmpeg run as separate programs; their sources are available from the links in the notices.
