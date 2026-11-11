# Third party notices

The resampling logic in `extension/pcm-worklet.js` is adapted from Avorythm,
commit be95dc7fb2cfaa9d4a5055ab714bdec5d1b496cb:
https://github.com/msmahdinejad/avorythm

MIT License

Copyright (c) 2026 Mohammad Saleh Mahdinejad

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Server dependencies and models retain their own licenses. This notice does not
relicense model weights or Piper voices.

The YouTube audio format selection follows the approach used in the
DubPipe project (src/util/ytdlp.ts, MIT). yt-dlp is installed separately in the
server image under the Unlicense: https://github.com/yt-dlp/yt-dlp . Its optional
dependencies and the Node.js runtime retain their respective licenses.

The speech image updates eSpeak NG data from the hash-verified official Piper
1.8.0 wheel to support Russian U+0301 stress marks. eSpeak NG data retain their
GPL license: https://github.com/espeak-ng/espeak-ng . RUAccent is accessed through
an optional separately installed accent service: https://github.com/Den4ikAI/ruaccent .

GigaAM Multilingual (220M CTC) retains its MIT license:
https://huggingface.co/ai-sage/GigaAM-Multilingual . The CPU service uses the
ONNX export from https://huggingface.co/istupakov/gigaam-multilingual-ctc-onnx
and a separately installed onnx-asr / ONNX Runtime environment. Their licenses remain
applicable: https://github.com/istupakov/onnx-asr and https://github.com/microsoft/onnxruntime .

Synchro's private CPU speech service supports separately obtained Silero v5.5
Russian model (Aidar, Eugene, Xenia). Model code and weights retain the upstream
license conditions: https://github.com/snakers4/silero-models and
https://github.com/snakers4/silero-models/blob/master/LICENSE . Model weights
are not included in this repository or extension archives. The upstream default
model license is CC BY-NC-SA 4.0; Synchro's MIT license does not override it.

Gemma 4 model weights retain their Apache 2.0 license:
https://ai.google.dev/gemma/apache_2 . Other Gemma variants can have different
terms. llama.cpp is a separately installed runtime:
https://github.com/ggml-org/llama.cpp . No weights or runtime binaries are bundled.

Whisper / faster-whisper, Speaches, PyTorch, and FFmpeg are installed separately
and retain their upstream licenses:
https://github.com/openai/whisper , https://github.com/SYSTRAN/faster-whisper ,
https://github.com/speaches-ai/speaches , https://github.com/pytorch/pytorch ,
https://ffmpeg.org/legal.html . Piper voice licenses must be checked per voice.

SenseVoice-Small weights (FunAudioLLM / Alibaba Group) are not distributed with
Synchro. They are licensed under the FunASR Model Open Source License Agreement,
which requires attribution of the source and author and retaining the model name:
https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE ,
https://github.com/FunAudioLLM/SenseVoice . The sherpa-onnx runtime is
Apache-2.0: https://github.com/k2-fsa/sherpa-onnx .

The Windows desktop installer (desktop/) additionally bundles, unmodified:
mpv (https://mpv.io , GPL-2.0-or-later; Windows build by shinchiro,
https://github.com/shinchiro/mpv-winbuild-cmake , release 20261111, whose
build scripts and component sources are linked from that repository);
FFmpeg (https://ffmpeg.org , GPL-3.0 build by gyan.dev,
https://www.gyan.dev/ffmpeg/builds/ ; sources at https://ffmpeg.org/download.html);
a portable CPython 3.12 runtime (python-build-standalone,
https://github.com/astral-sh/python-build-standalone , PSF license and the
licenses of its bundled libraries); PyTorch, ONNX Runtime, sherpa-onnx, RUAccent
and their Python dependencies under their own licenses (see each package's
metadata in runtime/Lib/site-packages). These programs run as separate
processes or libraries of the bundled engine; Synchro's MIT license does not
apply to them. Model weights retain the licenses listed above.
