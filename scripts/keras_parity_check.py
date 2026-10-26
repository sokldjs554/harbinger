"""Keras 패리티 검사 — 별도 프로세스에서 PyTorch 위험 네트와 Keras 구현을 같은 분할로 학습해 결과를 JSON 으로 출력한다.

    python scripts/keras_parity_check.py --features data/features.parquet --epochs 12
TF 와 torch 를 한 프로세스에 함께 올릴 때의 충돌을 피하기 위해 torch 학습을 먼저 끝내고 그 다음 TF 를 import 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--train-months", type=int, default=5)
    ap.add_argument("--val-months", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, help="Save the same JSON evidence printed to stdout")
    ap.add_argument(
        "--shared-initialization",
        action="store_true",
        help="Copy common pre-training weights; stochastic training still differs",
    )
    a = ap.parse_args()

    import numpy as np
    import pandas as pd
    from sklearn.metrics import roc_auc_score

    from harbinger.models.common import labeled, model_columns, split_by_time
    from harbinger.models.deep import train_deep

    X = pd.read_parquet(a.features)
    sp = split_by_time(X, a.train_months, a.val_months)
    cols = model_columns(X)
    vl = labeled(sp.val)
    if a.epochs < 1 or not len(sp.train) or not len(sp.val) or vl["y30"].nunique() < 2:
        ap.error("positive epochs, nonempty train/validation, and two mature validation classes required")
    initial_weights = None
    if a.shared_initialization:
        import torch

        from harbinger.models.deep import HazardNet

        # train_deep resets this seed and constructs the same no-CNN/no-site network.
        # Capture INITIAL weights; copying the fitted network would invalidate comparison.
        torch.manual_seed(a.seed)
        initial = HazardNet(len(cols), sp.train.site_id.nunique(), 2, use_text=False, use_site=False)
        initial_weights = {
            "category": initial.cat_emb.weight.detach().numpy().copy(),
            "archetype": initial.arch_emb.weight.detach().numpy().copy(),
        }
        for name, layer in [
            ("hidden1", initial.trunk[0]),
            ("hidden2", initial.trunk[3]),
            ("hazard", initial.trunk[6]),
        ]:
            initial_weights[name] = [
                layer.weight.detach().numpy().T.copy(),
                layer.bias.detach().numpy().copy(),
            ]
    torch_b = train_deep(
        sp.train, sp.val, cols, use_text=False, use_site=False, epochs=a.epochs, seed=a.seed, verbose=False
    )
    auc_t = float(roc_auc_score(vl["y30"], torch_b.p_fail_within(vl, 30)))
    torch_nll = float(torch_b.meta["best_val_nll"])

    from harbinger.models.keras_parity import train_keras_hazard  # TF 는 여기서 처음 import 된다

    kr = train_keras_hazard(
        sp.train, sp.val, cols, epochs=a.epochs, seed=a.seed, initial_weights=initial_weights
    )
    mask = sp.val["label_valid"].to_numpy()
    auc_k = float(roc_auc_score(vl["y30"], kr["p30_val"][mask]))
    out = {
        "evaluation_role": "validation_reused_for_early_stopping",
        "independent_test": False,
        "initialization": "shared_pretraining_weights"
        if a.shared_initialization
        else "independent_framework_initializers",
        "training_note": "Batch shuffling and dropout remain framework-specific; no identical-training claim.",
        "seed": a.seed,
        "epochs_requested": a.epochs,
        "feature_sha256": hashlib.sha256(Path(a.features).read_bytes()).hexdigest(),
        "train_cutoff": sp.train_end.isoformat(),
        "validation_cutoff": sp.val_end.isoformat(),
        "mature_validation_rows": len(vl),
        "versions": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "torch", "keras")}
        | {"tensorflow": sys.modules["tensorflow"].__version__},
        "source_sha256": {
            str(p.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in [Path(__file__).resolve()]
            + [
                Path(__file__).resolve().parents[1] / "src/harbinger/models" / n
                for n in ("keras_parity.py", "deep.py", "common.py")
            ]
        },
        "torch": {
            "val_nll": torch_nll,
            "val_auroc_p30": auc_t,
            "n_params": torch_b.meta["n_params"],
            "active_params": torch_b.meta["n_params"] - torch_b.model.site_emb.weight.numel(),
        },
        "keras": {
            "val_nll": float(kr["val_nll"]),
            "val_auroc_p30": auc_k,
            "n_params": kr["n_params"],
            "epochs_run": kr["epochs_run"],
        },
        "rows": {"train": int(len(sp.train)), "val": int(len(sp.val))},
    }
    out["nll_gap"] = abs(out["torch"]["val_nll"] - out["keras"]["val_nll"])
    out["auroc_gap"] = abs(auc_t - auc_k)
    out["criteria"] = {"nll_gap_lt": 0.25, "auroc_gap_lt": 0.12}
    out["comparison_passed"] = bool(out["nll_gap"] < 0.25 and out["auroc_gap"] < 0.12)
    encoded = json.dumps(out, ensure_ascii=False, allow_nan=False)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(encoded + "\n")
    print(encoded)
    return 0 if np.isfinite(auc_t) and np.isfinite(auc_k) else 1


if __name__ == "__main__":
    sys.exit(main())
