"""점검 레코드 → 테이블 행. 인제스트(상태를 바꿈)와 what-if(바꾸지 않음)가 같은 변환을 쓴다."""

from __future__ import annotations

import pandas as pd


def inspection_frame(
    inspections: pd.DataFrame, assets: pd.DataFrame, site_id: str, records: list[dict]
) -> pd.DataFrame:
    """records 를 inspections 테이블과 같은 열·dtype 으로 맞춘 DataFrame 으로 만든다. 알 수 없는 설비는 ValueError."""
    new = pd.DataFrame(records)
    new["site_id"] = site_id
    for c in ("scheduled_at", "performed_at"):
        new[c] = pd.to_datetime(new[c])
    known = set(assets.loc[assets["site_id"] == site_id, "asset_id"])
    bad = sorted(set(new["asset_id"]) - known)
    if bad:
        raise ValueError(f"알 수 없는 설비: {bad[:5]}")
    for c in inspections.columns:
        if c not in new:
            new[c] = pd.NA
    new = new[inspections.columns]
    for c in [c for c in inspections.columns if c.startswith("chk_")]:
        new[c] = new[c].astype("Int8")
    return new


def site_tables(tables: dict[str, pd.DataFrame], site_id: str) -> dict[str, pd.DataFrame]:
    """사이트 하나로 잘라낸 테이블 사본 (site_id 열이 없는 테이블은 그대로)."""
    return {k: (v[v["site_id"] == site_id] if "site_id" in v.columns else v) for k, v in tables.items()}
