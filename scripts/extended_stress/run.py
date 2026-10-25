"""Reuse verified frozen weights; save all conditions on the original mature cohort."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from scripts.extended_stress.contracts import CONDITIONS, rebuild, verify_files
from scripts.memo_artifacts import write_csv
from scripts.memo_robustness import DATA_SEEDS, KEYS, MODEL_SEEDS, MODELS, assert_same_cohort
from scripts.robustness.contracts import decision_snapshot, paired_site_interval, weekly_metrics
from scripts.robustness.run import digest, metrics, write_json

from harbinger.features.build import load_tables
from harbinger.models.deep import load_deep

DESIGN = Path("docs/superpowers/specs/2026-10-25-extended-stress-design.md")
PRIOR = Path("docs/verification/memo-20261025/results")


def read_rows(path):
    rows = pd.read_csv(path)
    rows["decision_at"] = pd.to_datetime(rows.decision_at, format="ISO8601")
    return rows


def intervals(scores, seed):
    return {
        "stress_minus_clean": {
            m: {c: paired_site_interval(scores[m][c], scores[m]["clean"], seed=seed) for c in CONDITIONS[1:]}
            for m in MODELS
        },
        "candidate_minus_legacy": {
            m: {c: paired_site_interval(scores[m][c], scores["legacy"][c], seed=seed) for c in CONDITIONS}
            for m in ("robust", "no_memo")
        },
    }


def run(args):
    work = args.work / f"data-{args.data_seed}"
    prior = PRIOR / f"data-{args.data_seed}"
    out = args.out / f"data-{args.data_seed}"
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite evidence: {out}")
    proof = json.loads((prior / "provenance.json").read_text())
    verify_files(prior, json.loads((prior / "sha256.json").read_text()))
    raw_hashes = verify_files(work / "data", proof["raw_sha256"])
    model_hashes = {}
    models = {}
    for seed in MODEL_SEEDS:
        for name in MODELS:
            record = prior / f"model-{seed}" / f"{name}-training.json"
            expected = json.loads(record.read_text())["saved_model_sha256"]
            location = work / f"model-{seed}" / name
            model_hashes[f"{seed}/{name}"] = {
                "files": verify_files(location, expected),
                "training_record_sha256": digest(record),
            }
            models[seed, name] = load_deep(location)
    tables = load_tables(work / "data")
    features = pd.read_parquet(work / "data/features.parquet")
    fit_until = pd.Timestamp(proof["features"]["fit_until"])
    end = pd.Timestamp(proof["features"]["observation_end"])
    reference = read_rows(prior / "model-17/test/rows.csv.gz")
    assert_same_cohort(reference, read_rows(prior / "model-29/test/rows.csv.gz"))
    assert not reference[KEYS[:-1]].duplicated().any()
    assert reference.decision_at.max() + pd.Timedelta(days=30) <= end
    assert reference.decision_at.min() >= pd.Timestamp(proof["split"]["val"]["to"])
    out.mkdir(parents=True)
    write_csv(reference, out / "rows.csv.gz")
    arrays = {s: {} for s in MODEL_SEEDS}
    scores = {s: {m: {} for m in MODELS} for s in MODEL_SEEDS}
    damage, coverage = {}, {}
    for condition in CONDITIONS:
        if condition in ("clean", "delay_7d"):
            altered = features
            damage[condition] = {"kind": condition, "delay_days": 7 if condition == "delay_7d" else 0}
        else:
            altered, damage[condition] = rebuild(
                features, tables, fit_until, condition, args.data_seed + 2000, fit_until, end
            )
        frames = [
            decision_snapshot(altered, tables, at, 7 if condition == "delay_7d" else 0, end).reset_index(
                drop=True
            )
            for at in sorted(reference.decision_at.unique())
        ]
        cohort = pd.concat(frames, ignore_index=True)
        assert_same_cohort(reference, cohort)
        assert (
            cohort.source_t <= cohort.decision_at - pd.Timedelta(days=7 if condition == "delay_7d" else 0)
        ).all()
        write_csv(cohort[["inspection_id", "source_t"]], out / f"{condition}-sources.csv.gz")
        coverage[condition] = {
            "rows": len(cohort),
            "sites": int(cohort.site_id.nunique()),
            "dates": int(cohort.decision_at.nunique()),
            "mean_source_age_days": float(
                ((cohort.decision_at - cohort.source_t).dt.total_seconds() / 86400).mean()
            ),
        }
        for seed in MODEL_SEEDS:
            for name in MODELS:
                p = models[seed, name].predict_proba(cohort).astype(np.float32)
                if condition == "clean":
                    with np.load(prior / f"model-{seed}/test/predictions.npz") as old:
                        np.testing.assert_array_equal(p, old[f"{name}__clean"])
                elif name == "no_memo" and condition != "delay_7d":
                    np.testing.assert_array_equal(p, arrays[seed]["no_memo__clean"])
                arrays[seed][f"{name}__{condition}"] = p
                scores[seed][name][condition] = metrics(reference.y30.to_numpy(), p) | weekly_metrics(
                    reference.assign(p=p)
                )
        print(f"world {args.data_seed}: scored {condition}; {damage[condition]}", flush=True)
    for seed in MODEL_SEEDS:
        dest = out / f"model-{seed}"
        dest.mkdir()
        np.savez_compressed(dest / "predictions.npz", **arrays[seed])
        write_json(dest / "metrics.json", scores[seed])
        write_json(dest / "paired-site-bootstrap.json", intervals(scores[seed], seed))
    paths = (
        sorted(Path("scripts/extended_stress").glob("*.py"))
        + [
            Path("scripts/memo_artifacts.py"),
            Path("scripts/memo_robustness.py"),
            Path("scripts/robustness/contracts.py"),
            Path("scripts/robustness/run.py"),
        ]
        + sorted(Path("src/harbinger").rglob("*.py"))
    )
    write_json(
        out / "provenance.json",
        {
            "data_seed": args.data_seed,
            "model_seeds": list(MODEL_SEEDS),
            "synthetic": True,
            "scale": 1,
            "months": 36,
            "retrained": False,
            "selection_changed": False,
            "design_sha256": digest(DESIGN),
            "design_commit": "43a4ce5",
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "source_sha256": {str(p): digest(p) for p in paths},
            "raw_sha256": raw_hashes,
            "prior_provenance_sha256": digest(prior / "provenance.json"),
            "models": model_hashes,
            "fit_until": fit_until.isoformat(),
            "observation_end": end.isoformat(),
            "test_start": reference.decision_at.min().isoformat(),
            "test_end": reference.decision_at.max().isoformat(),
            "damage": damage,
            "coverage": coverage,
            "cohort_sha256": digest(out / "rows.csv.gz"),
            "python": platform.python_version(),
            "packages": {
                n: importlib.metadata.version(n)
                for n in ("numpy", "pandas", "torch", "scikit-learn", "pyarrow")
            },
            "limits": "Fixed synthetic worlds; invented stress distributions; inspection delivery lag only; no field or deployment claim.",
        },
    )
    write_json(
        out / "sha256.json",
        {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob("*")) if p.is_file()},
    )
    print(f"world {args.data_seed}: COMPLETE", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-seed", type=int, choices=DATA_SEEDS, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())
