# Optional VoiceStudio voices

Synchro 0.4.3 can use six operator-configured VoiceStudio profiles: Female 1–3 and Male 1–3. They appear in both extension settings and the YouTube overlay after the gateway advertises them. Xenia, Aidar and Eugene remain available. Full cloud mode uses the provider's Nova, Onyx and Echo instead.

VoiceStudio is a separately installed service, accessed through its OpenAI-compatible `/v1/audio/speech` API. No VoiceStudio application code, profile recordings or model weights are distributed with Synchro. The integration was tested with VoiceStudio 0.5.7 and its OmniVoice engine. Create the six profiles in VoiceStudio first, set their language to Russian and copy their IDs into a private gateway environment file:

```dotenv
SYNCHRO_VOICESTUDIO_URL=http://127.0.0.1:3900
SYNCHRO_VOICESTUDIO_TOKEN=replace-with-private-server-key
SYNCHRO_VOICESTUDIO_VOICES={"studio-female-1":"profile-id-1","studio-female-2":"profile-id-2","studio-female-3":"profile-id-3","studio-male-1":"profile-id-4","studio-male-2":"profile-id-5","studio-male-3":"profile-id-6"}
SYNCHRO_ACCENT_URL=http://127.0.0.1:8775
```

Restart the gateway after changing its environment. Provide a separately installed RUAccent-compatible service at `SYNCHRO_ACCENT_URL`; `POST /accent` accepts `{"text":"..."}` and returns text with `+` before stressed vowels. Synchro validates its words, transfers stress to the original characters and preserves original punctuation and e/yo spelling. If the annotation changes words or the service fails, VoiceStudio receives the original text and a metadata-only warning is logged. Stress annotation is an aid, not a guarantee of correct pronunciation by the speech model.

Keep VoiceStudio authenticated and bound to loopback or a trusted private interface. The extension receives logical voice IDs and display names only. Its keys cannot change profile mappings or submit an arbitrary speech endpoint. The gateway sends each translated phrase to the configured service and normalizes its returned WAV.

## Sharing GPU memory

The tested 16 GB deployment cannot keep its large local Gemma translator and OmniVoice in VRAM together. Set `SYNCHRO_VOICESTUDIO_SHARED_GPU=1` on that gateway to offer VoiceStudio only in **Cloud: text translation only**. Local mode retains the CPU Silero voices. This restriction is unnecessary if the translator and VoiceStudio have independent resources.

VoiceStudio's supported `omnivoice-subprocess` backend can release its CUDA worker after an idle timeout (`OMNIVOICE_SIDECAR_IDLE_TIMEOUT_S=30`). The tested local llama.cpp translator also unloads after idle. This prevents residual GPU allocations from one service blocking the other; cold voice requests take longer. Concurrent load and production capacity need separate measurement.

The [host CPU worker](HOST.md) can use the same integration through a private SSH forward. Selecting a voice labeled **VoiceStudio · server** sends speech text to that server; it does not run OmniVoice on the host CPU. Selecting Xenia/Aidar/Eugene keeps speech synthesis on the host.

## Licenses

[VoiceStudio](https://github.com/debpalash/VoiceStudio) has its own application license. [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) weights have noncommercial terms; its Higgs Audio tokenizer has separate Higgs/Meta Llama terms. Accept the applicable upstream conditions before downloading or using them. Synchro's MIT license does not grant rights to these models or reference voices.
