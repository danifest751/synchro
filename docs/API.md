# Gateway API

Base URL: the operator-configured loopback or HTTPS origin. All session state belongs to one gateway process. Requests and responses are JSON unless noted otherwise. Model endpoints are private implementation details and must not be exposed as this API.

## Authentication

Except for `/health`, send `Authorization: Bearer <personal-key>`. Browser requests must have the exact configured `Origin: chrome-extension://<extension-id>`. Non-browser clients may omit Origin; a matching key is still required. Never put credentials in a URL.

The owner key is configured directly. Guest keys are matched against SHA-256 hashes in the registry, which is re-read on every authenticated request. Each key can own one active session. Default global capacity is three sessions, shared by both playback modes. The per-key limit is 120 authenticated requests per minute. Idle unlocked sessions expire after 120 seconds; a janitor checks every ten seconds.

## Endpoints

| Method and path | Description |
| --- | --- |
| `GET /health` | Unauthenticated service name, version, `max_sessions` |
| `GET /api/check` | Validate credentials; returns `ok`, client name, `max_sessions` |
| `POST /api/translation/check` | Test selected local/cloud text translator; returns translation and elapsed seconds |
| `POST /api/translation/models` | Fetch filtered Kilo/OpenRouter models and per-token prices; body `{"provider":"kilo"}`; no provider key needed |
| `POST /api/translation/balance` | Read personal account balance; body is a cloud `translation` object with the provider key |
| `POST /api/video` | Create a native-YouTube session and warm up models |
| `GET /api/video/{id}` | Read `ready_until` and `finished`; also refreshes activity |
| `POST /api/video/{id}/next` | Decode and translate the next audio window |
| `POST /api/session?voice=female` | Create a tab-capture session and warm up models |
| `POST /api/session/{id}/chunk` | Submit PCM input for a capture session |
| `DELETE /api/session/{id}` | Close either type of session; returns 204 |

### Create a YouTube session

```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "position": 0,
  "voice": "female"
}
```

Session creation optionally accepts a `translation` object: `{"provider":"kilo","model":"tencent/hy-mt2-1.8b","api_key":"YOUR_PRIVATE_PROVIDER_KEY"}`. Supported providers are `local` (default), `openai`, `kilo`, and `openrouter`. Model IDs are limited to 128 characters and fixed provider URLs are used. The key is never included in a session response. Send the same object directly as the body of `POST /api/translation/check`. Model-validation failures return a sanitized message rather than echoing a submitted key.

`url` is a validated HTTPS YouTube video URL, at most 2048 characters. `position` is a finite nonnegative number in seconds and must precede the end of the video. `voice` is `female` (Xenia), `male` (Aidar), or `male-eugene` (Eugene). Only recorded public videos are supported.

The response contains `session_id`, `base` (actual starting position), and `duration` in seconds. Fetch windows sequentially with `/next`; do not issue concurrent requests for the same session. Close the session on cancellation and start a new one after seeking or changing voices.

### Create a capture session

`POST /api/session?voice=female` has an empty body and returns:

```json
{"session_id":"example-id","window_samples":128000,"step_samples":112000}
```

New clients can instead send JSON `{"voice":"female","translation":{"provider":"local"}}` to `/api/session`. The legacy query/empty-body request remains compatible. Both capture and native-YouTube sessions freeze their own translation settings when created.

Upload raw **mono PCM16 little-endian at 16 kHz**, without a WAV header. Each non-final window contains 128000 samples (256000 bytes). Advance by 112000 samples, so windows overlap by one second. A final window can be shorter and must contain a positive whole number of samples.

Required chunk headers:

| Header | Meaning |
| --- | --- |
| `Content-Type: application/octet-stream` | Raw PCM request body |
| `X-Offset` | Integer sample offset, starting at zero; must match server progression |
| `X-Final` | Exactly `0` or `1` |

### Translation response

Both `/next` and `/chunk` return this shape:

```json
{
  "session_id": "example-id",
  "ready_until": 7.0,
  "finished": false,
  "segments": [{
    "id": 1,
    "start": 0.4,
    "duration": 6.8,
    "source_duration": 6.6,
    "source": "Recognized English speech.",
    "text": "Russian translation text",
    "sample_rate": 48000,
    "wav": "BASE64_ENCODED_MONO_WAV"
  }]
}
```

Times are seconds on the source timeline. `duration` is synthesized audio length; `source_duration` is its allocated video interval. They may differ, so clients must apply the timeline rate mapping instead of assuming every WAV ends at `start + source_duration`. `ready_until` can advance with an empty segment list during silence. An empty finished response is valid at EOF.

## Errors

FastAPI errors usually return `{"detail":"message"}`; request-validation errors may contain a list. A wrong owner's session appears as not found. Failed sessions should be deleted and restarted rather than reused.

| Status | Meaning |
| --- | --- |
| 400 | Invalid window metadata |
| 401 / 403 | Invalid key / rejected browser Origin |
| 404 | Missing session or another viewer's session |
| 409 | Key already in use, request already processing, or wrong session mode |
| 413 | Audio window exceeds its size limit |
| 422 | Invalid input, timing sequence, or rejected video URL |
| 429 | Per-key request rate exceeded |
| 502 | YouTube, inference, or audio processing failed |
| 503 | Capacity full, key registry unavailable, or model warmup failed |

The gateway model client timeout is 90 seconds. Session creation has a 105-second budget. Reverse proxies should allow at least 120 seconds for response headers. Warm models and preload weights before accepting viewers.
