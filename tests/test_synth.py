from datetime import date

import numpy as np
import pandas as pd

from harbinger.schema import CHECK_ITEMS, AssetCategory
from harbinger.synth.generate import GenConfig, generate


def test_deterministic_given_seed():
    cfg = GenConfig(seed=3, start=date(2024, 1, 1), months=3, scale=0.1)
    a = generate(cfg, verbose=False)
    b = generate(cfg, verbose=False)
    for k in ("inspections", "workorders", "energy"):
        pd.testing.assert_frame_equal(a[k], b[k])


def test_distributions_are_plausible(tiny):
    ins, wo, a = tiny["tables"]["inspections"], tiny["tables"]["workorders"], tiny["tables"]["assets"]
    dist = ins["overall"].value_counts(normalize=True)
    assert dist.get(0, 0) > 0.6, "양호가 다수여야 한다"
    assert dist.get(2, 0) < 0.1, "불량은 드물어야 한다"
    years = tiny["cfg"].months / 12
    bd_per_asset_year = (wo["type"] == "breakdown").sum() / len(a) / years
    assert 0.2 < bd_per_asset_year < 2.0
    # 법정 설비 점검 간격 ≤ 31일 (+ 지연 허용 3일)
    legal = a[a["category"].isin(["elevator", "fire_pump", "generator"])]["asset_id"]
    s = ins[ins["asset_id"].isin(legal)].sort_values(["asset_id", "performed_at"])
    gaps = s.groupby("asset_id")["performed_at"].diff().dt.days.dropna()
    assert gaps.quantile(0.99) <= 36


def test_checklist_columns_match_category(tiny):
    ins, a = tiny["tables"]["inspections"], tiny["tables"]["assets"]
    m = ins.merge(a[["asset_id", "category"]], on="asset_id")
    for cat, items in CHECK_ITEMS.items():
        sub = m[m["category"] == cat.value]
        if sub.empty:
            continue
        for item in items:
            assert sub[f"chk_{item}"].notna().all()
        others = [f"chk_{i}" for c2, its in CHECK_ITEMS.items() for i in its if c2 != cat and i not in items]
        if others:
            assert sub[others].isna().all().all()


def test_memo_weak_signals_precede_failures(tiny):
    """핵심 가설: 메모 약신호가 있는 점검 뒤에 고장이 더 자주 온다 (생성 모델이 그렇게 만들었는지 확인)."""
    from harbinger.features.text import memo_features

    X = tiny["X"]
    v = X[X["label_valid"]]
    tx = memo_features(v["memo"])
    with_weak = v[tx["tx_weak_score"] > 0]["y30"].mean()
    without = v[tx["tx_weak_score"] == 0]["y30"].mean()
    assert with_weak > without


def test_latent_state_drives_failures(tiny):
    lat = tiny["tables"]["latent"]
    wo = tiny["tables"]["workorders"]
    bd = wo[wo["type"] == "breakdown"].copy()
    bd["day"] = bd["opened_at"].dt.normalize() - pd.Timedelta(days=1)
    m = bd.merge(lat, on=["asset_id", "day"], how="left")["d"].dropna()
    assert m.median() > lat["d"].median(), "고장 직전 열화는 전체 중앙값보다 높아야 한다"
    assert set(np.unique(lat["asset_id"])) == set(tiny["tables"]["assets"]["asset_id"])
    assert all(c in AssetCategory._value2member_map_ for c in tiny["tables"]["assets"]["category"].unique())
