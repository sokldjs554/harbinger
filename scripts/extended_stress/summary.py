"""Independently verify saved arrays, frozen provenance and paired site intervals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scripts.extended_stress.contracts import CONDITIONS, verify_files
from scripts.extended_stress.run import DESIGN, PRIOR, intervals, read_rows
from scripts.memo_artifacts import verify_gzip
from scripts.memo_robustness import DATA_SEEDS, KEYS, MODEL_SEEDS, MODELS, assert_same_cohort
from scripts.robustness.contracts import weekly_metrics
from scripts.robustness.run import digest, metrics, write_json


def summarize(root):
    runs = []
    for data_seed in DATA_SEEDS:
        world = root / f"data-{data_seed}"
        verify_files(world, json.loads((world / "sha256.json").read_text()))
        for path in world.rglob("*.gz"):
            verify_gzip(path)
        proof = json.loads((world / "provenance.json").read_text())
        prior = PRIOR / f"data-{data_seed}"
        prior_proof = json.loads((prior / "provenance.json").read_text())
        assert proof["design_sha256"] == digest(DESIGN)
        assert proof["prior_provenance_sha256"] == digest(prior / "provenance.json")
        assert proof["raw_sha256"] == prior_proof["raw_sha256"]
        assert proof["data_seed"] == data_seed and proof["model_seeds"] == list(MODEL_SEEDS)
        assert proof["scale"] == 1 and not proof["retrained"] and not proof["selection_changed"]
        rows = read_rows(world / "rows.csv.gz")
        assert proof["cohort_sha256"] == digest(world / "rows.csv.gz")
        assert not rows[KEYS[:-1]].duplicated().any()
        assert rows.decision_at.max() + pd.Timedelta(days=30) <= pd.Timestamp(proof["observation_end"])
        clean_sources = None
        for condition in CONDITIONS:
            sources = pd.read_csv(world / f"{condition}-sources.csv.gz")
            sources["source_t"] = pd.to_datetime(sources.source_t, format="ISO8601")
            assert len(sources) == len(rows)
            assert (
                sources.source_t <= rows.decision_at - pd.Timedelta(days=7 if condition == "delay_7d" else 0)
            ).all()
            if condition not in ("clean", "delay_7d"):
                pd.testing.assert_frame_equal(sources, clean_sources)
                assert proof["damage"][condition]["changed_rows"] > 0
            if condition == "clean":
                clean_sources = sources
        for seed in MODEL_SEEDS:
            dest = world / f"model-{seed}"
            assert_same_cohort(rows, read_rows(prior / f"model-{seed}/test/rows.csv.gz"))
            saved = json.loads((dest / "metrics.json").read_text())
            actual = {m: {} for m in MODELS}
            with (
                np.load(dest / "predictions.npz") as arrays,
                np.load(prior / f"model-{seed}/test/predictions.npz") as old,
            ):
                assert set(arrays.files) == {f"{m}__{c}" for m in MODELS for c in CONDITIONS}
                for model in MODELS:
                    record = prior / f"model-{seed}/{model}-training.json"
                    assert proof["models"][f"{seed}/{model}"]["training_record_sha256"] == digest(record)
                    assert (
                        proof["models"][f"{seed}/{model}"]["files"]
                        == json.loads(record.read_text())["saved_model_sha256"]
                    )
                    np.testing.assert_array_equal(arrays[f"{model}__clean"], old[f"{model}__clean"])
                    for condition in CONDITIONS:
                        p = arrays[f"{model}__{condition}"]
                        assert len(p) == len(rows) and np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()
                        value = metrics(rows.y30.to_numpy(), p) | weekly_metrics(rows.assign(p=p))
                        for key in ("auroc", "pr_auc", "brier", "logloss", "precision_at_k"):
                            assert np.isclose(value[key], saved[model][condition][key], rtol=1e-7, atol=1e-9)
                        for key in ("selected", "decisions", "per_site"):
                            assert value[key] == saved[model][condition][key]
                        actual[model][condition] = value
                        if model == "no_memo" and condition != "delay_7d":
                            np.testing.assert_array_equal(p, arrays["no_memo__clean"])
            assert intervals(actual, seed) == json.loads((dest / "paired-site-bootstrap.json").read_text())
            runs.append({"data_seed": data_seed, "model_seed": seed, "metrics": actual})
    means = {
        m: {
            c: {
                k: float(np.mean([r["metrics"][m][c][k] for r in runs]))
                for k in ("auroc", "pr_auc", "brier", "logloss", "precision_at_k")
            }
            for c in CONDITIONS
        }
        for m in MODELS
    }
    result = {
        "synthetic": True,
        "world_count": 3,
        "training_seeds_per_world": 2,
        "runs": runs,
        "means": means,
        "note": "Six nested runs; not six independent worlds. Fixed models; no selection or adoption change. Site bootstrap is conditional on each synthetic world.",
    }
    write_json(root / "summary.json", result)
    print(json.dumps({"verified_runs": len(runs), "means": means}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    summarize(parser.parse_args().root)
