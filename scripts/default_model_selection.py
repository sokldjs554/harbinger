"""Frozen validation-only HGB default decision on previously unexamined synthetic seeds."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scripts.memo_artifacts import write_csv
from scripts.memo_robustness import snapshots
from scripts.robustness.run import digest, write_json

from harbinger.eval.metrics import classification_metrics
from harbinger.features.build import FEATURE_GROUPS, load_tables
from harbinger.features.cache import cached_features
from harbinger.models.classify import train_hgb
from harbinger.models.common import labeled, model_columns, split_by_time
from harbinger.synth.generate import GenConfig, generate, write_tables

DATA_SEEDS = (202610261, 202610262, 202610263)
MODEL_SEEDS = (17, 29)
MODELS = ("full", "no_memo")
DESIGN = Path("docs/superpowers/specs/2026-10-26-evaluation-completion.md")
KEYS = ["site_id", "asset_id", "decision_at", "source_t", "y30"]


def selection_source_paths():
    """Code used to generate features, fit/predict, construct cohorts and score them."""
    return sorted(
        list(Path("src/harbinger/features").glob("*.py"))
        + list(Path("src/harbinger/models").glob("*.py"))
        + list(Path("src/harbinger/synth").glob("*.py"))
        + [
            Path("src/harbinger/config.py"),
            Path("src/harbinger/schema.py"),
            Path("src/harbinger/eval/metrics.py"),
            Path("scripts/default_model_selection.py"),
            Path("scripts/memo_robustness.py"),
            Path("scripts/memo_artifacts.py"),
            Path("scripts/robustness/contracts.py"),
            Path("scripts/robustness/run.py"),
        ]
    )


def capture_source_hashes():
    return {str(path): digest(path) for path in selection_source_paths()}


def verify_source_hashes(recorded):
    required = {str(path) for path in selection_source_paths()}
    if set(recorded) != required:
        raise ValueError("Source manifest is missing or has unexpected required files")
    for path, expected in recorded.items():
        if not Path(path).is_file() or digest(path) != expected:
            raise ValueError("Source changed since validation capture: " + path)


def snapshot_metrics(frame, predictions, k=10):
    rows = frame.reset_index(drop=True).assign(p=np.asarray(predictions))
    if rows.empty or rows[["site_id", "asset_id", "decision_at"]].duplicated().any():
        raise ValueError("Empty or duplicate decision cohort")
    selected = (
        rows.sort_values(["p", "asset_id"], ascending=[False, True], kind="stable")
        .groupby(["site_id", "decision_at"], sort=True)
        .head(k)
    )
    daily = selected.groupby(["site_id", "decision_at"]).y30.mean()
    sites = daily.groupby(level=0).mean()
    return classification_metrics(rows.y30.to_numpy(), rows.p.to_numpy()) | {
        "precision_at_k": float(sites.mean()),
        "per_site_precision": {str(s): float(v) for s, v in sites.items()},
        "selected": len(selected),
        "site_days": len(daily),
        "k": k,
        "weighting": "equal sites; equal eligible decision dates within each site",
    }


def choose_default(validation_runs):
    """Accept exactly the preregistered validation runs, never test results."""
    if any(r["phase"] != "validation" for r in validation_runs):
        raise ValueError("Only validation metrics may choose the default")
    expected = {(d, m) for d in DATA_SEEDS for m in MODEL_SEEDS}
    keys = {(r["data_seed"], r["model_seed"]) for r in validation_runs}
    criteria = {"six_unique_runs": len(validation_runs) == 6 and keys == expected}
    deltas, per_world = [], {}
    for run in validation_runs:
        b, c = (run["models"][name] for name in MODELS)
        sites = sorted(b["per_site_precision"])
        if sites != sorted(c["per_site_precision"]):
            raise ValueError("Paired sites differ")
        values = [b[k] for k in ("auroc", "pr_auc", "brier", "precision_at_k")]
        values += [c[k] for k in ("auroc", "pr_auc", "brier", "precision_at_k")]
        values += list(b["per_site_precision"].values()) + list(c["per_site_precision"].values())
        if any(v is None or not np.isfinite(v) for v in values):
            criteria["finite"] = False
            continue
        criteria.setdefault("finite", True)
        deltas.append({k: c[k] - b[k] for k in ("auroc", "pr_auc", "brier", "precision_at_k")})
        difference = np.array([c["per_site_precision"][s] - b["per_site_precision"][s] for s in sites])
        world = per_world.setdefault(run["data_seed"], {"sites": sites, "deltas": []})
        if world["sites"] != sites:
            raise ValueError("Training seeds must share sites")
        world["deltas"].append(difference)
    criteria.setdefault("finite", False)
    interval = None
    if criteria["six_unique_runs"] and criteria["finite"] and len(deltas) == 6:
        criteria |= {
            "every_precision_nondecreasing": all(r["precision_at_k"] >= -1e-12 for r in deltas),
            "every_brier_nonincreasing": all(r["brier"] <= 1e-12 for r in deltas),
            "mean_auroc_nondecreasing": np.mean([r["auroc"] for r in deltas]) >= -1e-12,
            "mean_pr_auc_nondecreasing": np.mean([r["pr_auc"] for r in deltas]) >= -1e-12,
            "enough_site_clusters": all(len(v["sites"]) >= 5 for v in per_world.values()),
        }
        if criteria["enough_site_clusters"]:
            rng = np.random.default_rng(20261026)
            draws = []
            for world in DATA_SEEDS:
                w = per_world[world]
                # Same site's repeated training seeds are not independent clusters.
                site_delta = np.mean(w["deltas"], axis=0)
                ids = rng.integers(0, len(site_delta), size=(2000, len(site_delta)))
                draws.append(site_delta[ids].mean(axis=1))
            interval = np.quantile(np.mean(draws, axis=0), [0.025, 0.975]).tolist()
    criteria["paired_precision_ci_positive"] = interval is not None and interval[0] > 0
    criteria = {k: bool(v) for k, v in criteria.items()}
    return {
        "selected": "no_memo" if all(criteria.values()) else "full",
        "criteria": criteria,
        "reasons": [k for k, v in criteria.items() if not v],
        "precision_delta_ci95": interval,
        "run_deltas": deltas,
        "selection_role": "validation reused for calibration; not independent test",
        "uncertainty": "2000 paired site-block draws within each fixed synthetic world; same draws across training seeds; equal world/seed weights; not customer confidence",
    }


def verify_freeze(out, *, check_source=False):
    """Read historical artifacts by default; require current source integrity for new scoring.

    Legacy runs lack the complete pre-fit source guard. Their existing artifacts
    remain readable, but cannot authorize fresh predictions under this version.
    """
    out = Path(out)
    if not (out / "freeze.json").exists() or not (out / "selection.json").exists():
        raise ValueError("Test scoring requires a frozen validation selection")
    record = json.loads((out / "freeze.json").read_text())
    if digest(out / "selection.json") != record["selection_sha256"]:
        raise ValueError("Frozen selection changed")
    for name, expected in record["validation_sha256"].items():
        if digest(out / name) != expected:
            raise ValueError("Frozen validation evidence changed: " + name)
    if digest(DESIGN) != record["design_sha256"]:
        raise ValueError("Frozen design changed")
    if check_source:
        for data_seed in DATA_SEEDS:
            path = out / str(data_seed) / "provenance.json"
            if not path.is_file():
                raise ValueError("Source provenance is missing")
            proof = json.loads(path.read_text())
            if proof.get("source_integrity_version") != 1:
                raise ValueError(
                    "Source integrity guard unavailable for legacy validation; historical artifacts remain readable"
                )
            verify_source_hashes(proof.get("source_sha256", {}))
    return json.loads((out / "selection.json").read_text())


def cohort(features, tables, start, end):
    result = snapshots({"clean": features}, tables, start, end, False)["clean"]
    return result[result.source_t > result.decision_at - pd.Timedelta(days=120)].reset_index(drop=True)


def score(models, rows, dest):
    dest.mkdir(parents=True)
    write_csv(rows[KEYS], dest / "rows.csv.gz")
    arrays = {name: models[name].predict_proba(rows) for name in MODELS}
    np.savez_compressed(dest / "predictions.npz", **arrays)
    result = {name: snapshot_metrics(rows, predictions) for name, predictions in arrays.items()}
    write_json(dest / "metrics.json", result)
    return result


def validate(args):
    source_hashes = capture_source_hashes()
    seeds = (args.data_seed,) if args.data_seed is not None else DATA_SEEDS
    for data_seed in seeds:
        work, out = args.work / str(data_seed), args.out / str(data_seed)
        if work.exists() or out.exists():
            raise FileExistsError("Fresh work/output paths required")
        out.mkdir(parents=True)
        cfg = GenConfig(seed=data_seed, scale=1, months=36, out=work / "data")
        write_tables(generate(cfg), cfg.out, cfg)
        tables = load_tables(cfg.out)
        fit_until = tables["inspections"].performed_at.min().normalize() + pd.DateOffset(months=24)
        features, provenance = cached_features(cfg.out, fit_until)
        split = split_by_time(features, 24, 6)
        val_rows = cohort(features, tables, split.train_end, split.val_end)
        cols = {
            "full": model_columns(features),
            "no_memo": model_columns(features, tuple(g for g in FEATURE_GROUPS if g != "tx")),
        }
        model_hashes = {}
        for model_seed in MODEL_SEEDS:
            models = {}
            for name in MODELS:
                print(f"validation world={data_seed} seed={model_seed} fit={name}", flush=True)
                models[name] = train_hgb(
                    labeled(split.train), labeled(split.val), cols[name], seed=model_seed, name=name
                )
                path = work / f"{model_seed}-{name}.joblib"
                joblib.dump(models[name], path)
                model_hashes[path.name] = digest(path)
            dest = out / f"model-{model_seed}" / "validation"
            values = score(models, val_rows, dest)
            write_json(
                dest / "run.json",
                {"data_seed": data_seed, "model_seed": model_seed, "phase": "validation", "models": values},
            )
        verify_source_hashes(source_hashes)
        write_json(
            out / "provenance.json",
            {
                "data_seed": data_seed,
                "model_seeds": MODEL_SEEDS,
                "scale": 1,
                "months": 36,
                "split": split.describe(),
                "features": provenance,
                "model_columns": cols,
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "source_sha256": source_hashes,
                "source_integrity_version": 1,
                "source_capture": "before validation generation/fitting; verified unchanged after validation scoring",
                "design_sha256": digest(DESIGN),
                "raw_sha256": {p.name: digest(p) for p in cfg.out.glob("*.parquet")},
                "model_sha256": model_hashes,
                "packages": {n: importlib.metadata.version(n) for n in ("numpy", "pandas", "scikit-learn")},
                "validation_note": "calibration uses validation inspection labels; candidate choice uses same-period mature weekly snapshots; test predictions not computed yet",
            },
        )
        print(f"validation world={data_seed} complete; no test predictions", flush=True)


def freeze(args):
    if (args.out / "selection.json").exists():
        raise FileExistsError("Selection already frozen")
    if any(p.is_dir() for p in args.out.rglob("test")):
        raise ValueError("Cannot freeze selection after test output exists")
    files = [
        args.out / str(d) / f"model-{m}" / "validation/run.json" for d in DATA_SEEDS for m in MODEL_SEEDS
    ]
    choice = choose_default([json.loads(p.read_text()) for p in files])
    write_json(args.out / "selection.json", choice)
    paths = [
        p for p in args.out.rglob("*") if p.is_file() and p.name not in {"selection.json", "freeze.json"}
    ]
    write_json(
        args.out / "freeze.json",
        {
            "selection_sha256": digest(args.out / "selection.json"),
            "validation_sha256": {str(p.relative_to(args.out)): digest(p) for p in paths},
            "design_sha256": digest(DESIGN),
            "test_predictions_exist": False,
        },
    )
    print(json.dumps(choice, ensure_ascii=False), flush=True)


def test(args):
    selected = verify_freeze(args.out, check_source=True)
    for data_seed in DATA_SEEDS:
        work, out = args.work / str(data_seed), args.out / str(data_seed)
        proof = json.loads((out / "provenance.json").read_text())
        for name, expected in proof["raw_sha256"].items():
            if digest(work / "data" / name) != expected:
                raise ValueError("Input changed after validation")
        features = pd.read_parquet(work / "data/features.parquet")
        tables = load_tables(work / "data")
        start = pd.Timestamp(proof["split"]["val"]["to"])
        end = pd.Timestamp(proof["features"]["observation_end"])
        rows = cohort(features, tables, start, end)
        for model_seed in MODEL_SEEDS:
            models = {}
            for name in MODELS:
                path = work / f"{model_seed}-{name}.joblib"
                if digest(path) != proof["model_sha256"][path.name]:
                    raise ValueError("Model changed after validation")
                models[name] = joblib.load(path)
            dest = out / f"model-{model_seed}" / "test"
            values = score(models, rows, dest)
            write_json(
                dest / "run.json",
                {
                    "data_seed": data_seed,
                    "model_seed": model_seed,
                    "phase": "test",
                    "selected_before_test": selected["selected"],
                    "models": values,
                },
            )
            print(f"test world={data_seed} seed={model_seed} complete", flush=True)
        verify_freeze(args.out, check_source=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=["validation", "freeze", "test"])
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--data-seed", type=int, choices=DATA_SEEDS)
    args = p.parse_args()
    {"validation": validate, "freeze": freeze, "test": test}[args.phase](args)


if __name__ == "__main__":
    main()
