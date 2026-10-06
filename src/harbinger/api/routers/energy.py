from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from harbinger.api.deps import ensure_site, get_store, parse_as_of
from harbinger.api.store import Store

router = APIRouter(prefix="/v1/sites/{site_id}/energy", tags=["energy"])


@router.get("/anomalies")
def anomalies(
    site_id: str,
    as_of: str | None = None,
    days: int = Query(120, ge=14, le=730),
    store: Store = Depends(get_store),
) -> dict:
    """날씨·재실을 감안한 기대 전기사용량 대비 잔차와 7일 이동평균 z-score, 이상일 목록."""
    ensure_site(store, site_id)
    return store.energy_anomalies(site_id, parse_as_of(store, as_of), days)
