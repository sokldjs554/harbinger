"""시간 의존 피처 갱신 — 위험도를 '마지막 점검 시점'이 아니라 기준 시각(as_of)에 맞춘다.

피처 행은 점검이 일어난 시각 t 에 만들어진다. 그런데 점검 뒤에 고장이 나거나 정비가 끝나면 그 설비의 위험은 달라지는데,
행의 이력 피처는 t 에 고정돼 있어 다음 점검 전까지 반영되지 않는다(점검 1일 뒤 고장난 펌프가 계속 고위험 1위로 뜨던 문제).
여기서는 점검 시점에 정해지지 않는, **시간이 흐르면 변하는 피처**만 as_of 기준으로 다시 계산한다:

  wo_*  고장/정비/부품교체 이력 (as_of 이전 이벤트 전부)       ck_days_since_bad/caution (경과일 가산)
  st_age_years (연식 가산)  se_sin/se_cos (계절)               wo_site_bd_180d_per_asset (사이트 최근 고장)

점검 내용(체크리스트·메모·점검 품질)과 에너지 잔차는 점검 시점 그대로 둔다. as_of == t 이면 원래 값과 정확히 같다
(tests/test_refresh.py). 학습 행은 항상 점검 시각이므로 학습 분포는 바뀌지 않는다 — 바뀌는 것은 추론 경로뿐이다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harbinger.features.build import _days_since_last, _window_counts

DAY_NS = 86_400_000_000_000
REFRESHED = (
    "wo_bd_90d",
    "wo_bd_365d",
    "wo_bd_total",
    "wo_days_since_bd",
    "wo_days_since_pm",
    "wo_days_since_parts",
    "wo_parts_365d",
    "wo_pm_365d",
    "wo_bd_rate_yr",
    "wo_site_bd_180d_per_asset",
    "ck_days_since_bad",
    "ck_days_since_caution",
    "st_age_years",
    "se_sin",
    "se_cos",
)


class Refresher:
    def __init__(self, tables: dict[str, pd.DataFrame]):
        wo = tables["workorders"].sort_values("opened_at")
        self.by_type = {
            typ: {a: v["opened_at"].to_numpy() for a, v in g.groupby("asset_id")}
            for typ, g in wo.groupby("type")
        }
        self.site_bd = {
            s: v["opened_at"].to_numpy() for s, v in wo[wo["type"] == "breakdown"].groupby("site_id")
        }
        self.first_seen = tables["inspections"].groupby("asset_id")["performed_at"].min()
        self.n_assets_site = tables["assets"].groupby("site_id").size()

    def apply(self, rows: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
        """rows(설비당 최근 행)의 시간 의존 피처를 as_of 기준으로 바꾼 사본. as_of 가 행의 t 보다 이르면 t 를 쓴다."""
        if rows.empty:
            return rows
        out = rows.copy()
        keys = out["asset_id"].to_numpy()
        # _window_counts 는 배열 하나의 기준 시각을 받으므로 설비별 기준 시각을 같은 값(as_of)으로 통일한다.
        ts = np.full(len(out), np.datetime64(as_of.to_datetime64(), "ns"))
        ts = np.maximum(ts, out["t"].to_numpy("datetime64[ns]"))
        bd = self.by_type.get("breakdown", {})
        out["wo_bd_90d"] = _window_counts(bd, keys, ts, 90)
        out["wo_bd_365d"] = _window_counts(bd, keys, ts, 365)
        out["wo_bd_total"] = _window_counts(bd, keys, ts, None)
        out["wo_days_since_bd"] = _days_since_last(bd, keys, ts)
        out["wo_days_since_pm"] = _days_since_last(self.by_type.get("preventive", {}), keys, ts)
        out["wo_days_since_parts"] = _days_since_last(self.by_type.get("parts", {}), keys, ts)
        out["wo_parts_365d"] = _window_counts(self.by_type.get("parts", {}), keys, ts, 365)
        out["wo_pm_365d"] = _window_counts(self.by_type.get("preventive", {}), keys, ts, 365)
        first = out["asset_id"].map(self.first_seen).to_numpy("datetime64[ns]")
        # build.py 는 Timedelta.days(정수 일)를 쓴다 — 같은 정의로 맞춰야 as_of==t 에서 원래 값과 같다
        years = np.floor((ts - first) / np.timedelta64(1, "D")) / 365.25
        out["wo_bd_rate_yr"] = out["wo_bd_total"] / (years + 0.25)
        site_counts = _window_counts(self.site_bd, out["site_id"].to_numpy(), ts, 180)
        out["wo_site_bd_180d_per_asset"] = site_counts / out["site_id"].map(self.n_assets_site).to_numpy()
        delta_days = (ts - out["t"].to_numpy("datetime64[ns]")) / np.timedelta64(1, "D")
        for c in ("ck_days_since_bad", "ck_days_since_caution"):
            out[c] = out[c] + delta_days
        out["st_age_years"] = out["st_age_years"] + delta_days / 365.25
        doy = pd.DatetimeIndex(ts).dayofyear.to_numpy()
        out["se_sin"] = np.sin(2 * np.pi * doy / 365.25)
        out["se_cos"] = np.cos(2 * np.pi * doy / 365.25)
        return out
