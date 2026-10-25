import json

import numpy as np
import pandas as pd
import pytest
import torch

from harbinger.features.build import FEATURE_GROUPS
from harbinger.models.common import model_columns, split_by_time
from harbinger.models.deep import HazardNet, load_deep, save_deep, train_deep


def fit(tiny, **kwargs):
    split = split_by_time(tiny["X"], 5, 2)
    cols = model_columns(tiny["X"], tuple(g for g in FEATURE_GROUPS if g != "tx"))
    return train_deep(
        split.train.iloc[:96], split.val.iloc[:32], cols, epochs=2, batch=32, seed=17, verbose=False, **kwargs
    )


def test_absent_text_is_independent_of_cnn_bias():
    torch.manual_seed(4)
    model = HazardNet(2, 1, 5, missing_aware=True).eval()
    args = [
        torch.zeros(3, 2),
        *[torch.zeros(3, dtype=torch.long) for _ in range(3)],
        torch.zeros(3, 64, dtype=torch.long),
    ]
    with torch.no_grad():
        before = model(*args)
        for conv in model.convs:
            conv.bias.fill_(500)
        after = model(*args)
    torch.testing.assert_close(before, after, rtol=0, atol=0)
    args[-1][:, 0] = 1  # Unknown token still means present text.
    assert not torch.allclose(before, model(*args))


def test_missing_aware_rejects_derived_numeric_memo_features(tiny):
    split = split_by_time(tiny["X"], 5, 2)
    for feature in [
        "tx_len",
        "q_inspector_lazy_rate",
        "q_evidence_weight",
        "q_evidence_sum6",
        "ck_overall_wmean6",
    ]:
        with pytest.raises(ValueError, match="memo-derived"):
            train_deep(split.train, split.val, [feature], missing_aware=True, epochs=1)


@pytest.mark.parametrize("rate", [-0.1, 1.1, float("nan")])
def test_invalid_dropout_fails_early(tiny, rate):
    with pytest.raises(ValueError, match="memo_dropout"):
        fit(tiny, missing_aware=True, memo_dropout=rate)


def test_dropout_requires_safe_text_path(tiny):
    with pytest.raises(ValueError, match="missing_aware"):
        fit(tiny, memo_dropout=0.35)
    with pytest.raises(ValueError, match="use_text"):
        fit(tiny, missing_aware=True, use_text=False)


def test_training_dropout_and_inference_normalization(tiny, tmp_path):
    original = tiny["X"].head(4).copy(deep=True)
    bundle = fit(tiny, missing_aware=True, memo_dropout=1.0)
    assert bundle.meta["memo_rows_dropped"] == 96 * bundle.meta["epochs_run"]
    rows = pd.concat([original.iloc[:1]] * 4, ignore_index=True)
    rows["memo"] = ["", None, " \t\n", "새로운증상"]
    tensors = bundle.tensors(rows)
    assert not tensors[-1][:3].any() and tensors[-1][3].any()
    predictions = bundle.predict_proba(rows)
    np.testing.assert_array_equal(predictions[:3], np.repeat(predictions[0], 3))
    np.testing.assert_array_equal(predictions, bundle.predict_proba(rows))
    assert bundle.hazards(rows.iloc[:0]).shape == (0, 12)
    pd.testing.assert_frame_equal(original, tiny["X"].head(4))
    save_deep(bundle, tmp_path)
    restored = load_deep(tmp_path)
    assert restored.model.missing_aware
    np.testing.assert_array_equal(predictions, restored.predict_proba(rows))


def test_same_seed_repeats_new_training(tiny):
    a = fit(tiny, missing_aware=True, memo_dropout=0.35)
    b = fit(tiny, missing_aware=True, memo_dropout=0.35)
    np.testing.assert_array_equal(a.predict_proba(tiny["X"].head(8)), b.predict_proba(tiny["X"].head(8)))
    assert a.meta["memo_rows_dropped"] > 0


def test_legacy_checkpoint_without_new_metadata_still_loads(tiny, tmp_path):
    old = fit(tiny)
    save_deep(old, tmp_path)
    meta = json.loads((tmp_path / "deep_meta.json").read_text())
    meta.pop("missing_aware", None)
    (tmp_path / "deep_meta.json").write_text(json.dumps(meta))
    loaded = load_deep(tmp_path)
    assert not loaded.model.missing_aware
    np.testing.assert_array_equal(
        old.predict_proba(tiny["X"].head(8)), loaded.predict_proba(tiny["X"].head(8))
    )


def test_full_dropout_masks_actual_training_input_only(tiny, monkeypatch):
    seen = []
    forward = HazardNet.forward

    def observe(self, *args):
        seen.append((self.training, args[-1].detach().clone()))
        return forward(self, *args)

    monkeypatch.setattr(HazardNet, "forward", observe)
    fit(tiny, missing_aware=True, memo_dropout=1.0)
    training = [chars for train_mode, chars in seen if train_mode]
    validation = [chars for train_mode, chars in seen if not train_mode]
    assert training and all(not chars.any() for chars in training)
    assert validation and all(chars.any() for chars in validation)
