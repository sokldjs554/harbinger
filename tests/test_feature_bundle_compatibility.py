"""A feature semantic change must not silently reuse a differently trained model."""

import json
import shutil

import pandas as pd
import pytest

from harbinger.api.store import Store
from harbinger.config import Settings


@pytest.mark.parametrize("operation", ["ingest", "whatif", "upload"])
def test_legacy_bundle_cannot_rebuild_current_features(trained, operation):
    from fastapi import HTTPException

    from harbinger.api.routers.workbench import create_upload
    from harbinger.api.upload import export_example

    store = Store(
        Settings(
            data_dir=trained["data"],
            model_dir=trained["models"],
            artifact_dir=trained["artifacts"],
            demo_bootstrap=False,
        )
    )
    store.load()
    # Simulate an otherwise readable historical bundle. Rebuilding must fail
    # before touching its tables/cache, regardless of input changes.
    store.bundle["entry"]["feature_semantics_version"] = 2
    before = store.tables["inspections"].copy(deep=True)
    features_before = store.X.copy(deep=True)
    site = str(store.tables["sites"].site_id.iloc[0])
    asset = str(store.tables["assets"].query("site_id == @site").asset_id.iloc[0])
    if operation == "upload":
        content = export_example(store.tables, site, store.data_end - pd.Timedelta(seconds=1))
        with pytest.raises(HTTPException, match="재학습") as err:
            create_upload(content, str(store.data_end.date()), store)
        assert err.value.status_code == 422
    elif operation == "whatif":
        with pytest.raises(ValueError, match="재학습"):
            store.whatif(site, asset, [{"items": {}, "memo": "점검"}])
    else:
        row = before[before.site_id == site].iloc[0]
        record = {
            "inspection_id": "legacy-rebuild-probe",
            "asset_id": row.asset_id,
            "inspector_id": row.inspector_id,
            "scheduled_at": row.scheduled_at,
            "performed_at": row.performed_at,
            "method": row.method,
            "dwell_seconds": 60,
            "overall": 1,
            "items": {},
            "memo": "점검",
            "photo_count": 0,
        }
        with pytest.raises(ValueError, match="재학습"):
            store.ingest_inspections(site, [record])
    pd.testing.assert_frame_equal(store.tables["inspections"], before)
    pd.testing.assert_frame_equal(store.X, features_before)


@pytest.mark.parametrize(
    "cache_version,model_version,shared_inspector,allowed",
    [
        (2, 2, True, True),
        (3, 3, True, True),
        (3, 2, False, False),
        (3, None, False, False),
        (None, None, False, True),
        (1, 1, True, False),
        (99, 99, False, False),
    ],
)
def test_load_requires_compatible_feature_semantics(
    trained, tmp_path, cache_version, model_version, shared_inspector, allowed
):
    data, models = tmp_path / "data", tmp_path / "models"
    shutil.copytree(trained["data"], data)
    shutil.copytree(trained["models"], models)
    meta_path = data / "features_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["provenance"]["feature_semantics_version"] = cache_version
    meta_path.write_text(json.dumps(meta))
    manifest = json.loads((models / "manifest.json").read_text())
    bundle_path = models / manifest["latest"] / "bundle.json"
    bundle = json.loads(bundle_path.read_text())
    bundle["feature_semantics_version"] = model_version
    bundle["metrics"]["observation"]["feature_semantics_version"] = model_version
    bundle_path.write_text(json.dumps(bundle))
    if shared_inspector:
        inspections = pd.read_parquet(data / "inspections.parquet")
        inspections["inspector_id"] = "reused-across-sites"
        inspections.to_parquet(data / "inspections.parquet", index=False)
    store = Store(
        Settings(data_dir=data, model_dir=models, artifact_dir=trained["artifacts"], demo_bootstrap=False)
    )
    if allowed:
        store.load()
        assert len(store.X) > 0
    else:
        with pytest.raises(RuntimeError, match="(?i)semantics"):
            store.load()
