"""오늘 순찰 우선순위 — 기대손실(확률 × 중요도 가중) 순, 법정점검 기한 임박 설비는 무조건 포함, 동선은 층·구역으로 묶는다."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from harbinger.schema import LEGAL_MAX_INTERVAL_DAYS, AssetCategory

CRITICALITY_WEIGHT = {1: 1.0, 2: 1.8, 3: 3.0}
LEGAL_DUE_SOON_DAYS = 3


@dataclass
class PatrolItem:
    rank: int
    asset_id: str
    name: str
    category: str
    floor: int
    zone: str
    p30: float
    criticality: int
    score: float
    mandatory: bool
    days_since_inspection: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def rule_reasons(row: pd.Series) -> list[str]:
    """SHAP 없이도 읽히는 규칙 기반 근거 문장 (설명기가 있으면 그 결과가 앞에 붙는다)."""
    r = []
    if row.get("ck_overall", 0) >= 2:
        r.append("이번 점검 불량 판정")
    elif row.get("ck_overall", 0) == 1:
        r.append("이번 점검 주의 판정")
    if row.get("ck_overall_mean3", 0) >= 0.67:
        r.append("최근 3회 점검에서 반복 지적")
    if row.get("tx_weak_on_good_sum6", 0) >= 2:
        r.append(f"양호 판정인데 메모에 약신호 {int(row['tx_weak_on_good_sum6'])}회")
    elif row.get("tx_weak_score_ewm", 0) > 0.5:
        r.append("최근 메모에 약신호(약간·미세·간헐) 반복")
    if row.get("wo_bd_90d", 0) >= 1:
        r.append(f"최근 90일 고장 {int(row['wo_bd_90d'])}회")
    if row.get("wo_days_since_pm", 0) and row["wo_days_since_pm"] > 300:
        r.append("예방정비 후 300일 초과")
    if row.get("st_age_years", 0) >= 15:
        r.append(f"연식 {row['st_age_years']:.0f}년")
    if row.get("en_hvac_x_resid30", 0) > 0.05:
        r.append("건물 전기 사용량이 기대치보다 높음(HVAC 효율 저하 의심)")
    if row.get("q_inspector_lazy_rate", 0) and row["q_inspector_lazy_rate"] > 0.5:
        r.append("최근 점검 기록의 신뢰도가 낮음(형식적 메모 비율 높음)")
    return r


def rank_patrol(
    latest: pd.DataFrame, today: pd.Timestamp, k: int = 10, explanations: list[list[dict]] | None = None
) -> list[PatrolItem]:
    """latest: 설비당 1행(가장 최근 피처 행) + 'p30' 열. 반환: 순찰 순서(동선 정렬된 상위 k)."""
    df = latest.copy()
    df["days_since_inspection"] = (today - df["t"]).dt.total_seconds() / 86400
    df["weight"] = df["st_criticality"].map(lambda c: CRITICALITY_WEIGHT.get(int(c), 1.0))
    df["score"] = df["p30"] * df["weight"]
    legal_max = df["category"].map(
        lambda c: (
            LEGAL_MAX_INTERVAL_DAYS.get(AssetCategory(c)) if c in AssetCategory._value2member_map_ else None
        )
    )
    df["mandatory"] = legal_max.notna() & (
        df["days_since_inspection"] >= (legal_max.fillna(10**6) - LEGAL_DUE_SOON_DAYS)
    )
    df = df.sort_values(["mandatory", "score"], ascending=[False, False])
    chosen = pd.concat(
        [df[df["mandatory"]], df[~df["mandatory"]].head(max(0, k - int(df["mandatory"].sum())))]
    )
    chosen = chosen.head(max(k, int(df["mandatory"].sum())))
    # 동선: 지하 기계실 → 저층 → 고층, 같은 층은 구역순
    chosen = chosen.sort_values(["st_floor", "zone"]).reset_index(drop=True)
    expl_map = {}
    if explanations is not None:
        expl_map = {aid: ex for aid, ex in zip(latest["asset_id"], explanations)}
    items = []
    for i, (_, r) in enumerate(chosen.iterrows(), start=1):
        reasons = []
        if r["mandatory"]:
            reasons.append("법정점검 기한 임박")
        for c in expl_map.get(r["asset_id"], [])[:3]:
            if c["contribution"] > 0:
                reasons.append(f"{c['label']} ↑")
        reasons += [x for x in rule_reasons(r) if x not in reasons]
        items.append(
            PatrolItem(
                rank=i,
                asset_id=r["asset_id"],
                name=str(r.get("name", r["asset_id"])),
                category=str(r["category"]),
                floor=int(r["st_floor"]),
                zone=str(r.get("zone", "")),
                p30=float(r["p30"]),
                criticality=int(r["st_criticality"]),
                score=float(r["score"]),
                mandatory=bool(r["mandatory"]),
                days_since_inspection=float(r["days_since_inspection"]),
                reasons=reasons[:5],
            )
        )
    return items


def expected_hits(items: list[PatrolItem]) -> float:
    return float(np.sum([it.p30 for it in items]))
