"""Integration boundaries: pooled eligibility and legacy report provenance."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from harbinger.api.backtest import replay, replay_site
from harbinger.api.routers.report import build_report, to_markdown
from harbinger.api.store import Store
from harbinger.models.classify import train_logistic


@pytest.mark.parametrize("site_order", [["S1", "S2"], ["S2", "S1"]])
def test_pooled_replay_requires_every_contributing_site_to_be_held_out(site_order):
    rows = pd.DataFrame(
        [
            {
                "site_id": site,
                "asset_id": f"{site}-{i}",
                "name": f"{site}-{i}",
                "t": pd.Timestamp("2025-08-31"),
                "category": "pump",
                "zone": "A",
                "st_floor": 1,
                "st_criticality": 1,
                "p30": 0.1,
                "ck_overall": 0,
                "policy_test_start": "2025-10-01" if site == "S2" else None,
            }
            for site in site_order
            for i in range(5)
        ]
    )
    store = SimpleNamespace(
        X=rows,
        data_end=pd.Timestamp("2025-12-31"),
        latest_rows=lambda site, as_of: rows[rows.site_id == site].copy(),
        tables={
            "sites": pd.DataFrame({"site_id": site_order}),
            "workorders": pd.DataFrame(
                {"asset_id": ["S1-0", "S2-0"], "type": "breakdown", "opened_at": pd.Timestamp("2025-09-10")}
            ),
        },
        bundle={
            "entry": {"metrics": {"observation": {"boundary_version": 2, "max_observed_at": "2025-07-01"}}}
        },
    )
    date = pd.Timestamp("2025-09-01")
    assert replay_site(store, "S1", date, date, k=2)["weeks"][0]["held_out"] is True
    assert replay_site(store, "S2", date, date, k=2)["weeks"][0]["held_out"] is False
    pooled = replay(store, "all", date, date, k=2)
    assert pooled["weeks"][0]["n_assets"] == 10  # Preserve the actual comparison denominator.
    assert pooled["weeks"][0]["held_out"] is False
    assert pooled["evaluation_status"] == "withheld"
    assert pooled["excluded_weeks"] == 1
    assert pooled["summary"]["weeks"] == 0
    assert pooled["summary"]["harbinger_rate"] is None
    later = pd.Timestamp("2025-11-01")
    assert replay(store, "all", later, later, k=2)["evaluation_status"] == "available"


def report_store(selected):
    frame = pd.DataFrame(
        {
            "x": np.tile([0.0, 1.0], 20),
            "y30": np.tile([0, 1], 20),
            "st_category": "pump",
            "st_archetype": "office",
        }
    )
    model = train_logistic(frame, frame.iloc[:0], ["x"])
    trace = {
        "selected_model": selected,
        "policy_revision": "a" * 64 if selected != "baseline" else None,
        "policy_reason": "validation_brier" if selected != "baseline" else "no_policy",
        "policy_test_start": "2027-01-01" if selected != "baseline" else None,
    }
    rows = (
        frame.iloc[:2]
        .copy()
        .assign(
            asset_id=["S1-a", "S1-b"],
            name=["A", "B"],
            category="pump",
            st_criticality=1,
            ck_overall=0,
            t=pd.Timestamp("2026-10-01"),
            **trace,
        )
    )
    rows["p30"] = model.predict_proba(rows)
    summary = {
        "site_id": "S1",
        "name": "Site 1",
        "n_assets": 2,
        "n_inspectors": 1,
        "breakdowns_90d": 0,
        "downtime_hours_90d": 0,
        "mean_p30": float(rows.p30.mean()),
        "n_high_risk(p30>=0.15)": int((rows.p30 >= 0.15).sum()),
    }
    return SimpleNamespace(
        latest_rows=lambda *a, **kw: rows.copy(),
        site_summary=lambda *a: summary,
        patrol=lambda *a, **kw: {
            "k": 2,
            "items": [],
            "expected_breakdowns_in_list": float(rows.p30.sum()),
            "expected_breakdowns_round_robin": float(rows.p30.sum()),
            **trace,
        },
        schedule=lambda *a: [],
        energy_anomalies=lambda *a: {},
        quality=lambda *a: {},
        routing_trace=Store.routing_trace,
        model_for=lambda *a: (model, trace),
        bundle={"version": "v1", "entry": {"metrics": {"headline": {"auroc": 0.88}}}},
    )


def test_legacy_report_identifies_selected_model_and_withholds_baseline_headline():
    store = report_store("logistic")
    result = build_report(store, "S1", pd.Timestamp("2026-10-25"))
    assert result["model"]["selected_model"] == "logistic"
    assert result["model"]["policy_revision"] == "a" * 64
    assert result["model"]["policy_reason"] == "validation_brier"
    assert result["model"]["policy_test_start"] == "2027-01-01"
    assert result["model"]["headline"] is None
    assert result["model"]["headline_status"] == "withheld_for_selected_model"
    assert result["model"]["baseline_reference"]["headline"] == {"auroc": 0.88}
    assert result["model"]["baseline_reference"]["scope"] == "stored_bundle_baseline_reference"
    for asset in result["top_risk_assets"]:
        assert asset["selected_model"] == "logistic"
        assert asset["policy_revision"] == "a" * 64
    markdown = to_markdown(result)
    for value in ["logistic", "a" * 64, "validation_brier", "2027-01-01"]:
        assert value in markdown
    assert "기본 모델의 저장된 참조 지표" in markdown
    assert "현재 사이트의 선택 모델 평가가 아닙니다" in markdown


def test_legacy_baseline_report_preserves_headline_with_explicit_reference_scope():
    result = build_report(report_store("baseline"), "S1", pd.Timestamp("2026-10-25"))
    assert result["model"]["headline"] == {"auroc": 0.88}
    assert result["model"]["headline_scope"] == "stored_bundle_baseline_reference"
    assert result["model"]["selected_model"] == "baseline"
    assert result["model"]["policy_revision"] is None
    assert "baseline" in to_markdown(result)
