from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from harbinger.api.deps import ensure_site, get_store, parse_as_of
from harbinger.api.store import Store
from harbinger.schema import CheckResult, InspectionMethod

router = APIRouter(prefix="/v1/sites/{site_id}", tags=["risk"])


@router.get("/assets/{asset_id}/risk")
def asset_risk(
    site_id: str,
    asset_id: str,
    as_of: str | None = None,
    explain: bool = True,
    store: Store = Depends(get_store),
) -> dict:
    ensure_site(store, site_id)
    out = store.asset_risk(site_id, asset_id, parse_as_of(store, as_of), explain=explain)
    if out is None:
        raise HTTPException(404, f"설비 없음 또는 해당 시점 이전 점검 기록 없음: {asset_id}")
    return out


class InspectionIn(BaseModel):
    inspection_id: str
    asset_id: str
    inspector_id: str
    scheduled_at: datetime
    performed_at: datetime
    method: InspectionMethod = InspectionMethod.nfc
    dwell_seconds: int = Field(ge=0, default=60)
    overall: CheckResult
    items: dict[str, CheckResult] = Field(
        default_factory=dict, description="체크리스트 항목명 → 0 양호 / 1 주의 / 2 불량"
    )
    memo: str = ""
    photo_count: int = 0


@router.post("/inspections", status_code=202)
def ingest(
    site_id: str,
    records: list[InspectionIn] = Body(..., min_length=1, max_length=5000),
    store: Store = Depends(get_store),
) -> dict:
    """새 점검 기록 인제스트 → 영향 받은 설비의 피처·위험도 즉시 갱신. (메모리 상태만 바꾼다. 영속화는 FMS DB 몫.)"""
    ensure_site(store, site_id)
    rows = []
    for r in records:
        d = r.model_dump()
        items = d.pop("items")
        d["method"] = d["method"].value
        d["overall"] = int(d["overall"])
        for k, v in items.items():
            d[f"chk_{k}"] = int(v)
        rows.append(d)
    try:
        return store.ingest_inspections(site_id, rows)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
