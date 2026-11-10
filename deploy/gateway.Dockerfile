FROM node:22-bookworm-slim AS javascript
FROM ghcr.io/speaches-ai/speaches@sha256:6ec12ebf890a17e0d4b242a8ba9e0eb1fb836e60e8a3c857aea9838d541579ac
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
COPY server/requirements.txt /tmp/synchro-requirements.txt
RUN uv pip install --python /home/ubuntu/speaches/.venv/bin/python -r /tmp/synchro-requirements.txt
COPY server/synchro /home/ubuntu/synchro
WORKDIR /home/ubuntu
ENTRYPOINT ["python", "-m", "uvicorn", "synchro.app:app", "--host", "127.0.0.1", "--port", "8768", "--no-access-log"]
