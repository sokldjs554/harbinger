"""The online comparison must apply the same mandatory inclusion and report overflow."""

from types import SimpleNamespace

import pandas as pd
import pytest

from harbinger.api.store import Store


def test_online_patrol_reports_actual_budget_and_fair_round_robin():
    today = pd.Timestamp("2025-06-01")
    rows = pd.DataFrame(
        {
            "asset_id": ["m1", "m2", "m3", "old"],
            "name": ["m1", "m2", "m3", "old"],
            "category": ["elevator"] * 3 + ["pump"],
            "zone": ["A"] * 4,
            "st_floor": [1] * 4,
            "st_criticality": [1] * 4,
            "t": [today - pd.Timedelta(days=30)] * 3 + [today - pd.Timedelta(days=110)],
            "p30": [0.1, 0.2, 0.3, 0.9],
            "ck_overall": [0] * 4,
            "memo": [""] * 4,
        }
    )
    store = SimpleNamespace(
        latest_rows=lambda *args: rows, routing_trace=lambda row: {}, bundle={"version": "test"}
    )
    result = Store.patrol(store, "S01", today, k=2, explain=False)
    assert result["requested_k"] == 2
    assert result["selected_count"] == 3
    assert result["mandatory_count"] == 3
    assert result["budget_overflow"] == 1
    assert result["round_robin_selected_count"] == 3
    assert result["expected_breakdowns_round_robin"] == pytest.approx(0.6)
    assert {r["asset_id"] for r in result["items"]} == {"m1", "m2", "m3"}


def test_empty_online_patrol_reports_zero_selection_with_requested_budget():
    store = SimpleNamespace(latest_rows=lambda *args: pd.DataFrame())
    result = Store.patrol(store, "S01", pd.Timestamp("2025-06-01"), k=2, explain=False)
    assert result["requested_k"] == 2
    assert result["selected_count"] == result["mandatory_count"] == result["budget_overflow"] == 0
    assert result["round_robin_selected_count"] == 0
