from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from harbinger.api.deps import ensure_site, get_store
from harbinger.api.store import Store

router = APIRouter(prefix="/v1", tags=["replay"])


def _ts(v: str | None) -> pd.Timestamp | None:
    if not v:
        return None
    try:
        return pd.Timestamp(v)
    except Exception as e:
        raise HTTPException(422, f"날짜 형식 오류: {v}") from e


@router.get("/replay")
def replay(
    site: str = Query("all", description="사이트 ID 또는 all(전 사이트 합산)"),
    start: str | None = Query(None, alias="from", description="첫 기준일 (기본: 모델이 학습하지 않은 첫 날)"),
    end: str | None = Query(
        None, alias="to", description="마지막 기준일 (기본: 결과 30일치가 있는 마지막 날)"
    ),
    step: int = Query(7, ge=1, le=31),
    k: int = Query(10, ge=1, le=50),
    store: Store = Depends(get_store),
) -> dict:
    """**과거 시점 재현** — 매주 그 시점의 harbinger 상위 K 와 라운드로빈 상위 K 를 뽑고, 이후 30일의 실제 비계획 고장과 대조한다.

    site=all 은 25개 사이트를 합산하므로 첫 호출이 느리다(캐시됨). 점수에는 기준일 이전 데이터만 쓰인다.
    """
    if site != "all":
        ensure_site(store, site)
    return store.replay(site, _ts(start), _ts(end), step, k)
