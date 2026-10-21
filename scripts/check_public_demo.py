"""Verify that Pages serves the exact browser-tested assets and model responses."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    base = args.url.rstrip("/") + "/"
    version = json.loads(Path("artifacts/metrics.json").read_text())["bundle_version"]
    files = ["index.html", "workbench.js", "workbench.css", "workbench-data.json", "example.csv"]
    for attempt in range(6):
        try:
            for name in files:
                with urlopen(base + name + "?verify=" + str(time.time_ns()), timeout=30) as response:
                    payload = response.read()
                expected = (Path("docs/demo") / name).read_bytes()
                assert hashlib.sha256(payload).digest() == hashlib.sha256(expected).digest(), name
                if name == "workbench-data.json":
                    data = json.loads(payload)
                    assert data["session"]["model_version"] == version
                    assert all(s["model_version"] == version for s in data["snapshots"].values())
            with urlopen(base + "walkthrough.mp4", timeout=30) as response:
                assert int(response.headers["Content-Length"]) > 10000
                assert b"ftyp" in response.read(32)
            print(
                f"Public demo verified: {base}; model={version}; {len(files)} matching assets; MP4 available"
            )
            return
        except (OSError, AssertionError, ValueError, KeyError):
            if attempt == 5:
                raise
            time.sleep(10)


if __name__ == "__main__":
    main()
