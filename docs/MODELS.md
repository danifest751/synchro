# Models, licenses, and performance

## Reference inference stack

| Task | Model/runtime | Placement |
| --- | --- | --- |
| Primary ASR | GigaAM Multilingual 220M CTC, ONNX Runtime | CPU, 8 intra-op threads |
| ASR fallback | Whisper large-v3-turbo, faster-whisper through Speaches | Separate GPU |
| Text translation | Gemma 4 26B-A4B GGUF, llama.cpp with optional MTP | RTX 5060 Ti 16 GB |
| Speech | Silero V5 CIS with Russian stress marks from RUAccent | CPU, 2 synthesis threads |

Synchro translates **recognized text**. It does not translate video frames or perform end-to-end speech-to-speech inference. The public repository contains integration code, not weights. Download and review models separately.

Version 0.4.0 also supports [optional cloud text translation](CLOUD.md). Its HY-MT2 route uses the provider's plain-text API. Since 0.4.2, speech preparation uses cloud Gemma through the same provider instead of a local LLM.

## What is implemented

The gateway's translator requests a JSON object containing `translation`, passes the last two source/translation pairs as context, and asks for speech-friendly Russian. With Silero enabled it rejects remaining Latin letters and digits after one rewrite attempt. The model must support these requirements; a raw translation benchmark is not proof of drop-in compatibility.

GigaAM's public model card describes moderate English quality. The current service uses greedy CTC decoding and does not expose a general accuracy/temperature/beam control. Silero exposes five selected Russian speakers. The gateway prepares stress marks before synthesis. The host worker runs RUAccent directly on CPU.

## Historical prototype measurements

These are short development measurements from November 9–10, 2026. They are not hardware guarantees or long-session service-level claims. Model revisions, quantization, runtime build, audio content, queueing, and other GPU workloads matter.

- Gemma 26B-A4B with MTP on RTX 5060 Ti: approximately **202–227 generated tokens/s**, **0.41–0.77 s** for short translation requests. The full model/draft setup used roughly 15.6 GB of VRAM.
- GigaAM 220M on Xeon E5-2630 v4, warmed: approximately **0.38 s** for the 11-second JFK speech sample with eight threads. More threads were not automatically faster; ten threads took approximately 0.42 s.
- Three simultaneous different videos, separate keys and voices, four windows each: approximately **9.4 / 10.1 / 15.6 s** of processing for about 28 seconds of source per viewer. This was a short integration test, not an hour-long capacity test.

Additional standalone text-translator experiments on **CMP 50HX**:

| Model | Short sequential phrase latency | Shared model throughput | Approximate extra VRAM after warmup |
| --- | --- | --- | --- |
| HY-MT2 1.8B Q4_K_M, llama.cpp | 0.13–0.40 s | 5.96 phrases/s, 4 slots, 6 clients | 1.8 GiB, 4 slots |
| TranslateGemma 4B Q4_K_M, llama.cpp | 0.21–0.57 s | 3.61 phrases/s, 4 slots, 6 clients | 3.4 GiB, 4 slots |
| OPUS-MT TC Big EN→ZLE FP16, CTranslate2 | 0.02–0.06 s | 108 phrases/s, explicit batch of 8 | 0.7 GiB, single model after warmup |

The LLM tests used continuous concurrent requests; OPUS used fixed batches. Those throughput columns are different workloads, not an apples-to-apples ranking. VRAM is the observed increment after warmup, not peak allocation. HY-MT2 and TranslateGemma generated roughly 166 and 99 tokens/s respectively; their tokenizers differ. OPUS was very fast but mistranslated idioms literally. TranslateGemma handled some idioms well and also made factual/grammatical mistakes. These standalone measurements predate the optional HY-MT2 cloud route in 0.4.0; they do not measure its network or speech-preparation overhead.

Run `tools/smoke.py`, `tools/smoke_youtube.py`, and `tools/bench_viewers.py` against your own installation to measure the complete chain. Warmup/download time and processing time should be reported separately. Long viewing sessions, queue fairness, and recovery need further validation.

## Third-party terms

Synchro's [MIT license](../LICENSE) applies to its own source and documentation. It grants no additional rights to separately obtained weights, voices, runtimes, or content.

- [GigaAM Multilingual](https://huggingface.co/ai-sage/GigaAM-Multilingual) and the [ONNX export](https://huggingface.co/istupakov/gigaam-multilingual-ctc-onnx) identify MIT licenses in their model cards.
- [Gemma 4](https://ai.google.dev/gemma/apache_2) is published under Apache 2.0. Other Gemma generations and specialized variants can have different terms; check the actual model you download.
- [Silero V5 CIS Base](https://github.com/snakers4/silero-models#v5-cis-base-models) lists the selected weights under MIT. Other Silero releases can use different terms. Review [RUAccent's terms](https://github.com/Den4ikAI/ruaccent) separately.
- Whisper, faster-whisper, Speaches, CTranslate2, ONNX Runtime, PyTorch, and individual Piper voices retain their own terms.
- The optional Piper/eSpeak data path includes GPL-licensed eSpeak NG material inside the built speech image. Distribution of that image has separate obligations. This repository does not bundle that image or those data.

See [third-party notices](../THIRD_PARTY_NOTICES.md) for the retained Avorythm notice and upstream links.

## Chinese, Korean and Japanese recognition on CPU

Measured on a Ryzen 7 8745HS with eight threads, the same 21-second English window, median of three runs: SenseVoice-Small int8 (sherpa-onnx) 0.42 s, GigaAM Multilingual CTC 0.92 s, faster-whisper large-v3-turbo int8 with word timestamps 7.49 s. On real 21-second talk windows SenseVoice took 1.7–2.2 s including the first model load. GigaAM's vocabulary contains only Latin and Cyrillic letters, so it cannot transcribe Han, kana, or Hangul. SenseVoice transcribes English with dropped and merged words, so English stays on GigaAM. Its Korean output can split words with extra spaces; translation tolerates this.
