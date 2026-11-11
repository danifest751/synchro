# Changelog

## 0.4.5 — 2026-11-11

- Added Chinese, Korean, and Japanese videos. A Video language setting (options page and player panel) selects the original-language YouTube audio track, the recognizer, and the translation prompt.
- Chinese, Korean, and Japanese are recognized by SenseVoice-Small int8 through sherpa-onnx on CPU (about 50× real time on an 8-core laptop); Whisper with the selected language is the fallback. English stays on GigaAM.
- Phrase splitting understands `。！？`; untranslated Han, kana, or Hangul never reaches Russian speech.

## 0.4.4 — 2026-11-11

- Replaced Xenia/Aidar/Eugene and the optional VoiceStudio voices with five Silero V5 CIS voices (Roman, Eduard, Albina, Alexander, Alfia); legacy voice IDs map to them. RUAccent marks stress on the host worker and through the gateway accent service.
- A failed or timed-out window no longer ends the session: it stays pending, and the extension retries network errors and 409/502/503/504 three times. `/next` and `/chunk` are idempotent, so a response lost in transit is sent again instead of skipping audio.
- A dropped YouTube audio stream reconnects inside FFmpeg and otherwise resumes at the exact received position with a freshly resolved URL.
- Closing or seeking cancels work in progress immediately; starting a session replaces the previous session of the same key instead of returning 409.
- A recent successful model warmup is reused for five minutes, making seeks faster; window failures clear it.
- Latin names and digits that survive the translation retry are transliterated and spelled out in Russian; a failed stress lookup speaks unmarked text. Neither stops playback.
- Local model requests time out after 60 seconds with connection retries; GigaAM and Silero workers queue requests in-process; the gateway logs per-window stage timings without content.
- Kilo HY-MT2 empty answers fall back to Gemma for the same window; phrase alignment repairs a wrong boundary count once.

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
