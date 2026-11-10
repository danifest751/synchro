# Changelog

## 0.4.1 — 2026-11-10

- Added searchable Kilo/OpenRouter model catalogs, translation-first ordering, and highlighted selection.
- Added personal Kilo balance and OpenRouter remaining credits with manual refresh and per-key isolation.
- Displayed approximate translation cost per minute/hour using live token prices and explicit token-budget assumptions.
- Kept unknown prices and unavailable balances distinct from zero; preserved manual model entry and existing choices.

## 0.4.0 — 2026-11-10

- Added per-session Local, OpenAI, Kilo Gateway, and OpenRouter text translation choices in settings.
- Added separate provider/model/key profiles, key removal, and a real translator test button.
- Kept provider API keys out of archives and responses, isolated them per session, and sanitized validation/provider errors.
- Added HY-MT2 plain-text translation with local preparation of Latin names and digits for Silero.
- Preserved legacy local capture API requests and local ASR/TTS behavior.

## 0.3.1 — 2026-11-10

- Published the self-hosted prototype as Synchro — Local Video Dubbing, with English UI/documentation and MIT source licensing.
- Replaced private deployment addresses, GPU UUIDs, and model paths with configurable examples.
- Added fresh private configuration generation and public-safe extension packaging.
- Added Xenia, Aidar, and Eugene voice choices using Silero v5.5.
- Preserved complete multi-sentence TTS responses by joining concatenated RIFF/WAV files.
- Added consistent phrase loudness and smoother original-audio ducking.
- Accepted trailing FFmpeg output statistics after loudness JSON reports for compatibility with newer FFmpeg releases.
- Preserved original spelling during stress handling and disabled automatic yo substitution in Silero.
- Improved visibility of YouTube overlay controls and picture settings.
- Disabled proxy upstream keepalive in the reference Caddy configuration to fix stale-connection 502 errors.

## Earlier prototype work

- Added native YouTube audio-only translation, local recognition/translation/synthesis, and synchronized playback.
- Added per-viewer access keys, concurrent session isolation, private inference services, and HTTPS gateway support.
- Added GigaAM CPU recognition with Whisper fallback, OPFS capture storage, seeking, and deferred local-file updates.
