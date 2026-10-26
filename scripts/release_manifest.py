"""Bind current synthetic artifacts, demo responses, and model version by SHA-256."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def training_context(metrics, path=Path("artifacts/training-provenance.json")):
    record = json.loads(path.read_text()) if path.exists() else None
    if record and record["model_version"] != metrics["bundle_version"]:
        raise ValueError("Training provenance model differs from published model")
    return {
        "base_commit": record.get("base_commit") if record else None,
        "training_provenance": record,
        "code_state": "Published source snapshot; see separate training provenance for fitted model source",
        "source_note": "Source hashes alone do not establish when or with which code a model was fitted.",
    }


def verify_observations(artifact_dir=Path("artifacts")):
    reference = json.loads((artifact_dir / "patrol.json").read_text()).get("observations")
    if reference:
        assert digest(artifact_dir / reference["file"]) == reference["sha256"], "Patrol observations changed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    target = Path("artifacts/release.json")
    verify_observations()
    if a.check:
        r = json.loads(target.read_text())
        for name, expected in r["sha256"].items():
            assert digest(Path(name)) == expected, f"Changed after release manifest: {name}"
        m = json.loads(Path("artifacts/metrics.json").read_text())
        d = json.loads(Path("docs/demo/workbench-data.json").read_text())
        assert m["bundle_version"] == d["session"]["model_version"] == r["model_version"]
        assert r["training_provenance"] == training_context(m)["training_provenance"]
        for snapshot in d["snapshots"].values():
            assert snapshot["model_version"] == r["model_version"]
            assert snapshot["computation"] == "saved-python-model-response"
        print("release artifact hashes and model versions match")
        return
    m = json.loads(Path("artifacts/metrics.json").read_text())
    files = list(Path("artifacts").glob("*.json")) + list(Path("src/harbinger").rglob("*.py"))
    files += list(Path("artifacts").glob("*.json.gz"))
    files += list(Path("src/harbinger/console").glob("workbench.*"))
    files += [p for p in Path("src/harbinger/console").iterdir() if p.is_file()]
    files += [
        Path("src/harbinger/console/index.html"),
        Path("src/harbinger/console/reports.js"),
        Path("constraints.txt"),
    ]
    files += [
        Path("docs/demo") / n
        for n in [
            "index.html",
            "workbench.js",
            "workbench.css",
            "reports.js",
            "workbench-data.json",
            "example.csv",
        ]
    ]
    r = {
        "model_version": m["bundle_version"],
        "synthetic": True,
        **training_context(m),
        "observation": m["observation"],
        "sha256": {str(p): digest(p) for p in sorted(set(files)) if p != target},
    }
    target.write_text(json.dumps(r, ensure_ascii=False, indent=2))
    print("wrote", target)


if __name__ == "__main__":
    main()
