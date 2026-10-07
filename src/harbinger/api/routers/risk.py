from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from harbinger.api.deps import ensure_site, get_store, parse_as_of
from harbinger.api.store import Store
from harbinger.prescribe.scenarios import preset_scenarios
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


class ScenarioIn(BaseModel):
    id: str | None = None
    name: str | None = None
    description: str = ""
    items: dict[str, int] = Field(
        default_factory=dict, description="체크리스트 항목 → 0 양호 / 1 주의 / 2 불량"
    )
    overall: int | None = Field(None, ge=0, le=2, description="생략하면 항목 최댓값")
    memo: str = Field("", max_length=500)
    dwell_seconds: int = Field(120, ge=0, le=3600)
    inspector_id: str | None = None


class WhatIfIn(BaseModel):
    scenarios: list[ScenarioIn] = Field(..., min_length=1, max_length=6)


def _asset_category(store: Store, site_id: str, asset_id: str) -> str:
    a = store.tables["assets"]
    row = a[(a["asset_id"] == asset_id) & (a["site_id"] == site_id)]
    if row.empty:
        raise HTTPException(404, f"설비 없음: {asset_id}")
    return str(row.iloc[0]["category"])


@router.get("/assets/{asset_id}/whatif/presets")
def whatif_presets(site_id: str, asset_id: str, store: Store = Depends(get_store)) -> dict:
    """이 설비 종류에 맞춘 시나리오 네 가지(형식적 메모 / 약신호 메모 / 주의 / 불량)."""
    ensure_site(store, site_id)
    return {"asset_id": asset_id, "scenarios": preset_scenarios(_asset_category(store, site_id, asset_id))}


@router.post("/assets/{asset_id}/whatif")
def whatif(site_id: str, asset_id: str, body: WhatIfIn, store: Store = Depends(get_store)) -> dict:
    """**What-if**: 같은 설비에 가상의 점검 기록을 붙이면 30일 고장확률이 어떻게 바뀌나. 서버 상태를 바꾸지 않는다."""
    ensure_site(store, site_id)
    _asset_category(store, site_id, asset_id)
    try:
        return store.whatif(site_id, asset_id, [s.model_dump() for s in body.scenarios])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
