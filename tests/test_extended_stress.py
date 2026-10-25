import numpy as np
import pandas as pd
import pytest
from scripts.extended_stress.contracts import (
    CONDITIONS,
    abbreviate,
    perturb,
    severity,
    substitute,
    verify_files,
)


def records(n=112):
    return pd.DataFrame(
        {
            "inspection_id": [f"i{i}" for i in range(n)],
            "asset_id": "a",
            "site_id": "s",
            "inspector_id": "p",
            "performed_at": pd.date_range("2025-01-01", periods=n),
            "memo": "소음 심함, 베어링 교체 필요",
            "y30": np.arange(n) % 2,
        }
    )


@pytest.mark.parametrize("kind", CONDITIONS[1:-1])
def test_deterministic_order_independent_posttrain_only(kind):
    raw = records()
    before = raw.copy(deep=True)
    got, counts = perturb(raw, "2025-01-10", kind, 123)
    shuffled, _ = perturb(raw.sample(frac=1, random_state=7), "2025-01-10", kind, 123)
    pd.testing.assert_frame_equal(got.sort_index(), shuffled.sort_index())
    pd.testing.assert_frame_equal(raw, before)
    pd.testing.assert_frame_equal(got.iloc[:9], raw.iloc[:9])
    pd.testing.assert_frame_equal(got.drop(columns="memo"), raw.drop(columns="memo"))
    assert counts["changed_rows"] > 0


@pytest.mark.parametrize("kind", ["cluster_asset", "cluster_inspector"])
def test_missingness_continuous_and_group_correlated(kind):
    raw = records()
    sibling = raw.assign(inspection_id=lambda f: f.inspection_id + "b")
    if kind == "cluster_inspector":
        sibling["asset_id"] = "b"
    data = pd.concat([raw, sibling], ignore_index=True)
    got, _ = perturb(data, "2025-01-01", kind, 42)
    missing = got.memo.eq("").to_numpy()
    np.testing.assert_array_equal(missing[:112], missing[112:])
    assert missing[:56].sum() == 28
    np.testing.assert_array_equal(missing[:56], missing[56:112])
    assert np.count_nonzero(missing[1:112] != missing[:111]) <= 4


def test_selective_missing_uses_observed_text_never_future_labels():
    raw = records(2000)
    raw["memo"] = ["정상", "소음 증가", "소음 심함", "누유 심함"] * 500
    a, count = perturb(raw, "2025-01-01", "selective_missing", 42)
    b, _ = perturb(raw.assign(y30=999), "2025-01-01", "selective_missing", 42)
    pd.testing.assert_series_equal(a.memo, b.memo)
    assert [severity(s) for s in ["정상", "소음 증가", "소음 심함"]] == ["low", "medium", "high"]
    rates = {k: v["removed"] / v["eligible"] for k, v in count["severity"].items()}
    assert rates["high"] > rates["medium"] > rates["low"]


def test_substitution_is_not_deletion_and_abbreviations_are_explicit():
    new, changed = substitute("소음 심함 ABC!", np.random.default_rng(1), rate=1)
    assert len(new) == len("소음 심함 ABC!") and new.endswith(" ABC!")
    assert changed == 4 and new != "소음 심함 ABC!"
    assert abbreviate("베어링 교체 필요, 필터 점검 완료") == "BRG 교체要, FLT 점검完"


def test_file_hash_mismatch_is_rejected(tmp_path):
    (tmp_path / "weights").write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_files(tmp_path, {"weights": "old"})


def test_raw_memo_rebuild_updates_text_features_and_preserves_history(tiny):
    from scripts.extended_stress.contracts import rebuild

    start = pd.Timestamp("2024-07-01")
    end = max(tiny["tables"]["inspections"].performed_at.max(), tiny["tables"]["workorders"].opened_at.max())
    out, counts = rebuild(
        tiny["X"], tiny["tables"], start, "cluster_asset", 42, tiny["X"].t.min() + pd.Timedelta(days=365), end
    )
    assert counts["changed_rows"] > 0
    assert (out.memo != tiny["X"].memo).any()
    assert (out.tx_len != tiny["X"].tx_len).any()


def test_existing_output_rejected_before_loading_weights(tmp_path):
    from argparse import Namespace

    from scripts.extended_stress.run import run

    (tmp_path / "data-202610251").mkdir()
    with pytest.raises(FileExistsError, match="overwrite"):
        run(Namespace(work=tmp_path / "absent", out=tmp_path, data_seed=202610251))
