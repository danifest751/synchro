# Changelog

## 0.3.1 — 2026-11-10

- Published the self-hosted prototype as Synchro — Local Video Dubbing, with English UI/documentation and MIT source licensing.
- Replaced private deployment addresses, GPU UUIDs, and model paths with configurable examples.
- Added fresh private configuration generation and public-safe extension packaging.
- Added Xenia, Aidar, and Eugene voice choices using Silero v5.5.
- Preserved complete multi-sentence TTS responses by joining concatenated RIFF/WAV files.
- Added consistent phrase loudness and smoother original-audio ducking.
- Preserved original spelling during stress handling and disabled automatic yo substitution in Silero.
- Improved visibility of YouTube overlay controls and picture settings.
- Disabled proxy upstream keepalive in the reference Caddy configuration to fix stale-connection 502 errors.

## Earlier prototype work

- Added native YouTube audio-only translation, local recognition/translation/synthesis, and synchronized playback.
- Added per-viewer access keys, concurrent session isolation, private inference services, and HTTPS gateway support.
- Added GigaAM CPU recognition with Whisper fallback, OPFS capture storage, seeking, and deferred local-file updates.
