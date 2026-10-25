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
WORKBENCH_ROUTES = frozenset(
    {
        "/v1/workbench/upload",
        "/v1/workbench/sessions/{token}/analysis",
        "/v1/workbench/sessions/{token}/download",
    }
)
WORKBENCH_LATENCY = Histogram(
    "harbinger_workbench_seconds",
    "Main workbench request latency by outcome",
    ["route", "outcome"],
    registry=registry,
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
PRED_P30 = Histogram(
    "harbinger_p30",
    "Observed-data latest_rows p30 scores, including repeats; excludes what-if and offline evaluation",
    registry=registry,
    buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0),
)
MODEL_INFO = Gauge("harbinger_model_loaded", "로드된 모델 (1)", ["version"], registry=registry)
DRIFT_ALERTS = Gauge("harbinger_drift_alert_features", "PSI 경보 피처 수", registry=registry)
DRIFT_STATUS = Gauge(
    "harbinger_drift_status", "Default-window drift calculation state", ["state"], registry=registry
)
DRIFT_LAST_ATTEMPT = Gauge(
    "harbinger_drift_last_attempt_timestamp_seconds", "Last default-window drift attempt", registry=registry
)
DRIFT_LAST_SUCCESS = Gauge(
    "harbinger_drift_last_success_timestamp_seconds",
    "Last successful default-window drift calculation",
    registry=registry,
)
DRIFT_STATES = ("not_initialized", "success", "insufficient_data", "error")
for _state in DRIFT_STATES:
    DRIFT_STATUS.labels(state=_state).set(int(_state == "not_initialized"))
DRIFT_ALERTS.set(float("nan"))
ASSETS_LOADED = Gauge("harbinger_assets_loaded", "로드된 설비 수", registry=registry)


def render() -> bytes:
    return generate_latest(registry)
