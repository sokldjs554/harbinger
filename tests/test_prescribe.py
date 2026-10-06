import numpy as np
import pandas as pd

from harbinger.prescribe.priority import rank_patrol


def _latest(n=30, seed=0):
    rng = np.random.default_rng(seed)
    cats = ["pump"] * 20 + ["elevator"] * 5 + ["fire_pump"] * 5
    t = pd.Timestamp("2025-06-01")
    return pd.DataFrame(
        {
            "asset_id": [f"A{i}" for i in range(n)],
            "name": [f"설비{i}" for i in range(n)],
            "category": cats,
            "zone": [f"{(i % 5) - 2}F-A" for i in range(n)],
            "st_floor": [(i % 5) - 2 for i in range(n)],
            "st_criticality": [1] * 20 + [3] * 10,
            "p30": rng.uniform(0.01, 0.3, n),
            "t": [t - pd.Timedelta(days=int(d)) for d in rng.integers(1, 40, n)],
            "ck_overall": 0,
            "ck_overall_mean3": 0.0,
            "tx_weak_on_good_sum6": 0.0,
            "tx_weak_score_ewm": 0.0,
            "wo_bd_90d": 0,
            "wo_days_since_pm": 10.0,
            "st_age_years": 5.0,
            "en_hvac_x_resid30": 0.0,
            "q_inspector_lazy_rate": 0.1,
        }
    )


def test_mandatory_legal_assets_always_included():
    df = _latest()
    today = pd.Timestamp("2025-06-01")
    # 승강기 하나를 32일 전 점검으로 — 법정 기한 초과
    df.loc[df["category"] == "elevator", "t"] = today - pd.Timedelta(days=32)
    df.loc[df["category"] == "elevator", "p30"] = 0.001  # 위험은 최저
    items = rank_patrol(df, today, k=5)
    ids = {i.asset_id for i in items}
    assert set(df.loc[df["category"] == "elevator", "asset_id"]) <= ids
    assert all(i.mandatory for i in items if i.category == "elevator")


def test_ranking_monotone_in_expected_loss():
    df = _latest()
    today = pd.Timestamp("2025-06-01")
    df["t"] = today - pd.Timedelta(days=5)  # 법정 기한 없음
    items = rank_patrol(df, today, k=8)
    chosen = {i.asset_id for i in items}
    df["score"] = df["p30"] * df["st_criticality"].map({1: 1.0, 2: 1.8, 3: 3.0})
    top = set(df.nlargest(8, "score")["asset_id"])
    assert chosen == top
    # 동선 정렬: 층 오름차순
    floors = [i.floor for i in items]
    assert floors == sorted(floors)


def test_reasons_are_strings():
    df = _latest()
    items = rank_patrol(df, pd.Timestamp("2025-06-01"), k=3)
    for it in items:
        assert isinstance(it.reasons, list) and all(isinstance(r, str) for r in it.reasons)
        d = it.to_dict()
        assert {"rank", "asset_id", "p30", "score", "mandatory"} <= set(d)
