from types import SimpleNamespace

import pandas as pd
import pytest

from harbinger.api.analysis import analyze
from harbinger.api.backtest import replay


def test_random_comparator_uses_same_per_customer_budget():
    ids = [f"a{i}" for i in range(12)]
    rows = pd.DataFrame(
        {
            "asset_id": ids,
            "site_id": ["small"] * 3 + ["large"] * 9,
            "t": pd.Timestamp("2025-08-30"),
            "p30": 0.1,
            "name": ids,
            "category": "pump",
            "memo": "",
            "ck_overall": 0,
            "st_age_years": 5.0,
            "wo_days_since_bd": 100.0,
            "wo_bd_90d": 0,
        }
    )
    wo = pd.DataFrame({"asset_id": ids[:3], "type": "breakdown", "opened_at": pd.Timestamp("2025-09-10")})
    store = SimpleNamespace(
        latest_rows=lambda *a, **kw: rows.copy(),
        data_end=pd.Timestamp("2025-11-01"),
        tables={"workorders": wo},
        bundle={
            "version": "test",
            "comparators": {},
            "entry": {"metrics": {"observation": {"boundary_version": 2, "max_observed_at": "2025-07-01"}}},
        },
    )
    result = analyze(store, pd.Timestamp("2025-09-01"), k=1)
    unconfirmed = analyze(store, pd.Timestamp("2025-09-01"), k=1, observation_confirmed=False)
    assert result["evaluation_status"] == "available"
    assert unconfirmed["evaluation_status"] == "withheld"
    assert all(m["metrics"] == {} and m["precision_at_k"] is None for m in unconfirmed["comparisons"])
    assert all(a["failed_within_30d"] is None for a in unconfirmed["assets"])
    row = next(r for r in result["comparisons"] if r["method"] == "random_expectation")
    assert row["precision_at_k"] == 0.5  # 1 random pick from each site, not from pooled assets
    current = next(r for r in result["comparisons"] if r["method"] == "current_model")
    # Equal scores still need exact selected identities so the UI can show the
    # same outcomes as the metric, rather than independently breaking ties.
    assert sorted(current["selected_asset_ids"]) == ["a0", "a3"]


@pytest.mark.parametrize(
    "cutoff, flags", [(None, [False, False]), ("2025-07-01", [False, False]), ("2025-07-01", [False, True])]
)
def test_replay_summary_excludes_nonheldout_weeks(monkeypatch, cutoff, flags):
    weeks = [
        {
            "as_of": f"2025-07-0{i + 1}",
            "held_out": flag,
            "n_assets": 10,
            "base_rate": 0.2,
            "harbinger": {"n": 2, "hits": 1},
            "round_robin": {"n": 2, "hits": 0},
        }
        for i, flag in enumerate(flags)
    ]
    monkeypatch.setattr(
        "harbinger.api.backtest.replay_site", lambda *a, **kw: {"weeks": weeks, "summary": {}}
    )
    store = SimpleNamespace(
        X=pd.DataFrame({"t": [pd.Timestamp("2025-01-01")]}),
        data_end=pd.Timestamp("2025-10-01"),
        bundle={"entry": {"metrics": {"observation": {"boundary_version": 2, "max_observed_at": cutoff}}}},
    )
    result = replay(store, "S01", None, None)
    assert result["summary"]["weeks"] == sum(flags)
    if not any(flags):
        assert result["evaluation_status"] == "withheld"
        assert result["summary"]["harbinger_rate"] is None
        assert result["summary"]["lift_vs_base"] is None
    else:
        assert result["summary"]["harbinger_picks"] == 2
