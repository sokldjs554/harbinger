from __future__ import annotations

import copy

import pandas as pd
from fastapi import HTTPException, Request

from harbinger.api.auth import principal
from harbinger.api.store import Store


def get_store(request: Request) -> Store:
    store = getattr(request.app.state, "store", None)
    if store is None or store.bundle is None:
        raise HTTPException(503, "모델이 아직 로드되지 않았습니다")
    p = principal(request)
    if p is None or p.role == "admin":
        return store
    # Every request gets isolated tables and caches; never mutate the shared Store.
    scoped = copy.copy(store)
    scoped.tables = {
        name: frame[frame.site_id.isin(p.sites)].copy() if "site_id" in frame else frame.iloc[0:0].copy()
        for name, frame in store.tables.items()
    }
    scoped.X = store.X[store.X.site_id.isin(p.sites)].copy()
    scoped._refresher = None
    scoped._drift_cache = {}
    scoped._replay_cache = {}
    scoped._bd_index = None
    scoped.data_meta = {}
    scoped._observation_end = store.data_end
    scoped.bundle = dict(store.bundle)
    scoped.bundle["entry"] = dict(store.bundle.get("entry", {}))
    observation = store.bundle.get("entry", {}).get("metrics", {}).get("observation", {})
    scoped.bundle["entry"]["metrics"] = {
        "observation": {
            key: observation[key]
            for key in ("boundary_version", "max_observed_at", "observation_end")
            if key in observation
        }
    }
    return scoped


def parse_as_of(store: Store, as_of: str | None) -> pd.Timestamp:
    try:
        return store.resolve_as_of(as_of)
    except Exception as e:
        raise HTTPException(422, f"as_of 형식 오류: {e}") from e


def ensure_site(store: Store, site_id: str) -> None:
    if site_id not in set(store.tables["sites"]["site_id"]):
        raise HTTPException(404, f"사이트 없음: {site_id}")
