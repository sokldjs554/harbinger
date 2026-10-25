"""Reproduce one preregistered synthetic world; keep raw predictions and fold membership."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scripts.robustness.contracts import (
    SCHEMES,
    calibration_splits,
    decision_snapshot,
    oof_predictions,
    paired_site_interval,
    rebuild_memos,
    select_calibration,
    weekly_metrics,
)

from harbinger.eval.metrics import classification_metrics
from harbinger.features.build import FEATURE_GROUPS, load_tables
from harbinger.features.cache import cached_features
from harbinger.models.calibration import logloss
from harbinger.models.classify import BASELINE_FEATURES, train_hgb, train_logistic
from harbinger.models.common import labeled, model_columns, split_by_time
from harbinger.models.deep import train_deep
from harbinger.synth.generate import GenConfig, generate, write_tables

DATA_SEEDS = (20260101, 20260102, 20260103)
MODEL_SEEDS = (17, 29)
DAMAGE = (("missing", 0.25), ("missing", 0.5), ("typo", 0.1), ("typo", 0.3))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    def finite(x):
        if isinstance(x, dict):
            return {str(k): finite(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [finite(v) for v in x]
        if isinstance(x, (float, np.floating)):
            return float(x) if np.isfinite(x) else None
        if isinstance(x, np.integer):
            return int(x)
        return x

    Path(path).write_text(json.dumps(finite(obj), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def metrics(y, p):
    return classification_metrics(y, p) | {"logloss": logloss(p, y)}


def subgroups(rows, scores):
    result = {}
    for column in ("site_id", "category"):
        result[column] = {}
        for key, indices in rows.groupby(column, observed=True).indices.items():
            result[column][str(key)] = metrics(rows.iloc[indices].y30.to_numpy(), scores[indices])
    return result


def evaluate_calibration(model, val, seed, out):
    p, y = model.predict_raw(val), val.y30.to_numpy()
    results, arrays, members, notes = {}, {}, {}, {}
    for scheme in SCHEMES:
        splits = calibration_splits(val, scheme, seed)
        oof, audit = oof_predictions(p, y, splits)
        results[scheme] = oof
        notes[scheme] = audit
        for number, (tr, va) in enumerate(splits):
            members[f"{scheme}_{number}_fit"] = np.asarray(tr, dtype=np.int32)
            members[f"{scheme}_{number}_held"] = np.asarray(va, dtype=np.int32)
        for method, values in oof.items():
            arrays[f"{scheme}_{method}"] = values
    common = np.ones(len(val), dtype=bool)
    for oof in results.values():
        for values in oof.values():
            common &= np.isfinite(values)
    chosen, selections = {}, {}
    for scheme, oof in results.items():
        chosen[scheme], info = select_calibration(p, y, oof, common)
        selections[scheme] = info | {"folds": notes[scheme]}
    # Freeze choices before reading the final test predictions/outcomes.
    write_json(
        out / "calibration-selection.json", {"common_selection_n": int(common.sum()), "schemes": selections}
    )
    val[["inspection_id", "site_id", "asset_id", "t", "y30"]].to_csv(
        out / "calibration-rows.csv.gz", index=False
    )
    np.savez_compressed(out / "calibration-folds.npz", **members)
    np.savez_compressed(out / "calibration-oof.npz", raw=p, y=y, common_mask=common, **arrays)
    return chosen, selections


def validate_world_cache(root, expected):
    marker = root / "world-provenance.json"
    data = root / "data"
    if data.exists() and any(data.iterdir()):
        if not marker.exists() or json.loads(marker.read_text()) != expected:
            raise ValueError("World cache provenance differs or is missing; use a fresh work directory")


def prepare(args):
    root = args.work / str(args.data_seed)
    data = root / "data"
    scale = 0.08 if args.smoke else 1.0
    cfg = GenConfig(seed=args.data_seed, scale=scale, months=36, out=data)
    expected = {
        "seed": cfg.seed,
        "scale": cfg.scale,
        "months": cfg.months,
        "start": cfg.start.isoformat(),
        "source_sha256": {str(p): digest(p) for p in sorted(Path("src/harbinger").rglob("*.py"))},
    }
    validate_world_cache(root, expected)
    if not (data / "meta.json").exists():
        write_tables(generate(cfg), data, cfg)
        write_json(root / "world-provenance.json", expected)
    metadata = json.loads((data / "meta.json").read_text())
    assert metadata["seed"] == args.data_seed and metadata["scale"] == scale and metadata["months"] == 36
    tables = load_tables(data)
    train_end = tables["inspections"].performed_at.min().normalize() + pd.DateOffset(months=24)
    features, provenance = cached_features(data, train_end)
    split = split_by_time(features, 24, 6)
    end = pd.Timestamp(provenance["observation_end"])
    dates = pd.date_range(split.val_end, end - pd.Timedelta(days=30), freq="W-MON")
    if args.smoke:
        dates = dates[:2]
    sources = {"clean": features}
    conditions = {}
    for kind, rate in DAMAGE:
        name = f"{kind}_{int(rate * 100)}"
        altered, report = rebuild_memos(
            features,
            tables,
            split.val_end,
            kind,
            rate,
            args.data_seed + 1000,
            pd.Timestamp(provenance["fit_until"]),
            end,
        )
        sources[name], conditions[name] = altered, report
        print(f"[world {args.data_seed}] prepared {name}", flush=True)
    weekly, coverage = {k: [] for k in [*sources, "delay_3d", "delay_7d"]}, []
    for at in dates:
        frames = {name: decision_snapshot(frame, tables, at, 0, end) for name, frame in sources.items()}
        for lag in (3, 7):
            frames[f"delay_{lag}d"] = decision_snapshot(features, tables, at, lag, end)
        ids = frames["clean"].index
        for frame in frames.values():
            ids = ids.intersection(frame.index)
        if ids.empty:
            raise ValueError("No common decision population")
        coverage.append(
            {
                "decision_at": at.isoformat(),
                "common_n": len(ids),
                "available": {k: len(v) for k, v in frames.items()},
            }
        )
        for name, frame in frames.items():
            frame = frame.loc[ids].reset_index(drop=True)
            pd.testing.assert_series_equal(frame.y30, frames["clean"].loc[ids].reset_index(drop=True).y30)
            weekly[name].append(frame)
    weekly = {k: pd.concat(v, ignore_index=True) for k, v in weekly.items()}
    return tables, features, split, weekly, provenance, conditions, coverage


def run(args):
    started = time.time()
    out = args.out / f"data-{args.data_seed}"
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite experiment evidence: {out}")
    out.mkdir(parents=True)
    tables, features, split, weekly, provenance, damage, coverage = prepare(args)
    val, test, train = (labeled(f).reset_index(drop=True) for f in (split.val, split.test, split.train))
    cols = model_columns(features)
    source_files = sorted(Path("src/harbinger").rglob("*.py")) + sorted(
        Path("scripts/robustness").glob("*.py")
    )
    source_hashes = {str(p): digest(p) for p in source_files}
    write_json(
        out / "provenance.json",
        {
            "base_source_commit": "d9b5d7a57d6fa4c24e4ed52e3e7e44e386b5d7d7",
            "execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "source_sha256": source_hashes,
            "data": provenance,
            "data_seed": args.data_seed,
            "model_seeds": [17] if args.smoke else list(MODEL_SEEDS),
            "synthetic": True,
            "smoke": args.smoke,
            "scale": 0.08 if args.smoke else 1.0,
            "months": 36,
            "split": split.describe(),
            "damage": damage,
            "coverage": coverage,
            "python": platform.python_version(),
            "packages": {
                n: importlib.metadata.version(n)
                for n in ("numpy", "pandas", "scikit-learn", "torch", "scipy", "pyarrow")
            },
            "limits": "inspection delivery delay only; workorders immediate; synthetic deletion typos; no customer validation",
        },
    )
    weekly["clean"][["site_id", "asset_id", "category", "decision_at", "y30"]].to_csv(
        out / "weekly-rows.csv.gz", index=False
    )
    for name, frame in weekly.items():
        frame[["inspection_id", "source_t"]].to_csv(out / f"{name}-sources.csv.gz", index=False)
    test[["inspection_id", "site_id", "asset_id", "t", "y30"]].to_csv(out / "test-rows.csv.gz", index=False)
    for seed in [17] if args.smoke else MODEL_SEEDS:
        dest = out / f"model-{seed}"
        dest.mkdir(exist_ok=True)
        if (dest / "summary.json").exists():
            raise ValueError(f"Refusing to overwrite a completed experiment: {dest}")
        print(f"[world {args.data_seed}, seed {seed}] fit HGB / logistic / no-memo / limited", flush=True)
        models = {
            "hgb": train_hgb(train, val, cols, seed=seed),
            "logistic": train_logistic(train, val, cols, seed=seed),
            "hgb_no_memo": train_hgb(
                train, val, model_columns(features, tuple(g for g in FEATURE_GROUPS if g != "tx")), seed=seed
            ),
            "hgb_last_inspection": train_hgb(train, val, BASELINE_FEATURES["last_inspection"], seed=seed),
        }
        chosen, selections = evaluate_calibration(models["hgb"], val, seed, dest)
        print(f"[world {args.data_seed}, seed {seed}] fit PyTorch", flush=True)
        models["pytorch_text_site"] = train_deep(
            split.train, split.val, cols, epochs=2 if args.smoke else 40, seed=seed, verbose=True
        )
        summary = {
            "data_seed": args.data_seed,
            "model_seed": seed,
            "smoke": args.smoke,
            "inspection_test": {},
            "weekly": {},
            "calibration": {},
            "training": {"hgb": models["hgb"].meta, "pytorch": models["pytorch_text_site"].meta},
        }
        arrays = {}
        for name, model in models.items():
            p = model.predict_proba(test).astype(np.float32)
            arrays[f"inspection_{name}"] = p
            summary["inspection_test"][name] = metrics(test.y30, p) | {"subgroups": subgroups(test, p)}
        raw = models["hgb"].predict_raw(test)
        arrays["calibration_raw"] = raw
        for scheme, cal in chosen.items():
            p = raw if cal is None else cal.predict(raw)
            arrays[f"calibration_{scheme}"] = p
            summary["calibration"][scheme] = {"selection": selections[scheme], "test": metrics(test.y30, p)}
        for condition, frame in weekly.items():
            summary["weekly"][condition] = {}
            for name, model in models.items():
                p = model.predict_proba(frame).astype(np.float32)
                arrays[f"{condition}__{name}"] = p
                scores = frame[["site_id", "asset_id", "decision_at", "y30"]].assign(p=p)
                summary["weekly"][condition][name] = (
                    metrics(frame.y30, p) | weekly_metrics(scores) | {"subgroups": subgroups(frame, p)}
                )
            rule = frame.ck_overall.to_numpy(dtype=np.float32)
            arrays[f"{condition}__last_inspection_rule"] = rule
            summary["weekly"][condition]["last_inspection_rule"] = weekly_metrics(
                frame[["site_id", "asset_id", "decision_at", "y30"]].assign(p=rule)
            )
            print(f"[world {args.data_seed}, seed {seed}] scored {condition}", flush=True)
        summary["paired_site_bootstrap"] = {
            "hgb_vs_logistic_clean": paired_site_interval(
                summary["weekly"]["clean"]["hgb"], summary["weekly"]["clean"]["logistic"]
            ),
            "hgb_vs_rule_clean": paired_site_interval(
                summary["weekly"]["clean"]["hgb"], summary["weekly"]["clean"]["last_inspection_rule"]
            ),
            "hgb_stress_minus_clean": {
                c: paired_site_interval(summary["weekly"][c]["hgb"], summary["weekly"]["clean"]["hgb"])
                for c in weekly
                if c != "clean"
            },
        }
        np.savez_compressed(dest / "predictions.npz", **arrays)
        write_json(dest / "summary.json", summary)
        write_json(
            dest / "sha256.json",
            {p.name: digest(p) for p in dest.iterdir() if p.is_file() and p.name != "sha256.json"},
        )
        print(f"[world {args.data_seed}, seed {seed}] COMPLETE", flush=True)
    write_json(
        out / "sha256.json",
        {
            str(p.relative_to(out)): digest(p)
            for p in out.rglob("*")
            if p.is_file() and p != out / "sha256.json"
        },
    )
    print(f"[world {args.data_seed}] COMPLETE in {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-seed", type=int, choices=DATA_SEEDS, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    run(parser.parse_args())
