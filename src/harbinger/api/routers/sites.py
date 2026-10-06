from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from harbinger.api.deps import ensure_site, get_store, parse_as_of
from harbinger.api.store import Store

router = APIRouter(prefix="/v1/sites", tags=["sites"])


@router.get("")
def list_sites(
    as_of: str | None = Query(None, description="기준 시점 YYYY-MM-DD (기본: 데이터 끝)"),
    store: Store = Depends(get_store),
) -> dict:
    ts = parse_as_of(store, as_of)
    return {"as_of": ts.isoformat(timespec="minutes"), "sites": store.sites(ts)}


@router.get("/{site_id}")
def site_summary(site_id: str, as_of: str | None = None, store: Store = Depends(get_store)) -> dict:
    ensure_site(store, site_id)
    out = store.site_summary(site_id, parse_as_of(store, as_of))
    if out is None:
        raise HTTPException(404, "사이트 없음")
    return out


@router.get("/{site_id}/assets")
def site_assets(
    site_id: str,
    as_of: str | None = None,
    sort: str = Query("p30", pattern="^(p30|name|category)$"),
    limit: int = Query(500, ge=1, le=5000),
    store: Store = Depends(get_store),
) -> dict:
    ensure_site(store, site_id)
    ts = parse_as_of(store, as_of)
    rows = store.latest_rows(site_id, ts, max_age_days=36500)
    if rows.empty:
        return {"site_id": site_id, "as_of": ts.isoformat(), "assets": []}
    rows = rows.sort_values(sort, ascending=(sort != "p30")).head(limit)
    return {
        "site_id": site_id,
        "as_of": ts.isoformat(timespec="minutes"),
        "assets": [
            {
                "asset_id": r["asset_id"],
                "name": r["name"],
                "category": r["category"],
                "floor": int(r["st_floor"]),
                "zone": r["zone"],
                "criticality": int(r["st_criticality"]),
                "p30": float(r["p30"]),
                "last_inspection_at": r["t"].isoformat(timespec="minutes"),
                "last_overall": int(r["ck_overall"]),
                "age_years": round(float(r["st_age_years"]), 1),
            }
            for _, r in rows.iterrows()
        ],
    }


@router.get("/{site_id}/quality")
def site_quality(
    site_id: str,
    as_of: str | None = None,
    days: int = Query(180, ge=30, le=730),
    store: Store = Depends(get_store),
) -> dict:
    ensure_site(store, site_id)
    return store.quality(site_id, parse_as_of(store, as_of), days)


@router.get("/{site_id}/schedule")
def site_schedule(site_id: str, as_of: str | None = None, store: Store = Depends(get_store)) -> dict:
    ensure_site(store, site_id)
    ts = parse_as_of(store, as_of)
    items = store.schedule(site_id, ts)
    changes = [
        i
        for i in items
        if i["current_interval_days"]
        and abs(i["recommended_interval_days"] - i["current_interval_days"]) >= 7
    ]
    return {
        "site_id": site_id,
        "as_of": ts.isoformat(timespec="minutes"),
        "n_assets": len(items),
        "n_shorten": sum(1 for i in changes if i["recommended_interval_days"] < i["current_interval_days"]),
        "n_lengthen": sum(1 for i in changes if i["recommended_interval_days"] > i["current_interval_days"]),
        "items": items,
    }
