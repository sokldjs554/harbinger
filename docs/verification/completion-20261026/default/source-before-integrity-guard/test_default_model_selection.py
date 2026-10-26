"""Predeclared validation-only default selection; no test-driven gate changes."""

import copy

import numpy as np
import pandas as pd
import pytest


def validation_runs(gain=0.03):
    rows = []
    for world in (202610261, 202610262, 202610263):
        for seed in (17, 29):
            base = {
                "auroc": 0.72,
                "pr_auc": 0.24,
                "brier": 0.07,
                "precision_at_k": 0.2,
                "per_site_precision": {f"S{i}": 0.2 for i in range(5)},
            }
            candidate = {
                "auroc": 0.73,
                "pr_auc": 0.25,
                "brier": 0.069,
                "precision_at_k": 0.2 + gain,
                "per_site_precision": {f"S{i}": 0.2 + gain for i in range(5)},
            }
            rows.append(
                {
                    "data_seed": world,
                    "model_seed": seed,
                    "phase": "validation",
                    "models": {"full": base, "no_memo": candidate},
                }
            )
    return rows


def test_eligible_candidate_is_selected_without_test_scores():
    from scripts.default_model_selection import choose_default

    rows = validation_runs()
    original = copy.deepcopy(rows)
    choice = choose_default(rows)
    assert choice["selected"] == "no_memo"
    assert choice["criteria"]["paired_precision_ci_positive"]
    assert choice["precision_delta_ci95"][0] > 0
    assert rows == original


@pytest.mark.parametrize(
    "reason", ["budget_regression", "probability_regression", "unstable", "discrimination", "missing", "nan"]
)
def test_insufficient_or_worse_evidence_keeps_default(reason):
    from scripts.default_model_selection import choose_default

    rows = validation_runs()
    c = rows[0]["models"]["no_memo"]
    if reason == "budget_regression":
        c["precision_at_k"] = 0.19
        c["per_site_precision"] = {s: 0.19 for s in c["per_site_precision"]}
    elif reason == "probability_regression":
        c["brier"] = 0.071
    elif reason == "unstable":
        rows = validation_runs(0)
    elif reason == "discrimination":
        for r in rows:
            r["models"]["no_memo"]["pr_auc"] = 0.23
    elif reason == "missing":
        rows.pop()
    else:
        c["brier"] = np.nan
    choice = choose_default(rows)
    assert choice["selected"] == "full"
    assert choice["reasons"]


def test_test_phase_or_mismatched_sites_are_rejected():
    from scripts.default_model_selection import choose_default

    rows = validation_runs()
    rows[0]["phase"] = "test"
    with pytest.raises(ValueError, match="validation"):
        choose_default(rows)
    rows = validation_runs()
    rows[0]["models"]["no_memo"]["per_site_precision"].pop("S0")
    with pytest.raises(ValueError, match="sites"):
        choose_default(rows)


def test_default_score_uses_site_equal_day_means_and_stable_budget():
    from scripts.default_model_selection import snapshot_metrics

    frame = pd.DataFrame(
        {
            "site_id": ["A"] * 3 + ["B"],
            "asset_id": ["a"] * 3 + ["b"],
            "decision_at": pd.to_datetime(["2025-01-01", "2025-01-08", "2025-01-15", "2025-01-01"]),
            "y30": [0, 0, 0, 1],
        }
    )
    score = snapshot_metrics(frame, np.full(4, 0.5))
    assert score["precision_at_k"] == 0.5
    assert score["per_site_precision"] == {"A": 0.0, "B": 1.0}
    assert score["selected"] == 4


def test_test_scoring_requires_frozen_selection_and_unchanged_validation(tmp_path):
    from scripts.default_model_selection import verify_freeze

    with pytest.raises(ValueError, match="frozen"):
        verify_freeze(tmp_path)


def test_freeze_preserves_validation_hashes_and_rejects_prior_test(tmp_path, monkeypatch):
    import argparse
    import json

    import scripts.default_model_selection as module

    design = tmp_path / "design.md"
    design.write_text("frozen criteria")
    monkeypatch.setattr(module, "DESIGN", design)
    for row in validation_runs():
        path = tmp_path / str(row["data_seed"]) / f"model-{row['model_seed']}" / "validation/run.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(row))
    prior_test = tmp_path / "202610261/model-17/test"
    prior_test.mkdir()
    (prior_test / "predictions.npz").write_bytes(b"already inspected")
    with pytest.raises(ValueError, match="test"):
        module.freeze(argparse.Namespace(out=tmp_path))
    (prior_test / "predictions.npz").unlink()
    prior_test.rmdir()
    module.freeze(argparse.Namespace(out=tmp_path))
    assert module.verify_freeze(tmp_path)["selected"] == "no_memo"
    path.write_text("{}")
    with pytest.raises(ValueError, match="validation evidence changed"):
        module.verify_freeze(tmp_path)
