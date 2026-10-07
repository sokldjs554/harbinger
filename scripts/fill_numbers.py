"""README/문서의 숫자를 artifacts 에서 채운다.

문서에 `<!-- num:KEY -->값<!-- /num -->` 마커를 두면 KEY 에 해당하는 실측값으로 바꾼다. `--check` 는 불일치가 있으면 실패한다(CI).
KEY 는 점 경로다: metrics.classifier.hgb_full.auroc 처럼 artifacts/<file>.json 안을 따라간다. 포맷은 `KEY|fmt` (예: |.3f, |.1%, |,d).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DOCS = [
    "README.md",
    "docs/evaluation.md",
    "docs/modeling.md",
    "docs/limitations.md",
    "docs/synthetic-generator.md",
    "docs/data-model.md",
]
PAT = re.compile(r"<!-- num:([^ ]+?) -->(.*?)<!-- /num -->", re.S)


def resolve(artifacts: Path, key: str):
    parts = key.split(".")
    data = json.loads((artifacts / f"{parts[0]}.json").read_text())
    cur = data
    for p in parts[1:]:
        if p == "__len__":
            cur = len(cur)
        elif isinstance(cur, list):
            cur = cur[int(p)]
        else:
            cur = cur[p]
    return cur


def fmt(v, spec: str | None) -> str:
    if spec is None:
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v)
    if spec.endswith("%"):
        return format(v, spec)
    if spec == ",d":
        return f"{int(round(v)):,}"
    return format(v, spec)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    mismatches, filled = [], 0
    for doc in DOCS:
        p = Path(doc)
        if not p.exists():
            continue
        text = p.read_text()

        def repl(m, doc=doc):
            nonlocal filled
            key, spec = (m.group(1).split("|") + [None])[:2]
            try:
                val = fmt(resolve(a.artifacts, key), spec)
            except Exception as e:  # 산출물 없음 — 그대로 둔다
                if a.check:
                    mismatches.append(f"{doc}: {key} 해석 실패 ({e!r})")
                return m.group(0)
            if val != m.group(2):
                mismatches.append(f"{doc}: {key} 문서={m.group(2)!r} 실측={val!r}")
                filled += 1
            return f"<!-- num:{m.group(1)} -->{val}<!-- /num -->"

        new = PAT.sub(repl, text)
        if not a.check and new != text:
            p.write_text(new)
    if a.check:
        if mismatches:
            print("\n".join(mismatches))
            print(f"{len(mismatches)}개 불일치 — `make numbers` 로 다시 채우세요")
            return 1
        print("docs numbers OK")
        return 0
    print(f"filled {filled} numbers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
