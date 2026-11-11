import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import hashlib
import hmac
import json
import logging
import math
import os
from pathlib import Path
import re
import time
from typing import Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .pipeline import Pipeline, Session, STEP, WINDOW
from .relay import Relay
from .youtube import YoutubeAudio, youtube_url
from .cloud import TranslationSettings
from .catalog import CatalogRequest, ProviderCatalog
from .usage import collect_usage, usage_summary

if os.environ.get('SYNCHRO_HOST_MODE') == '1':
    from .host import HostPipeline as Pipeline

TOKEN = os.environ.get('SYNCHRO_TOKEN', '')
ORIGIN = os.environ.get('SYNCHRO_ORIGIN', '')
CLIENTS_FILE = os.environ.get('SYNCHRO_CLIENTS_FILE', '')
MAX_SESSIONS = int(os.environ.get('SYNCHRO_MAX_SESSIONS', '3'))
if not TOKEN or not re.fullmatch(r'chrome-extension://[a-p]{32}', ORIGIN):
    raise RuntimeError('SYNCHRO_TOKEN and the exact SYNCHRO_ORIGIN must be configured')

pipeline = Pipeline(os.environ.get('SPEECH_URL', 'http://127.0.0.1:8002'),
                    os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11435'),
                    accent_url=os.environ.get('SYNCHRO_ACCENT_URL', 'http://127.0.0.1:8775'),
                    model=os.environ.get('SYNCHRO_MODEL', 'gemma4:12b'), api=os.environ.get('SYNCHRO_LLM_API', 'ollama'),
                    asr_url=os.environ.get('SYNCHRO_ASR_URL', ''), asr_token=os.environ.get('SYNCHRO_ASR_TOKEN', ''),
                    silero_url=os.environ.get('SYNCHRO_SILERO_URL', ''), silero_token=os.environ.get('SYNCHRO_SILERO_TOKEN', ''),
                    cloud_proxy=os.environ.get('SYNCHRO_CLOUD_PROXY', ''),
                    cloud_tunnels={name: int(os.environ.get(f'SYNCHRO_{name.upper()}_TUNNEL_PORT', '0'))
                                   for name in ['openai', 'kilo', 'openrouter']},
                    sensevoice_model=os.environ.get('SYNCHRO_SENSEVOICE_MODEL', ''))
catalog = ProviderCatalog(pipeline)
sessions = {}
registry_lock = asyncio.Lock()
warmup_lock = asyncio.Lock()
requests = defaultdict(deque)
relays = {}
warm = {}


async def discard(current):
    # Closing must not wait for a window that can take up to the 105-second deadline.
    current.closed = True
    if current.work:
        current.work.cancel()
    async with current.lock:
        current.finished = True
        if current.audio:
            await current.audio.close()
            current.audio = None
        sessions.pop(current.id, None)
        current.translation = TranslationSettings()


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
    if pipeline.cloud_client:
        await pipeline.cloud_client.aclose()
    if getattr(pipeline, 'host_executor', None):
        pipeline.host_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title='Synchro', lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=['GET', 'POST', 'DELETE'],
                   allow_headers=['Authorization', 'Content-Type', 'X-Offset', 'X-Final'])


@app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    # Validation errors can otherwise echo a submitted API key in the response.
    return JSONResponse(status_code=422, content={'detail': 'Invalid request. Check the provider, model, API key, voice, and input fields.'})


async def authenticate(request: Request):
    origin = request.headers.get('origin')
    if origin and origin != ORIGIN:
        raise HTTPException(403, 'Origin rejected')
    authorization = request.headers.get('authorization', '')
    if not authorization.startswith('Bearer ') or len(authorization) > 512:
        raise HTTPException(401, 'Invalid token')
    owner = key_owner(authorization[7:])
    now = time.monotonic()
    recent = requests[owner]
    while recent and recent[0] < now - 60:
        recent.popleft()
    if len(recent) >= 120:
        raise HTTPException(429, 'Too many requests; wait one minute')
    recent.append(now)
    return owner


def key_owner(token):
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
    return owner


@app.websocket('/api/relay')
async def browser_relay(socket: WebSocket):
    # The extension lends its network to this key's YouTube requests; see relay.py.
    if socket.headers.get('origin') != ORIGIN:
        await socket.close(1008)
        return
    await socket.accept()
    try:
        first = json.loads(await asyncio.wait_for(socket.receive_text(), 10))
        token = first.get('token') if isinstance(first, dict) else None
        if not isinstance(token, str) or len(token) > 512:
            raise ValueError()
        owner = key_owner(token)
    except (ValueError, TimeoutError, HTTPException, WebSocketDisconnect):
        await socket.close(1008)
        return
    current = relays[owner] = Relay(socket)
    await socket.send_text(json.dumps({'type': 'ready'}))
    try:
        while True:
            answer = json.loads(await socket.receive_text())
            if isinstance(answer, dict):
                current.resolve(answer)
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        current.close()
        if relays.get(owner) is current:
            del relays[owner]


def owned(session_id, owner):
    current = sessions.get(session_id)
    if not current or current.owner != owner:
        raise HTTPException(404, 'Session not found')
    return current


async def reserve(owner, voice, translation=None, language='en'):
    async with registry_lock:
        await reap()
        # One key holds one place: a seek, reload or second tab replaces the previous session.
        for current in [item for item in sessions.values() if item.owner == owner]:
            await discard(current)
        if len(sessions) >= MAX_SESSIONS:
            raise HTTPException(503, f'All {MAX_SESSIONS} slots are occupied. Try again when a viewer finishes')
        current = Session(id=uuid.uuid4().hex, touched=time.monotonic(), voice=voice, owner=owner,
                          translation=translation or TranslationSettings(), language=language)
        sessions[current.id] = current
        return current


async def exclusive(current, coroutine):
    """Run session work as a task that discard() can cancel."""
    if current.closed:
        coroutine.close()
        raise HTTPException(409, 'Translation was closed')
    current.work = asyncio.ensure_future(coroutine)
    try:
        return await current.work
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise
        raise HTTPException(409, 'Translation was closed') from None
    finally:
        current.work = None


async def warm_models(voice, translation, language='en'):
    # Every seek starts a session; skip a full model round trip that succeeded moments ago.
    key = (voice, language, translation.mode, translation.provider, translation.model,
           hashlib.sha256(translation.api_key.get_secret_value().encode()).hexdigest())
    if time.monotonic() - warm.get(key, -math.inf) < 300:
        return
    async with warmup_lock:
        await pipeline.warmup(voice, translation, language)
    if len(warm) >= 64:
        warm.clear()
    warm[key] = time.monotonic()


def failure(stage, error):
    # Error type and message only: cloud errors are sanitized and local errors name loopback services.
    logging.getLogger('uvicorn.error').warning('%s outcome=failed error_type=%s error=%s', stage, type(error).__name__, str(error)[:300])


async def warm_session(current):
    with collect_usage(current.usage):
        await warm_models(current.voice, current.translation, current.language)
    current.touched = time.monotonic()


async def open_video(current, url, position):
    current.audio = await YoutubeAudio.open(url, position, current.language, lambda: relays.get(current.owner))
    await warm_session(current)
    current.offset = round(current.audio.base * 16000)


async def window_result(current, pcm, offset, final, step=STEP):
    with collect_usage(current.usage):
        result = await pipeline.process(current, pcm, offset, final, step=step)
    result = {**result, 'cloud_usage': usage_summary(current.usage)}
    current.last = (offset, result)
    return result


def replay(current, offset):
    # The client lost the previous response and asks for the same window again.
    return current.last[1] if current.last and current.last[0] == offset else None


async def next_video_window(current, ready=None):
    if ready is not None and (repeated := replay(current, round(ready * 16000))):
        return repeated
    # A failed window stays pending: retrying the request repeats it instead of skipping audio.
    if current.pending is None:
        step = current.audio.step
        pcm, final = await current.audio.next()
        current.pending = (pcm, final, step)
    pcm, final, step = current.pending
    if not pcm:
        current.finished = True
        result = {'session_id': current.id, 'segments': [], 'ready_until': current.offset / 16000, 'finished': True}
        current.last = (current.offset, result)
    else:
        result = await window_result(current, pcm, current.offset, final, step=step)
    current.pending = None
    return result


@app.get('/health')
async def health():
    return {'service': 'synchro', 'version': '0.4.6', 'max_sessions': MAX_SESSIONS}


@app.get('/api/check')
async def check(owner=Depends(authenticate)):
    return {'ok': True, 'client': owner, 'max_sessions': MAX_SESSIONS}


Voice = Literal['roman', 'eduard', 'albina', 'alexandr', 'alfia', 'female', 'male', 'male-eugene']
Language = Literal['en', 'zh', 'ko', 'ja']


class SessionRequest(BaseModel):
    voice: Voice = 'female'
    language: Language = 'en'
    translation: TranslationSettings = Field(default_factory=TranslationSettings)


@app.post('/api/session')
async def start(body: SessionRequest | None = None, voice: Voice = 'female', owner=Depends(authenticate)):
    selected = body or SessionRequest(voice=voice)
    current = await reserve(owner, selected.voice, selected.translation, selected.language)
    try:
        async with current.lock, asyncio.timeout(105):
            await exclusive(current, warm_session(current))
    except Exception as error:
        failure('session_start', error)
        await discard(current)
        raise HTTPException(503, str(error) if isinstance(error, ValueError) else 'Could not warm up models. Check the server services')
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
    if repeated := replay(current, offset):
        return repeated
    async with current.lock:
        # A failed window leaves the session unchanged, so the client can resend the same offset.
        try:
            async with asyncio.timeout(105):
                return await exclusive(current, window_result(current, bytes(body), offset, final))
        except HTTPException:
            raise
        except TimeoutError:
            warm.clear()
            raise HTTPException(504, 'Audio translation timed out after 105 seconds')
        except Exception as error:
            warm.clear()
            failure('capture_window', error)
            raise HTTPException(502, str(error) if isinstance(error, ValueError) else 'Local model error; check the server services')
        finally:
            current.touched = time.monotonic()


@app.delete('/api/session/{session_id}')
async def stop(session_id: str, owner=Depends(authenticate)):
    await discard(owned(session_id, owner))
    return Response(status_code=204)


class VideoRequest(SessionRequest):
    url: str = Field(max_length=2048)
    position: float = Field(default=0, ge=0, allow_inf_nan=False)


@app.post('/api/video')
async def start_video(body: VideoRequest, owner=Depends(authenticate)):
    try:
        url = youtube_url(body.url)
    except ValueError as error:
        raise HTTPException(422, str(error))
    current = await reserve(owner, body.voice, body.translation, body.language)
    try:
        async with current.lock, asyncio.timeout(105):
            await exclusive(current, open_video(current, url, body.position))
    except Exception as error:
        failure('video_start', error)
        await discard(current)
        raise HTTPException(502, str(error) if isinstance(error, ValueError) else 'Could not prepare audio or models')
    return {'session_id': current.id, 'base': current.audio.base, 'duration': current.audio.duration}


@app.post('/api/translation/check')
async def check_translation(body: TranslationSettings, owner=Depends(authenticate)):
    started = time.monotonic()
    usage = {}
    try:
        with collect_usage(usage):
            text = await pipeline.translate('She decided to sleep on it and give me an answer in the morning.', [], 6, translation=body)
    except ValueError as error:
        raise HTTPException(502, str(error))
    except Exception as error:
        failure('translation_check', error)
        raise HTTPException(502, 'Translation check failed; check the model service')
    return {'ok': True, 'provider': body.provider, 'model': body.model, 'translation': text,
            'seconds': round(time.monotonic() - started, 3), 'cloud_usage': usage_summary(usage)}


@app.post('/api/pipeline/check')
async def check_pipeline(body: SessionRequest, owner=Depends(authenticate)):
    started, usage = time.monotonic(), {}
    try:
        async with asyncio.timeout(105), warmup_lock:
            with collect_usage(usage):
                await pipeline.warmup(body.voice, body.translation, body.language)
    except ValueError as error:
        raise HTTPException(502, str(error))
    except TimeoutError:
        raise HTTPException(504, 'Pipeline test timed out')
    except Exception as error:
        failure('pipeline_check', error)
        raise HTTPException(502, 'Pipeline test failed; check inference services')
    return {'ok': True, 'provider': body.translation.provider, 'mode': body.translation.mode,
            'translation': 'Recognition, translation and speech are available',
            'seconds': round(time.monotonic() - started, 3), 'cloud_usage': usage_summary(usage)}


@app.post('/api/translation/models')
async def translation_models(body: CatalogRequest, owner=Depends(authenticate)):
    try:
        result = await catalog.models(body.provider)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except ValueError as error:
        raise HTTPException(502, str(error))


@app.post('/api/translation/balance')
async def translation_balance(body: TranslationSettings, owner=Depends(authenticate)):
    try:
        result = await catalog.balance(body)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except ValueError as error:
        raise HTTPException(502, str(error))


@app.get('/api/video/{session_id}')
async def video_status(session_id: str, owner=Depends(authenticate)):
    current = owned(session_id, owner)
    current.touched = time.monotonic()
    return {'ready_until': current.offset / 16000, 'finished': current.finished, 'cloud_usage': usage_summary(current.usage)}


@app.post('/api/video/{session_id}/next')
async def video_next(session_id: str, ready: float | None = Query(default=None, ge=0, allow_inf_nan=False),
                     owner=Depends(authenticate)):
    # ready is the client's ready_until; it lets a repeated request receive a lost response again.
    current = owned(session_id, owner)
    if not current.audio:
        raise HTTPException(409, 'This session does not use YouTube audio')
    if current.lock.locked():
        raise HTTPException(409, 'The previous phrase is still processing')
    async with current.lock:
        try:
            async with asyncio.timeout(105):
                return await exclusive(current, next_video_window(current, ready))
        except HTTPException:
            raise
        except TimeoutError:
            warm.clear()
            logging.getLogger('uvicorn.error').warning('video_translation outcome=deadline offset_seconds=%.1f provider=%s model=%s', current.offset / 16000, current.translation.provider, current.translation.model)
            raise HTTPException(504, 'Audio translation timed out after 105 seconds')
        except Exception as error:
            warm.clear()
            logging.getLogger('uvicorn.error').warning('video_translation outcome=failed offset_seconds=%.1f provider=%s model=%s error_type=%s', current.offset / 16000, current.translation.provider, current.translation.model, type(error).__name__)
            raise HTTPException(502, str(error) if isinstance(error, ValueError) else 'Audio stream translation failed')
        finally:
            current.touched = time.monotonic()
