"""Content-addressed feature provenance. Never trust an unversioned parquet."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from harbinger.features.build import FEATURE_SEMANTICS_VERSION, build_features, load_tables

BOUNDARY_VERSION = 2


def cached_features(data_dir: Path, train_end: pd.Timestamp):
    tables = load_tables(data_dir)
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(data_dir.glob("*.parquet"))
        if p.name != "features.parquet"
    }
    meta_path = data_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    # Synthetic generator's declared observation interval is authoritative.
    end = (
        pd.Timestamp(meta["start"]) + pd.DateOffset(months=meta["months"])
        if meta.get("synthetic") and "start" in meta and "months" in meta
        else max(tables["inspections"].performed_at.max(), tables["workorders"].opened_at.max())
    )
    fit_until = min(tables["inspections"].performed_at.min() + pd.Timedelta(days=365), train_end)
    spec = {
        "boundary_version": BOUNDARY_VERSION,
        "feature_semantics_version": FEATURE_SEMANTICS_VERSION,
        "source_sha256": hashes,
        "fit_until": fit_until.isoformat(),
        "observation_end": end.isoformat(),
    }
    cache = data_dir / "features.parquet"
    manifest = data_dir / "features_meta.json"
    old = json.loads(manifest.read_text()) if manifest.exists() else {}
    if cache.exists() and old.get("provenance") == spec:
        x = pd.read_parquet(cache)
    else:
        x = build_features(tables, fit_until=fit_until, data_end=end)
        x.to_parquet(cache, index=False)
        manifest.write_text(json.dumps({"rows": len(x), "provenance": spec}, indent=2))
    return x, spec
