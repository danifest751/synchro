# Contributing

Use English for documentation, UI text, issues, and pull requests. Russian text in speech fixtures, character validation, and spoken warmup prompts is intentional: English → Russian remains the implemented language pair.

## Local development

Use Python 3.11+, Node.js 22+, and FFmpeg. Create a virtual environment and install `server/requirements.txt`. The extension has no npm build step: load `extension/` unpacked and reload it after edits. Keep `.local/` credentials and `models/` weights outside Git.

```bash
node --test tests/timeline.test.mjs
cd server
python -m unittest discover -s tests -v
cd ..
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/package.py
```

Tests mock inference/network dependencies; no model downloads are required. FFmpeg-specific tests skip if FFmpeg is absent, so install it before changing audio processing. GitHub Actions runs these checks on Linux with FFmpeg.

## Integration checks

With a running server and your own ignored `.local/connection.json`:

```bash
python tools/smoke.py
python tools/smoke_youtube.py 'https://www.youtube.com/watch?v=VIDEO_ID' 0
python tools/bench_viewers.py
```

The concurrent benchmark needs `guest-1`, `guest-2`, and `guest-3` connections and occupies three server slots. Coordinate with viewers before running it. Generated audio and reports go to ignored `output/`. Use only videos you are authorized to process. Smoke tests make real network/model requests and may download model weights on first use.

## Packaging

`python tools/package.py` produces `output/Synchro-extension.zip` without a connection file. `python tools/package.py --client guest-1` deliberately includes that guest's private key. Never upload personal archives as public release assets. The packager verifies contents and rejects owner-token or private-key inclusion.

## Changes

Keep changes focused. Test timing, cancellation, cleanup, and validation when modifying playback or server input. Preserve the exact endpoint allowlist, session ownership checks, request limits, and third-party notices. Never add real credentials or private infrastructure addresses to examples. Include a public video timestamp and expected behavior for reproducible playback bugs; redact private information.

Update relevant documentation and `CHANGELOG.md`. For an extension release, bump `extension/manifest.json` after preparing the rest of the files so developer-mode updates cannot reload a partially copied build. Pushing that bump to `main` publishes the GitHub Release automatically once tests pass; see [updates](docs/UPDATES.md#publishing-an-update). Deploy a compatible gateway first. Coordinate the gateway's `/health` version if an API release changes.
