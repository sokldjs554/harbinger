#!/usr/bin/env python3
"""Read-only audit of frozen-model patrol selection and aggregation.

Example:
  OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 python scripts/check_patrol_evaluation.py \
    --runtime /tmp/hb-requirements-after --output /workspace/harbinger-runs/completion-20261026/patrol/actual
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from harbinger.api.store import Store
from harbinger.config import HORIZON_DAYS, Settings
from harbinger.eval.patrol import simulate_patrol, summarize_patrol_rows
from harbinger.features.build import FEATURE_GROUPS
from harbinger.models.common import model_columns


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def mature_window(calibration_cutoff, observation_end):
    """Use explicit NumPy units and return pandas timestamps for the schedule."""
    horizon = np.timedelta64(HORIZON_DAYS, "D")
    return (
        pd.Timestamp(pd.Timestamp(calibration_cutoff).to_datetime64() + horizon),
        pd.Timestamp(pd.Timestamp(observation_end).to_datetime64() - horizon),
    )


def uneven_panel(rows: pd.DataFrame) -> pd.DataFrame:
    """Keep date indices divisible by 1 + first-eight SHA256(site_id) mod 4.

    The rule is fixed independently of scores, labels, selection or outcomes;
    every comparator retains precisely the same site/date rows.
    """
    retain = set()
    for site, group in rows.groupby("site_id"):
        stride = 1 + int(hashlib.sha256(str(site).encode()).hexdigest()[:8], 16) % 4
        for day in sorted(group.day.unique())[::stride]:
            retain.add((site, day))
    keys = pd.MultiIndex.from_frame(rows[["site_id", "day"]])
    return rows.loc[keys.isin(retain)].copy()


def estimator_checks(rows: pd.DataFrame, summary: dict, *, seed: int, service: bool) -> dict:
    """Recompute point and bootstrap independently from the saved site/day rows."""
    checks = {}
    metric = "selection_hit_rate" if service else "precision_at_k"
    for name, group in rows.groupby("method", sort=True):
        per_site = group.groupby("site_id", sort=True).precision.mean().to_numpy()
        draws = np.random.default_rng(seed).integers(0, len(per_site), size=(2000, len(per_site)))
        ci = np.quantile(per_site[draws].mean(axis=1), [0.025, 0.975])
        result = summary["methods"][name]
        assert np.isclose(result[metric], per_site.mean(), rtol=0, atol=1e-14)
        assert np.allclose(result["site_cluster_ci95"], ci, rtol=0, atol=1e-14)
        old = float(group.precision.mean())
        assert np.isclose(result[f"historical_date_weighted_{metric}"], old, rtol=0, atol=1e-14)
        checks[name] = dict(
            old_date_weighted=old,
            site_equal=float(per_site.mean()),
            difference=float(per_site.mean() - old),
            site_cluster_ci95=ci.tolist(),
            independently_recomputed=True,
        )
    return checks


def persist_scenario(output: Path, name: str, result: dict, seed: int) -> dict:
    """Keep row membership compressed; summaries contain only aggregates and hashes."""
    rows = pd.DataFrame(result["rows"])
    service = pd.DataFrame(result["service_policy"]["rows"])
    for frame in (rows, service):
        for _, group in frame.groupby(["site_id", "day"]):
            assert group.candidate_asset_ids.map(tuple).nunique() == 1
            assert group.mandatory_asset_ids.map(tuple).nunique() == 1
            assert group.requested_k.nunique() == 1
        if frame is service:
            assert (
                frame.picks
                == frame.requested_k.clip(upper=frame.candidate_asset_ids.map(len)).where(
                    frame.mandatory_count <= frame.requested_k, frame.mandatory_count
                )
            ).all()
            assert (frame.overflow == (frame.picks - frame.requested_k).clip(lower=0)).all()
    compressed = output / f"{name}.json.gz"
    with compressed.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            stream.write(
                json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            )
    # Verify the actual saved observations, rather than only the pre-write objects.
    with gzip.open(compressed, "rt") as stream:
        saved = json.load(stream)
    summary = {
        key: value for key, value in saved.items() if key not in {"rows", "snapshots", "service_policy"}
    }
    summary["service_policy"] = {
        key: value for key, value in saved["service_policy"].items() if key != "rows"
    }
    summary["estimator_checks"] = dict(
        raw=estimator_checks(pd.DataFrame(saved["rows"]), summary, seed=seed, service=False),
        service=estimator_checks(
            pd.DataFrame(saved["service_policy"]["rows"]), summary["service_policy"], seed=seed, service=True
        ),
    )
    summary["site_date_counts"] = rows.drop_duplicates(["site_id", "day"]).groupby("site_id").size().to_dict()
    summary["membership_artifact"] = dict(path=str(compressed), sha256=sha256(compressed))
    return summary


def run(runtime: Path, output: Path, threads: int = 2) -> dict:
    runtime, output = runtime.resolve(), output.resolve()
    if output == runtime or runtime in output.parents:
        raise ValueError("Evidence output must be outside the read-only source runtime")
    output.mkdir(parents=True, exist_ok=True)
    source_files = sorted(p for p in runtime.rglob("*") if p.is_file())
    before = {str(p.relative_to(runtime)): sha256(p) for p in source_files}
    old_metrics = json.loads((runtime / "artifacts/metrics.json").read_text())
    old_patrol = json.loads((runtime / "artifacts/patrol.json").read_text())
    store = Store(
        Settings(
            data_dir=runtime / "data",
            model_dir=runtime / "models",
            artifact_dir=runtime / "artifacts",
            demo_bootstrap=False,
        )
    )
    store.load()
    bundle, X, tables = store.bundle, store.X, store.tables
    models = {"harbinger_hgb": bundle["classifier"], **bundle["comparators"]}
    no_memo = model_columns(X, tuple(group for group in FEATURE_GROUPS if group != "tx"))
    assert models["without_text"].features == no_memo, (
        "Saved without_text must match the corrected no-memo definition"
    )
    scores = {name: model.predict_proba for name, model in models.items()}
    seed = int(old_metrics["seed"])
    val_end = pd.Timestamp(old_metrics["observation"]["calibration_cutoff"])
    observed_end = pd.Timestamp(old_metrics["observation"]["observation_end"])
    test = X.loc[X.t >= val_end]
    bd = tables["workorders"].loc[tables["workorders"].type == "breakdown"]
    options = dict(
        score_fns=scores,
        breakdowns=bd,
        refresher=store.refresher,
        assets=tables["assets"],
        k=10,
        step_days=7,
        seed=seed,
    )
    print("Evaluating original test-only history and original date schedule", flush=True)
    historical = simulate_patrol(test, **options)
    dates = sorted({row["day"] for row in historical["rows"]})
    scenarios = {"historical_test_only": persist_scenario(output, "historical_test_only", historical, seed)}
    print("Evaluating full history on exactly the same dates", flush=True)
    full_matched = simulate_patrol(X, evaluation_days=dates, **options)
    scenarios["full_history_same_dates"] = persist_scenario(
        output, "full_history_same_dates", full_matched, seed
    )
    requested_start, requested_end = mature_window(val_end, observed_end)
    requested_dates = pd.date_range(requested_start, requested_end, freq="7D")
    if dates == [day.isoformat() for day in requested_dates]:
        full_service = full_matched
    else:
        print("Evaluating full history on explicitly mature service dates", flush=True)
        full_service = simulate_patrol(X, evaluation_days=requested_dates, **options)
    scenarios["full_history_service_window"] = persist_scenario(
        output, "full_history_service_window", full_service, seed
    )
    unequal_rows = uneven_panel(pd.DataFrame(historical["rows"]))
    unequal_service = uneven_panel(pd.DataFrame(historical["service_policy"]["rows"]))
    unequal = summarize_patrol_rows(unequal_rows, seed=seed)
    unequal["rows"] = unequal_rows.to_dict("records")
    unequal["service_policy"] = summarize_patrol_rows(unequal_service, seed=seed, service_policy=True)
    unequal["service_policy"]["rows"] = unequal_service.to_dict("records")
    unequal["restriction"] = (
        "Retain sorted site-date indices 0,stride,2*stride,... where stride=1+int(SHA256(site_id)[:8],16)%4; no outcomes used"
    )
    scenarios["historical_unequal_dates"] = persist_scenario(
        output, "historical_unequal_dates", unequal, seed
    )
    parity = []
    selected_rows = pd.DataFrame(full_service["service_policy"]["rows"])
    all_dates = sorted(selected_rows.day.unique())
    sites = sorted(selected_rows.site_id.unique())
    for day in [all_dates[0], all_dates[len(all_dates) // 2], all_dates[-1]]:
        for site in [sites[0], sites[len(sites) // 2], sites[-1]]:
            live = store.patrol(site, pd.Timestamp(day), k=10, explain=False)
            live_rows = store.latest_rows(site, pd.Timestamp(day))
            row = selected_rows.loc[
                (selected_rows.day == day)
                & (selected_rows.site_id == site)
                & (selected_rows.method == "harbinger_hgb")
            ].iloc[0]
            assert sorted(item["asset_id"] for item in live["items"]) == sorted(row.selected_asset_ids)
            assert sorted(live_rows.asset_id.tolist()) == row.candidate_asset_ids
            assert (
                sorted(item["asset_id"] for item in live["items"] if item["mandatory"])
                == row.mandatory_asset_ids
            )
            assert live["model_version"] == bundle["version"]
            parity.append(
                dict(
                    site_id=site,
                    day=day,
                    selected_count=len(live["items"]),
                    mandatory_count=int(row.mandatory_count),
                    overflow=int(row.overflow),
                    candidates=len(live_rows),
                    selection_equal=True,
                    mandatory_equal=True,
                )
            )
    old_new = {}
    for name, method in scenarios["historical_test_only"]["methods"].items():
        if name in old_patrol["methods"]:
            old = old_patrol["methods"][name]["precision_at_k"]
            replay = method["historical_date_weighted_precision_at_k"]
            old_new[name] = dict(
                saved_old_date_weighted=old,
                replay_date_weighted=replay,
                replay_minus_saved=replay - old,
                new_site_equal=method["precision_at_k"],
            )
    candidate_effect = {}
    for name, method in scenarios["full_history_same_dates"]["methods"].items():
        limited = scenarios["historical_test_only"]["methods"][name]
        candidate_effect[name] = dict(
            limited_history_site_equal=limited["precision_at_k"],
            full_history_site_equal=method["precision_at_k"],
            difference=method["precision_at_k"] - limited["precision_at_k"],
        )
    after = {str(p.relative_to(runtime)): sha256(p) for p in source_files}
    assert before == after, "Historical source files changed"
    assert sorted(p for p in runtime.rglob("*") if p.is_file()) == source_files, (
        "Historical source file inventory changed"
    )
    source_code = [
        Path(__file__),
        Path("src/harbinger/eval/patrol.py"),
        Path("src/harbinger/eval/patrol_summary.py"),
        Path("src/harbinger/prescribe/priority.py"),
    ]
    result = dict(
        model_version=bundle["version"],
        source_runtime=str(runtime),
        source_hashes=before,
        source_inputs_unchanged=True,
        command=shlex.join([sys.executable, *sys.argv]),
        code_hashes={str(p): sha256(p) for p in source_code},
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        threads=threads,
        seed=seed,
        k=10,
        observation_end=observed_end.isoformat(),
        requested_start=requested_dates[0].isoformat(),
        requested_end=requested_end.isoformat(),
        models={
            name: dict(
                features=model.features, n_features=len(model.features), strict_no_memo=name == "without_text"
            )
            for name, model in models.items()
        },
        scenarios=scenarios,
        historical_replay=old_new,
        full_history_candidate_effect=candidate_effect,
        service_api_parity=parity,
        limitations=[
            "Historical synthetic world and frozen models; no independent new-world performance claim.",
            "Bootstrap resamples synthetic sites and is conditional on the frozen model.",
            "Unequal-date restriction is a deterministic estimator diagnostic, not a new outcome validation cohort.",
            "Actual service selection parity uses nine sampled site/dates; every comparator shares all candidates, mandatory constraints and requested budgets.",
        ],
    )
    path = output / "summary.json"
    path.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    print(f"Saved {path}; {len(parity)} Store.patrol parity checks passed", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    with threadpool_limits(limits=args.threads):
        run(args.runtime, args.output, args.threads)


if __name__ == "__main__":
    main()
