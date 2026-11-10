"""Run a short concurrent test of three videos through the HTTPS API."""
import asyncio
import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
VIDEOS = ['YmLp8qe87A0', 'wjZofJX0v4M', 'eMlx5fFNoYc']


async def main():
    barrier = asyncio.Barrier(3)
    async def viewer(index):
        name = f'guest-{index + 1}'
        config = json.loads((ROOT / '.local/connections' / name / 'connection.json').read_text())
        headers = {'Authorization': 'Bearer ' + config['token'], 'Origin': 'chrome-extension://' + config['extension_id']}
        sid = None
        async with httpx.AsyncClient(base_url=config['server_url'], headers=headers, timeout=150, trust_env=False) as client:
            try:
                opened_at = time.monotonic()
                response = await client.post('/api/video', json={'url': 'https://www.youtube.com/watch?v=' + VIDEOS[index], 'position': 0, 'voice': ['female', 'male', 'male-eugene'][index]})
                if response.status_code != 200:
                    raise RuntimeError(f'{name}: {response.status_code} {response.text[:200]}')
                sid = response.json()['session_id']
                warmup = time.monotonic() - opened_at
                await barrier.wait()
                started = time.monotonic()
                times = []
                segments = 0
                for _ in range(4):
                    tick = time.monotonic()
                    response = await client.post(f'/api/video/{sid}/next')
                    if response.status_code != 200:
                        raise RuntimeError(f'{name}: {response.status_code} {response.text[:200]}')
                    result = response.json()
                    assert result['session_id'] == sid
                    segments += len(result['segments'])
                    times.append(round(time.monotonic() - tick, 3))
                elapsed = time.monotonic() - started
                report = {'client': name, 'video': VIDEOS[index], 'warmup_seconds': round(warmup, 2), 'window_seconds': times,
                          'total_processing_seconds': round(elapsed, 3), 'source_seconds': result['ready_until'], 'segments': segments,
                          'faster_than_realtime': result['ready_until'] > elapsed}
                print(json.dumps(report), flush=True)
                return report
            except Exception:
                await barrier.abort()
                raise
            finally:
                if sid:
                    await client.delete('/api/session/' + sid)
    results = await asyncio.wait_for(asyncio.gather(*(viewer(i) for i in range(3)), return_exceptions=True), 240)
    if any(isinstance(item, BaseException) for item in results):
        for item in results:
            if isinstance(item, BaseException): print(str(item))
        raise SystemExit(1)
    (ROOT / 'output/viewers-benchmark.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    assert all(result['faster_than_realtime'] for result in results)


asyncio.run(main())
