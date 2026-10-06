"""사이트 에너지 기대치 대비 잔차 — 피처 빌드용 단순 OLS 버전.

fit_until 이전 데이터로만 사이트별 선형모형을 적합하고(누수 방지), 전 기간 잔차 비율을 계산한다.
제품용 회귀 모델(HGB)은 models/energy.py 에 따로 있다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _design(df: pd.DataFrame) -> np.ndarray:
    T = df["temp_mean_c"].to_numpy()
    cdd = np.maximum(0.0, T - 24.0)
    hdd = np.maximum(0.0, 18.0 - T)
    occ = df["occupancy_index"].to_numpy()
    return np.column_stack([np.ones(len(df)), occ, cdd, cdd**2, hdd, hdd * occ, cdd * occ])


def energy_residuals(energy: pd.DataFrame, fit_until: pd.Timestamp) -> pd.DataFrame:
    """site_id, day, en_resid_ratio(전기), en_gas_resid_ratio 를 돌려준다."""
    rows = []
    for _sid, g in energy.sort_values("day").groupby("site_id"):
        X = _design(g)
        fit = g["day"] < fit_until
        if fit.sum() < 60:
            fit = np.ones(len(g), dtype=bool)
        out = g[["site_id", "day"]].copy()
        for col, name in (("electricity_kwh", "en_resid_ratio"), ("gas_m3", "en_gas_resid_ratio")):
            y = g[col].to_numpy()
            coef, *_ = np.linalg.lstsq(X[fit], y[fit], rcond=None)
            yhat = np.maximum(X @ coef, 1e-6)
            out[name] = (y - yhat) / yhat
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def rolling_energy_features(resid: pd.DataFrame) -> pd.DataFrame:
    """일별 잔차의 과거 14일·30일 평균(당일 제외). 사이트별."""
    parts = []
    for _, g in resid.sort_values("day").groupby("site_id"):
        g = g.set_index("day").asfreq("D")
        g["site_id"] = g["site_id"].ffill().bfill()
        for base in ("en_resid_ratio", "en_gas_resid_ratio"):
            s = g[base].shift(1)
            g[f"{base}_14d"] = s.rolling(14, min_periods=5).mean()
            g[f"{base}_30d"] = s.rolling(30, min_periods=10).mean()
        parts.append(g.reset_index())
    return pd.concat(parts, ignore_index=True)
