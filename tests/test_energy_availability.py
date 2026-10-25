"""Energy unknowns must survive API/report serialization and range selection."""

import numpy as np
import pandas as pd

from harbinger.api.store import Store
from harbinger.config import Settings
from harbinger.models.energy import EnergyBundle


class ConstantEnergy:
    def predict(self, design):
        return np.full(len(design), 100.0)


def store(n=45, model=True):
    s = Store(Settings(demo_bootstrap=False))
    s.bundle = {"energy": EnergyBundle(ConstantEnergy(), {"S": 0}, {"S": 0.1}) if model else None}
    s.tables = {
        "energy": pd.DataFrame(
            {
                "site_id": ["S"] * n,
                "day": pd.date_range("2024-01-01", periods=n),
                "electricity_kwh": [100.0] * max(0, n - 6) + [150.0] * min(6, n),
                "temp_mean_c": [20.0] * n,
                "occupancy_index": [1.0] * n,
            }
        )
    }
    return s


def test_absent_energy_is_not_zero_anomalies():
    result = store(0).energy_anomalies("S", pd.Timestamp("2024-02-14"), 30)
    assert result.get("status") == "no_data"
    assert result["n_anomaly_days"] is None
    assert result["n_observed_days"] == result["n_evaluable_days"] == 0


def test_short_history_is_unknown_not_normal():
    result = store(2).energy_anomalies("S", pd.Timestamp("2024-01-02"), 30)
    assert all(d["anomaly"] is None for d in result["days"])
    assert result["status"] == "insufficient_observation"
    assert result["n_anomaly_days"] is None
    assert result["n_observed_days"] == 2
    assert result["n_evaluable_days"] == 0


def test_window_overlap_and_future_invariance():
    s = store()
    as_of = pd.Timestamp("2024-02-14")
    short = s.energy_anomalies("S", as_of, 14)
    long = s.energy_anomalies("S", as_of, 30)
    by_day = {d["day"]: d for d in long["days"]}
    assert short["days"] == [by_day[d["day"]] for d in short["days"]]
    before = s.energy_anomalies("S", pd.Timestamp("2024-02-01"), 30)
    s.tables["energy"].loc[s.tables["energy"].day > "2024-02-01", "electricity_kwh"] = 1e9
    assert before == s.energy_anomalies("S", pd.Timestamp("2024-02-01"), 30)
    assert short["n_anomaly_days"] > 0
    assert short["n_evaluable_days"] == 14


def test_missing_model_retains_observed_values():
    result = store(10, model=False).energy_anomalies("S", pd.Timestamp("2024-02-14"), 90)
    assert result.get("status") == "no_model"
    assert len(result["days"]) == result["n_observed_days"] == 10
    assert all(d["expected"] is None and d["anomaly"] is None for d in result["days"])


def test_unseen_site_has_no_future_derived_calibration():
    s = store()
    s.bundle["energy"].resid_sigma = {}
    result = s.energy_anomalies("S", pd.Timestamp("2024-02-14"), 30)
    assert result.get("status") == "no_model"
    assert all(d["anomaly"] is None for d in result["days"])


def test_calendar_gap_does_not_reuse_stale_observations():
    s = store(5)
    s.tables["energy"].loc[3:, "day"] += pd.Timedelta(days=30)
    result = s.energy_anomalies("S", pd.Timestamp("2024-02-04"), 14)
    assert result["n_observed_days"] == 2
    assert result["n_evaluable_days"] == 0
    assert result["n_anomaly_days"] is None


def test_energy_api_json_and_markdown_agree_when_data_absent(client):
    from harbinger.api.main import app

    s = app.state.store
    original = s.tables["energy"]
    site = s.tables["sites"].iloc[0].site_id
    try:
        s.tables["energy"] = original.iloc[:0]
        api = client.get(f"/v1/sites/{site}/energy/anomalies?days=90").json()
        report = client.get(f"/v1/sites/{site}/report").json()["energy"]
        md = client.get(f"/v1/sites/{site}/report?format=md").text
        assert api["status"] == report["status"] == "no_data"
        assert api["n_anomaly_days"] is report["n_anomaly_days_90d"] is None
        assert "관측 0일 · 판정 가능 0일 · 이상 여부 판정 보류" in md
        assert "이상일 0일" not in md
    finally:
        s.tables["energy"] = original


def test_missing_current_reading_cannot_inherit_prior_verdict():
    import json

    s = store(8)
    s.tables["energy"].loc[7, "electricity_kwh"] = np.nan
    result = s.energy_anomalies("S", pd.Timestamp("2024-01-08"), 1)
    assert result["days"][0]["anomaly"] is None
    assert result["days"][0]["status"] == "insufficient_observation"
    assert result["n_observed_days"] == result["n_evaluable_days"] == 0
    assert result["n_anomaly_days"] is None
    json.dumps(result, allow_nan=False)
    s.bundle["energy"] = None
    result = s.energy_anomalies("S", pd.Timestamp("2024-01-08"), 1)
    assert result["days"][0]["actual"] is None
    json.dumps(result, allow_nan=False)
