"""Verify saved evidence and recompute a six-run summary from raw predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scripts.robustness.contracts import SCHEMES, weekly_metrics
from scripts.robustness.run import DATA_SEEDS, MODEL_SEEDS, digest, metrics, write_json


def near(a, b):
    if a is None:
        assert b is None or not np.isfinite(b)
    else:
        assert np.isclose(a, b, rtol=1e-7, atol=1e-9), (a, b)


def verify_world(root):
    expected = json.loads((root / "sha256.json").read_text())
    for path, value in expected.items():
        assert digest(root / path) == value, f"Changed artifact: {root / path}"
    weekly = pd.read_csv(root / "weekly-rows.csv.gz", parse_dates=["decision_at"])
    test = pd.read_csv(root / "test-rows.csv.gz")
    proof = json.loads((root / "provenance.json").read_text())
    assert not proof["smoke"] and proof["scale"] == 1.0 and proof["months"] == 36
    for name in ["clean", "missing_25", "missing_50", "typo_10", "typo_30", "delay_3d", "delay_7d"]:
        records = pd.read_csv(root / f"{name}-sources.csv.gz", parse_dates=["source_t"])
        lag = int(name.split("_")[1][0]) if name.startswith("delay") else 0
        assert len(records) == len(weekly)
        assert (records.source_t <= weekly.decision_at - pd.Timedelta(days=lag)).all()
    summaries = []
    for seed in MODEL_SEEDS:
        dest = root / f"model-{seed}"
        s = json.loads((dest / "summary.json").read_text())
        assert not s["smoke"] and s["model_seed"] == seed
        arrays = np.load(dest / "predictions.npz")
        for model, recorded in s["inspection_test"].items():
            actual = metrics(test.y30, arrays[f"inspection_{model}"])
            for metric, value in actual.items():
                near(recorded[metric], value)
        for condition, models in s["weekly"].items():
            for model, recorded in models.items():
                p = arrays[f"{condition}__{model}"]
                actual = weekly_metrics(weekly.assign(p=p))
                near(recorded["precision_at_k"], actual["precision_at_k"])
                assert recorded["selected"] == actual["selected"]
                assert recorded["per_site"] == actual["per_site"]
                if model != "last_inspection_rule":
                    for metric, value in metrics(weekly.y30, p).items():
                        near(recorded[metric], value)
        for condition in ["missing_25", "missing_50", "typo_10", "typo_30"]:
            assert np.array_equal(arrays["clean__hgb_no_memo"], arrays[f"{condition}__hgb_no_memo"])
        val = pd.read_csv(dest / "calibration-rows.csv.gz", parse_dates=["t"])
        folds = np.load(dest / "calibration-folds.npz")
        oof = np.load(dest / "calibration-oof.npz")
        mask = np.ones(len(val), dtype=bool)
        for scheme in SCHEMES:
            for method in ("platt", "isotonic"):
                mask &= np.isfinite(oof[f"{scheme}_{method}"])
            seen = set()
            fit_keys = [k for k in folds.files if k.rsplit("_", 2)[0] == scheme and k.endswith("_fit")]
            for key in fit_keys:
                tr, va = folds[key], folds[key.removesuffix("_fit") + "_held"]
                assert not (set(tr) & set(va)) and not (set(va) & seen)
                seen.update(va)
                if scheme in ("asset_group", "purged_time_asset"):
                    left = set(zip(val.iloc[tr].site_id, val.iloc[tr].asset_id, strict=True))
                    right = set(zip(val.iloc[va].site_id, val.iloc[va].asset_id, strict=True))
                    assert left.isdisjoint(right)
                if scheme.startswith("purged_time"):
                    assert (val.iloc[tr].t + pd.Timedelta(days=30)).max() < val.iloc[va].t.min()
        assert np.array_equal(mask, oof["common_mask"])
        for scheme, result in s["calibration"].items():
            assert result["selection"]["selection_n"] == mask.sum()
            for metric, value in metrics(test.y30, arrays[f"calibration_{scheme}"]).items():
                near(result["test"][metric], value)
            for method, recorded in result["selection"]["scores"].items():
                p = oof["raw"] if method == "raw" else oof[f"{scheme}_{method}"]
                actual = metrics(val.y30.to_numpy()[mask], p[mask])
                near(recorded["logloss"], actual["logloss"])
                near(recorded["brier"], actual["brier"])
        summaries.append(s)
    return summaries


def summarize(root):
    runs = []
    for seed in DATA_SEEDS:
        runs += verify_world(root / f"data-{seed}")
    result = {
        "world_count": 3,
        "training_seeds_per_world": 2,
        "synthetic": True,
        "note": "Nested six runs, not six independent worlds; min/max are descriptive, not confidence intervals.",
        "inspection_models": {},
        "weekly_models": {},
        "hgb_stress": {},
        "calibration": {},
        "run_rankings": [],
    }
    for model in runs[0]["inspection_test"]:
        for section, lookup, columns in [
            (
                "inspection_models",
                lambda r, model=model: r["inspection_test"][model],
                ["auroc", "pr_auc", "brier"],
            ),
            (
                "weekly_models",
                lambda r, model=model: r["weekly"]["clean"][model],
                ["precision_at_k", "auroc", "brier"],
            ),
        ]:
            result[section][model] = {}
            for metric in columns:
                values = np.array([lookup(r)[metric] for r in runs])
                by_world = [float(values[i : i + 2].mean()) for i in range(0, 6, 2)]
                result[section][model][metric] = {
                    "world_mean": float(np.mean(by_world)),
                    "world_means": by_world,
                    "run_min": float(values.min()),
                    "run_max": float(values.max()),
                }
    for r in runs:
        result["run_rankings"].append(
            {
                "data_seed": r["data_seed"],
                "model_seed": r["model_seed"],
                "auroc_order": sorted(
                    r["inspection_test"], key=lambda m: r["inspection_test"][m]["auroc"], reverse=True
                ),
                "weekly_precision_order": sorted(
                    r["weekly"]["clean"],
                    key=lambda m: r["weekly"]["clean"][m]["precision_at_k"],
                    reverse=True,
                ),
            }
        )
    for condition in runs[0]["weekly"]:
        if condition == "clean":
            continue
        result["hgb_stress"][condition] = [
            {
                "data_seed": r["data_seed"],
                "model_seed": r["model_seed"],
                "precision_delta": r["paired_site_bootstrap"]["hgb_stress_minus_clean"][condition],
                "auroc_delta": r["weekly"][condition]["hgb"]["auroc"] - r["weekly"]["clean"]["hgb"]["auroc"],
            }
            for r in runs
        ]
    for scheme in SCHEMES:
        result["calibration"][scheme] = [
            {
                "data_seed": r["data_seed"],
                "model_seed": r["model_seed"],
                "method": r["calibration"][scheme]["selection"]["method"],
                "common_selection_n": r["calibration"][scheme]["selection"]["selection_n"],
                "test": r["calibration"][scheme]["test"],
            }
            for r in runs
        ]
    write_json(root / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    summarize(parser.parse_args().root)
