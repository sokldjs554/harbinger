"""에너지 기대사용량 회귀(HGB) → 잔차 비율 → 이상일 탐지.

질문: "이 건물의 이번 주 전기 사용량은 날씨·재실을 감안했을 때 정상인가?"
답이 '아니오'이고 HVAC 설비의 점검 약신호가 함께 올라가면, 설비 효율 저하의 독립적인 증거가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score


def energy_design(energy: pd.DataFrame, site_codes: dict[str, int]) -> pd.DataFrame:
    T = energy["temp_mean_c"]
    d = pd.DataFrame(
        {
            "temp": T,
            "cdd": (T - 24).clip(lower=0),
            "hdd": (18 - T).clip(lower=0),
            "occ": energy["occupancy_index"],
            "dow": energy["day"].dt.dayofweek.astype(float),
            "m_sin": np.sin(2 * np.pi * energy["day"].dt.dayofyear / 365.25),
            "m_cos": np.cos(2 * np.pi * energy["day"].dt.dayofyear / 365.25),
            "site": energy["site_id"].map(site_codes).fillna(-1).astype(float),
        }
    )
    return d


@dataclass
class EnergyBundle:
    model: HistGradientBoostingRegressor
    site_codes: dict[str, int]
    resid_sigma: dict[str, float]
    target: str = "electricity_kwh"
    meta: dict = field(default_factory=dict)

    def predict(self, energy: pd.DataFrame) -> np.ndarray:
        return self.model.predict(energy_design(energy, self.site_codes))

    def residual_ratio(self, energy: pd.DataFrame) -> pd.Series:
        yhat = np.maximum(self.predict(energy), 1e-6)
        return pd.Series((energy[self.target].to_numpy() - yhat) / yhat, index=energy.index)

    def anomalies(self, energy: pd.DataFrame, window: int = 7, z: float = 2.5) -> pd.DataFrame:
        """사이트별 7일 이동평균 잔차가 학습기간 이동평균 잔차 표준편차의 z 배를 넘는 날."""
        df = energy[["site_id", "day", self.target]].copy()
        df["yhat"] = self.predict(energy)
        df["resid_ratio"] = self.residual_ratio(energy)
        out = []
        for sid, g in df.sort_values("day").groupby("site_id"):
            g = g.copy()
            g["resid_ma"] = g["resid_ratio"].rolling(window, min_periods=max(3, window // 2)).mean()
            sigma = self.resid_sigma.get(sid, float(df["resid_ratio"].std()))
            g["z"] = g["resid_ma"] / (sigma + 1e-9)
            g["anomaly"] = g["z"] > z
            out.append(g)
        return pd.concat(out, ignore_index=True)


def train_energy(energy_train: pd.DataFrame, target: str = "electricity_kwh", seed: int = 0) -> EnergyBundle:
    sites = sorted(energy_train["site_id"].unique())
    codes = {s: i for i, s in enumerate(sites)}
    D = energy_design(energy_train, codes)
    model = HistGradientBoostingRegressor(
        learning_rate=0.05,
        max_iter=500,
        max_leaf_nodes=31,
        min_samples_leaf=20,
        categorical_features=[D.columns.get_loc("site")],
        random_state=seed,
    )
    model.fit(D, energy_train[target])
    yhat = np.maximum(model.predict(D), 1e-6)
    tmp = energy_train[["site_id", "day"]].copy()
    tmp["rr"] = (energy_train[target].to_numpy() - yhat) / yhat
    # 이상 탐지 기준: 잔차 7일 이동평균의 사이트별 표준편차 (잔차 자기상관을 그대로 반영)
    sig = {}
    for s, g in tmp.sort_values("day").groupby("site_id"):
        ma = g["rr"].rolling(7, min_periods=4).mean().dropna()
        sig[s] = float(ma.std()) if len(ma) > 10 else float(tmp["rr"].std())
    return EnergyBundle(model, codes, sig, target, {"rows": int(len(energy_train)), "sigma_is_7d_ma": True})


def energy_metrics(bundle: EnergyBundle, energy_test: pd.DataFrame) -> dict:
    y = energy_test[bundle.target].to_numpy()
    yhat = bundle.predict(energy_test)
    mape = float(np.mean(np.abs(y - yhat) / np.maximum(y, 1e-6)))
    return {
        "mae": float(mean_absolute_error(y, yhat)),
        "mape": mape,
        "r2": float(r2_score(y, yhat)),
        "rows": int(len(y)),
    }
