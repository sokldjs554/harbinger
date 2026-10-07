"""신호 근거표 — "체크리스트가 양호라고 했는데, 메모와 점검 품질이 그 뒤의 고장을 미리 알려 주는가"를 기술통계로 본다.

모델이 아니라 **피처 테이블만** 쓴다(라벨 유효 행 전체, 학습·검증·테스트 구분 없음). 즉 모델 성능 주장이 아니라
"이 합성 세계에서 신호가 데이터에 실제로 있는가"의 확인이다. 그리고 그 신호는 생성기가 넣은 가정이다
(docs/synthetic-generator.md §3·§5) — 실데이터에서는 이 표를 가장 먼저 다시 만들어야 한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (float(max(0.0, c - h)), float(min(1.0, c + h)))


def cell(y: pd.Series, mask: pd.Series) -> dict:
    sel = y[mask]
    n, k = int(len(sel)), int(sel.sum())
    lo, hi = wilson(k, n)
    return {"n": n, "k": k, "rate": (k / n) if n else float("nan"), "lo": lo, "hi": hi}


def signal_tables(X: pd.DataFrame) -> dict:
    v = X[X["label_valid"]]
    y = v["y30"]
    weak = v["tx_weak_score"] > 0
    judge = v["ck_overall"]
    good = judge == 0
    out: dict = {
        "n_rows": int(len(v)),
        "base_rate": float(y.mean()),
        "scope": "라벨 유효 점검 행 전체(학습·검증·테스트 합산) — 모델이 아니라 데이터의 기술통계",
    }
    out["by_judgement"] = {
        name: {"without_weak": cell(y, (judge == lvl) & ~weak), "with_weak": cell(y, (judge == lvl) & weak)}
        for name, lvl in (("good", 0), ("caution", 1), ("bad", 2))
    }
    cnt = v["tx_weak_on_good_sum6"].clip(upper=3).fillna(0).astype(int)
    out["good_by_weak_count"] = [
        {"label": lab, **cell(y, good & (cnt == c))}
        for c, lab in ((0, "0회"), (1, "1회"), (2, "2회"), (3, "3회 이상"))
    ]
    g = v[good & v["q_inspector_lazy_rate"].notna()]
    q = pd.qcut(g["q_inspector_lazy_rate"], 3, labels=False, duplicates="drop")
    labels = ["형식적 메모 적은 점검자", "중간", "형식적 메모 많은 점검자"]
    out["good_by_inspector"] = [
        {
            "label": labels[int(i)],
            "lazy_rate_median": float(g.loc[q == i, "q_inspector_lazy_rate"].median()),
            **cell(g["y30"], q == i),
        }
        for i in sorted(q.dropna().unique())
    ]
    short = v["q_dwell"] < 20
    out["good_by_dwell"] = {"short_under_20s": cell(y, good & short), "normal": cell(y, good & ~short)}
    return out
