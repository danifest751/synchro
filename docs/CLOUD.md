# Optional cloud text translation

Synchro supports **OpenAI**, **Kilo Gateway**, and **OpenRouter** with three explicit processing modes. The authenticated self-hosted gateway still fetches/decodes audio, synchronizes windows and post-processes speech; the extension is not serverless.

| Mode | Recognition | Translation and text preparation | Voice |
| --- | --- | --- | --- |
| Local | Own server | Own server | Own server |
| Cloud: translation only | Own server | Selected cloud provider | Own server |
| Cloud: everything | Selected cloud provider | Selected cloud provider | Selected cloud provider |

Cloud modes use **one key for the selected provider**, including when Kilo or OpenRouter routes requests to OpenAI models. A separate direct OpenAI key is not needed for those routes. There is no implicit fallback between local and cloud AI. Existing saved cloud configurations migrate to translation-only mode; local configurations stay local.

## Full cloud audio and measured cost

Full cloud mode uses `openai/whisper-1` and streaming `openai/gpt-audio-mini` through Kilo/OpenRouter. Direct OpenAI uses `whisper-1` and `gpt-4o-mini-tts`. The three voice choices become Nova, Onyx, and Echo. They are AI-generated voices, distinct from the local Silero voices. Router speech uses an exact-reading prompt and checks the returned transcript; changed words cause a bounded retry, then an explicit error. Speech is rendered in short parts for reliability while translation retains the full source window.

Cloud recognition receives only the committed portion of the audio window to avoid duplicate overlap text when a provider returns no timestamps. OpenRouter word timestamps are used when available; Kilo's tested route returned plain text, so its alignment is at window level. Do not interpret that as word-accurate alignment. Direct OpenAI's current `whisper-1` timestamp support is deprecated and scheduled to shut down on February 26, 2027; this prototype route must be migrated before then.

The YouTube overlay shows cumulative **provider-reported USD usage**; hover over it for ASR, translation, phrase alignment, text preparation and voice totals. Warmup and retried requests are included when the provider reports usage. Missing prices count as unpriced requests and the sum is marked incomplete, not assumed free. A provider-reported zero is displayed as zero but does not guarantee final billing. Direct OpenAI audio does not return a monetary cost in these responses, so its total is incomplete. The provider's account bill remains authoritative.

**Test full cloud pipeline** checks all three AI stages and reports its returned cost. The existing per-model minute estimate covers text translation only and must not be used as a full-cloud price estimate. Audio generation, speech density and retries can dominate that total. See the operator's own measured run before projecting hourly costs.

## Configure in the extension

1. Update the gateway and extension to 0.4.0 or later.
2. Open settings and configure your normal Synchro connection.
3. Under **Processing**, select a mode and provider.
4. Enter the model ID and an API key issued by that provider.
5. Click **Test translator**, or **Test full cloud pipeline** in full cloud mode. The result shows elapsed time and any provider-reported cost.
6. Select **Save and test**, then restart translation on the video.

| Provider | Default model | Destination |
| --- | --- | --- |
| Local server | Operator's configured model | Local gateway configuration |
| OpenAI | `gpt-4.1-mini` | `api.openai.com` |
| Kilo Gateway | `tencent/hy-mt2-1.8b` | `ai-gateway.kilo.ai` |
| OpenRouter | `google/gemma-4-26b-a4b-it` | `openrouter.ai` |

Model IDs are editable; availability and pricing depend on the provider and account. General instruction models must support Chat Completions and JSON-schema structured output. Arbitrary API base URLs are not accepted. OpenAI requests use `max_completion_tokens` and `store=false`; router requests use `max_tokens`. Output length is bounded. Reasoning models needing different parameters may not work with this prototype.

## Model list, balance, and price estimate

Version 0.4.1 adds searchable live Kilo and OpenRouter catalogs. HY-MT2 30B-A3B, 7B, and 1.8B appear first, followed by the tested Gemma 26B and a small set of fast general-model candidates. This is a shortlist for translation, not a claim that every model has been benchmarked. Your saved choice is preserved and highlighted; choose another row to change it. Other compatible models are searchable. At most 60 matches are shown at once, so narrow a broad search. You can still enter an exact ID manually.

The list filters for text output and structured-output support, with a special exception for supported HY-MT2 plain-text translation. Image-output and embedding models are excluded. Provider catalogs and token prices are fetched through the same configured server tunnels and cached for up to five minutes. **Refresh models** rechecks the catalog and shows its fetch time.

Kilo's available personal balance is read from its account API using your key. OpenRouter shows remaining personal credits. Balances refresh when the provider/key is selected or saved, after a translator test, and when you select **Refresh balance**. They are not continuously polled during playback. Account balances are not placed in the shared catalog cache or persisted in extension storage. Invalid keys and unavailable balance data show an error, not an assumed zero. Organization balances are not implemented.

Each model row shows an approximate USD cost per minute of speech. The selected model also shows cost per hour and its published input/output price per million tokens. The calculation is:

`estimated minute = input tokens per minute × input price per token + output tokens per minute × output price per token`

The baseline assumes 600 input + 450 output tokens/minute for HY-MT2, or 3,500 input + 450 output tokens/minute for general models, whose repeated instructions and recent context add input overhead. These are approximate assumptions, not measured billable usage or a guarantee. Speech pace, window length, tokenizer, phrasing, retries, extra reasoning, and caching can change the bill. The estimate covers the selected translator only; ASR, speech synthesis, and HY-MT2's extra cloud speech-preparation calls are excluded. Missing prices display **unavailable**; confirmed zero prices remain zero. Direct OpenAI model pricing is not supplied by these router catalogs, so its existing manual model-ID field remains available without a guessed price.

Provider profiles keep separate model IDs and keys in this browser's local extension storage. The key input is masked and displays a saved-key placeholder on reopen. **Remove this provider key** removes that profile's key and resets its saved active selection to Local server. Switching providers does not send a key to the previous provider. Settings changes take effect on a new playback session.

## HY-MT2 is a specialized translator

HY-MT2 accepts the documented plain-text translation prompt rather than the generic JSON conversation. Synchro sends the current recognized English window and reads a plain Russian translation. It does not send the JSON history wrapper to this model.

If that result contains Latin names or digits, **Gemma 4 26B-A4B through the same selected cloud provider and API key** rewrites only those elements into spoken Cyrillic names and Russian number words when the installation uses Russian speech preparation. The model ID is `google/gemma-4-26b-a4b-it`. No local LLM is called in cloud mode. Purely Cyrillic output needs no extra preparation request. This extra cloud request adds latency and billable tokens; it is not included in the basic HY-MT2 minute estimate or standalone API timing. If this preparation model is unavailable, the error is shown instead of switching to local inference.

HY-MT2 does not use the generic shortening retry. Long narration is synchronized through the existing tempo/video-rate path. For a cloud model that can perform translation and speech preparation in one structured request, choose an appropriate general instruction model instead.

## Data and credentials

Your API key travels from the extension to your authenticated Synchro gateway in the session-creation or translator-test request. Use HTTPS for remote gateways, or a trusted loopback SSH forward. The gateway operator can access submitted keys and text: connect only to a server you trust.

During playback, the key is held in that session's memory, masked in its settings representation, and cleared when the session is deleted. It is not written into the guest key registry, returned by API responses, or included in generated extension archives. Browser storage is not an encrypted password manager; protect the browser profile and remove unused keys.

## Existing server-to-server SSH tunnels

The gateway can reuse a local TCP forward to a provider's HTTPS port. Set `SYNCHRO_KILO_TUNNEL_PORT`, `SYNCHRO_OPENROUTER_TUNNEL_PORT`, or `SYNCHRO_OPENAI_TUNNEL_PORT` to the operator's loopback port and restart the gateway. For example, an existing forward on 8443 to Kilo and 8444 to OpenRouter can be reused without a workstation proxy. A nonzero setting routes that provider through the SSH forward and takes precedence over `SYNCHRO_CLOUD_PROXY`.

Synchro connects to loopback while preserving the provider's original HTTP Host and TLS SNI hostname. Tunnel requests close their HTTP connection after use so different provider hostnames on one loopback port cannot reuse the wrong TLS connection. Certificate verification stays enabled; do not use `verify=false`. The SSH destination must serve the intended API. If the tunnel fails, Synchro reports the error instead of retrying the provider directly. Browser-to-gateway access is independent of these outbound routes.

`deploy/openai_tunnel.service` is an optional user-service template for a dedicated OpenAI forward on 8445. Adapt its gateway host and key path, pre-provision trusted SSH host keys, and restrict the gateway account to `api.openai.com:443` with no interactive shell. Existing Kilo/OpenRouter tunnels need not be restarted or changed.

The selected cloud service receives recognized speech text and, for general instruction models, recent translation context. Its own retention and billing terms apply. A cloud error does not silently switch providers or transmit your transcript to a different provider. Existing local playback remains available when you explicitly select Local server.

## Test errors

- **401:** check that the API key belongs to the selected provider.
- **402:** check credits/billing.
- **429:** provider rate limit reached.
- **400:** check the model ID and structured-output support.
- **Timeout:** check the inference host's outbound HTTPS route, not just the browser's route.
- **403:** verify account access and the inference host's network route. If you have a trusted HTTPS CONNECT proxy, set `SYNCHRO_CLOUD_PROXY` in the gateway environment and restart the gateway. This affects cloud requests only, leaving local services unchanged. The optional `tools/connect.ps1` helper supports the three exact API hosts; its default forwarded proxy URL is `http://127.0.0.1:18770`.
- **Speech preparation failed with HY-MT2:** check access to the cloud Gemma model on the selected provider.

Version 0.4.2 retries one transient network failure, HTTP 502/503/504, or empty/invalid response inside the same translation operation. Authentication, credit, rate-limit, and content-filter failures are not automatically retried. The initial output budget is 512 tokens; an explicit output-limit response gets one retry with 1,024 tokens. Both attempts share a 60-second total budget. A retry may incur additional provider usage, including when a response was lost after processing. No provider or local fallback is implicit.

Empty responses, output limits, content filters, and network failures have separate messages with a diagnostic reference. Gateway logs record provider/model, attempt, duration, HTTP status, finish reason and numeric output/reasoning usage, without transcripts, raw responses, reasoning text or keys. Historical failures from older gateways cannot be reconstructed from these new logs. In the YouTube overlay, **Dismiss** clears the error message; **Retry translation** or Play restarts at the current video position and clears the old error.

The button tests a real translation, so it can incur API usage. A successful short test is not a guarantee of long-session throughput or translation accuracy.

Provider references: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Kilo Gateway API](https://kilo.ai/docs/gateway/api-reference), [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs).

Audio references: [Kilo voice transcription](https://kilo.ai/docs/code-with-ai/features/speech-to-text), [OpenRouter audio output](https://openrouter.ai/docs/guides/overview/multimodal/audio), [OpenRouter transcription](https://openrouter.ai/docs/guides/overview/multimodal/stt), [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text), [OpenAI speech generation](https://developers.openai.com/api/docs/guides/text-to-speech).

Since 0.4.3, source timestamps split voiceover into phrases while translation retains the complete window. Semantic phrase alignment is an additional text request; HY-MT2 uses Gemma through the same provider. Its reported cost appears as **alignment** in usage totals and is excluded from the model picker's base translation estimate. Models may condense neighboring phrases; repeated alignment boundaries merge only those neighbors. ASR without word timestamps still uses a coarser window interval.
