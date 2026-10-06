# harbinger — 분석 API 이미지. CPU 전용 PyTorch 로 작게 만든다.
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip
# CPU 전용 torch 를 먼저 설치해 CUDA 의존 휠이 끌려오지 않게 한다
RUN /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.4"
COPY pyproject.toml README.md ./
COPY src ./src
RUN /opt/venv/bin/pip install .

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    HARBINGER_DATA_DIR=/app/data HARBINGER_MODEL_DIR=/app/models HARBINGER_ARTIFACT_DIR=/app/artifacts \
    HARBINGER_DEMO_BOOTSTRAP=1 PORT=8000
RUN useradd -m -u 10001 app && mkdir -p /app/data /app/models /app/artifacts && chown -R app:app /app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
USER app
# 번들이 없으면 기동 시 합성 데이터로 축소 번들을 만든다(데모). 운영에서는 /app/models 를 볼륨·오브젝트 스토리지에서 받는다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=240s --retries=3 CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health').read()" || exit 1
EXPOSE 8000
CMD ["sh", "-c", "harbinger bootstrap --data $HARBINGER_DATA_DIR --models $HARBINGER_MODEL_DIR --artifacts $HARBINGER_ARTIFACT_DIR && exec uvicorn harbinger.api.main:app --host 0.0.0.0 --port ${PORT}"]
