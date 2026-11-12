# Synchro Desktop for macOS

Native Apple Silicon build with the same English/Russian interface and local speech engine as the Windows app.
Requires **macOS 15 or later**, an **M-series Mac**, 8 GB RAM and about 5 GB free for the installed app.
Intel Macs are not included in this build.

## Install and use

Open `Synchro-0.1.0-macos-arm64.dmg`, drag **Synchro** to **Applications**, then launch it there.
The test build is ad-hoc signed, without an Apple Developer ID or notarization; downloaded copies may be blocked
by Gatekeeper. Public distribution needs Developer ID signing and notarization.

Choose a provider and key in **Translation**, or enter a local OpenAI-compatible server address. Use
**Open video**, **⌘O**, or drag a video onto the Synchro window. Finder's **Open With** is not registered by this
initial Mac build. The video opens in a separate mpv window; Space pauses, arrow keys seek, F toggles full screen.

Choose **Language → Русский** in the app footer for Russian. Switching is immediate and saved automatically;
the interface language is separate from the spoken language of your video.

Original volume, optional ducking, speaker grammar, assigned male/female voices, model catalogs and account
information work as described in the [desktop guide](README.md). Output uses the default macOS audio device.
The app bundles Python, models, FFmpeg and mpv; it does not require Homebrew, a separate server or a GPU.

Settings (including provider keys) and logs are in `~/Library/Application Support/Synchro/`:

- `settings.json`: saved preferences and provider keys; the optional OpenRouter management key stays in memory.
- `engine.log`: engine startup and speech processing errors.
- `player.log`: playback timing and errors.

To uninstall, move Synchro from Applications to the Trash. Remove the folder above separately to erase settings
and logs. Closing Synchro ends its helper processes; private process groups and a watchdog also handle crashes.

## Build on an Apple Silicon Mac

Install Rust stable and Xcode Command Line Tools. Prepare the models listed in the
[Windows build guide](README.md#building-from-source) under `.local/host-models`; the model files are identical.
Then, from the repository root:

```sh
cargo test --manifest-path desktop/Cargo.toml
python3 -m unittest discover -s tests -p test_macos_bundle.py -v
python3 desktop/build_macos.py
```

The builder supports the system Python 3.9 and downloads checksum-pinned Apple Silicon Python 3.12, upstream
mpv and FFmpeg source. It compiles FFmpeg with Apple tools, installs the Python speech dependencies and creates
`desktop/dist/macos/Synchro.app` plus `Synchro-0.1.0-macos-arm64.dmg`. Use `--skip-dmg` for development.
The first build needs network access and at least 12 GB free for caches and staging. Models and runtime files
stay inside `Synchro.app/Contents/Resources`; the completed app can be moved without the source checkout.
Dependency checks reject libraries that depend on Homebrew or other absolute build-machine paths.

For development, `.local/host-env/bin/python3` must contain `desktop/requirements.txt` and PyTorch; put FFmpeg at
`.local/host-tools/ffmpeg`, and mpv.app at `.local/host-tools/mpv/mpv.app` (or set `SYNCHRO_MPV` to the mpv binary).
Then `cargo run --manifest-path desktop/Cargo.toml` uses the local checkout.

To check speech processing without opening a window, using your saved translation settings:

```sh
/Applications/Synchro.app/Contents/MacOS/Synchro --self-test "/path/to/video.mp4"
cat "$HOME/Library/Application Support/Synchro/self-test.txt"
```

The report translates two windows; it does not test audio hardware or mpv. See `licenses/macos-tools.txt` and
`THIRD_PARTY_NOTICES.md` inside the app resources for bundled program sources and licenses.

The native mpv integration test is opt-in (it opens a real player):

```sh
SYNCHRO_TEST_MPV="/path/to/mpv" SYNCHRO_TEST_VIDEO="/path/to/video.mp4" \
  cargo test --manifest-path desktop/Cargo.toml native_player_controls_and_cleanup -- --ignored
```

Headless testing can use a wrapper that adds `--vo=null --ao=null`; this checks IPC, pause, seek, volume and
cleanup, without claiming to test the displayed picture or audible output.
