"""Service selection parity and the site-equal patrol estimand."""

import json

import numpy as np
import pandas as pd
import pytest

from harbinger.eval import patrol
from harbinger.features.refresh import Refresher
from harbinger.prescribe import priority


def _panel(balanced=False):
    rows = []
    for site, count, value in [("a", 1, 1.0), ("b", 1 if balanced else 3, 0.0)]:
        for day in pd.date_range("2025-01-01", periods=count):
            for method, precision in [("model", value), ("last_inspection", 0.0)]:
                rows.append(
                    dict(
                        site_id=site,
                        day=day.isoformat(),
                        method=method,
                        precision=precision,
                        hits=int(precision),
                        positives=1,
                        picks=1,
                        candidate_asset_ids=[site],
                        selected_asset_ids=[site],
                        mandatory_asset_ids=[],
                        requested_k=1,
                        mandatory_count=0,
                        overflow=0,
                        base_rate=0.5,
                    )
                )
    return pd.DataFrame(rows)


@pytest.mark.parametrize("balanced,old", [(True, 0.5), (False, 0.25)])
def test_point_and_cluster_bootstrap_target_same_site_equal_mean(balanced, old):
    result = patrol.summarize_patrol_rows(_panel(balanced), seed=31)
    model = result["methods"]["model"]
    assert model["precision_at_k"] == 0.5
    assert model["historical_date_weighted_precision_at_k"] == old
    assert model["delta_vs_last_inspection"] == 0.5
    assert model["site_cluster_ci95"] == [0.0, 1.0]
    assert model["n_sites"] == 2


def test_repeated_days_do_not_create_independent_bootstrap_samples():
    original = _panel()
    repeated = pd.concat([original.assign(day=original.day + f"-{i}") for i in range(5)])
    a = patrol.summarize_patrol_rows(original, seed=31)["methods"]["model"]
    b = patrol.summarize_patrol_rows(repeated, seed=31)["methods"]["model"]
    assert a["site_cluster_ci95"] == b["site_cluster_ci95"]
    assert a["precision_at_k"] == b["precision_at_k"]


@pytest.mark.parametrize("case", ["single_site", "missing_day", "different_assets"])
def test_inadequate_or_unpaired_panels_withhold_uncertainty(case):
    rows = _panel()
    if case == "single_site":
        rows = rows[rows.site_id == "b"]
    elif case == "missing_day":
        rows = rows.drop(rows.index[-1])
    else:
        rows.at[rows.index[-1], "candidate_asset_ids"] = ["other"]
    result = patrol.summarize_patrol_rows(rows)
    model = result["methods"]["model"]
    assert model["delta_vs_last_inspection_ci95"] is None
    assert model["uncertainty_status"] != "available"
    json.dumps(result, allow_nan=False)


def _fixture():
    start = pd.Timestamp("2025-01-01")
    assets = pd.DataFrame(
        dict(
            asset_id=["a", "b", "c", "d", "old"],
            site_id="s",
            category=["elevator", "fire_pump", "pump", "pump", "pump"],
            name=["A", "B", "C", "D", "Old"],
            zone=["z"] * 5,
        )
    )
    X = assets[["asset_id", "site_id", "category"]].copy()
    X["t"] = start
    X["p30"] = [0.01, 0.02, 0.9, 0.4, 1.0]
    X["st_criticality"] = [1, 1, 1, 3, 1]
    X["st_floor"] = 0
    X["st_age_years"] = [1, 2, 30, 2, 5]
    X["ck_overall"] = [0, 0, 2, 1, 0]
    X["ck_days_since_bad"] = 0.0
    X["ck_days_since_caution"] = 0.0
    # Keep the stale row exactly 120 days before the first evaluation snapshot.
    X.loc[X.asset_id == "old", "t"] = start - pd.Timedelta(days=90)
    end = X[X.asset_id != "old"].assign(t=start + pd.Timedelta(days=90))
    X = pd.concat([X, end], ignore_index=True)
    wo = pd.DataFrame(
        dict(asset_id=["a"], site_id=["s"], type=["breakdown"], opened_at=[start + pd.Timedelta(days=40)])
    )
    tables = dict(
        assets=assets, workorders=wo, inspections=X[["asset_id", "t"]].rename(columns={"t": "performed_at"})
    )
    return X, tables


def test_service_overflow_is_not_raw_precision_at_k_and_rules_keep_their_scores():
    X, tables = _fixture()
    # Explicit dates avoid making the old stale observation determine the evaluation start.
    out = patrol.simulate_patrol(
        X,
        {"model": lambda x: x.p30.to_numpy()},
        tables["workorders"],
        Refresher(tables),
        k=1,
        evaluation_days=[pd.Timestamp("2025-01-31")],
        assets=tables["assets"],
    )
    raw = next(r for r in out["rows"] if r["method"] == "model")
    service = next(r for r in out["service_policy"]["rows"] if r["method"] == "model")
    assert raw["selected_asset_ids"] == ["c"]
    assert set(service["selected_asset_ids"]) == {"a", "b"}
    assert service["picks"] == service["mandatory_count"] == 2
    assert service["overflow"] == 1
    assert service["hits"] == 1
    assert service["precision"] == 0.5
    assert "precision_at_k" not in out["service_policy"]["methods"]["model"]
    assert out["service_policy"]["methods"]["model"]["selection_hit_rate"] == 0.5
    assert out["service_policy"]["random_expected_precision"] == 0.5
    assert out["random_expected_precision"] == 0.25
    assert "old" not in service["candidate_asset_ids"]
    for row in out["service_policy"]["rows"]:
        assert row["mandatory_asset_ids"] == ["a", "b"]
        assert row["candidate_asset_ids"] == ["a", "b", "c", "d"]
    json.dumps(out, allow_nan=False)


def test_service_selector_weights_probabilities_but_preserves_rule_priorities():
    X, tables = _fixture()
    day = pd.Timestamp("2025-01-11")
    rows = X[X.t == pd.Timestamp("2025-01-01")].merge(tables["assets"][["asset_id", "name", "zone"]])
    chosen = priority.select_patrol(rows, day, k=1)
    assert chosen.asset_id.tolist() == ["d"]
    rules = priority.select_patrol(
        rows.assign(rule=[10, 20, 30, 15]), day, k=1, score_column="rule", probability_score=False
    )
    assert rules.asset_id.tolist() == ["c"]
    assert rules.score.tolist() == [30]
    assert [x.asset_id for x in priority.rank_patrol(rows, day, k=1)] == ["d"]


def test_ties_are_stable_under_input_reordering():
    X, tables = _fixture()
    rows = X[X.t == pd.Timestamp("2025-01-01")].merge(tables["assets"][["asset_id", "name", "zone"]])
    rows["st_criticality"] = 1
    rows["p30"] = 0.5
    for frame in [rows, rows.iloc[::-1]]:
        assert priority.select_patrol(frame, pd.Timestamp("2025-01-11"), k=1).asset_id.tolist() == ["a"]


def test_empty_input_is_finite_and_has_both_sections():
    X, tables = _fixture()
    out = patrol.simulate_patrol(X.iloc[:0], {}, tables["workorders"], Refresher(tables))
    assert out["methods"] == out["service_policy"]["methods"] == {}
    assert out["days"] == 0
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    "day,k,want",
    [("2025-01-11", 1, ["d"]), ("2025-01-31", 1, ["a", "b"]), ("2025-01-31", 3, ["a", "b", "d"])],
)
def test_real_store_and_evaluator_share_selection_and_source_t(tmp_path, day, k, want):
    from harbinger.api.store import Store
    from harbinger.config import Settings

    class FixedProbabilities:
        def predict_proba(self, rows):
            return rows.asset_id.map({"a": 0.01, "b": 0.02, "c": 0.9, "d": 0.4, "old": 0.001}).to_numpy()

    X, tables = _fixture()
    store = Store(Settings(model_dir=tmp_path))
    store.X, store.tables = X, tables
    store.bundle = {"classifier": FixedProbabilities(), "version": "fixture"}
    day = pd.Timestamp(day)
    live_rows = store.latest_rows("s", day)
    live = store.patrol("s", day, k=k, explain=False)
    result = patrol.simulate_patrol(
        X,
        {"model": store.bundle["classifier"].predict_proba},
        tables["workorders"],
        store.refresher,
        k=k,
        evaluation_days=[day],
        assets=tables["assets"],
    )
    selected = next(r for r in result["service_policy"]["rows"] if r["method"] == "model")
    assert sorted(r["asset_id"] for r in live["items"]) == want
    assert sorted(selected["selected_asset_ids"]) == want
    assert selected["candidate_asset_ids"] == sorted(live_rows.asset_id.tolist())
    assert result["snapshots"][0]["source_t"] == {r.asset_id: r.t.isoformat() for r in live_rows.itertuples()}
    if k == 3:
        age_rule = next(r for r in result["service_policy"]["rows"] if r["method"] == "age")
        assert set(age_rule["selected_asset_ids"]) == {"a", "b", "c"}


def test_no_evaluable_breakdowns_returns_json_null():
    X, tables = _fixture()
    result = patrol.breakdown_recall_at_top(X.iloc[:0], np.array([]), tables["workorders"])
    assert result["recall"] is None
    json.dumps(result, allow_nan=False)


def test_actual_audit_unequal_dates_are_outcome_independent_and_keep_pairs():
    from scripts.check_patrol_evaluation import uneven_panel

    rows = pd.concat([_panel(True).assign(day=f"2025-01-{i + 1:02d}") for i in range(12)])
    rows["site_id"] = rows.site_id.replace({"b": "c"})
    selected = uneven_panel(rows)
    counts = selected.groupby(["site_id", "method"]).size().to_dict()
    assert counts == {
        ("a", "last_inspection"): 4,
        ("a", "model"): 4,
        ("c", "last_inspection"): 3,
        ("c", "model"): 3,
    }
    changed = rows.assign(hits=1 - rows.hits, precision=1 - rows.precision)
    keys = ["site_id", "day", "method"]
    pd.testing.assert_frame_equal(selected[keys], uneven_panel(changed)[keys])


def test_actual_audit_mature_window_has_no_numpy_timedelta_warning():
    import warnings

    from scripts.check_patrol_evaluation import mature_window

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        start, end = mature_window("2025-07-01T00:00:00", "2026-01-01T00:00:00")
    assert start == pd.Timestamp("2025-07-31")
    assert end == pd.Timestamp("2025-12-02")
