"""Keras 패리티 검사 — 별도 프로세스에서 PyTorch 위험 네트와 Keras 구현을 같은 분할로 학습해 결과를 JSON 으로 출력한다.

    python scripts/keras_parity_check.py --features data/features.parquet --epochs 12
TF 와 torch 를 한 프로세스에 함께 올릴 때의 충돌을 피하기 위해 torch 학습을 먼저 끝내고 그 다음 TF 를 import 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings

warnings.filterwarnings("ignore")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--train-months", type=int, default=5)
    ap.add_argument("--val-months", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    import numpy as np
    import pandas as pd
    from sklearn.metrics import roc_auc_score

    from harbinger.models.common import labeled, model_columns, split_by_time
    from harbinger.models.deep import train_deep

    X = pd.read_parquet(a.features)
    sp = split_by_time(X, a.train_months, a.val_months)
    cols = model_columns(X)
    torch_b = train_deep(
        sp.train, sp.val, cols, use_text=False, use_site=False, epochs=a.epochs, seed=a.seed, verbose=False
    )
    vl = labeled(sp.val)
    auc_t = float(roc_auc_score(vl["y30"], torch_b.p_fail_within(vl, 30)))
    torch_nll = float(torch_b.meta["best_val_nll"])

    from harbinger.models.keras_parity import train_keras_hazard  # TF 는 여기서 처음 import 된다

    kr = train_keras_hazard(sp.train, sp.val, cols, epochs=a.epochs, seed=a.seed)
    mask = sp.val["label_valid"].to_numpy()
    auc_k = float(roc_auc_score(vl["y30"], kr["p30_val"][mask]))
    out = {
        "torch": {"val_nll": torch_nll, "val_auroc_p30": auc_t, "n_params": torch_b.meta["n_params"]},
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
    print(json.dumps(out, ensure_ascii=False))
    return 0 if np.isfinite(auc_t) and np.isfinite(auc_k) else 1


if __name__ == "__main__":
    sys.exit(main())
