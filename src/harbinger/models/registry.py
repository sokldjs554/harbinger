"""모델 레지스트리 — 번들 저장/로드와 manifest.json 버전 관리.

번들 = HGB 분류기(+isotonic) · 이산위험 네트 · 에너지 회귀 · 피처 목록 · 학습 데이터 메타 · 평가 지표.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import joblib

from harbinger.models.deep import load_deep, save_deep


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return None


def _hash_features(features: list[str]) -> str:
    return hashlib.sha1("|".join(features).encode()).hexdigest()[:10]


def save_bundle(
    model_dir: Path,
    *,
    classifier,
    deep=None,
    energy=None,
    features: list[str],
    metrics: dict,
    data_meta: dict,
    version: str | None = None,
) -> str:
    model_dir.mkdir(parents=True, exist_ok=True)
    version = version or datetime.now().strftime("v%Y%m%d-%H%M%S")
    vdir = model_dir / version
    vdir.mkdir(parents=True, exist_ok=True)
    joblib.dump(classifier, vdir / "classifier.joblib")
    if deep is not None:
        save_deep(deep, vdir)
    if energy is not None:
        joblib.dump(energy, vdir / "energy.joblib")
    entry = {
        "version": version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "features": features,
        "feature_hash": _hash_features(features),
        "metrics": metrics,
        "data_meta": data_meta,
        "components": {"classifier": True, "deep": deep is not None, "energy": energy is not None},
    }
    (vdir / "bundle.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2))
    manifest_path = model_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"versions": []}
    manifest["versions"] = [v for v in manifest["versions"] if v["version"] != version] + [entry]
    manifest["latest"] = version
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return version


def load_bundle(model_dir: Path, version: str = "latest") -> dict:
    manifest = json.loads((model_dir / "manifest.json").read_text())
    if version == "latest":
        version = manifest["latest"]
    vdir = model_dir / version
    entry = json.loads((vdir / "bundle.json").read_text())
    out = {"version": version, "entry": entry, "classifier": joblib.load(vdir / "classifier.joblib")}
    out["deep"] = load_deep(vdir) if (vdir / "hazardnet.pt").exists() else None
    out["energy"] = joblib.load(vdir / "energy.joblib") if (vdir / "energy.joblib").exists() else None
    return out


def list_versions(model_dir: Path) -> list[dict]:
    p = model_dir / "manifest.json"
    if not p.exists():
        return []
    m = json.loads(p.read_text())
    return [
        {k: v[k] for k in ("version", "created_at", "git_sha", "feature_hash")}
        | {"headline": v["metrics"].get("headline", {})}
        for v in m["versions"]
    ]
