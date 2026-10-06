"""Prometheus 메트릭 — 요청 수·지연, 예측 분포, 모델 버전, 드리프트 게이지."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

registry = CollectorRegistry()
REQUESTS = Counter("harbinger_requests_total", "요청 수", ["route", "status"], registry=registry)
LATENCY = Histogram(
    "harbinger_request_seconds",
    "요청 지연",
    ["route"],
    registry=registry,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
PRED_P30 = Histogram(
    "harbinger_p30",
    "예측 30일 고장확률 분포",
    registry=registry,
    buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0),
)
MODEL_INFO = Gauge("harbinger_model_loaded", "로드된 모델 (1)", ["version"], registry=registry)
DRIFT_ALERTS = Gauge("harbinger_drift_alert_features", "PSI 경보 피처 수", registry=registry)
ASSETS_LOADED = Gauge("harbinger_assets_loaded", "로드된 설비 수", registry=registry)


def render() -> bytes:
    return generate_latest(registry)
