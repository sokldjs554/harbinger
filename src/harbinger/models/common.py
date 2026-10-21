"""학습 공통: 시간 분할, 행렬 준비, 지표 헬퍼."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from harbinger.features.build import FEATURE_GROUPS, feature_columns
from harbinger.schema import AssetCategory

CATEGORICAL = ("st_category", "st_archetype")


@dataclass
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame
    train_end: pd.Timestamp
    val_end: pd.Timestamp

    def describe(self) -> dict:
        return {
            "train": {
                "rows": int(len(self.train)),
                "mature_labels": int(self.train.label_valid.sum()),
                "immature_labels": int((~self.train.label_valid).sum()),
                "from": str(self.train["t"].min().date()),
                "to": str(self.train_end.date()),
            },
            "val": {
                "rows": int(len(self.val)),
                "to": str(self.val_end.date()),
                "mature_labels": int(self.val.label_valid.sum()),
                "immature_labels": int((~self.val.label_valid).sum()),
            },
            "test": {"rows": int(len(self.test)), "to": str(self.test["t"].max().date())},
        }


def observe_until(X: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Targets available at cutoff (inclusive). Never expose an immature y30.

    Keep censored rows for survival; classification uses labeled().
    Event exactly at cutoff is observed. Feature rows must precede cutoff.
    """
    out = X.loc[X["t"] < cutoff].copy()
    followup = (cutoff - out["t"]).dt.total_seconds() / 86400
    out["label_valid"] = out["label_valid"] & (followup >= 30)
    out.loc[~out["label_valid"], "y30"] = 0  # masked, never a scored negative
    if "tte_days" in out and "event" in out:
        out["event"] = ((out["event"] == 1) & (out["tte_days"] <= followup)).astype(int)
        out["tte_days"] = np.minimum(out["tte_days"], followup)
    return out


def split_by_time(X: pd.DataFrame, train_months: int = 24, val_months: int = 6) -> Split:
    """시작일 기준 train_months 까지 학습, 다음 val_months 검증(캘리브레이션·조기종료), 나머지 테스트."""
    t0 = X["t"].min().normalize()
    train_end = t0 + pd.DateOffset(months=train_months)
    val_end = train_end + pd.DateOffset(months=val_months)
    tr = observe_until(X, train_end)
    va = observe_until(X[X["t"] >= train_end], val_end)
    te = X[X["t"] >= val_end]
    return Split(tr, va, te, train_end, val_end)


def one_hot_columns() -> list[str]:
    cats = [f"st_category__{c.value}" for c in AssetCategory]
    arcs = [f"st_archetype__{a}" for a in ("gov_office", "hospital", "hotel", "office")]
    return cats + arcs


def model_columns(X: pd.DataFrame, groups: tuple[str, ...] = FEATURE_GROUPS) -> list[str]:
    """범주형은 원-핫 열 이름으로 바꾼 최종 피처 목록 (SHAP 호환을 위해 HGB 에도 원-핫을 쓴다)."""
    cols = [c for c in feature_columns(X, groups) if c not in CATEGORICAL]
    if "tx" not in groups:
        cols = [
            c
            for c in cols
            if c not in {"q_inspector_lazy_rate", "q_evidence_weight", "q_evidence_sum6", "ck_overall_wmean6"}
        ]
    if "q" not in groups:
        cols = [c for c in cols if c != "ck_overall_wmean6"]
    if "st" in groups:
        cols += one_hot_columns()
    return cols


def to_matrix(X: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """피처 DataFrame → 모델 입력 (float, 원-핫 포함, NaN 유지)."""
    cat = X["st_category"].astype(str)
    arc = X["st_archetype"].astype(str)
    data = {}
    for c in cols:
        if c.startswith("st_category__"):
            data[c] = (cat == c.split("__", 1)[1]).astype(float)
        elif c.startswith("st_archetype__"):
            data[c] = (arc == c.split("__", 1)[1]).astype(float)
        else:
            data[c] = X[c].astype(float)
    return pd.DataFrame(data, index=X.index)


def labeled(X: pd.DataFrame) -> pd.DataFrame:
    return X[X["label_valid"]]


def logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))
