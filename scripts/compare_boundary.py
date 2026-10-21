"""Compare old/new fitted models on identical mature test inspection IDs."""

import argparse
import json
from pathlib import Path

import pandas as pd

from harbinger.api.analysis import safe_json
from harbinger.eval.metrics import classification_metrics
from harbinger.models.common import labeled, split_by_time
from harbinger.models.registry import load_bundle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-data", type=Path, required=True)
    ap.add_argument("--before-models", type=Path, required=True)
    ap.add_argument("--before-artifacts", type=Path, required=True)
    a = ap.parse_args()
    old = pd.read_parquet(a.before_data / "features.parquet")
    new = pd.read_parquet("data/features.parquet")
    split = split_by_time(new)
    truth = labeled(split.test).set_index("inspection_id")
    old_test = old.set_index("inspection_id").loc[truth.index]
    # Same IDs, features respective to old/new pipeline; identical final outcomes.
    y = truth.y30
    before = load_bundle(a.before_models)
    after = load_bundle(Path("models"))
    metrics = json.loads(Path("artifacts/metrics.json").read_text())
    before_metrics = json.loads((a.before_artifacts / "metrics.json").read_text())
    result = {
        "seed": metrics["seed"],
        "synthetic": True,
        "same_test_rows": len(truth),
        "same_data_rows": len(old) == len(new),
        "data": metrics["observation"]["source_sha256"],
        "before_source": "fd346c75ddae39fa6383096d7dd6adabccfdb044",
        "before_bundle": before["version"],
        "after_bundle": after["version"],
        "before": classification_metrics(y, before["classifier"].predict_proba(old_test)),
        "after": classification_metrics(y, after["classifier"].predict_proba(truth)),
        "before_reexecuted_full": before_metrics["classifier"]["hgb_full"],
        "excluded_train_labels": int((~split.train.label_valid).sum()),
        "excluded_val_labels": int((~split.val.label_valid).sum()),
        "train_survival_events_censored": int(
            (
                (old.t < split.train_end)
                & (old.event == 1)
                & (old.t + pd.to_timedelta(old.tte_days, unit="D") > split.train_end)
            ).sum()
        ),
        "val_survival_events_censored": int(
            (
                (old.t >= split.train_end)
                & (old.t < split.val_end)
                & (old.event == 1)
                & (old.t + pd.to_timedelta(old.tte_days, unit="D") > split.val_end)
            ).sum()
        ),
        "notes": [
            "Old published numbers are not used as the rerun baseline.",
            "Includes boundary, energy preprocessing and supported observation-end fixes; not a causal attribution to one patch.",
            "Identical generator seed/scale/months and model hyperparameters. Runtime threads may differ; dependency lock recorded.",
        ],
    }
    Path("artifacts/before_after.json").write_text(
        json.dumps(safe_json(result), ensure_ascii=False, indent=2, allow_nan=False)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
