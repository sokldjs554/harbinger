import numpy as np
import pandas as pd
import pytest

from harbinger.models import site_policy as policy
from tests.test_site_policy import candidate as candidate  # noqa: F401


def test_single_inspection_window_cannot_select(candidate):
    from tests.test_site_policy import propose

    root, bundle, frame = candidate
    frame = frame[frame.t == frame.t.min()].copy()
    assert propose((root, bundle, frame))["sites"]["S1"]["model"] == "baseline"


def test_contract_cannot_be_weakened(candidate):
    from tests.test_site_policy import propose

    with pytest.raises(ValueError, match="fixed"):
        propose(candidate, min_rows=2)


def test_better_brier_harmful_ranking_rejected():
    from harbinger.models.policy_evaluation import evaluate

    rows = pd.DataFrame(
        [
            {"site_id": "S", "asset_id": str(i), "t": t, "y30": int(i < 10)}
            for t in pd.date_range("2024-01-01", periods=4, freq="30D")
            for i in range(60)
        ]
    )
    y = rows.y30.to_numpy()
    result = evaluate(
        rows,
        {"baseline": np.where(y, 0.9, 0.8), "logistic": np.where(y, 0.1, 0.11)},
        ["S"],
        pd.date_range("2024-01-01", periods=4, freq="30D"),
        50,
        3,
        0.001,
    )
    assert result["sites"]["S"]["model"] == "baseline"
    assert "precision_not_improved" in result["scores"]["S"]["candidates"]["logistic"]["reasons"]


def test_snapshot_preserves_inspection_time_refreshes_and_relabels():
    from harbinger.models.policy_evaluation import snapshots

    inspection = pd.Timestamp("2024-01-01")
    date = pd.Timestamp("2024-02-01")
    frame = pd.DataFrame(
        [
            dict(
                asset_id="a",
                site_id="S",
                t=inspection,
                y30=0,
                label_valid=True,
                ck_days_since_bad=2.0,
                ck_days_since_caution=3.0,
                st_age_years=5.0,
            )
        ]
    )
    tables = {
        "assets": pd.DataFrame([dict(asset_id="a", site_id="S"), dict(asset_id="b", site_id="missing")]),
        "inspections": pd.DataFrame([dict(asset_id="a", performed_at=inspection)]),
        "workorders": pd.DataFrame(
            [
                dict(asset_id="a", site_id="S", type="breakdown", opened_at=t)
                for t in [date - pd.Timedelta(days=1), date, date + pd.Timedelta(days=30)]
            ]
        ),
    }
    rows, sites, _ = snapshots(frame, tables, date, date)
    assert rows.iloc[0].inspection_t == inspection
    assert rows.iloc[0].t == date
    assert rows.iloc[0].ck_days_since_bad == 33
    assert rows.iloc[0].wo_bd_total == 1
    assert rows.iloc[0].y30 == 1
    tables["workorders"] = tables["workorders"].iloc[:2]
    assert snapshots(frame, tables, date, date)[0].iloc[0].y30 == 0
    assert "missing" in sites
    assert snapshots(frame, tables, date + pd.Timedelta(days=121), date + pd.Timedelta(days=121))[0].empty


def test_schema_one_fails_closed_and_fixed_contract_is_validated(candidate):
    import copy

    from tests.test_site_policy import propose

    root, bundle, _ = candidate
    proposal = propose(candidate)
    old = copy.deepcopy(proposal)
    old["schema"] = 1
    with pytest.raises(ValueError):
        policy.validate(root, bundle, old)


def test_missing_site_date_grid_is_explicit():
    from harbinger.models.policy_evaluation import evaluate

    dates = pd.date_range("2024-01-01", periods=4, freq="30D")
    rows = pd.DataFrame(columns=["site_id", "asset_id", "t", "y30"])
    result = evaluate(rows, {"baseline": np.array([]), "logistic": np.array([])}, ["missing"], dates)
    assert len(result["scores"]["missing"]["dates"]) == 4
    assert all(d["assets"] == 0 for d in result["scores"]["missing"]["dates"])
    assert result["sites"]["missing"]["model"] == "baseline"


def test_asset_history_draws_with_undersized_dates_fail_conservatively():
    from harbinger.models.policy_evaluation import evaluate

    dates = pd.date_range("2024-01-01", periods=4, freq="30D")
    rows = pd.DataFrame(
        [
            dict(site_id="S", asset_id=f"{j}-{i}", t=t, y30=i % 2)
            for j, t in enumerate(dates)
            for i in range(10)
        ]
    )
    y = rows.y30.to_numpy()
    result = evaluate(rows, {"baseline": 1 - y * 0.8, "logistic": y * 0.8}, ["S"], dates, min_rows=10)
    candidate = result["scores"]["S"]["candidates"]["logistic"]
    assert candidate["invalid_asset_replicates"] > 0
    assert candidate["asset_lower"] is None
    assert "undersized_asset_bootstrap" in candidate["reasons"]
    assert result["sites"]["S"]["model"] == "baseline"


def test_cached_decision_still_checks_files_contract_and_current_time(candidate, monkeypatch):
    import copy

    from tests.test_site_policy import propose

    root, bundle, _ = candidate
    proposal = propose(candidate)
    policy._cached_decision.cache_clear()
    policy.validate(root, bundle, proposal)
    policy.validate(root, bundle, proposal)
    assert policy._cached_decision.cache_info().hits == 1
    assert policy._cached_decision.cache_info().maxsize == 16
    changed = copy.deepcopy(proposal)
    changed["contract"]["budget"] = 1
    with pytest.raises(ValueError):
        policy.validate(root, bundle, changed)
    monkeypatch.setattr(policy, "_now", lambda: "2024-01-01")
    with pytest.raises(ValueError, match="chronology"):
        policy.validate(root, bundle, proposal)
    monkeypatch.undo()
    evidence = root / "site-policy-evidence" / (proposal["evidence_sha256"] + ".json")
    original = evidence.read_bytes()
    evidence.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="evidence hash"):
        policy.validate(root, bundle, proposal)
    evidence.write_bytes(original)
    (root / "v1" / "classifier.joblib").write_text("changed")
    with pytest.raises(ValueError, match="bundle hash"):
        policy.validate(root, bundle, proposal)


def test_all_stale_snapshots_preserve_eligibility_evidence(candidate):
    import json

    from tests.test_site_policy import propose

    root, bundle, frame = candidate
    old = frame.assign(t=pd.Timestamp("2023-01-01"))
    assets = old[["site_id", "asset_id"]].drop_duplicates()
    tables = {
        "assets": assets,
        "inspections": assets.assign(performed_at=pd.Timestamp("2023-01-01")),
        "workorders": pd.DataFrame(
            {
                "site_id": pd.Series(dtype=str),
                "asset_id": pd.Series(dtype=str),
                "type": pd.Series(dtype=str),
                "opened_at": pd.Series(dtype="datetime64[ns]"),
            }
        ),
    }
    proposal = propose((root, bundle, old), tables=tables)
    evidence = json.loads(
        (root / "site-policy-evidence" / (proposal["evidence_sha256"] + ".json")).read_text()
    )
    assert len(evidence["grid"]) == 4
    assert all(d["stale_assets"] == 80 for d in evidence["scores"]["S1"]["dates"])
    assert proposal["sites"]["S1"]["model"] == "baseline"
    policy.validate(root, bundle, proposal)
