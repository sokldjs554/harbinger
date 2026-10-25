"""Recompute frozen memo selection and adoption gates from saved predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scripts.memo_artifacts import verify_gzip
from scripts.memo_robustness import CONDITIONS, DATA_SEEDS, MODEL_SEEDS, MODELS, choose_candidate
from scripts.robustness.contracts import paired_site_interval, weekly_metrics
from scripts.robustness.run import digest, metrics, write_json


def adoption_gate(runs):
    complete = len(runs) == 6
    values = [
        v
        for r in runs
        for v in (r["clean_delta"], r["missing_mean_delta"], r["clean_brier"], r["legacy_clean_brier"])
    ]
    finite = bool(values and all(np.isfinite(v) for v in values))
    criteria = {"six_runs": complete, "finite": finite}
    if finite:
        criteria |= {
            "every_clean_drop_at_most_2pp": all(r["clean_delta"] >= -0.02 - 1e-12 for r in runs),
            "every_missing_mean_nondecreasing": all(r["missing_mean_delta"] >= -1e-12 for r in runs),
            "mean_missing_gain_at_least_2pp": np.mean([r["missing_mean_delta"] for r in runs])
            >= 0.02 - 1e-12,
            "mean_clean_drop_at_most_1pp": np.mean([r["clean_delta"] for r in runs]) >= -0.01 - 1e-12,
            "mean_clean_brier_at_most_5pct_worse": np.mean([r["clean_brier"] for r in runs])
            <= 1.05 * np.mean([r["legacy_clean_brier"] for r in runs]) + 1e-12,
        }
    return {"passed": bool(all(criteria.values())), "criteria": {k: bool(v) for k, v in criteria.items()}}


def summarize(root):
    runs = []
    all_metrics = []
    for data_seed in DATA_SEEDS:
        world = root / f"data-{data_seed}"
        for path, expected in json.loads((world / "sha256.json").read_text()).items():
            assert digest(world / path) == expected, path
        for compressed in world.rglob("*.gz"):
            verify_gzip(compressed)
        proof = json.loads((world / "provenance.json").read_text())
        assert proof["data_seed"] == data_seed and proof["scale"] == 1 and not proof["smoke"]
        assert proof["months"] == 36 and proof["model_config"]["epochs"] == 40
        for seed in MODEL_SEEDS:
            dest = world / f"model-{seed}"
            phase_results = {}
            phase_rows = {}
            for phase in ("validation", "test"):
                d = dest / phase
                rows = pd.read_csv(d / "rows.csv.gz", parse_dates=["decision_at"])
                assert not rows[["site_id", "asset_id", "decision_at"]].duplicated().any()
                saved = json.loads((d / "metrics.json").read_text())
                arrays = np.load(d / "predictions.npz")
                actual = {}
                for model in MODELS:
                    actual[model] = {}
                    for condition in CONDITIONS:
                        p = arrays[f"{model}__{condition}"]
                        assert len(p) == len(rows) and np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()
                        value = metrics(rows.y30.to_numpy(), p) | weekly_metrics(rows.assign(p=p))
                        for metric in ("auroc", "pr_auc", "brier", "logloss", "precision_at_k"):
                            assert np.isclose(
                                value[metric], saved[model][condition][metric], rtol=1e-7, atol=1e-9
                            )
                        assert value["per_site"] == saved[model][condition]["per_site"]
                        actual[model][condition] = value
                for condition in CONDITIONS[1:]:
                    np.testing.assert_array_equal(arrays["no_memo__clean"], arrays[f"no_memo__{condition}"])
                phase_results[phase] = actual
                phase_rows[phase] = rows
            val_end = pd.Timestamp(proof["split"]["val"]["to"])
            assert phase_rows["validation"].decision_at.max() + pd.Timedelta(days=30) <= val_end
            assert phase_rows["test"].decision_at.min() >= val_end
            selection = json.loads((dest / "selection.json").read_text())
            assert selection["validation_sha256"] == digest(dest / "validation/metrics.json")
            assert selection["selected"] == choose_candidate(phase_results["validation"])["selected"]
            assert json.loads((dest / "freeze.json").read_text())["selection_sha256"] == digest(
                dest / "selection.json"
            )
            test = phase_results["test"]
            for name in ("robust", "no_memo"):
                saved = json.loads((dest / "paired-site-bootstrap.json").read_text())[name]
                for condition in CONDITIONS:
                    actual = paired_site_interval(test[name][condition], test["legacy"][condition], seed=seed)
                    assert actual == saved[condition]
            selected = selection["selected"]
            chosen, legacy = test[selected], test["legacy"]
            runs.append(
                {
                    "data_seed": data_seed,
                    "model_seed": seed,
                    "selected": selected,
                    "clean_delta": chosen["clean"]["precision_at_k"] - legacy["clean"]["precision_at_k"],
                    "missing_mean_delta": float(
                        np.mean(
                            [
                                chosen[c]["precision_at_k"] - legacy[c]["precision_at_k"]
                                for c in CONDITIONS[1:3]
                            ]
                        )
                    ),
                    "clean_brier": chosen["clean"]["brier"],
                    "legacy_clean_brier": legacy["clean"]["brier"],
                }
            )
            all_metrics.append(test)
    means = {
        m: {
            c: {
                metric: float(np.mean([r[m][c][metric] for r in all_metrics]))
                for metric in ("auroc", "pr_auc", "brier", "logloss", "precision_at_k")
            }
            for c in CONDITIONS
        }
        for m in MODELS
    }
    summary = {
        "synthetic": True,
        "world_count": 3,
        "training_seeds_per_world": 2,
        "runs": runs,
        "test_means": means,
        "adoption": adoption_gate(runs),
        "note": "Six nested runs, not six independent worlds; validation-selected policy only; no deployment or customer proof.",
    }
    write_json(root / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    summarize(parser.parse_args().root)
