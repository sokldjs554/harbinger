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
                "from": str(self.train["t"].min().date()),
                "to": str(self.train_end.date()),
            },
            "val": {"rows": int(len(self.val)), "to": str(self.val_end.date())},
            "test": {"rows": int(len(self.test)), "to": str(self.test["t"].max().date())},
        }


def split_by_time(X: pd.DataFrame, train_months: int = 24, val_months: int = 6) -> Split:
    """시작일 기준 train_months 까지 학습, 다음 val_months 검증(캘리브레이션·조기종료), 나머지 테스트."""
    t0 = X["t"].min().normalize()
    train_end = t0 + pd.DateOffset(months=train_months)
    val_end = train_end + pd.DateOffset(months=val_months)
    tr = X[X["t"] < train_end]
    va = X[(X["t"] >= train_end) & (X["t"] < val_end)]
    te = X[X["t"] >= val_end]
    return Split(tr, va, te, train_end, val_end)


def one_hot_columns() -> list[str]:
    cats = [f"st_category__{c.value}" for c in AssetCategory]
    arcs = [f"st_archetype__{a}" for a in ("gov_office", "hospital", "hotel", "office")]
    return cats + arcs


def model_columns(X: pd.DataFrame, groups: tuple[str, ...] = FEATURE_GROUPS) -> list[str]:
    """범주형은 원-핫 열 이름으로 바꾼 최종 피처 목록 (SHAP 호환을 위해 HGB 에도 원-핫을 쓴다)."""
    cols = [c for c in feature_columns(X, groups) if c not in CATEGORICAL]
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
