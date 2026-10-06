from __future__ import annotations

import pandas as pd
from fastapi import HTTPException, Request

from harbinger.api.store import Store


def get_store(request: Request) -> Store:
    store = getattr(request.app.state, "store", None)
    if store is None or store.bundle is None:
        raise HTTPException(503, "모델이 아직 로드되지 않았습니다")
    return store


def parse_as_of(store: Store, as_of: str | None) -> pd.Timestamp:
    try:
        return store.resolve_as_of(as_of)
    except Exception as e:
        raise HTTPException(422, f"as_of 형식 오류: {e}") from e


def ensure_site(store: Store, site_id: str) -> None:
    if site_id not in set(store.tables["sites"]["site_id"]):
        raise HTTPException(404, f"사이트 없음: {site_id}")
