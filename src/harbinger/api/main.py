"""FastAPI 앱 — 라이프스팬에서 스토어를 로드하고, 요청 메트릭·구조화 로그·콘솔 정적 파일을 붙인다."""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from harbinger import __version__
from harbinger.api.routers import admin, energy, health, patrol, replay, report, risk, sites, text
from harbinger.api.store import Store, console_dir
from harbinger.config import settings
from harbinger.monitoring.metrics import LATENCY, REQUESTS, render


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)


def _setup_logging() -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(settings.log_level.upper())


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    store = Store(settings)
    store.load()
    app.state.store = store
    yield


app = FastAPI(
    title="harbinger",
    version=__version__,
    lifespan=lifespan,
    description="사람이 쓴 점검 기록에서 설비 고장의 전조를 읽는다 — 센서 없는 시설의 예지보전·순찰 처방 API. 모든 데이터는 합성(SYNTHETIC)이다.",
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    route = request.scope.get("path", "?")
    # 경로 파라미터 카디널리티를 줄인다
    for seg in ("/sites/", "/assets/"):
        if seg in route:
            head, _, tail = route.partition(seg)
            rest = tail.split("/", 1)
            route = head + seg + "{id}" + ("/" + rest[1] if len(rest) > 1 else "")
    try:
        resp = await call_next(request)
        status = resp.status_code
    except Exception:
        REQUESTS.labels(route=route, status="500").inc()
        raise
    REQUESTS.labels(route=route, status=str(status)).inc()
    LATENCY.labels(route=route).observe(time.perf_counter() - t0)
    return resp


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(render(), media_type="text/plain; version=0.0.4; charset=utf-8")


for r in (
    health.router,
    sites.router,
    risk.router,
    patrol.router,
    energy.router,
    report.router,
    replay.router,
    text.router,
    admin.router,
):
    app.include_router(r)

_console = console_dir()
if _console.exists():
    app.mount("/console", StaticFiles(directory=str(_console), html=True), name="console")

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        return RedirectResponse(url="/console/")

    @app.get("/console", include_in_schema=False)
    def console_index() -> Response:
        return FileResponse(Path(_console) / "index.html")
