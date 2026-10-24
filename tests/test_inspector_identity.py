"""Inspector history belongs to a site, while assets within that site share it."""

import json

import pandas as pd
import pytest

from harbinger.features.build import build_features, feature_columns
from harbinger.features.cache import cached_features


def _tables(rows):
    inspections = pd.DataFrame(rows)
    inspections["performed_at"] = pd.to_datetime(inspections.pop("day"))
    inspections["scheduled_at"] = inspections["performed_at"]
    inspections["method"] = "manual"
    inspections["photo_count"] = 0
    assets = (
        inspections[["asset_id", "site_id"]]
        .drop_duplicates()
        .assign(category="pump", criticality=1, floor=1, installed=pd.Timestamp("2020-01-01"))
    )
    return {
        "inspections": inspections,
        "assets": assets,
        "sites": assets[["site_id"]].drop_duplicates().assign(archetype="office"),
        "workorders": pd.DataFrame(
            {
                "asset_id": pd.Series(dtype=str),
                "site_id": pd.Series(dtype=str),
                "type": pd.Series(dtype=str),
                "opened_at": pd.Series(dtype="datetime64[ns]"),
            }
        ),
        "energy": pd.DataFrame(),
    }


def _row(record, site, asset, day, memo, overall, dwell, inspector="person-1"):
    return {
        "inspection_id": record,
        "site_id": site,
        "asset_id": asset,
        "inspector_id": inspector,
        "day": f"2024-01-{day:02d}",
        "memo": memo,
        "overall": overall,
        "dwell_seconds": dwell,
    }


def _build(rows):
    return (
        build_features(
            _tables(rows),
            fit_until=pd.Timestamp("2024-01-01"),
            data_end=pd.Timestamp("2024-03-01"),
            verbose=False,
        )
        .set_index("inspection_id")
        .sort_index()
    )


@pytest.mark.parametrize("other_inspector", ["person-1", "person-2"])
def test_other_site_history_cannot_change_existing_site_features(other_inspector):
    own = [
        _row("a1", "site-a", "asset-a", 2, "압력 측정 1", 1, 60),
        _row("a2", "site-a", "asset-a", 4, "압력 측정 2", 2, 120),
        _row("a3", "site-a", "asset-a", 6, "압력 측정 3", 1, 180),
    ]
    unrelated = [
        _row(f"b{i}", "site-b", "asset-b", day, "양호", 0, 10, other_inspector)
        for i, day in enumerate([1, 3, 5], start=1)
    ]
    before = _build(own)
    after = _build(own + unrelated).loc[before.index]
    pd.testing.assert_frame_equal(before[feature_columns(before)], after[feature_columns(after)])
    assert after.loc["a3", "q_inspector_lazy_rate"] == 0
    assert after.loc["a3", "q_inspector_good_rate"] == 0
    assert after.loc["a3", "q_inspector_dwell_med"] == 120


def test_same_site_inspector_history_combines_across_assets():
    rows = [
        _row("a1", "site-a", "asset-a", 1, "양호", 0, 30),
        _row("a2", "site-a", "asset-b", 2, "압력 측정 2", 2, 60),
        _row("a3", "site-a", "asset-c", 3, "압력 측정 3", 0, 90),
    ]
    result = _build(rows)
    assert result.loc[["a1", "a2"], "q_inspector_lazy_rate"].isna().all()
    assert result.loc["a3", "q_inspector_lazy_rate"] == pytest.approx(1 / 3)
    assert result.loc["a3", "q_inspector_good_rate"] == pytest.approx(2 / 3)
    assert result.loc["a3", "q_inspector_dwell_med"] == 60
    assert result.loc["a3", "q_evidence_weight"] == pytest.approx(0.75)


def test_cache_rebuilds_features_without_current_inspector_identity_provenance(tmp_path):
    rows = [_row(f"a{i}", "site-a", "asset-a", i, f"압력 측정 {i}", 1, 60) for i in range(1, 4)]
    tables = _tables(rows)
    tables["inspectors"] = tables["inspections"][["site_id", "inspector_id"]].drop_duplicates()
    for name, frame in tables.items():
        frame.to_parquet(tmp_path / f"{name}.parquet", index=False)
    cached, _ = cached_features(tmp_path, pd.Timestamp("2024-01-01"))
    cached["q_inspector_lazy_rate"] = 0.9
    cached.to_parquet(tmp_path / "features.parquet", index=False)
    manifest_path = tmp_path / "features_meta.json"
    old = json.loads(manifest_path.read_text())
    old["provenance"].pop("feature_semantics_version", None)
    manifest_path.write_text(json.dumps(old))

    rebuilt, _ = cached_features(tmp_path, pd.Timestamp("2024-01-01"))

    assert rebuilt.set_index("inspection_id").loc["a3", "q_inspector_lazy_rate"] == 0
