"""전체 사이트 과거 재현(제품 순찰 목록, 보류 기간)의 요약을 artifacts/replay_summary.json 으로 저장한다.

    python scripts/make_replay_summary.py            # 약 1~2분
README·docs/evaluation.md 의 `replay_summary.*` 숫자 마커가 이 파일을 읽는다. 정적 데모 빌드도 같은 파일을 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--models", type=Path, default=Path("models"))
    ap.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    ap.add_argument("--k", type=int, default=10)
    a = ap.parse_args()
    os.environ["HARBINGER_DATA_DIR"] = str(a.data)
    os.environ["HARBINGER_MODEL_DIR"] = str(a.models)
    os.environ["HARBINGER_ARTIFACT_DIR"] = str(a.artifacts)
    os.environ["HARBINGER_DEMO_BOOTSTRAP"] = "0"
    from harbinger import config
    from harbinger.api.backtest import replay, summary_record
    from harbinger.api.store import Store

    config.settings = config.Settings()
    store = Store(config.settings)
    store.load()
    rep = replay(store, "all", None, None, 7, a.k)
    out = a.artifacts / "replay_summary.json"
    out.write_text(json.dumps(summary_record(rep), ensure_ascii=False, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
