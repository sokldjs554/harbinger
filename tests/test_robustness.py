import numpy as np
import pandas as pd
import pytest
from scripts.robustness.contracts import (
    calibration_splits,
    latest_available,
    oof_predictions,
    perturb_memos,
    select_calibration,
    weekly_metrics,
)


def records():
    return pd.DataFrame(
        [
            {
                "inspection_id": str(i),
                "performed_at": pd.Timestamp("2025-07-01") + pd.Timedelta(days=i),
                "memo": "모터 소음 증가",
            }
            for i in range(20)
        ]
    )


def test_memo_damage_preserves_past_and_is_order_independent():
    data = records()
    out, info = perturb_memos(data, pd.Timestamp("2025-07-10"), "missing", 1.0, 7)
    pd.testing.assert_frame_equal(out.iloc[:9], data.iloc[:9])
    assert out.iloc[9:].memo.eq("").all()
    assert info["changed_rows"] == 11
    other, _ = perturb_memos(
        data.sample(frac=1, random_state=4), pd.Timestamp("2025-07-10"), "missing", 1.0, 7
    )
    pd.testing.assert_frame_equal(out.sort_index(), other.sort_index())
    assert data.memo.eq("모터 소음 증가").all()


def test_typo_is_nonspace_character_deletion_with_measured_rate():
    data = records()
    out, info = perturb_memos(data, pd.Timestamp("2025-01-01"), "typo", 1.0, 7)
    assert out.memo.eq("  ").all()
    assert info["deleted_characters"] == info["eligible_characters"]


@pytest.mark.parametrize("rate", [-0.1, 1.1, np.nan])
def test_invalid_damage_rate(rate):
    with pytest.raises(ValueError):
        perturb_memos(records(), pd.Timestamp("2025-01-01"), "missing", rate, 7)


def validation():
    return pd.DataFrame(
        [
            {"site_id": "s", "asset_id": f"a{a}", "t": t, "y30": (a + t.day) % 2}
            for t in pd.date_range("2025-01-01", periods=170, freq="D")
            for a in range(12)
        ]
    )


def test_group_and_calendar_purge_apply_together():
    data = validation()
    seen = []
    for tr, va in calibration_splits(data, "purged_time_asset", 7):
        assert len(tr) and len(va)
        assert set(data.iloc[tr].asset_id).isdisjoint(data.iloc[va].asset_id)
        assert (data.iloc[tr].t + pd.Timedelta(days=30)).max() < data.iloc[va].t.min()
        seen.extend(va)
    assert seen and len(seen) == len(set(seen))
    assert len(seen) < len(data)  # warm-up is not silently scored


def test_group_split_never_shares_an_asset():
    data = validation()
    for tr, va in calibration_splits(data, "asset_group", 7):
        assert set(data.iloc[tr].asset_id).isdisjoint(data.iloc[va].asset_id)


def test_calibration_sparse_folds_are_withheld_and_mask_is_shared():
    data = validation()
    p = np.full(len(data), 0.2)
    oof, notes = oof_predictions(p, np.zeros(len(data)), calibration_splits(data, "row_random", 7))
    assert all(n["status"] == "withheld" for n in notes)
    _, info = select_calibration(p, np.zeros(len(data)), oof, np.ones(len(data), dtype=bool))
    assert info["status"] == "withheld" and info["method"] == "raw"
    y = data.y30.to_numpy()
    oof, _ = oof_predictions(p, y, calibration_splits(data, "row_random", 7))
    mask = np.arange(len(data)) % 3 == 0
    _, info = select_calibration(p, y, oof, mask)
    assert info["selection_n"] == mask.sum()
    assert set(info["scores"]) == {"raw", "platt", "isotonic"}


def test_latest_record_is_only_available_after_delay_boundary():
    data = pd.DataFrame(
        {
            "asset_id": ["a", "a", "b"],
            "site_id": ["s"] * 3,
            "t": pd.to_datetime(["2025-07-01", "2025-07-08", "2025-07-09"]),
            "memo": ["old", "new", "future"],
        }
    )
    out = latest_available(data, pd.Timestamp("2025-07-10"), 3)
    assert out.asset_id.tolist() == ["a"] and out.memo.tolist() == ["old"]
    assert latest_available(data, pd.Timestamp("2025-07-11"), 3).memo.tolist() == ["new"]


def test_weekly_top_k_uses_same_budget_and_deterministic_ties():
    f = pd.DataFrame(
        {
            "site_id": ["s"] * 3,
            "decision_at": ["2025-07-01"] * 3,
            "asset_id": ["c", "b", "a"],
            "y30": [0, 0, 1],
            "p": [0.4] * 3,
        }
    )
    out = weekly_metrics(f, k=2)
    assert out["precision_at_k"] == 0.5
    assert out["selected"] == 2 and out["decisions"] == 1


def test_delayed_snapshots_keep_decision_labels_and_reject_immature(tiny):
    from scripts.robustness.contracts import decision_snapshot

    at = pd.Timestamp("2024-08-01")
    end = pd.Timestamp("2024-11-01")
    a = decision_snapshot(tiny["X"], tiny["tables"], at, 0, end)
    b = decision_snapshot(tiny["X"], tiny["tables"], at, 7, end)
    ids = a.index.intersection(b.index)
    pd.testing.assert_series_equal(a.loc[ids, "y30"], b.loc[ids, "y30"])
    assert (b.source_t <= at - pd.Timedelta(days=7)).all()
    assert (b.decision_at == at).all()
    with pytest.raises(ValueError, match="mature"):
        decision_snapshot(tiny["X"], tiny["tables"], end, 0, end)


def test_rebuilt_memos_leave_past_features_and_targets_unchanged(tiny):
    from scripts.robustness.contracts import rebuild_memos

    start = pd.Timestamp("2024-07-01")
    out, _ = rebuild_memos(
        tiny["X"],
        tiny["tables"],
        start,
        "missing",
        1.0,
        7,
        tiny["X"].t.min() + pd.Timedelta(days=365),
        max(tiny["tables"]["inspections"].performed_at.max(), tiny["tables"]["workorders"].opened_at.max()),
    )
    before = tiny["X"].set_index("inspection_id").sort_index()
    after = out.set_index("inspection_id").sort_index()
    pd.testing.assert_frame_equal(before[before.t < start], after.loc[before[before.t < start].index])
    pd.testing.assert_frame_equal(
        before[["y30", "event", "tte_days", "label_valid"]],
        after[["y30", "event", "tte_days", "label_valid"]],
    )


def test_completed_output_is_refused_before_preparation(tmp_path, monkeypatch):
    from argparse import Namespace

    from scripts.robustness import run as runner

    output = tmp_path / "results" / "data-20260101"
    output.mkdir(parents=True)
    sentinel = output / "provenance.json"
    sentinel.write_text("previous evidence")
    called = []
    monkeypatch.setattr(runner, "prepare", lambda args: called.append(True))
    with pytest.raises(FileExistsError):
        runner.run(Namespace(out=tmp_path / "results", data_seed=20260101))
    assert not called and sentinel.read_text() == "previous evidence"


def test_world_cache_rejects_untracked_or_different_source(tmp_path):
    from scripts.robustness.run import validate_world_cache

    expected = {"seed": 1, "code": "sha-a"}
    validate_world_cache(tmp_path, expected)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "meta.json").write_text("{}")
    with pytest.raises(ValueError, match="provenance"):
        validate_world_cache(tmp_path, expected)
    (tmp_path / "world-provenance.json").write_text('{"seed":1,"code":"sha-a"}')
    validate_world_cache(tmp_path, expected)
    with pytest.raises(ValueError, match="provenance"):
        validate_world_cache(tmp_path, {"seed": 1, "code": "sha-b"})
