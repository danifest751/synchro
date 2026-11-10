# Troubleshooting

## Cannot connect in settings

Check `/health` on the configured host, then verify the URL and private key with **Save and test**. A browser connection file can use only loopback or the exact HTTPS origin compiled into that extension. Change both manifest permissions/CSP and `PUBLIC_API` when configuring another remote host. Verify the installed extension ID matches `SYNCHRO_ORIGIN`. A token does not authorize a different web Origin.

Never paste access keys or complete connection files into an issue. Redact `Authorization` headers and private environment files before sharing diagnostics.

## Translation will not start on YouTube

Wait for a regular recorded video to load and for the advertisement to finish. Click the Synchro toolbar icon on the actual video tab: starting it indirectly may not grant `activeTab`. After reloading the extension, refresh the YouTube tab too. Private, age-restricted, and live videos are not supported by this path.

## YouTube plays, but the server cannot fetch audio

Browser video and server audio use different network paths. Inspect gateway logs and test yt-dlp from the inference host's network, with the configured proxy if applicable. Ensure Node.js and FFmpeg are available. A server IP can encounter a sign-in challenge even when the same video works in the browser. Browser cookies are not automatically transferred. If using the optional operator-side proxy, keep its computer, network route, and SSH tunnel online.

## 502 after the first translated window

Use `deploy/Caddyfile` as the reference for `transport http { keepalive off }`. Uvicorn or an SSH tunnel can close an idle upstream connection before the proxy does. Validate and reload Caddy after changing it; this server-side fix does not require reinstalling the extension.

For continuing 502s, inspect the gateway error and the model services separately. Check speech and translation timeouts, a truncated YouTube stream, GPU memory, and service availability. After a failed stream, close translation and restart it.

## Session occupied or server full

One key permits one active session. Close the previous translation, or wait about two minutes for an idle session to expire. Issue separate guest keys for different viewers. The default shared cap is three; increasing it does not make inference faster. Measure the complete pipeline before raising capacity.

## Speech starts late, pauses, or feels disconnected

Check whether the original speech begins late inside the current eight-second ASR window, whether ASR missed words, and whether the translated phrase is much shorter than its source interval. Some pauses are source silence; others can be recognition/window-boundary errors. Provide a public video URL, source timestamp, expected words, and whether the issue is reproducible. Do not attach private connection files.

The browser pauses while translation catches up and slows video for long phrases. This prototype does not yet have sentence-level boundary stabilization. GigaAM's fallback detects failures and mixed alphabets, not every semantically wrong English transcript.

## Missing sentences or changing loudness

Use the current `join_wav` implementation: older code read only the first RIFF file when a TTS response concatenated multiple sentence WAVs. Current loudness normalization requires working FFmpeg `loudnorm` support. Verify the speech service returns mono 16-bit WAV with intact headers and consistent sample rates. Compare saved output audio before blaming browser volume controls.

## Wrong stress or unexpected spelling

Silero receives original translated spelling and handles stress itself. Keep `put_yo=False` and `put_yo_homo=False`; automatic substitution previously changed a normal word's meaning. Names must be transliterated into Cyrillic and numbers written as Russian words for the selected Silero model. The gateway retries text preparation once. The optional Piper path validates that an accent service changed only stress and permitted spelling variants, then restores the original spelling.

## Tab capture, storage, and picture controls

Keep the source tab open. A full disk, browser quota, unsupported MediaRecorder codec, or DRM can stop recording. Captured data is local to the extension's OPFS; a new recording replaces the previous one. **Fit** resets framing; double-click resets capture-player zoom. If a site replaces its video element or navigates, start translation again.

## Local update does not apply

The update checker reads files already present in the installation folder; it does not download them. Close all Synchro playback, confirm the manifest version changed, and reload the extension manually if necessary. Refresh source tabs after reloading. Do not install a second unpacked copy to update the existing one.
