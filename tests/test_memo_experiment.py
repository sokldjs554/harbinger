import copy

import pandas as pd
import pytest


def score(clean=0.25, missing25=0.17, missing50=0.16, brier=0.07):
    return {
        "clean": {"precision_at_k": clean, "brier": brier},
        "missing_25": {"precision_at_k": missing25},
        "missing_50": {"precision_at_k": missing50},
    }


def test_selection_rejects_clean_regression_and_accepts_missing_gain():
    from scripts.memo_robustness import choose_candidate

    metrics = {"legacy": score(), "robust": score(0.245, 0.23, 0.22), "no_memo": score(0.21, 0.24, 0.24)}
    before = copy.deepcopy(metrics)
    assert choose_candidate(metrics)["selected"] == "robust"
    assert metrics == before
    metrics["robust"]["clean"]["brier"] = 0.08
    assert choose_candidate(metrics)["selected"] == "legacy"


def test_selection_handles_missing_condition_and_nonfinite_scores():
    from scripts.memo_robustness import choose_candidate

    for invalid in [float("nan"), float("inf")]:
        metrics = {"legacy": score(), "robust": score(0.25, invalid, 0.23)}
        assert choose_candidate(metrics)["selected"] == "legacy"
    metrics = {"legacy": score(), "robust": score(0.25, 0.24, 0.15)}
    assert choose_candidate(metrics)["selected"] == "legacy"
    metrics["robust"] = {"clean": {"precision_at_k": 0.25, "brier": 0.07}}
    with pytest.raises(ValueError):
        choose_candidate(metrics)


def test_selection_tie_prefers_no_memo_and_does_not_use_extreme_condition():
    from scripts.memo_robustness import choose_candidate

    metrics = {"legacy": score(), "robust": score(0.25, 0.23, 0.23), "no_memo": score(0.25, 0.23, 0.23)}
    metrics["robust"]["missing_100"] = {"precision_at_k": 1.0}
    assert choose_candidate(metrics)["selected"] == "no_memo"


def test_cohort_rejects_mismatched_ids_or_outcomes():
    from scripts.memo_robustness import assert_same_cohort

    frame = pd.DataFrame(
        {"site_id": ["s"], "asset_id": ["a"], "decision_at": [pd.Timestamp("2025-01-01")], "y30": [1]}
    )
    assert_same_cohort(frame, frame.copy())
    for col, value in [("asset_id", "b"), ("y30", 0), ("decision_at", pd.Timestamp("2025-01-02"))]:
        other = frame.copy()
        other[col] = value
        with pytest.raises(AssertionError):
            assert_same_cohort(frame, other)


def test_final_gate_requires_all_runs_and_limits_clean_regression():
    from scripts.memo_summary import adoption_gate

    runs = [
        {"clean_delta": -0.005, "missing_mean_delta": 0.03, "clean_brier": 0.07, "legacy_clean_brier": 0.07}
    ] * 6
    assert adoption_gate(runs)["passed"]
    assert not adoption_gate(runs[:5])["passed"]
    bad = copy.deepcopy(runs)
    bad[0] = dict(bad[0], missing_mean_delta=-0.001)
    assert not adoption_gate(bad)["passed"]
    bad[0] = dict(bad[0], missing_mean_delta=0.03, clean_delta=-0.021)
    assert not adoption_gate(bad)["passed"]


def test_atomic_csv_roundtrip_and_truncated_gzip_detection(tmp_path):
    from scripts.memo_artifacts import verify_gzip, write_csv

    frame = pd.DataFrame({"memo": ["누수, 점검", "", "메모\n두 줄"], "value": [1, 2, 3]})
    target = tmp_path / "rows.csv.gz"
    write_csv(frame, target)
    assert verify_gzip(target) == frame.to_csv(index=False).encode()
    target.write_bytes(target.read_bytes()[:-8])
    with pytest.raises((EOFError, OSError)):
        verify_gzip(target)
