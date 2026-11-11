# User guide

## Install the extension

You need either a running Synchro server or a personal connection from its operator. Downloading the source alone does not start the models.

1. Unpack the supplied ZIP into a permanent directory, or use the repository's `extension/` directory.
2. Open `chrome://extensions` or `edge://extensions`.
3. Enable **Developer mode**, select **Load unpacked**, and choose `extension/`.
4. Pin Synchro to the toolbar and open its settings.
5. Import your private `connection.json`, or enter the approved server URL and token.
6. Select a voice, set the initial buffer (10–40 seconds; default 20), and click **Save and test**.

Keep the extension directory in place. A personal connection contains an access key: do not publish it or share it with another person. Server operators should issue one key per viewer.

Under **Processing**, choose Local, Cloud: text translation only, or Cloud: recognition, translation and voice. Cloud modes use one OpenAI, Kilo Gateway, or OpenRouter key. Enter your provider key and translation model, then use the test button for the selected mode. Save settings before starting playback. See [cloud modes](CLOUD.md) for data flow, audio charges and HY-MT2 requirements.

## Watch YouTube

1. Open a public English recorded video and wait for advertisements to finish.
2. Click the Synchro toolbar icon on that tab, then **Translate tab**. The actual toolbar click grants access to the current tab.
3. Wait for audio and models to prepare, then select **Play with translation** in the player overlay.
4. Use normal YouTube controls to pause, seek, or enter fullscreen.

Video is loaded by YouTube directly in your browser. Synchro's server separately retrieves the audio track. Seeking and changing voices discard the current translation session and prepare audio again from the selected position.

## Overlay controls

| Control | Effect |
| --- | --- |
| Play/pause | Start or pause translated playback |
| Captions | Show or hide translated captions; off by default |
| Settings | Select voice, adjust audio levels and picture |
| Voice | Local: Roman, Eduard, Albina, Alexander, Alfia; full cloud: Nova, Onyx, Echo |
| Dismiss / Retry translation | Clear an error message or restart at the current position |
| Cloud usage | Provider-reported USD total; hover for stage details and missing-price notes |
| Voiceover / Original | Set the two audio levels independently |
| Zoom / Fit / Fill | Adjust video framing; Fit resets the fit view |
| Close | End translation and restore the source player's settings |

Original audio remains audible between phrases and is lowered while Russian speech plays. Buffering pauses the video until translation catches up. Video speed adjusts within each speech phrase so its start and end follow the voiceover; pauses retain normal speed. This uses estimated recognition timestamps, so it does not promise exact lip synchronization. Speech is not simply cut off at a chunk boundary.

## Other sites: tab capture

Synchro captures the current tab and opens a separate delayed player. Keep the source tab open and control delayed playback in the Synchro window. **Finish recording** stops capture and processes the remaining audio. Use Space to pause, F for fullscreen, and C for captions. Drag a zoomed picture to pan; double-click to reset zoom.

Captured video and synthesized audio are stored in the browser's Origin Private File System. There is no fixed 15-minute or 512 MB application limit; available disk space and browser quota still apply. A new capture replaces the previous recording. Capture is not restored after a browser restart. DRM-protected content may not be capturable.

## Update

Replace the files in the installed `extension/` directory, then select **Reload** on the browser's extensions page and refresh the source tab. Keep Developer mode enabled. Avoid replacing files during playback; when copying manually, copy `manifest.json` last.

The optional automatic check notices a changed manifest version in that same local folder once a minute, then reloads after playback is closed. An optional external [GitHub updater](UPDATES.md) checks stable Releases every 15 minutes and installs verified files into that folder, preserving server endpoints and extension identity. On Windows, install its current-user schedule once with `tools/install-updater.ps1`.

## If playback fails

Close translation and start it again. For a connection error, first use **Save and test** in settings. If a key is already in use, close the previous Synchro session; abandoned sessions expire after about two minutes. Detailed steps are in [troubleshooting](TROUBLESHOOTING.md).
