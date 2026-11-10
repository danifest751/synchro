import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .pipeline import Pipeline, Session, WINDOW
from .youtube import YoutubeAudio, youtube_url
from .cloud import TranslationSettings
from .catalog import CatalogRequest, ProviderCatalog
from .usage import collect_usage, usage_summary
from .voices import Voice

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
                                   for name in ['openai', 'kilo', 'openrouter']})
catalog = ProviderCatalog(pipeline)
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


async def reserve(owner, voice, translation=None):
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
        current = Session(id=uuid.uuid4().hex, touched=time.monotonic(), voice=voice, owner=owner,
                          translation=translation or TranslationSettings())
        sessions[current.id] = current
        return current


@app.get('/health')
async def health():
    return {'service': 'synchro', 'version': '0.4.3', 'max_sessions': MAX_SESSIONS}


@app.get('/api/check')
async def check(owner=Depends(authenticate)):
    return {'ok': True, 'client': owner, 'max_sessions': MAX_SESSIONS}


@app.get('/api/voices')
async def voices(mode: Literal['local', 'cloud_translation', 'cloud_all'] = 'local', owner=Depends(authenticate)):
    note = 'VoiceStudio voices require cloud text translation on this server because its local translator shares the same GPU.' if mode == 'local' and pipeline.studio.shared_gpu and pipeline.studio.profiles else ''
    return {'voices': pipeline.studio.available(mode), 'note': note}


class SessionRequest(BaseModel):
    voice: Voice = 'female'
    translation: TranslationSettings = Field(default_factory=TranslationSettings)


@app.post('/api/session')
async def start(body: SessionRequest | None = None, voice: Voice = 'female', owner=Depends(authenticate)):
    selected = body or SessionRequest(voice=voice)
    current = await reserve(owner, selected.voice, selected.translation)
    try:
        async with current.lock, asyncio.timeout(105), warmup_lock:
            with collect_usage(current.usage):
                await pipeline.warmup(current.voice, current.translation)
                current.touched = time.monotonic()
    except Exception as error:
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
    async with current.lock:
        try:
            async with asyncio.timeout(105):
                with collect_usage(current.usage):
                    result = await pipeline.process(current, bytes(body), offset, final)
                return {**result, 'cloud_usage': usage_summary(current.usage)}
        except ValueError as error:
            current.failed = True
            raise HTTPException(422, str(error))
        except TimeoutError:
            current.failed = True
            raise HTTPException(504, 'Audio translation timed out after 105 seconds; retry translation')
        except Exception:
            current.failed = True
            raise HTTPException(502, 'Local model error; start a new session')
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
    current = await reserve(owner, body.voice, body.translation)
    try:
        async with current.lock, asyncio.timeout(105):
            current.audio = await YoutubeAudio.open(url, body.position)
            async with warmup_lock:
                with collect_usage(current.usage):
                    await pipeline.warmup(body.voice, current.translation)
            current.offset = round(current.audio.base * 16000)
            current.touched = time.monotonic()
    except Exception as error:
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
    except Exception:
        raise HTTPException(502, 'Translation check failed; check the model service')
    return {'ok': True, 'provider': body.provider, 'model': body.model, 'translation': text,
            'seconds': round(time.monotonic() - started, 3), 'cloud_usage': usage_summary(usage)}


@app.post('/api/pipeline/check')
async def check_pipeline(body: SessionRequest, owner=Depends(authenticate)):
    started, usage = time.monotonic(), {}
    try:
        async with asyncio.timeout(105), warmup_lock:
            with collect_usage(usage):
                await pipeline.warmup(body.voice, body.translation)
    except ValueError as error:
        raise HTTPException(502, str(error))
    except TimeoutError:
        raise HTTPException(504, 'Pipeline test timed out')
    except Exception:
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
async def video_next(session_id: str, owner=Depends(authenticate)):
    current = owned(session_id, owner)
    if not current.audio:
        raise HTTPException(409, 'This session does not use YouTube audio')
    if current.lock.locked():
        raise HTTPException(409, 'The previous phrase is still processing')
    async with current.lock:
        try:
            async with asyncio.timeout(105):
                step = current.audio.step
                pcm, final = await current.audio.next()
                if not pcm:
                    current.finished = True
                    return {'session_id': current.id, 'segments': [], 'ready_until': current.offset / 16000, 'finished': True}
                with collect_usage(current.usage):
                    result = await pipeline.process(current, pcm, current.offset, final, step=step)
                return {**result, 'cloud_usage': usage_summary(current.usage)}
        except TimeoutError:
            current.failed = True
            logging.getLogger('uvicorn.error').warning('video_translation outcome=deadline offset_seconds=%.1f provider=%s model=%s', current.offset / 16000, current.translation.provider, current.translation.model)
            raise HTTPException(504, 'Audio translation timed out after 105 seconds; retry translation')
        except Exception as error:
            current.failed = True
            logging.getLogger('uvicorn.error').warning('video_translation outcome=failed offset_seconds=%.1f provider=%s model=%s error_type=%s', current.offset / 16000, current.translation.provider, current.translation.model, type(error).__name__)
            raise HTTPException(502, str(error) if isinstance(error, ValueError) else 'Audio stream translation failed')
        finally:
            current.touched = time.monotonic()
