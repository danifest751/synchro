# Roadmap

Prototype 0.3.1 implements English-to-Russian dubbing with self-hosted models. YouTube uses its native player and a separate server audio stream; other sites use tab capture.

## Implemented

- Native YouTube playback, restart on seek/voice change, visible overlay controls, zoom/fit/fill.
- Three Silero voices, phrase loudness normalization, full concatenated-WAV handling, preserved spelling and stress.
- Smooth original-audio ducking, buffering, long-phrase video-rate synchronization, optional captions.
- GigaAM word timestamps, Whisper fallback for failed or mixed-alphabet recognition, context-aware text translation.
- Per-viewer keys, revocation, ownership isolation, session expiry, request/capacity limits.
- Private inference endpoints, optional public HTTPS proxy and SSH gateway link.
- Disk-backed capture with decoded-buffer cleanup and no fixed application recording-duration limit.
- Deferred reload after local extension-file updates; public English documentation and MIT source release.

## Next validation

1. Run one-hour simultaneous viewing tests: memory, queues, seeking, network loss, recovery, and latency growth.
2. Compare English ASR accents, names, technical speech, and noise against Whisper.
3. Improve sentence boundaries based on reproducible missed/repeated-word examples.
4. Test mid-video advertisements, playlists, navigation, and source-player replacement.
5. Establish server-side YouTube access without depending on an operator's workstation proxy.
6. Compare integrated translation models for quality, phrase latency, memory, and concurrency using the same workload.
7. Package browser-store distribution and signed updates.
8. Explore live streams with explicit accumulated-delay management.

Voice cloning, arbitrary language pairs, accounts/billing, and cloud-provider routing are not implemented.
