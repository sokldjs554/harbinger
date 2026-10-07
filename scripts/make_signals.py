"""artifacts/signals.json — 메모 약신호·점검 품질별 30일 고장률 기술통계 (피처 테이블만 필요)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from harbinger.eval.signals import signal_tables


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("artifacts/signals.json"))
    a = ap.parse_args()
    X = pd.read_parquet(a.data / "features.parquet")
    out = signal_tables(X)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"signals → {a.out}")


if __name__ == "__main__":
    main()
