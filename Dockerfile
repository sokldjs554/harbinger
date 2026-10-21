# CPU-only reproducible analysis service. Proxy CA mount is optional.
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
RUN --mount=type=secret,id=proxy_ca,target=/run/secrets/ca.pem \
    if [ -f /run/secrets/ca.pem ]; then export PIP_CERT=/run/secrets/ca.pem; fi && \
    python -m venv /opt/venv && \
    /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu' && \
    /opt/venv/bin/pip install -c constraints.txt .

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    HARBINGER_DATA_DIR=/app/data HARBINGER_MODEL_DIR=/app/models HARBINGER_ARTIFACT_DIR=/app/artifacts \
    HARBINGER_DEMO_BOOTSTRAP=1 PORT=8000
RUN useradd -m -u 10001 app && mkdir -p /app/data /app/models /app/artifacts && chown -R app:app /app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
USER app
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health').read()" || exit 1
EXPOSE 8000
CMD ["sh", "-c", "harbinger bootstrap --data $HARBINGER_DATA_DIR --models $HARBINGER_MODEL_DIR --artifacts $HARBINGER_ARTIFACT_DIR && exec uvicorn harbinger.api.main:app --host 0.0.0.0 --port ${PORT}"]
