from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from harbinger.api.deps import ensure_site, get_store, parse_as_of
from harbinger.api.store import Store

router = APIRouter(prefix="/v1/sites/{site_id}/patrol", tags=["patrol"])


@router.get("/today")
def patrol_today(
    site_id: str,
    as_of: str | None = None,
    k: int = Query(10, ge=1, le=200),
    explain: bool = True,
    store: Store = Depends(get_store),
) -> dict:
    """오늘 먼저 볼 설비 k 개 — 기대손실 순, 법정점검 기한 임박은 무조건 포함, 동선(층·구역) 순으로 정렬."""
    ensure_site(store, site_id)
    return store.patrol(site_id, parse_as_of(store, as_of), k=k, explain=explain)
