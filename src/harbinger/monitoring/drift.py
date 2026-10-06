"""드리프트 — 학습 시점 피처 분포(참조) 대비 최근 창의 PSI, 예측 확률 분포 이동, 라벨 지연을 감안한 최근 성능."""

from __future__ import annotations

import numpy as np
import pandas as pd

PSI_WARN, PSI_ALERT = 0.10, 0.25


def psi(ref: np.ndarray, cur: np.ndarray, bins: int = 10) -> float:
    ref = ref[~np.isnan(ref)]
    cur = cur[~np.isnan(cur)]
    if len(ref) < 20 or len(cur) < 20:
        return float("nan")
    qs = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(qs) < 3:
        return 0.0
    qs[0], qs[-1] = -np.inf, np.inf
    r = np.histogram(ref, qs)[0] / len(ref)
    c = np.histogram(cur, qs)[0] / len(cur)
    r = np.clip(r, 1e-4, None)
    c = np.clip(c, 1e-4, None)
    return float(np.sum((c - r) * np.log(c / r)))


def feature_drift(ref: pd.DataFrame, cur: pd.DataFrame, features: list[str], top: int = 15) -> dict:
    rows = []
    for f in features:
        if f not in ref or f not in cur:
            continue
        v = psi(ref[f].to_numpy(dtype=float), cur[f].to_numpy(dtype=float))
        if not np.isnan(v):
            rows.append(
                {
                    "feature": f,
                    "psi": v,
                    "level": "alert" if v >= PSI_ALERT else ("warn" if v >= PSI_WARN else "ok"),
                }
            )
    rows.sort(key=lambda r: -r["psi"])
    return {
        "n_features": len(rows),
        "n_warn": sum(r["level"] == "warn" for r in rows),
        "n_alert": sum(r["level"] == "alert" for r in rows),
        "top": rows[:top],
        "ref_rows": int(len(ref)),
        "cur_rows": int(len(cur)),
    }


def prediction_drift(p_ref: np.ndarray, p_cur: np.ndarray) -> dict:
    return {
        "psi": psi(p_ref, p_cur),
        "mean_ref": float(np.mean(p_ref)),
        "mean_cur": float(np.mean(p_cur)),
        "p90_ref": float(np.quantile(p_ref, 0.9)),
        "p90_cur": float(np.quantile(p_cur, 0.9)),
    }
