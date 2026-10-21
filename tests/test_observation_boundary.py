"""미래 정답/전처리 관측 경계의 회귀 테스트."""

from types import SimpleNamespace

import numpy as np
import pandas as pd

from harbinger.models.common import labeled, split_by_time


def frame():
    return pd.DataFrame(
        {
            "t": pd.to_datetime(
                ["2023-01-01", "2024-12-02", "2024-12-31", "2025-01-01", "2025-06-30", "2025-07-01"]
            ),
            "label_valid": True,
            "y30": [0, 1, 1, 0, 1, 0],
            "tte_days": [1000.0, 30.0, 5.0, 500.0, 5.0, 100.0],
            "event": 1,
        }
    )


def test_mature_classification_labels_only():
    split = split_by_time(frame())
    assert (labeled(split.train).t + pd.Timedelta(days=30) <= split.train_end).all()
    assert (labeled(split.val).t + pd.Timedelta(days=30) <= split.val_end).all()
    assert pd.Timestamp("2024-12-02") in set(labeled(split.train).t)  # exactly cutoff is allowed


def test_survival_is_censored_at_each_boundary():
    split = split_by_time(frame())
    for part, cutoff in [(split.train, split.train_end), (split.val, split.val_end)]:
        assert (part.t + pd.to_timedelta(part.tte_days, unit="D") <= cutoff).all()
        assert part.iloc[-1].event == 0
        assert part.iloc[-1].tte_days == 1
    assert split.train.iloc[1].event == 1  # event exactly at cutoff preserved


def test_future_outcomes_do_not_change_training_targets():
    before = frame()
    after = before.copy()
    after.loc[[0, 2, 3, 4], "tte_days"] = 2000.0
    after.loc[[0, 2, 3, 4], "event"] = 0
    after.loc[[2, 4], "y30"] = 0
    a, b = split_by_time(before), split_by_time(after)
    for name in ("train", "val"):
        pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name))


def test_energy_never_falls_back_to_future():
    from harbinger.features.energy import energy_residuals

    en = pd.DataFrame(
        {
            "site_id": "s",
            "day": pd.date_range("2024-01-01", periods=100),
            "temp_mean_c": 20.0,
            "occupancy_index": 1.0,
            "electricity_kwh": 100.0,
            "gas_m3": 20.0,
        }
    )
    cutoff = pd.Timestamp("2024-01-20")
    a = energy_residuals(en, cutoff)
    en.loc[en.day >= cutoff, ["electricity_kwh", "gas_m3"]] *= 100
    b = energy_residuals(en, cutoff)
    pd.testing.assert_frame_equal(a[a.day < cutoff], b[b.day < cutoff])
    assert a.loc[a.day < cutoff, "en_resid_ratio"].isna().all()


def test_unknown_model_cutoff_is_not_invented(tmp_path):
    from harbinger.api.backtest import heldout_start

    store = SimpleNamespace(
        settings=SimpleNamespace(artifact_dir=tmp_path),
        bundle={"entry": {}},
        data_end=pd.Timestamp("2025-12-31"),
    )
    assert heldout_start(store) is None


def test_explicit_data_end_censors_future_workorders(tiny):
    from harbinger.features.build import build_features

    cutoff = pd.Timestamp("2024-06-01")
    tables = {k: v.copy() for k, v in tiny["tables"].items()}
    tables["inspections"] = tables["inspections"].query("performed_at < @cutoff")
    x = build_features(tables, data_end=cutoff, fit_until=cutoff, verbose=False)
    assert np.all(x.tte_days <= (cutoff - x.t).dt.total_seconds() / 86400 + 1e-8)


def test_future_records_leave_inputs_labels_and_fits_unchanged(tiny):
    from harbinger.features.build import build_features
    from harbinger.models.classify import train_hgb
    from harbinger.models.common import model_columns, observe_until, to_matrix

    cutoff = pd.Timestamp("2024-06-01")
    tables = {k: v.copy() for k, v in tiny["tables"].items()}
    changed = {k: v.copy() for k, v in tables.items()}
    changed["workorders"] = changed["workorders"][changed["workorders"].opened_at <= cutoff]
    changed["inspections"] = changed["inspections"][changed["inspections"].performed_at <= cutoff]
    changed["energy"].loc[changed["energy"].day > cutoff, "electricity_kwh"] *= 100
    a = observe_until(build_features(tables, fit_until=cutoff, verbose=False), cutoff)
    b = observe_until(
        build_features(
            changed, fit_until=cutoff, data_end=tables["inspections"].performed_at.max(), verbose=False
        ),
        cutoff,
    )
    cols = model_columns(a)
    pd.testing.assert_frame_equal(to_matrix(a, cols), to_matrix(b, cols))
    pd.testing.assert_frame_equal(
        a[["y30", "label_valid", "tte_days", "event"]], b[["y30", "label_valid", "tte_days", "event"]]
    )
    ma = train_hgb(labeled(a), a.iloc[:0], cols, max_iter=10, early_stopping=False, seed=1)
    mb = train_hgb(labeled(b), b.iloc[:0], cols, max_iter=10, early_stopping=False, seed=1)
    assert ma.meta == mb.meta
    np.testing.assert_array_equal(ma.predict_proba(a), mb.predict_proba(b))
