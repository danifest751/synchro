# Optional cloud text translation

Synchro can translate recognized text using **OpenAI**, **Kilo Gateway**, or **OpenRouter**. **Local server** remains the default. Recognition and speech synthesis still run on your own inference services; selecting a cloud translator does not make Synchro a serverless extension.

## Configure in the extension

1. Update the gateway and extension to 0.4.0 or later.
2. Open settings and configure your normal Synchro connection.
3. Under **Text translation**, select a provider.
4. Enter the model ID and an API key issued by that provider.
5. Click **Test translator** to run a short translation through the gateway. The result shows a translated sentence and elapsed time.
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

The baseline assumes 600 input + 450 output tokens/minute for HY-MT2, or 3,500 input + 450 output tokens/minute for general models, whose repeated instructions and recent context add input overhead. These are approximate assumptions, not measured billable usage or a guarantee. Speech pace, tokenizer, phrasing, retries, extra reasoning, and caching can change the bill. The estimate covers cloud text translation only; local ASR, speech synthesis, and HY-MT2's local speech preparation are excluded. Missing prices display **unavailable**; confirmed zero prices remain zero. Direct OpenAI model pricing is not supplied by these router catalogs, so its existing manual model-ID field remains available without a guessed price.

Provider profiles keep separate model IDs and keys in this browser's local extension storage. The key input is masked and displays a saved-key placeholder on reopen. **Remove this provider key** removes that profile's key and resets its saved active selection to Local server. Switching providers does not send a key to the previous provider. Settings changes take effect on a new playback session.

## HY-MT2 is a specialized translator

HY-MT2 accepts the documented plain-text translation prompt rather than the generic JSON conversation. Synchro sends the current recognized English window and reads a plain Russian translation. It does not send the JSON history wrapper to this model.

If that result contains Latin names or digits, the existing **local translation model** rewrites only those elements into spoken Cyrillic names and Russian number words before Silero synthesis. Keep the local translator online when using HY-MT2 with Silero. Purely Cyrillic output needs no extra local text request. This preparation adds latency and is not included in a standalone HY-MT2 API timing.

HY-MT2 does not use the generic shortening retry. Long narration is synchronized through the existing tempo/video-rate path. For a cloud model that can perform translation and speech preparation in one structured request, choose an appropriate general instruction model instead.

## Data and credentials

Your API key travels from the extension to your authenticated Synchro gateway in the session-creation or translator-test request. Use HTTPS for remote gateways, or a trusted loopback SSH forward. The gateway operator can access submitted keys and text: connect only to a server you trust.

During playback, the key is held in that session's memory, masked in its settings representation, and cleared when the session is deleted. It is not written into the guest key registry, returned by API responses, or included in generated extension archives. Browser storage is not an encrypted password manager; protect the browser profile and remove unused keys.

## Existing server-to-server SSH tunnels

The gateway can reuse a local TCP forward to a provider's HTTPS port. Set `SYNCHRO_KILO_TUNNEL_PORT`, `SYNCHRO_OPENROUTER_TUNNEL_PORT`, or `SYNCHRO_OPENAI_TUNNEL_PORT` to the operator's loopback port and restart the gateway. For example, an existing forward on 8443 to Kilo and 8444 to OpenRouter can be reused without a workstation proxy. A nonzero setting routes that provider through the SSH forward and takes precedence over `SYNCHRO_CLOUD_PROXY`.

Synchro connects to loopback while preserving the provider's original HTTP Host and TLS SNI hostname. Certificate verification stays enabled; do not use `verify=false`. The SSH destination must serve the intended API. If the tunnel fails, Synchro reports the error instead of retrying the provider directly. Browser-to-gateway access is independent of these outbound routes.

`deploy/openai_tunnel.service` is an optional user-service template for a dedicated OpenAI forward on 8445. Adapt its gateway host and key path, pre-provision trusted SSH host keys, and restrict the gateway account to `api.openai.com:443` with no interactive shell. Existing Kilo/OpenRouter tunnels need not be restarted or changed.

The selected cloud service receives recognized speech text and, for general instruction models, recent translation context. Its own retention and billing terms apply. A cloud error does not silently switch providers or transmit your transcript to a different provider. Existing local playback remains available when you explicitly select Local server.

## Test errors

- **401:** check that the API key belongs to the selected provider.
- **402:** check credits/billing.
- **429:** provider rate limit reached.
- **400:** check the model ID and structured-output support.
- **Timeout:** check the inference host's outbound HTTPS route, not just the browser's route.
- **403:** verify account access and the inference host's network route. If you have a trusted HTTPS CONNECT proxy, set `SYNCHRO_CLOUD_PROXY` in the gateway environment and restart the gateway. This affects cloud requests only, leaving local services unchanged. The optional `tools/connect.ps1` helper supports the three exact API hosts; its default forwarded proxy URL is `http://127.0.0.1:18770`.
- **Local preparation failed with HY-MT2:** check the operator's local translation service.

The button tests a real translation, so it can incur API usage. A successful short test is not a guarantee of long-session throughput or translation accuracy.

Provider references: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Kilo Gateway API](https://kilo.ai/docs/gateway/api-reference), [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs).
