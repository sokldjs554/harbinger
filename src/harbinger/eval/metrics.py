"""지표 — 분류(AUROC·PR-AUC·Brier·ECE), 생존(C-index·IPCW Brier·IBS), 순위(precision@k)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter
from lifelines.utils import concordance_index
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from harbinger.models.calibration import ece


def classification_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype=float)
    out = {"n": int(len(y)), "pos_rate": float(y.mean()) if len(y) else float("nan")}
    if len(np.unique(y)) < 2:
        return out | {
            "auroc": float("nan"),
            "pr_auc": float("nan"),
            "brier": float("nan"),
            "ece": float("nan"),
        }
    is_prob = bool(np.nanmin(p) >= 0.0 and np.nanmax(p) <= 1.0)
    out.update(
        {
            "auroc": float(roc_auc_score(y, p)),
            "pr_auc": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, p)) if is_prob else float("nan"),
            "ece": ece(p, y) if is_prob else float("nan"),
            "pr_auc_lift": float(average_precision_score(y, p) / max(y.mean(), 1e-9)),
        }
    )
    return out


def c_index_from_risk(tte: np.ndarray, event: np.ndarray, risk: np.ndarray) -> float:
    return float(concordance_index(tte, -np.asarray(risk, dtype=float), event))


def censoring_km(tte_train: np.ndarray, event_train: np.ndarray) -> KaplanMeierFitter:
    km = KaplanMeierFitter()
    km.fit(tte_train, event_observed=1 - np.asarray(event_train))
    return km


def ipcw_brier(
    surv_at_t: np.ndarray, tte: np.ndarray, event: np.ndarray, t: float, km_c: KaplanMeierFitter
) -> float:
    """IPCW Brier score at horizon t (Graf et al. 1999)."""
    tte = np.asarray(tte, dtype=float)
    event = np.asarray(event).astype(bool)
    S = np.asarray(surv_at_t, dtype=float)
    G_T = (
        np.maximum(km_c.predict(np.minimum(tte, t)).to_numpy(), 1e-3)
        if hasattr(km_c.predict(1.0), "to_numpy")
        else np.maximum(np.asarray(km_c.predict(np.minimum(tte, t))), 1e-3)
    )
    G_t = max(float(km_c.predict(t)), 1e-3)
    died = (tte <= t) & event
    alive = tte > t
    bs = (S**2) * died / G_T + ((1 - S) ** 2) * alive / G_t
    return float(bs.mean())


def integrated_brier(
    surv_matrix: np.ndarray, times: list[float], tte: np.ndarray, event: np.ndarray, km_c: KaplanMeierFitter
) -> dict:
    scores = [ipcw_brier(surv_matrix[:, i], tte, event, t, km_c) for i, t in enumerate(times)]
    ibs = float(np.trapezoid(scores, times) / (times[-1] - times[0])) if len(times) > 1 else scores[0]
    return {"brier_at": {str(int(t)): s for t, s in zip(times, scores)}, "ibs": ibs}


def precision_at_k(groups: pd.DataFrame, score_col: str, k: int) -> float:
    """groups: (group, score, hit) — 그룹별 상위 k 적중률의 평균."""
    vals = []
    for _, g in groups.groupby("group"):
        top = g.nlargest(k, score_col)
        vals.append(top["hit"].mean())
    return float(np.mean(vals)) if vals else float("nan")
