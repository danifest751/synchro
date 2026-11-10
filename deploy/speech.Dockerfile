FROM ghcr.io/speaches-ai/speaches@sha256:6ec12ebf890a17e0d4b242a8ba9e0eb1fb836e60e8a3c857aea9838d541579ac
RUN uv pip install --python /home/ubuntu/speaches/.venv/bin/python \
    ctranslate2==4.8.5 nvidia-cublas-cu12==12.8.4.1 nvidia-cuda-runtime-cu12==12.8.90
COPY russian_dictionary.py /tmp/russian_dictionary.py
RUN python /tmp/russian_dictionary.py /home/ubuntu/speaches/.venv/lib/python3.12/site-packages/piper_phonemize/espeak-ng-data
RUN python -c "from piper_phonemize import phonemize_espeak as p; assert p('за\u0301мок', 'ru') != p('замо\u0301к', 'ru'), 'Russian stress marks are ignored'"
ENV LD_LIBRARY_PATH=/home/ubuntu/speaches/.venv/lib/python3.12/site-packages/nvidia/cublas/lib:/home/ubuntu/speaches/.venv/lib/python3.12/site-packages/nvidia/cuda_runtime/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
ENV WHISPER__INFERENCE_DEVICE=cuda WHISPER__COMPUTE_TYPE=float16 WHISPER__TTL=-1
ENV LOG_LEVEL=WARNING GRADIO_ANALYTICS_ENABLED=False
