"""시간 의존 피처 갱신 — as_of == t 이면 원래 값 그대로, 점검 뒤 이벤트는 반영, 미래는 보지 않는다."""

import numpy as np
import pandas as pd

from harbinger.features.refresh import REFRESHED, Refresher


def test_refresh_at_row_time_is_identity(tiny):
    X, tables = tiny["X"], tiny["tables"]
    R = Refresher(tables)
    checked = 0
    for t, g in X[X["t"] > X["t"].min() + pd.Timedelta(days=120)].groupby("t"):
        out = R.apply(g, t)
        for c in REFRESHED:
            assert np.allclose(
                g[c].to_numpy(float), out[c].to_numpy(float), equal_nan=True, rtol=1e-9, atol=1e-9
            ), c
        checked += len(g)
        if checked > 400:
            break
    assert checked > 100


def test_refresh_picks_up_breakdown_after_inspection(tiny):
    X, tables = tiny["X"], tiny["tables"]
    wo = tables["workorders"]
    bd = wo[wo["type"] == "breakdown"].sort_values("opened_at")
    last_rows = X.sort_values("t").groupby("asset_id").tail(1)
    R = Refresher(tables)
    found = 0
    for _, b in bd.iterrows():
        row = last_rows[last_rows["asset_id"] == b["asset_id"]]
        if row.empty or not (row["t"].iloc[0] < b["opened_at"]):
            continue
        as_of = b["opened_at"] + pd.Timedelta(hours=1)
        out = R.apply(row, as_of)
        assert out["wo_days_since_bd"].iloc[0] < 1.1, "점검 뒤 고장이 이력에 반영되어야 한다"
        assert out["wo_bd_total"].iloc[0] >= row["wo_bd_total"].iloc[0] + 1
        found += 1
        if found >= 5:
            break
    assert found > 0


def test_refresh_never_uses_the_future(tiny):
    X, tables = tiny["X"], tiny["tables"]
    R = Refresher(tables)
    row = X.sort_values("t").groupby("asset_id").tail(1).head(30)
    early = row["t"].min()
    a = R.apply(row, early)  # as_of 가 각 행의 t 보다 이르면 t 를 쓴다 → 원래 값
    for c in REFRESHED:
        assert np.allclose(
            a[c].to_numpy(float), row[c].to_numpy(float), equal_nan=True, rtol=1e-9, atol=1e-9
        ), c
