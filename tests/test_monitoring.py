"""Regression coverage for drift blind spots and monitoring freshness."""

import json

import numpy as np
import pandas as pd
import pytest

from harbinger.monitoring.drift import feature_drift, prediction_drift, psi


@pytest.mark.parametrize(
    ("reference", "current"),
    [
        ([0] * 100, [1] * 100),
        ([0] * 85 + [1] * 15, [0] * 15 + [1] * 85),
        ([0] * 50 + [1] * 50, [0] * 50 + [2] * 50),
        ([0] * 100, [0] * 20 + [np.nan] * 80),
        ([0] * 100, [np.nan] * 100),
        ([0] * 990 + list(range(1, 12)), [1] * 1001),
    ],
)
def test_psi_detects_discrete_and_missingness_shifts(reference, current):
    assert psi(np.array(reference, dtype=float), np.array(current, dtype=float)) > 0.25


@pytest.mark.parametrize("values", [[0] * 100, [0, 1] * 50, list(range(100))])
def test_psi_identical_distributions_are_zero(values):
    assert psi(np.array(values, dtype=float), np.array(values, dtype=float)) == 0


def test_prediction_drift_insufficient_data_is_explicit_and_json_safe():
    result = prediction_drift(np.zeros(100), np.array([]))
    assert result["status"] == "insufficient_data"
    assert result["psi"] is None
    assert result["mean_cur"] is None and result["p90_cur"] is None
    json.dumps(result, allow_nan=False)


def test_feature_drift_reports_unavailable_features():
    ref = pd.DataFrame({"signal": [np.nan] * 100, "absent": [1] * 100})
    result = feature_drift(ref, ref[["signal"]], ["signal", "absent"])
    assert result["status"] == "insufficient_data"
    assert result["n_features"] == 0
    assert {r["feature"] for r in result["insufficient_features"]} == {"signal", "absent"}
    json.dumps(result, allow_nan=False)


def test_prediction_drift_nonfinite_values_are_json_safe():
    result = prediction_drift(np.array([np.nan, np.inf] * 50), np.zeros(100))
    assert result["mean_ref"] is None and result["p90_ref"] is None
    assert result["psi"] > 0.25
    json.dumps(result, allow_nan=False)


def test_reports_expose_missingness_shift_separately():
    reference = np.zeros(100)
    current = np.r_[np.zeros(10), np.full(90, np.nan)]
    predictions = prediction_drift(reference, current)
    features = feature_drift(pd.DataFrame({"x": reference}), pd.DataFrame({"x": current}), ["x"])
    for report in (predictions, features["top"][0]):
        assert report["missing_rate_ref"] == 0
        assert report["missing_rate_cur"] == 0.9
    insufficient = feature_drift(pd.DataFrame({"x": [np.nan]}), pd.DataFrame({"x": [1]}), ["x"])
    assert insufficient["insufficient_features"][0]["missing_rate_ref"] == 1


class SignalClassifier:
    """Deterministic predictor isolates monitoring from model training."""

    fail = False

    def predict_proba(self, rows):
        if self.fail:
            raise RuntimeError("prediction unavailable")
        return rows["signal"].to_numpy(dtype=float)


@pytest.fixture
def monitoring_store(tmp_path, monkeypatch):
    from harbinger.api.store import Store
    from harbinger.config import Settings

    data, models = tmp_path / "data", tmp_path / "models"
    data.mkdir()
    models.mkdir()
    (models / "manifest.json").write_text("{}")
    times = pd.date_range("2024-01-01", periods=200)
    features = pd.DataFrame(
        {
            "t": times,
            "asset_id": "A",
            "site_id": "S",
            "signal": [0] * 100 + [1] * 100,
            "ck_days_since_bad": 0,
            "ck_days_since_caution": 0,
            "st_age_years": 1,
        }
    )
    features.to_parquet(data / "features.parquet")
    tables = {
        "assets": pd.DataFrame({"asset_id": ["A"], "site_id": ["S"], "name": ["Asset"], "zone": ["Z"]}),
        "inspections": pd.DataFrame(
            {
                "asset_id": ["A"],
                "site_id": ["S"],
                "inspector_id": ["I"],
                "performed_at": [times[0]],
                "scheduled_at": [times[0]],
            }
        ),
        "workorders": pd.DataFrame(columns=["asset_id", "site_id", "opened_at", "type"]),
        "sites": pd.DataFrame(),
        "inspectors": pd.DataFrame(),
        "energy": pd.DataFrame(),
    }
    for name, table in tables.items():
        table.to_parquet(data / f"{name}.parquet")
    classifier = SignalClassifier()
    bundle = {"version": "test", "classifier": classifier, "entry": {"features": ["signal"], "metrics": {}}}
    monkeypatch.setattr("harbinger.api.store.load_bundle", lambda path: bundle)
    return Store(Settings(data_dir=data, model_dir=models, demo_bootstrap=False))


def test_load_publishes_drift_before_manual_endpoint_and_caches_it(monitoring_store):
    from harbinger.monitoring.metrics import registry, render

    monitoring_store.load()
    assert registry.get_sample_value("harbinger_drift_alert_features") == 1
    assert registry.get_sample_value("harbinger_drift_status", {"state": "success"}) == 1
    assert registry.get_sample_value("harbinger_drift_last_success_timestamp_seconds") > 0
    monitoring_store.bundle["classifier"].fail = True
    assert monitoring_store.drift()["status"] == "success"
    assert b"harbinger_drift_alert_features 1.0" in render()


def test_prediction_requests_observe_histogram(monitoring_store):
    from harbinger.monitoring.metrics import registry

    monitoring_store.load()
    before = registry.get_sample_value("harbinger_p30_count")
    rows = monitoring_store.latest_rows("S", monitoring_store.data_end)
    assert len(rows) == 1
    assert registry.get_sample_value("harbinger_p30_count") == before + 1


def test_empty_current_window_is_not_replaced_with_reference_predictions(monitoring_store):
    monitoring_store._observation_end = pd.Timestamp("2026-01-01")
    monitoring_store.load()
    result = monitoring_store.drift()
    assert result["status"] == "insufficient_data"
    assert result["predictions"]["mean_cur"] is None
    assert result["predictions"]["psi"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("outcome", ["success", "insufficient_data", "error"])
def test_ingestion_refreshes_drift_state(monitoring_store, monkeypatch, outcome):
    from harbinger.monitoring.metrics import registry

    monitoring_store.load()
    before_success = registry.get_sample_value("harbinger_drift_last_success_timestamp_seconds")
    rebuilt = monitoring_store.X.copy()
    rebuilt["signal"] = 0
    if outcome == "insufficient_data":
        rebuilt = rebuilt.tail(10)
    if outcome == "error":
        # Drift includes old rows; online prediction uses the healthy latest row.
        original = monitoring_store.bundle["classifier"].predict_proba

        def fail_batch(rows):
            if len(rows) > 1:
                raise RuntimeError("batch unavailable")
            return original(rows)

        monkeypatch.setattr(monitoring_store.bundle["classifier"], "predict_proba", fail_batch)
    monkeypatch.setattr("harbinger.api.store.build_features", lambda *args, **kwargs: rebuilt)
    monitoring_store.ingest_inspections(
        "S", [{"asset_id": "A", "performed_at": "2024-07-18", "scheduled_at": "2024-07-18"}]
    )
    assert registry.get_sample_value("harbinger_drift_status", {"state": outcome}) == 1
    result = monitoring_store.drift()
    assert result["status"] == outcome
    json.dumps(result, allow_nan=False)
    if outcome == "success":
        assert registry.get_sample_value("harbinger_drift_alert_features") == 0
    else:
        assert registry.get_sample_value("harbinger_drift_last_success_timestamp_seconds") == before_success


@pytest.mark.parametrize(("cache_version", "model_version"), [(None, None), (2, None), (None, 2)])
def test_shared_inspector_ids_reject_legacy_features_or_model(monitoring_store, cache_version, model_version):
    monitoring_store.load()
    inspections = monitoring_store.tables["inspections"]
    pd.concat([inspections, inspections.assign(site_id="OTHER")]).to_parquet(
        monitoring_store.settings.data_dir / "inspections.parquet"
    )
    (monitoring_store.settings.data_dir / "features_meta.json").write_text(
        json.dumps({"provenance": {"feature_semantics_version": cache_version}})
    )
    monitoring_store.bundle["entry"]["feature_semantics_version"] = model_version
    with pytest.raises(RuntimeError, match="rebuild.*retrain"):
        monitoring_store.load()


def test_shared_inspector_ids_load_corrected_features_and_model(monitoring_store):
    monitoring_store.load()
    inspections = monitoring_store.tables["inspections"]
    pd.concat([inspections, inspections.assign(site_id="OTHER")]).to_parquet(
        monitoring_store.settings.data_dir / "inspections.parquet"
    )
    (monitoring_store.settings.data_dir / "features_meta.json").write_text(
        json.dumps({"provenance": {"feature_semantics_version": 2}})
    )
    monitoring_store.bundle["entry"]["feature_semantics_version"] = 2
    monitoring_store.load()
    assert monitoring_store.drift()["status"] == "success"


@pytest.mark.parametrize("has_observation_metadata", [False, True])
def test_ingestion_updates_drift_without_certifying_failure_followup(
    monitoring_store, monkeypatch, has_observation_metadata
):
    from harbinger.api.analysis import analyze
    from harbinger.api.backtest import last_scorable_day

    monitoring_store.load()
    previous_end = monitoring_store.data_end
    previous_scorable = last_scorable_day(monitoring_store)
    if has_observation_metadata:
        monitoring_store.bundle["entry"]["metrics"]["observation"] = {
            "observation_end": previous_end.isoformat()
        }
    rebuilt = monitoring_store.X.copy()
    rebuilt["t"] += pd.Timedelta(days=365)
    new_end = rebuilt["t"].max()
    monkeypatch.setattr("harbinger.api.store.build_features", lambda *args, **kwargs: rebuilt)
    monitoring_store.ingest_inspections(
        "S", [{"asset_id": "A", "scheduled_at": new_end.isoformat(), "performed_at": new_end.isoformat()}]
    )
    assert monitoring_store.data_end == previous_end
    assert last_scorable_day(monitoring_store) == previous_scorable
    evaluation = analyze(monitoring_store, previous_end)
    assert evaluation["outcomes_observed"] is False
    assert evaluation["evaluation_status"] == "withheld"
    result = monitoring_store.drift()
    assert result["data_as_of"] == new_end.isoformat()
    assert result["features"]["cur_rows"] == 60
