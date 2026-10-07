"""확률 캘리브레이션 — 처방(순찰 우선순위·점검주기)은 순위가 아니라 '확률'을 쓰므로 필수."""

from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold


def fit_isotonic(p: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(p, y)
    return iso


_EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
    return np.log(p / (1 - p))


class PlattCalibrator:
    """σ(a·logit(p)+b) — 모수 두 개의 매끄러운 단조 변환. isotonic 과 달리 계단(동점 구간)이 생기지 않는다."""

    def __init__(self, a: float, b: float):
        self.a, self.b = float(a), float(b)

    def predict(self, p) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-(self.a * _logit(p) + self.b)))

    def __repr__(self) -> str:
        return f"PlattCalibrator(a={self.a:.3f}, b={self.b:.3f})"


def fit_platt(p: np.ndarray, y: np.ndarray) -> PlattCalibrator:
    lr = LogisticRegression(C=1e6, max_iter=1000)
    lr.fit(_logit(p).reshape(-1, 1), y)
    return PlattCalibrator(lr.coef_[0, 0], lr.intercept_[0])


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def choose_calibrator(p: np.ndarray, y: np.ndarray, min_gain: float = 0.005, folds: int = 5, seed: int = 0):
    """원시 확률 / Platt / isotonic 중 **교차적합** 로그손실로 고른다.

    검증 구간에서 같은 행으로 적합하고 평가하면 유연한 isotonic 이 늘 이기므로, 검증 행을 folds 로 나눠
    접힘 밖 예측으로 비교한다. 후보가 원시 대비 min_gain(상대) 이상 좋아지지 않으면 보정하지 않는다 —
    로그손실로 학습한 HGB 는 이미 확률 척도가 맞는 경우가 많고, 억지 보정은 계단과 ECE 악화만 만든다(첫 실행에서 실제로 그랬다).
    """
    p = np.asarray(p, dtype=float)
    y = np.asarray(y).astype(float)
    oof = {"platt": np.zeros(len(p)), "isotonic": np.zeros(len(p))}
    for tr, te in KFold(folds, shuffle=True, random_state=seed).split(p):
        oof["platt"][te] = fit_platt(p[tr], y[tr]).predict(p[te])
        oof["isotonic"][te] = fit_isotonic(p[tr], y[tr]).predict(p[te])
    ll = {"raw": logloss(p, y), **{k: logloss(v, y) for k, v in oof.items()}}
    brier = {"raw": float(np.mean((p - y) ** 2)), **{k: float(np.mean((v - y) ** 2)) for k, v in oof.items()}}
    best = min(("platt", "isotonic"), key=lambda k: ll[k])
    method = best if ll[best] < ll["raw"] * (1 - min_gain) else "raw"
    calibrator = {"raw": None, "platt": None, "isotonic": None}
    if method == "platt":
        calibrator["platt"] = fit_platt(p, y)
    elif method == "isotonic":
        calibrator["isotonic"] = fit_isotonic(p, y)
    info = {
        "method": method,
        "adopted": method != "raw",
        "val_logloss": ll,
        "val_brier": brier,
        "min_gain": min_gain,
        "folds": folds,
    }
    return calibrator[method], info


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
