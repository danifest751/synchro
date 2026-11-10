"""Exercise authentication, GPU pipeline and final audio against the real server."""
import base64
import io
import json
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
connection = json.loads((ROOT / ".local/connection.json").read_text())
BASE = sys.argv[1] if len(sys.argv) > 1 else connection['server_url']
headers = {"Authorization": "Bearer " + connection["token"], "Origin": "chrome-extension://" + connection["extension_id"]}


def request(path, method="GET", data=None, extra=None):
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={**headers, **(extra or {})})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


for bad in [{"Authorization": "Bearer invalid"}, {"Origin": "https://example.com"}]:
    try:
        request("/api/check", extra=bad)
        raise AssertionError("Invalid authentication accepted")
    except urllib.error.HTTPError as error:
        assert error.code in (401, 403), error.code

with urllib.request.urlopen("https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/samples/jfk.wav", timeout=20) as response:
    sample = response.read()
with wave.open(io.BytesIO(sample)) as audio:
    assert audio.getframerate() == 16000
    pcm = audio.readframes(audio.getnframes())
started = time.perf_counter()
session = request("/api/session", "POST", b"")
sid = session["session_id"]
print(json.dumps({"warmup_seconds": round(time.perf_counter() - started, 3)}), flush=True)
try:
    request(f"/api/session/{sid}/chunk", "POST", b'\0' * 256001, {"X-Offset": "0", "X-Final": "0"})
    raise AssertionError("Oversized audio accepted")
except urllib.error.HTTPError as error:
    assert error.code == 413, error.code
result_cues = []
for offset, part, final in [(0, pcm[:256000], False), (112000, pcm[224000:], True)]:
    started = time.perf_counter()
    result = request(f"/api/session/{sid}/chunk", "POST", part, {"X-Offset": str(offset), "X-Final": "1" if final else "0"})
    assert result["session_id"] == sid and result["ready_until"] > offset / 16000
    for cue in result["segments"]:
        assert cue["text"] and cue["source"]
        with wave.open(io.BytesIO(base64.b64decode(cue["wav"]))) as audio:
            assert audio.getframerate() == cue["sample_rate"]
        result_cues.append(cue)
    print(json.dumps({"offset": offset, "seconds": round(time.perf_counter() - started, 3), "ready_until": result["ready_until"], "texts": [c["text"] for c in result["segments"]]}, ensure_ascii=False), flush=True)
assert result["finished"] and result_cues
out = ROOT / "output"
out.mkdir(exist_ok=True)
for cue in result_cues:
    (out / f"smoke-{cue['id']}.wav").write_bytes(base64.b64decode(cue.pop("wav")))
(out / "smoke.json").write_text(json.dumps(result_cues, ensure_ascii=False, indent=2), encoding="utf-8")
print("Smoke passed; generated audio saved in output/.")
