from __future__ import annotations

from fastapi import APIRouter, Depends

from harbinger import __version__
from harbinger.api.deps import get_store
from harbinger.api.store import Store

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "harbinger", "version": __version__}


@router.get("/ready")
def ready(store: Store = Depends(get_store)) -> dict:
    return {
        "status": "ready",
        "model_version": store.bundle["version"],
        "assets": int(len(store.tables["assets"])),
        "feature_rows": int(len(store.X)),
    }


@router.get("/version")
def version(store: Store = Depends(get_store)) -> dict:
    e = store.bundle["entry"]
    return {
        "service": __version__,
        "model_version": store.bundle["version"],
        "git_sha": e.get("git_sha"),
        "feature_hash": e.get("feature_hash"),
        "n_features": len(e.get("features", [])),
        "headline_metrics": e.get("metrics", {}).get("headline"),
        "data": store.data_meta,
        "synthetic_data": bool(store.data_meta.get("synthetic", True)),
    }
