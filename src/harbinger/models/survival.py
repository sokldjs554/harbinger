"""생존분석 — 점검 데이터는 '아직 고장 안 남'이 대부분이라 중도절단을 다루는 모델이 자연스럽다.

CoxPH / Weibull AFT (lifelines) 를 쓰고, 30일 고장확률 P30 = 1 − S(30) 로 분류기와 같은 잣대로 비교한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, WeibullAFTFitter
from lifelines.utils import concordance_index

from harbinger.models.common import to_matrix

SURV_HORIZONS = (30, 60, 90, 180, 360)


@dataclass
class SurvivalBundle:
    fitter: object
    features: list[str]
    medians: pd.Series
    means: pd.Series
    stds: pd.Series
    kind: str = "cox"
    meta: dict = field(default_factory=dict)

    def _prep(self, X: pd.DataFrame) -> pd.DataFrame:
        M = to_matrix(X, self.features)
        M = M.fillna(self.medians)
        M = (M - self.means) / self.stds.replace(0, 1.0)
        return M

    def survival_at(self, X: pd.DataFrame, times=SURV_HORIZONS) -> np.ndarray:
        """행별 S(t) 행렬 (n × len(times))."""
        M = self._prep(X)
        sf = self.fitter.predict_survival_function(M, times=list(times))
        return sf.to_numpy().T

    def p_fail_within(self, X: pd.DataFrame, days: int = 30) -> np.ndarray:
        return np.clip(1.0 - self.survival_at(X, times=(days,))[:, 0], 1e-6, 1 - 1e-6)

    def risk_score(self, X: pd.DataFrame) -> np.ndarray:
        M = self._prep(X)
        if self.kind == "cox":
            return self.fitter.predict_partial_hazard(M).to_numpy().ravel()
        return -self.fitter.predict_median(M).to_numpy().ravel()


def _drop_constant(M: pd.DataFrame) -> list[str]:
    return [c for c in M.columns if M[c].nunique(dropna=True) > 1]


def train_survival(
    train: pd.DataFrame,
    features: list[str],
    kind: str = "cox",
    penalizer: float = 0.05,
    max_rows: int | None = 60000,
    seed: int = 0,
) -> SurvivalBundle:
    """kind: cox | aft. 전체 행(라벨 유효성 무관 — 중도절단으로 처리)을 쓴다. 속도를 위해 행 수를 제한할 수 있다."""
    df = train
    if max_rows is not None and len(df) > max_rows:
        df = df.sample(max_rows, random_state=seed)
    M = to_matrix(df, features)
    keep = _drop_constant(M)
    M = M[keep]
    medians = M.median()
    M = M.fillna(medians)
    means, stds = M.mean(), M.std().replace(0, 1.0)
    Z = (M - means) / stds
    Z["tte_days"] = df["tte_days"].to_numpy()
    Z["event"] = df["event"].to_numpy()
    if kind == "cox":
        f = CoxPHFitter(penalizer=penalizer, l1_ratio=0.0)
        f.fit(Z, duration_col="tte_days", event_col="event", robust=False)
    else:
        f = WeibullAFTFitter(penalizer=penalizer)
        f.fit(Z, duration_col="tte_days", event_col="event")
    return SurvivalBundle(f, keep, medians, means, stds, kind, {"rows": int(len(df)), "penalizer": penalizer})


def c_index(bundle: SurvivalBundle, X: pd.DataFrame) -> float:
    r = bundle.risk_score(X)
    return float(concordance_index(X["tte_days"].to_numpy(), -r, X["event"].to_numpy()))
