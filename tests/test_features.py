import numpy as np
import pandas as pd

from harbinger.features.build import FEATURE_GROUPS, build_features, feature_columns
from harbinger.features.text import memo_features, novelty


def test_point_in_time_no_leakage(tiny):
    """데이터를 T0 에서 자른 뒤 다시 빌드해도 T0 - 45일 이전 행의 피처가 바뀌지 않아야 한다."""
    tables = tiny["tables"]
    X_full = tiny["X"]
    T0 = X_full["t"].min() + pd.Timedelta(days=200)
    cut = {k: v.copy() for k, v in tables.items()}
    cut["inspections"] = cut["inspections"][cut["inspections"]["performed_at"] < T0]
    cut["workorders"] = cut["workorders"][cut["workorders"]["opened_at"] < T0]
    cut["energy"] = cut["energy"][cut["energy"]["day"] < T0]
    fit_until = X_full["t"].min() + pd.Timedelta(days=120)
    X_cut = build_features(cut, fit_until=fit_until, data_end=T0, verbose=False)
    X_ref = build_features(tables, fit_until=fit_until, verbose=False)
    cat_cols = ["st_category", "st_archetype"]
    cols = [c for c in feature_columns(X_ref) if not c.startswith("en_") and c not in cat_cols]
    margin = T0 - pd.Timedelta(days=45)
    a = X_ref[X_ref["t"] < margin].set_index("inspection_id").sort_index()
    b = X_cut[X_cut["t"] < margin].set_index("inspection_id").sort_index()
    assert len(a) == len(b) and len(a) > 100
    pd.testing.assert_frame_equal(
        a[cols].astype(float), b[cols].astype(float), check_exact=False, rtol=1e-9, atol=1e-9
    )
    assert (a[cat_cols].astype(str) == b[cat_cols].astype(str)).all().all()
    en = [c for c in feature_columns(X_ref) if c.startswith("en_")]
    pd.testing.assert_frame_equal(
        a[en].astype(float), b[en].astype(float), check_exact=False, rtol=1e-9, atol=1e-9
    )


def test_labels_consistent(tiny):
    X = tiny["X"]
    assert set(X["y30"].unique()) <= {0, 1}
    assert (X["tte_days"] > 0).all()
    assert ((X["event"] == 1) | (X["y30"] == 0)).all(), "사건 없이 30일 라벨이 1일 수 없다"
    v = X[X["label_valid"]]
    assert 0.01 < v["y30"].mean() < 0.3
    assert (X.loc[X["y30"] == 1, "tte_days"] <= 30).all()


def test_feature_groups_present(tiny):
    X = tiny["X"]
    for g in FEATURE_GROUPS:
        assert feature_columns(X, (g,)), f"그룹 {g} 피처 없음"
    assert X["ck_good_streak"].min() >= 0
    assert (X["q_evidence_weight"].between(0.2, 1.0)).all()


def test_text_features():
    s = pd.Series(["약간의 소음 감지, 미세 진동", "특이사항 없음", "누유 심함, 긴급 수리", ""])
    f = memo_features(s)
    assert f.loc[0, "tx_weak_score"] > 0 and f.loc[0, "tx_n_groups"] == 2
    assert f.loc[1, "tx_lazy"] == 1.0 and f.loc[1, "tx_weak_score"] == 0
    assert f.loc[2, "tx_strong_score"] > 0
    assert f.loc[3, "tx_len"] == 0
    nov = novelty(
        pd.Series([None, "특이사항 없음", "특이사항 없음"]), pd.Series(["정상", "특이사항 없음", "소음 증가"])
    )
    assert nov.iloc[0] == 1.0 and nov.iloc[1] == 0.0 and 0 < nov.iloc[2] <= 1.0


def test_rolling_uses_only_past(tiny):
    X = tiny["X"].sort_values(["asset_id", "t"])
    g = X.groupby("asset_id")
    first = g.head(1)
    assert first["ck_overall_prev"].isna().all()
    assert (first["ck_n_inspections"] == 1).all()
    assert np.allclose(first["ck_overall_mean3"], first["ck_overall"])
