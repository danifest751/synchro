import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from typing import Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .pipeline import Pipeline, Session, WINDOW
from .youtube import YoutubeAudio, youtube_url

TOKEN = os.environ.get('SYNCHRO_TOKEN', '')
ORIGIN = os.environ.get('SYNCHRO_ORIGIN', '')
CLIENTS_FILE = os.environ.get('SYNCHRO_CLIENTS_FILE', '')
MAX_SESSIONS = int(os.environ.get('SYNCHRO_MAX_SESSIONS', '3'))
if not TOKEN or not re.fullmatch(r'chrome-extension://[a-p]{32}', ORIGIN):
    raise RuntimeError('SYNCHRO_TOKEN and the exact SYNCHRO_ORIGIN must be configured')

pipeline = Pipeline(os.environ.get('SPEECH_URL', 'http://127.0.0.1:8002'),
                    os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11435'),
                    model=os.environ.get('SYNCHRO_MODEL', 'gemma4:12b'), api=os.environ.get('SYNCHRO_LLM_API', 'ollama'),
                    asr_url=os.environ.get('SYNCHRO_ASR_URL', ''), asr_token=os.environ.get('SYNCHRO_ASR_TOKEN', ''),
                    silero_url=os.environ.get('SYNCHRO_SILERO_URL', ''), silero_token=os.environ.get('SYNCHRO_SILERO_TOKEN', ''))
sessions = {}
registry_lock = asyncio.Lock()
warmup_lock = asyncio.Lock()
requests = defaultdict(deque)


async def discard(current):
    async with current.lock:
        current.finished = True
        if current.audio:
            await current.audio.close()
            current.audio = None
        sessions.pop(current.id, None)


async def reap():
    for current in list(sessions.values()):
        if not current.lock.locked() and time.monotonic() - current.touched > 120:
            await discard(current)


async def janitor():
    while True:
        await asyncio.sleep(10)
        async with registry_lock:
            await reap()


@asynccontextmanager
async def lifespan(app):
    cleanup = asyncio.create_task(janitor())
    yield
    cleanup.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup
    for current in list(sessions.values()):
        await discard(current)
    await pipeline.client.aclose()


app = FastAPI(title='Synchro', lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=['GET', 'POST', 'DELETE'],
                   allow_headers=['Authorization', 'Content-Type', 'X-Offset', 'X-Final'])


async def authenticate(request: Request):
    origin = request.headers.get('origin')
    if origin and origin != ORIGIN:
        raise HTTPException(403, 'Origin rejected')
    authorization = request.headers.get('authorization', '')
    if not authorization.startswith('Bearer ') or len(authorization) > 512:
        raise HTTPException(401, 'Invalid token')
    token = authorization[7:]
    owner = 'owner' if hmac.compare_digest(token.encode(), TOKEN.encode()) else None
    if owner is None and CLIENTS_FILE:
        try:
            clients = json.loads(Path(CLIENTS_FILE).read_text())
            digest = hashlib.sha256(token.encode()).hexdigest()
            for name, client in clients.items():
                if not client.get('disabled') and hmac.compare_digest(digest, client['token_sha256']):
                    owner = name
                    break
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Could not validate the access key')
    if owner is None:
        raise HTTPException(401, 'Invalid token')
    now = time.monotonic()
    recent = requests[owner]
    while recent and recent[0] < now - 60:
        recent.popleft()
    if len(recent) >= 120:
        raise HTTPException(429, 'Too many requests; wait one minute')
    recent.append(now)
    return owner


def owned(session_id, owner):
    current = sessions.get(session_id)
    if not current or current.owner != owner:
        raise HTTPException(404, 'Session not found')
    return current


async def reserve(owner, voice):
    async with registry_lock:
        await reap()
        for current in list(sessions.values()):
            if current.owner == owner:
                if not current.lock.locked() and (current.finished or current.failed):
                    await discard(current)
                else:
                    raise HTTPException(409, 'This key already has an active session. Close translation first')
        if len(sessions) >= MAX_SESSIONS:
            raise HTTPException(503, f'All {MAX_SESSIONS} slots are occupied. Try again when a viewer finishes')
        current = Session(id=uuid.uuid4().hex, touched=time.monotonic(), voice=voice, owner=owner)
        sessions[current.id] = current
        return current


@app.get('/health')
async def health():
    return {'service': 'synchro', 'version': '0.3.1', 'max_sessions': MAX_SESSIONS}


@app.get('/api/check')
async def check(owner=Depends(authenticate)):
    return {'ok': True, 'client': owner, 'max_sessions': MAX_SESSIONS}


@app.post('/api/session')
async def start(voice: Literal['female', 'male', 'male-eugene'] = 'female', owner=Depends(authenticate)):
    current = await reserve(owner, voice)
    try:
        async with current.lock, asyncio.timeout(105), warmup_lock:
            await pipeline.warmup(voice)
            current.touched = time.monotonic()
    except Exception:
        await discard(current)
        raise HTTPException(503, 'Could not warm up local models. Check the server services')
    return {'session_id': current.id, 'window_samples': WINDOW, 'step_samples': 7 * 16000}


@app.post('/api/session/{session_id}/chunk')
async def chunk(session_id: str, request: Request, owner=Depends(authenticate)):
    current = owned(session_id, owner)
    if current.audio or current.lock.locked():
        raise HTTPException(409, 'The previous window is still processing or a different mode is active')
    try:
        offset = int(request.headers['x-offset'])
        if request.headers.get('x-final') not in ('0', '1'):
            raise ValueError()
        final = request.headers['x-final'] == '1'
    except (KeyError, ValueError):
        raise HTTPException(400, 'Invalid window metadata')
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > WINDOW * 2:
            raise HTTPException(413, 'Audio window too large')
        body.extend(part)
    if current.lock.locked():
        raise HTTPException(409, 'The previous window is still processing')
    async with current.lock:
        try:
            return await pipeline.process(current, bytes(body), offset, final)
        except ValueError as error:
            current.failed = True
            raise HTTPException(422, str(error))
        except Exception:
            current.failed = True
            raise HTTPException(502, 'Local model error; start a new session')
        finally:
            current.touched = time.monotonic()


@app.delete('/api/session/{session_id}')
async def stop(session_id: str, owner=Depends(authenticate)):
    await discard(owned(session_id, owner))
    return Response(status_code=204)


class VideoRequest(BaseModel):
    url: str = Field(max_length=2048)
    position: float = Field(default=0, ge=0, allow_inf_nan=False)
    voice: Literal['female', 'male', 'male-eugene'] = 'female'


@app.post('/api/video')
async def start_video(body: VideoRequest, owner=Depends(authenticate)):
    try:
        url = youtube_url(body.url)
    except ValueError as error:
        raise HTTPException(422, str(error))
    current = await reserve(owner, body.voice)
    try:
        async with current.lock, asyncio.timeout(105):
            current.audio = await YoutubeAudio.open(url, body.position)
            async with warmup_lock:
                await pipeline.warmup(body.voice)
            current.offset = round(current.audio.base * 16000)
            current.touched = time.monotonic()
    except Exception as error:
        await discard(current)
        raise HTTPException(502, str(error) if isinstance(error, ValueError) else 'Could not prepare audio or local models')
    return {'session_id': current.id, 'base': current.audio.base, 'duration': current.audio.duration}


@app.get('/api/video/{session_id}')
async def video_status(session_id: str, owner=Depends(authenticate)):
    current = owned(session_id, owner)
    current.touched = time.monotonic()
    return {'ready_until': current.offset / 16000, 'finished': current.finished}


@app.post('/api/video/{session_id}/next')
async def video_next(session_id: str, owner=Depends(authenticate)):
    current = owned(session_id, owner)
    if not current.audio:
        raise HTTPException(409, 'This session does not use YouTube audio')
    if current.lock.locked():
        raise HTTPException(409, 'The previous phrase is still processing')
    async with current.lock:
        try:
            pcm, final = await current.audio.next()
            if not pcm:
                current.finished = True
                return {'session_id': current.id, 'segments': [], 'ready_until': current.offset / 16000, 'finished': True}
            return await pipeline.process(current, pcm, current.offset, final)
        except Exception as error:
            current.failed = True
            raise HTTPException(502, str(error) if isinstance(error, ValueError) else 'Audio stream translation failed')
        finally:
            current.touched = time.monotonic()
