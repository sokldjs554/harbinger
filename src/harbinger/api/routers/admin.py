from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from harbinger.api.deps import get_store
from harbinger.api.store import Store

ARTIFACTS = {
    "metrics",
    "ablation",
    "calibration",
    "survival",
    "energy",
    "patrol",
    "loso",
    "importance",
    "signals",
    "keras_parity",
}

router = APIRouter(prefix="/v1", tags=["admin"])


@router.get("/models")
def models(store: Store = Depends(get_store)) -> dict:
    return store.models()


@router.get("/monitoring/drift")
def drift(window_days: int = Query(60, ge=7, le=365), store: Store = Depends(get_store)) -> dict:
    return store.drift(window_days)


@router.get("/artifacts/{name}")
def artifact(name: str, store: Store = Depends(get_store)) -> dict:
    """평가 산출물(JSON) — 콘솔의 모델 탭과 문서 숫자 채우기가 읽는다."""
    if name not in ARTIFACTS:
        raise HTTPException(404, f"알 수 없는 산출물: {name}")
    p = store.settings.artifact_dir / f"{name}.json"
    if not p.exists():
        raise HTTPException(404, f"산출물 없음: {name}")
    return json.loads(p.read_text())
