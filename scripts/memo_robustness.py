"""Frozen missing-memo experiment; validation selection precedes held-out test scoring."""

from __future__ import annotations

import argparse
import importlib.metadata
import platform
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scripts.robustness.contracts import (
    decision_snapshot,
    paired_site_interval,
    rebuild_memos,
    weekly_metrics,
)
from scripts.robustness.run import digest, metrics, write_json

from harbinger.features.build import FEATURE_GROUPS, load_tables
from harbinger.features.cache import cached_features
from harbinger.models.common import model_columns, split_by_time, to_matrix
from harbinger.models.deep import save_deep, train_deep
from harbinger.synth.generate import GenConfig, generate, write_tables

DATA_SEEDS = (202610251, 202610252, 202610253)
MODEL_SEEDS = (17, 29)
CONDITIONS = ("clean", "missing_25", "missing_50", "missing_100")
MODELS = ("legacy", "robust", "no_memo")
KEYS = ["site_id", "asset_id", "decision_at", "y30"]


def choose_candidate(validation: dict) -> dict:
    """Only validation metrics accepted. Extreme missingness is report-only."""
    eligible = []
    details = {}
    try:
        base = validation["legacy"]
        for name in ("no_memo", "robust"):
            if name not in validation:
                continue
            row = validation[name]
            clean = row["clean"]["precision_at_k"] - base["clean"]["precision_at_k"]
            gains = [row[c]["precision_at_k"] - base[c]["precision_at_k"] for c in CONDITIONS[1:3]]
            brier = row["clean"]["brier"]
            values = [clean, *gains, brier, base["clean"]["brier"]]
            good = bool(
                all(np.isfinite(v) for v in values)
                and clean >= -0.01 - 1e-12
                and min(gains) >= -1e-12
                and np.mean(gains) >= 0.02 - 1e-12
                and brier <= base["clean"]["brier"] * 1.05 + 1e-12
            )
            details[name] = {
                "eligible": good,
                "clean_delta": clean,
                "missing_mean_delta": float(np.mean(gains)),
                "missing_deltas": gains,
            }
            if good:
                eligible.append((float(np.mean([row[c]["precision_at_k"] for c in CONDITIONS[1:3]])), name))
    except KeyError as exc:
        raise ValueError("Incomplete validation metrics") from exc
    # Stable traversal no_memo first; max retains first on ties.
    selected = max(eligible, key=lambda item: item[0])[1] if eligible else "legacy"
    return {"selected": selected, "candidates": details, "basis": "validation only; clean/25%/50%"}


def assert_same_cohort(reference, candidate):
    pd.testing.assert_frame_equal(
        reference[KEYS].reset_index(drop=True), candidate[KEYS].reset_index(drop=True)
    )


def snapshots(sources, tables, start, end, smoke):
    dates = pd.date_range(start, end - pd.Timedelta(days=30), freq="W-MON")
    if smoke:
        dates = dates[:2]
    if not len(dates):
        raise ValueError("No mature weekly decisions")
    result = {c: [] for c in sources}
    for at in dates:
        ref = None
        for condition, features in sources.items():
            rows = decision_snapshot(features, tables, at, 0, end).reset_index(drop=True)
            if ref is not None:
                assert_same_cohort(ref, rows)
            ref = rows
            result[condition].append(rows)
    return {c: pd.concat(v, ignore_index=True) for c, v in result.items()}


def evaluate(models, cohorts, dest):
    reference = cohorts["clean"]
    reference[KEYS].to_csv(dest / "rows.csv.gz", index=False)
    scores, arrays = {}, {}
    for name, model in models.items():
        scores[name] = {}
        for condition, frame in cohorts.items():
            assert_same_cohort(reference, frame)
            p = model.predict_proba(frame).astype(np.float32)
            arrays[f"{name}__{condition}"] = p
            scores[name][condition] = metrics(frame.y30.to_numpy(), p) | weekly_metrics(
                frame[KEYS].assign(p=p)
            )
        print(f"  scored {dest.name}/{name}", flush=True)
    np.savez_compressed(dest / "predictions.npz", **arrays)
    write_json(dest / "metrics.json", scores)
    return scores


def run(args):
    started = time.time()
    out = args.out / f"data-{args.data_seed}"
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite {out}")
    out.mkdir(parents=True)
    work = args.work / f"data-{args.data_seed}"
    if work.exists():
        raise FileExistsError(f"Use a fresh work directory: {work}")
    work.mkdir(parents=True)
    cfg = GenConfig(seed=args.data_seed, scale=0.08 if args.smoke else 1.0, months=36, out=work / "data")
    write_tables(generate(cfg), cfg.out, cfg)
    tables = load_tables(cfg.out)
    fit_until = tables["inspections"].performed_at.min().normalize() + pd.DateOffset(months=24)
    features, feature_provenance = cached_features(cfg.out, fit_until)
    split = split_by_time(features, 24, 6)
    end = pd.Timestamp(feature_provenance["observation_end"])
    safe_cols = model_columns(features, tuple(g for g in FEATURE_GROUPS if g != "tx"))
    sources, damage = {"clean": features}, {}
    for rate in (0.25, 0.5, 1.0):
        name = f"missing_{int(rate * 100)}"
        altered, report = rebuild_memos(
            features, tables, split.train_end, "missing", rate, args.data_seed + 1000, fit_until, end
        )
        pd.testing.assert_frame_equal(to_matrix(features, safe_cols), to_matrix(altered, safe_cols))
        sources[name], damage[name] = altered, report
        print(f"world {args.data_seed}: rebuilt {name}", flush=True)
    # Both sets are constructed, but test predictions and labels are never passed to selection.
    validation = snapshots(sources, tables, split.train_end, split.val_end, args.smoke)
    test = snapshots(sources, tables, split.val_end, end, args.smoke)
    assert validation["clean"].decision_at.max() + pd.Timedelta(days=30) <= split.val_end
    assert test["clean"].decision_at.min() >= split.val_end
    for condition, frame in sources.items():
        frame[["inspection_id", "t", "memo"]].to_csv(out / f"{condition}-memos.csv.gz", index=False)
    source_paths = sorted(Path("src/harbinger").rglob("*.py")) + [
        Path("scripts/memo_robustness.py"),
        Path("scripts/robustness/contracts.py"),
        Path("scripts/robustness/run.py"),
    ]
    write_json(
        out / "provenance.json",
        {
            "data_seed": args.data_seed,
            "smoke": args.smoke,
            "scale": cfg.scale,
            "months": 36,
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "source_sha256": {str(p): digest(p) for p in source_paths},
            "raw_sha256": {p.name: digest(p) for p in sorted(cfg.out.glob("*.parquet"))},
            "features": feature_provenance,
            "split": split.describe(),
            "damage": damage,
            "safe_features": safe_cols,
            "python": platform.python_version(),
            "packages": {
                n: importlib.metadata.version(n)
                for n in ("numpy", "pandas", "torch", "scikit-learn", "pyarrow")
            },
            "model_config": {
                "epochs": 2 if args.smoke else 40,
                "patience": 6,
                "batch": 1024,
                "lr": 0.002,
                "memo_dropout": 0.35,
                "early_stop": "clean validation survival NLL",
            },
            "design_sha256": digest("docs/superpowers/specs/2026-10-25-memo-design.md"),
            "limits": "Synthetic new seeds, same generator and time range; no customer performance; no automatic production replacement.",
        },
    )
    for seed in (17,) if args.smoke else MODEL_SEEDS:
        dest = out / f"model-{seed}"
        dest.mkdir()
        models = {}
        for name in MODELS:
            print(f"world {args.data_seed}, seed {seed}: training {name}", flush=True)
            model = train_deep(
                split.train,
                split.val,
                model_columns(features) if name == "legacy" else safe_cols,
                use_text=name != "no_memo",
                missing_aware=name == "robust",
                memo_dropout=0.35 if name == "robust" else 0,
                epochs=2 if args.smoke else 40,
                seed=seed,
            )
            models[name] = model
            model_path = work / f"model-{seed}" / name
            save_deep(model, model_path)
            write_json(
                dest / f"{name}-training.json",
                model.meta | {"saved_model_sha256": {p.name: digest(p) for p in model_path.iterdir()}},
            )
        for phase in ("validation", "test"):
            (dest / phase).mkdir()
        val_metrics = evaluate(models, validation, dest / "validation")
        selection = choose_candidate(val_metrics)
        write_json(
            dest / "selection.json",
            selection | {"validation_sha256": digest(dest / "validation/metrics.json")},
        )
        frozen = digest(dest / "selection.json")
        test_metrics = evaluate(models, test, dest / "test")
        assert digest(dest / "selection.json") == frozen
        intervals = {
            name: {
                c: paired_site_interval(test_metrics[name][c], test_metrics["legacy"][c], seed=seed)
                for c in CONDITIONS
            }
            for name in ("robust", "no_memo")
        }
        write_json(dest / "paired-site-bootstrap.json", intervals)
        write_json(dest / "freeze.json", {"selection_sha256": frozen, "written_before_test_scoring": True})
        print(f"world {args.data_seed}, seed {seed}: COMPLETE; selected={selection['selected']}", flush=True)
    write_json(
        out / "sha256.json",
        {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob("*")) if p.is_file()},
    )
    print(f"world {args.data_seed}: COMPLETE in {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-seed", type=int, choices=DATA_SEEDS, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    run(parser.parse_args())
