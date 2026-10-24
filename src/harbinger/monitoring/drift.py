"""Reference/current PSI, including discrete values and missingness."""

from __future__ import annotations

import numpy as np
import pandas as pd

PSI_WARN, PSI_ALERT = 0.10, 0.25
MIN_ROWS = 20


def _missing_rate(values: np.ndarray) -> float | None:
    return float(np.count_nonzero(~np.isfinite(values)) / len(values)) if len(values) else None


def psi(ref: np.ndarray, cur: np.ndarray, bins: int = 10) -> float | None:
    """Return PSI, or None when either window has fewer than 20 observations.

    Low-cardinality reference values get individual bins plus an unseen-value
    bin. Continuous values use reference quantiles. Nonfinite observations are
    retained in a missingness bin; two entirely missing windows are unavailable.
    """
    ref, cur = np.asarray(ref, dtype=float), np.asarray(cur, dtype=float)
    if len(ref) < MIN_ROWS or len(cur) < MIN_ROWS:
        return None
    r_valid, c_valid = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if not len(r_valid) and not len(c_valid):
        return None
    values, counts = np.unique(r_valid, return_counts=True)
    cuts = np.unique(np.quantile(r_valid, np.linspace(0, 1, bins + 1))) if len(values) > bins else values
    if len(values) <= bins or len(cuts) < 3:
        # Quantiles also collapse for nearly constant higher-cardinality columns.
        current_counts = dict(zip(*np.unique(c_valid, return_counts=True)))
        r = counts.tolist()
        c = [int(current_counts.get(value, 0)) for value in values]
        r.append(0)
        c.append(len(c_valid) - sum(c))
    else:
        # Keep out-of-reference-range observations visible, even in constant tails.
        cuts = np.r_[-np.inf, cuts[:-1], np.nextafter(cuts[-1], np.inf), np.inf]
        r = np.histogram(r_valid, cuts)[0].tolist()
        c = np.histogram(c_valid, cuts)[0].tolist()
    r.append(len(ref) - len(r_valid))
    c.append(len(cur) - len(c_valid))
    r = np.clip(np.asarray(r, dtype=float) / len(ref), 1e-4, None)
    c = np.clip(np.asarray(c, dtype=float) / len(cur), 1e-4, None)
    return float(np.sum((c - r) * np.log(c / r)))


def feature_drift(ref: pd.DataFrame, cur: pd.DataFrame, features: list[str], top: int = 15) -> dict:
    rows, insufficient = [], []
    for f in features:
        reference = ref[f].to_numpy(dtype=float) if f in ref else np.array([])
        current = cur[f].to_numpy(dtype=float) if f in cur else np.array([])
        missingness = {
            "missing_rate_ref": _missing_rate(reference),
            "missing_rate_cur": _missing_rate(current),
        }
        if f not in ref or f not in cur:
            insufficient.append({"feature": f, "reason": "missing_column", **missingness})
            continue
        v = psi(reference, current)
        if v is None:
            insufficient.append({"feature": f, "reason": "insufficient_data", **missingness})
        else:
            rows.append(
                {
                    "feature": f,
                    "psi": v,
                    "level": "alert" if v >= PSI_ALERT else ("warn" if v >= PSI_WARN else "ok"),
                    **missingness,
                }
            )
    rows.sort(key=lambda r: -r["psi"])
    return {
        "status": "success" if rows and not insufficient else "insufficient_data",
        "n_features": len(rows),
        "n_warn": sum(r["level"] == "warn" for r in rows),
        "n_alert": sum(r["level"] == "alert" for r in rows),
        "top": rows[:top],
        "insufficient_features": insufficient,
        "ref_rows": int(len(ref)),
        "cur_rows": int(len(cur)),
    }


def prediction_drift(p_ref: np.ndarray, p_cur: np.ndarray) -> dict:
    p_ref, p_cur = np.asarray(p_ref, dtype=float), np.asarray(p_cur, dtype=float)
    value = psi(p_ref, p_cur)
    ref, cur = p_ref[np.isfinite(p_ref)], p_cur[np.isfinite(p_cur)]
    return {
        "status": "success" if value is not None else "insufficient_data",
        "psi": value,
        "missing_rate_ref": _missing_rate(p_ref),
        "missing_rate_cur": _missing_rate(p_cur),
        "mean_ref": float(np.mean(ref)) if len(ref) else None,
        "mean_cur": float(np.mean(cur)) if len(cur) else None,
        "p90_ref": float(np.quantile(ref, 0.9)) if len(ref) else None,
        "p90_cur": float(np.quantile(cur, 0.9)) if len(cur) else None,
    }
