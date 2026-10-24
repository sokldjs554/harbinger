"""Bind current synthetic artifacts, demo responses, and model version by SHA-256."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    target = Path("artifacts/release.json")
    if a.check:
        r = json.loads(target.read_text())
        for name, expected in r["sha256"].items():
            assert digest(Path(name)) == expected, f"Changed after release manifest: {name}"
        m = json.loads(Path("artifacts/metrics.json").read_text())
        d = json.loads(Path("docs/demo/workbench-data.json").read_text())
        assert m["bundle_version"] == d["session"]["model_version"] == r["model_version"]
        for snapshot in d["snapshots"].values():
            assert snapshot["model_version"] == r["model_version"]
            assert snapshot["computation"] == "saved-python-model-response"
        print("release artifact hashes and model versions match")
        return
    m = json.loads(Path("artifacts/metrics.json").read_text())
    files = list(Path("artifacts").glob("*.json")) + list(Path("src/harbinger").rglob("*.py"))
    files += list(Path("src/harbinger/console").glob("workbench.*"))
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
        "base_commit": "fd346c75ddae39fa6383096d7dd6adabccfdb044",
        "code_state": "current source snapshot with preserved historical synthetic model/demo artifacts; source hashes do not imply model retraining",
        "observation": m["observation"],
        "sha256": {str(p): digest(p) for p in sorted(files) if p != target},
        "source_note": "survival bin-edge correction applied after fitting; zero affected full train/val/test event rows (verification/survival-edge-impact.txt)",
    }
    target.write_text(json.dumps(r, ensure_ascii=False, indent=2))
    print("wrote", target)


if __name__ == "__main__":
    main()
