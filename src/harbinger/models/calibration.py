"""확률 캘리브레이션 — 처방(순찰 우선순위·점검주기)은 순위가 아니라 '확률'을 쓰므로 필수."""

from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression


def fit_isotonic(p: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(p, y)
    return iso


def ece(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error (등간격 구간)."""
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(total)


def reliability_table(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> list[dict]:
    """분위수 구간별 (예측 평균, 실제 비율, 개수) — 신뢰도 다이어그램용."""
    qs = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    qs[0], qs[-1] = -np.inf, np.inf
    idx = np.clip(np.digitize(p, qs) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            rows.append(
                {"bin": b, "pred_mean": float(p[m].mean()), "obs_rate": float(y[m].mean()), "n": int(m.sum())}
            )
    return rows
