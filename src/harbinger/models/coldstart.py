"""콜드스타트 — 신규 고객사에 데이터가 거의 없을 때.

pooled 모델(다른 사이트들로 학습)의 확률을 그대로 쓰되, 신규 사이트의 관측이 쌓이는 만큼
경험적 베이즈 오프셋으로 로짓을 보정한다:  δ = n/(n+κ) · (logit(관측률) − logit(예측 평균)).
κ 는 '사건 κ 건어치의 사전 확신'. 데이터가 없으면 δ=0 → pooled 모델 그대로.
"""

from __future__ import annotations

import numpy as np

from harbinger.models.common import logit, sigmoid


def site_offset(p_hist: np.ndarray, y_hist: np.ndarray, kappa: float = 20.0) -> float:
    """해당 사이트의 과거 (예측, 라벨) 쌍으로 로짓 오프셋을 추정한다."""
    if len(y_hist) == 0:
        return 0.0
    n_ev = float(y_hist.sum())
    shrink = n_ev / (n_ev + kappa)
    obs = (y_hist.sum() + 0.5) / (len(y_hist) + 1.0)  # 라플라스
    pred = float(np.clip(p_hist.mean(), 1e-4, 1 - 1e-4))
    return float(shrink * (logit(np.array([obs]))[0] - logit(np.array([pred]))[0]))


def apply_offset(p: np.ndarray, delta: float) -> np.ndarray:
    return np.clip(sigmoid(logit(p) + delta), 1e-6, 1 - 1e-6)
