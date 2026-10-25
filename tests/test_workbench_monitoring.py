"""Main-path metrics retain failures, rejects, and latency without token labels."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from starlette.requests import Request

from harbinger.api.main import metrics_middleware
from harbinger.monitoring.metrics import registry


@pytest.mark.parametrize(
    "status,outcome", [(200, "success"), (429, "rejected"), (422, "client_error"), (503, "failed")]
)
@pytest.mark.parametrize(
    "route",
    [
        "/v1/workbench/upload",
        "/v1/workbench/sessions/{token}/analysis",
        "/v1/workbench/sessions/{token}/download",
    ],
)
def test_workbench_status_and_latency_are_observable(status, outcome, route):
    app = FastAPI()
    app.add_api_route(route, lambda: None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": route.replace("{token}", "secret-token"),
            "route": app.routes[-1],
        }
    )
    labels = {"route": route, "outcome": outcome}
    metric = "harbinger_workbench_seconds_count"
    before = registry.get_sample_value(metric, labels) or 0

    async def respond(_request):
        return Response(status_code=status)

    asyncio.run(metrics_middleware(request, respond))
    assert registry.get_sample_value(metric, labels) == before + 1
    assert "secret-token" not in str(list(registry.collect()))


def test_unhandled_exception_also_observes_latency():
    app = FastAPI()
    route = "/v1/workbench/sessions/{token}/analysis"
    app.add_api_route(route, lambda: None)
    request = Request({"type": "http", "method": "GET", "path": route, "route": app.routes[-1]})
    before = registry.get_sample_value("harbinger_request_seconds_count", {"route": route}) or 0

    async def fail(_request):
        raise RuntimeError("test computation failure")

    with pytest.raises(RuntimeError):
        asyncio.run(metrics_middleware(request, fail))
    assert registry.get_sample_value("harbinger_request_seconds_count", {"route": route}) == before + 1
