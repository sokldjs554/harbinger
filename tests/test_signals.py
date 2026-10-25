"""Signal intervals must preserve the site sampling unit and report unavailable inference."""

import hashlib
import json
import subprocess
import sys

import pandas as pd
import pytest

from harbinger.eval.signals import signal_tables


def features(outcomes=(0, 0, 0, 1, 1), repeats=10):
    return pd.DataFrame(
        [
            {
                "site_id": f"S{site}",
                "asset_id": f"S{site}-A",
                "inspector_id": f"S{site}-I",
                "label_valid": True,
                "y30": outcome,
                "tx_weak_score": 0,
                "ck_overall": 0,
                "tx_weak_on_good_sum6": 0,
                "q_inspector_lazy_rate": site / 10,
                "q_dwell": 30,
            }
            for site, outcome in enumerate(outcomes)
            for _ in range(repeats)
        ]
    )


def selected(result):
    return result["by_judgement"]["good"]["without_weak"]


def test_site_bootstrap_preserves_repeated_assets_and_inspectors():
    # Five homogeneous sites: resampling intact clusters spans 0 to .8 at 95%.
    # A row bootstrap/Wilson interval would incorrectly tighten with repetitions.
    once = signal_tables(features(repeats=1))
    repeated = signal_tables(features(repeats=100))
    assert selected(once)["lo"] == 0
    assert selected(once)["hi"] == 0.8
    assert selected(repeated)["lo"] == selected(once)["lo"]
    assert selected(repeated)["hi"] == selected(once)["hi"]
    assert selected(repeated)["n_clusters"] == 5
    assert selected(repeated)["n"] == 500
    assert selected(repeated)["rate"] == 0.4
    assert selected(repeated)["ci_status"] == "ok"
    assert repeated["uncertainty"]["method"] == "site_cluster_percentile_bootstrap"
    assert repeated["uncertainty"]["draws"] == 2000
    assert repeated["uncertainty"]["seed"] == 20261025


def test_site_bootstrap_is_deterministic_and_row_order_invariant():
    frame = features()
    first = signal_tables(frame)
    assert first == signal_tables(frame)
    assert first == signal_tables(frame.sample(frac=1, random_state=7))


def test_estimate_is_row_weighted_and_excludes_invalid_labels():
    frame = pd.concat([features(repeats=1), features(repeats=1).iloc[[4]]])
    invalid = features(repeats=1).assign(label_valid=False, y30=1)
    out = signal_tables(pd.concat([frame, invalid], ignore_index=True))
    assert selected(out)["n"] == 6
    assert selected(out)["k"] == 3
    assert selected(out)["rate"] == 0.5
    assert out["base_rate"] == 0.5


@pytest.mark.parametrize("frame", [features(outcomes=(0, 1)), features().iloc[:0]])
def test_insufficient_clusters_withhold_interval_and_never_emit_nan(frame):
    out = signal_tables(frame)
    c = selected(out)
    assert c["lo"] is None and c["hi"] is None
    assert c["ci_status"] in {"insufficient_clusters", "empty"}
    if not len(frame):
        assert out["base_rate"] is None and c["rate"] is None
    json.dumps(out, allow_nan=False)


def test_missing_site_ids_do_not_silently_drop_rows_or_supply_interval():
    frame = features()
    frame.loc[0, "site_id"] = None
    c = selected(signal_tables(frame))
    assert c["n"] == 50 and c["k"] == 20
    assert c["ci_status"] == "missing_cluster_ids"
    assert c["lo"] is None and c["hi"] is None


def test_single_outcome_withholds_falsely_certain_interval():
    c = selected(signal_tables(features(outcomes=(0, 0, 0, 0, 0))))
    assert c["rate"] == 0
    assert c["ci_status"] == "single_outcome"
    assert c["lo"] is None and c["hi"] is None


@pytest.mark.parametrize("bad_label", [None, float("inf"), 0.5, -1])
def test_mature_rows_require_binary_observed_outcomes(bad_label):
    frame = features()
    frame.loc[0, "y30"] = bad_label
    with pytest.raises(ValueError, match="binary"):
        signal_tables(frame)


def test_signal_cli_records_exact_feature_source(tmp_path):
    source = tmp_path / "features.parquet"
    features().to_parquet(source)
    destination = tmp_path / "signals.json"
    subprocess.run(
        [sys.executable, "scripts/make_signals.py", "--data", str(tmp_path), "--out", str(destination)],
        check=True,
    )
    report = json.loads(destination.read_text())
    assert report["source"]["features_path"] == str(source.resolve())
    assert report["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["source"]["n_source_rows"] == 50
    assert report["source"]["bytes"] == source.stat().st_size
