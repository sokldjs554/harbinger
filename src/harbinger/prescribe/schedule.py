"""권고 점검 주기 — "다음 점검 전에 고장날 확률이 예산(기본 5 %)을 넘지 않는 가장 긴 간격"."""

from __future__ import annotations

import math

import numpy as np

from harbinger.config import RISK_BUDGET, SURVIVAL_BIN_DAYS
from harbinger.schema import LEGAL_MAX_INTERVAL_DAYS, AssetCategory

MIN_INTERVAL, MAX_INTERVAL = 7, 90


def interval_from_p30(p30: float, risk_budget: float = RISK_BUDGET) -> float:
    """일정 위험 가정: λ = −ln(1−P30)/30, Δ = −ln(1−budget)/λ."""
    lam = -math.log(max(1e-9, 1 - min(p30, 1 - 1e-9))) / 30.0
    if lam <= 0:
        return MAX_INTERVAL
    return -math.log(1 - risk_budget) / lam


def interval_from_survival(
    surv: np.ndarray, risk_budget: float = RISK_BUDGET, bin_days: int = SURVIVAL_BIN_DAYS
) -> float:
    """이산 생존곡선 S(k·bin) 에서 1−S(Δ) ≤ budget 인 최대 Δ (구간 안에서 선형 보간)."""
    F = 1.0 - np.asarray(surv, dtype=float)
    if F[0] >= risk_budget:
        # 첫 구간 안에서 보간 (F(0)=0)
        return float(bin_days * risk_budget / max(F[0], 1e-9))
    for k in range(1, len(F)):
        if F[k] >= risk_budget:
            frac = (risk_budget - F[k - 1]) / max(F[k] - F[k - 1], 1e-9)
            return float(bin_days * (k + frac))
    return float(bin_days * len(F))


def recommend_interval(
    category: str, p30: float, surv: np.ndarray | None = None, risk_budget: float = RISK_BUDGET
) -> dict:
    raw = (
        interval_from_survival(surv, risk_budget) if surv is not None else interval_from_p30(p30, risk_budget)
    )
    rec = int(np.clip(round(raw), MIN_INTERVAL, MAX_INTERVAL))
    legal_max = (
        LEGAL_MAX_INTERVAL_DAYS.get(AssetCategory(category))
        if category in AssetCategory._value2member_map_
        else None
    )
    if legal_max is not None:
        rec = min(rec, legal_max)
    return {
        "recommended_interval_days": rec,
        "raw_interval_days": round(float(raw), 1),
        "legal_max_days": legal_max,
        "urgent": bool(p30 >= risk_budget),
        "risk_budget": risk_budget,
        "basis": "survival_curve" if surv is not None else "constant_hazard",
    }
