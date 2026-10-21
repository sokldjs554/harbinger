"""Session-scoped upload and analysis endpoints; memory only, 30 minute TTL."""

from __future__ import annotations

import io
import json
import secrets
import threading
import time
from dataclasses import dataclass

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from harbinger.api.analysis import analyze, markdown_report, safe_json
from harbinger.api.deps import get_store
from harbinger.api.store import Store
from harbinger.api.upload import MAX_BYTES, UploadError, export_example, parse_csv, timestamp
from harbinger.features.build import build_features

router = APIRouter(prefix="/v1/workbench", tags=["workbench"])
MAX_SESSIONS = 8
TTL = 1800
lock = threading.RLock()
compute = threading.BoundedSemaphore(2)


@dataclass
class Session:
    store: Store
    expires: float
    source: str
    summary: dict


sessions: dict[str, Session] = {}


def cleanup():
    for key in list(sessions):
        if sessions[key].expires < time.monotonic():
            del sessions[key]


def register(store, source, summary):
    with lock:
        cleanup()
        if len(sessions) >= MAX_SESSIONS:
            raise HTTPException(429, "분석 세션이 가득 찼습니다. 기존 세션을 닫거나 30분 뒤 다시 시도하세요.")
        token = secrets.token_urlsafe(24)
        sessions[token] = Session(store, time.monotonic() + TTL, source, summary)
    default = min(store.data_end - pd.Timedelta(days=45), store.X.t.max())
    return {
        "session_id": token,
        "source": source,
        "summary": summary,
        "ttl_seconds": TTL,
        "sites": store.tables["sites"][["site_id", "name"]].to_dict("records"),
        "default_as_of": default.date().isoformat(),
        "observation_end": store.data_end.isoformat(),
        "latest_as_of_date": (store.data_end - pd.Timedelta(seconds=1)).date().isoformat(),
        "model_version": store.bundle["version"],
    }


def session(token):
    with lock:
        cleanup()
        if token not in sessions:
            raise HTTPException(
                404, "세션이 만료되었거나 존재하지 않습니다. 예제 또는 CSV를 다시 불러오세요."
            )
        return sessions[token]


@router.get("/info")
def info(store: Store = Depends(get_store)):
    return {
        "mode": "live",
        "synthetic_example": True,
        "model_version": store.bundle["version"],
        "limits": {
            "bytes": MAX_BYTES,
            "rows": 20000,
            "assets": 500,
            "sites": 10,
            "years": 5,
            "ttl_seconds": TTL,
        },
        "observation_end": store.data_end.isoformat(),
        "latest_as_of_date": (store.data_end - pd.Timedelta(seconds=1)).date().isoformat(),
    }


@router.post("/example")
def example(store: Store = Depends(get_store)):
    return register(
        store,
        "synthetic-example",
        {
            "rows": len(store.X),
            "assets": len(store.tables["assets"]),
            "sites": len(store.tables["sites"]),
            "warnings": ["모든 예제 기록과 고장 결과는 합성 데이터입니다."],
        },
    )


@router.get("/example.csv")
def example_csv(site: str = "S01", store: Store = Depends(get_store)):
    if site not in set(store.tables["sites"].site_id):
        raise HTTPException(404, "알 수 없는 고객사입니다.")
    return Response(
        export_example(store.tables, site, store.data_end - pd.Timedelta(seconds=1)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="harbinger-example.csv"'},
    )


def create_upload(content, end, base):
    if not compute.acquire(blocking=False):
        raise HTTPException(429, "계산 중입니다. 잠시 뒤 다시 시도하세요.")
    try:
        with lock:
            cleanup()
            if len(sessions) >= MAX_SESSIONS:
                raise HTTPException(429, "세션 한도 8개에 도달했습니다.")
        tables, summary = parse_csv(content, end)
        store = Store(base.settings)
        store.tables = tables
        store.bundle = base.bundle
        store._observation_end = pd.Timestamp(summary["observation_end"])
        store.X = build_features(tables, data_end=store._observation_end, verbose=False)
        return register(store, "uploaded-csv; synthetic-trained-model", summary)
    except UploadError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        compute.release()


@router.post("/upload")
async def upload(request: Request, observation_end: str, store: Store = Depends(get_store)):
    if request.headers.get("content-type", "").split(";")[0] not in ["text/csv", "application/octet-stream"]:
        raise HTTPException(415, "UTF-8 CSV 파일만 지원합니다(Content-Type: text/csv).")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, "파일 크기 초과: 최대 5 MiB입니다.")
    return await run_in_threadpool(create_upload, bytes(content), observation_end, store)


@router.delete("/sessions/{token}")
def close_session(token: str):
    with lock:
        sessions.pop(token, None)
    return {"deleted": True}


def result(token, as_of, site, k):
    s = session(token)
    try:
        cutoff = timestamp(as_of, end_of_day=True)
    except UploadError as exc:
        raise HTTPException(422, str(exc)) from exc
    if cutoff > s.store.data_end:
        raise HTTPException(422, "예측 기준일은 데이터 관측 종료일을 넘을 수 없습니다.")
    if site and site not in set(s.store.tables["sites"].site_id):
        raise HTTPException(404, "알 수 없는 고객사입니다.")
    if not compute.acquire(blocking=False):
        raise HTTPException(429, "계산 중입니다. 잠시 뒤 다시 시도하세요.")
    try:
        return analyze(s.store, cutoff, site, k, s.source)
    finally:
        compute.release()


@router.get("/sessions/{token}/analysis")
def analysis(token: str, as_of: str, site: str | None = None, k: int = Query(10, ge=1, le=50)):
    return result(token, as_of, site, k)


@router.get("/sessions/{token}/assets/{asset_id}")
def evidence(token: str, asset_id: str, as_of: str):
    s = session(token)
    try:
        cutoff = timestamp(as_of, end_of_day=True)
    except UploadError as exc:
        raise HTTPException(422, str(exc)) from exc
    if cutoff > s.store.data_end:
        raise HTTPException(422, "예측 기준일은 데이터 관측 종료일을 넘을 수 없습니다.")
    a = s.store.tables["assets"]
    a = a[a.asset_id == asset_id]
    if a.empty:
        raise HTTPException(404, "알 수 없는 설비입니다.")
    if not compute.acquire(blocking=False):
        raise HTTPException(429, "계산 중입니다. 잠시 뒤 다시 시도하세요.")
    try:
        return safe_json(s.store.asset_risk(a.iloc[0].site_id, asset_id, cutoff))
    finally:
        compute.release()


@router.get("/sessions/{token}/download")
def download(
    token: str,
    as_of: str,
    site: str | None = None,
    k: int = Query(10, ge=1, le=50),
    format: str = Query("json", pattern="^(json|csv|md)$"),
):
    r = result(token, as_of, site, k)
    if format == "md":
        body, mime = markdown_report(r), "text/markdown; charset=utf-8"
    elif format == "csv":
        df = pd.DataFrame(r["assets"])
        # Spreadsheet formula injection: escape text cells in exported CSV only.
        for col in df.select_dtypes(include=["object"]):
            df[col] = df[col].map(
                lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
            )
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        body, mime = "\ufeff" + buf.getvalue(), "text/csv; charset=utf-8"
    else:
        body, mime = json.dumps(r, ensure_ascii=False, indent=2, allow_nan=False), "application/json"
    return Response(
        body,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="harbinger-analysis.{format}"'},
    )
