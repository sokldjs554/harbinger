"""30일 내 비계획 고장 분류기 — HistGradientBoosting + isotonic 캘리브레이션, 그리고 베이스라인들."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from harbinger.models.calibration import choose_calibrator, fit_isotonic
from harbinger.models.common import to_matrix


@dataclass
class ClassifierBundle:
    model: object
    features: list[str]
    calibrator: object | None = None
    name: str = "hgb"
    meta: dict = field(default_factory=dict)

    def predict_raw(self, X: pd.DataFrame) -> np.ndarray:
        M = to_matrix(X, self.features)
        if isinstance(self.model, Pipeline):
            return self.model.predict_proba(M.to_numpy())[:, 1]
        return self.model.predict_proba(M)[:, 1]

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = self.predict_raw(X)
        if self.calibrator is not None:
            q = self.calibrator.predict(p)
            # isotonic 은 계단함수라 동점이 많이 생긴다. 원 점수를 0.1 % 섞어 순위를 보존한다(둘 다 단조라 캘리브레이션은 유지).
            p = 0.999 * q + 0.001 * p if isinstance(self.calibrator, IsotonicRegression) else q
        return np.clip(p, 1e-6, 1 - 1e-6)


def train_hgb(
    train: pd.DataFrame,
    val: pd.DataFrame,
    features: list[str],
    seed: int = 0,
    name: str = "hgb",
    calibrate: bool = True,
    **params,
) -> ClassifierBundle:
    hp = dict(
        learning_rate=0.04,
        max_iter=800,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        l2_regularization=2.0,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=30,
        random_state=seed,
    )
    hp.update(params)
    clf = HistGradientBoostingClassifier(**hp)
    Mtr = to_matrix(train, features)
    clf.fit(Mtr, train["y30"].to_numpy())
    bundle = ClassifierBundle(
        clf,
        features,
        None,
        name,
        {"n_iter": int(clf.n_iter_), "params": {k: v for k, v in hp.items() if k != "random_state"}},
    )
    if calibrate and len(val) > 0:
        calibrator, info = choose_calibrator(bundle.predict_raw(val), val["y30"].to_numpy(), seed=seed)
        bundle.meta["calibration"] = info
        bundle.calibrator = calibrator
    return bundle


def train_logistic(
    train: pd.DataFrame, val: pd.DataFrame, features: list[str], seed: int = 0, name: str = "logreg"
) -> ClassifierBundle:
    pipe = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("lr", LogisticRegression(C=0.5, max_iter=2000, random_state=seed)),
        ]
    )
    pipe.fit(to_matrix(train, features).to_numpy(), train["y30"].to_numpy())
    bundle = ClassifierBundle(pipe, features, None, name)
    if len(val) > 0:
        bundle.calibrator = fit_isotonic(bundle.predict_raw(val), val["y30"].to_numpy())
    return bundle


# ---- 베이스라인 ----
BASELINE_FEATURES = {
    # 연식만 — "오래된 설비가 고장난다" 수준의 상식
    "age_only": ["st_age_years", "st_criticality"]
    + [
        f"st_category__{c}"
        for c in (
            "chiller",
            "ahu",
            "pump",
            "boiler",
            "elevator",
            "generator",
            "switchgear",
            "fire_pump",
            "cooling_tower",
            "exhaust_fan",
            "auto_door",
            "water_tank",
        )
    ],
    # 마지막 점검 결과만 — 현장이 지금 실제로 쓰는 규칙에 가장 가깝다
    "last_inspection": ["ck_overall", "ck_n_caution", "ck_n_bad", "ck_frac_flagged"],
}
