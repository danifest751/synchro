# All-in-one CPU gateway: recognition, stress marks and Russian speech run in one process;
# text translation uses a cloud provider. Models are mounted read-only at /models (see docs/DEPLOYMENT.md).
FROM node:22-bookworm-slim AS javascript

FROM python:3.12-slim-bookworm
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY server/requirements.txt server/requirements-host.txt /tmp/
# The CPU wheel avoids several gigabytes of CUDA libraries.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.8,<3" \
    && pip install --no-cache-dir -r /tmp/requirements-host.txt
COPY server/synchro /app/synchro
COPY deploy/gigaam_server.py /app/deploy/gigaam_server.py
RUN useradd --system --uid 10001 --home-dir /tmp synchro
USER synchro
WORKDIR /app
ENV PYTHONPATH=/app SYNCHRO_HOST_MODE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 \
    SYNCHRO_HOST_ASR_MODEL=/models/gigaam SYNCHRO_HOST_WHISPER_MODEL=/models/whisper \
    SYNCHRO_HOST_TTS_MODEL=/models/silero/v5_cis_base_nostress.pt SYNCHRO_HOST_ACCENT_MODEL=/models/ruaccent \
    SYNCHRO_SENSEVOICE_MODEL=/models/sensevoice SYNCHRO_SPEAKER_MODEL=/models/speaker/model.onnx
ENTRYPOINT ["python", "-m", "uvicorn", "synchro.app:app", "--host", "127.0.0.1", "--no-access-log"]
CMD ["--port", "8768"]
