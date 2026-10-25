"""신호 근거표 — "체크리스트가 양호라고 했는데, 메모와 점검 품질이 그 뒤의 고장을 미리 알려 주는가"를 기술통계로 본다.

모델이 아니라 **피처 테이블만** 쓴다(라벨 유효 행 전체, 학습·검증·테스트 구분 없음). 즉 모델 성능 주장이 아니라
"이 합성 세계에서 신호가 데이터에 실제로 있는가"의 확인이다. 그리고 그 신호는 생성기가 넣은 가정이다
(docs/synthetic-generator.md §3·§5) — 실데이터에서는 이 표를 가장 먼저 다시 만들어야 한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BOOTSTRAP_SEED = 20261025
BOOTSTRAP_DRAWS = 2000
MIN_CLUSTERS = 5


def cell(frame: pd.DataFrame, mask: pd.Series) -> dict:
    """Resample contributing sites intact; estimate the pooled, row-weighted rate.

    Site-level totals are sufficient for this statistic and preserve all within-site
    asset, inspector and temporal repetitions. This does not model dependencies
    between sites, nor provide simultaneous intervals across cells.
    """
    sel = frame.loc[mask, ["site_id", "y30"]]
    n, k = int(len(sel)), int(sel["y30"].sum())
    sites = sel.groupby("site_id", sort=True, observed=True)["y30"].agg(["sum", "size"])
    clusters = len(sites)
    result = {
        "n": n,
        "k": k,
        "rate": (k / n) if n else None,
        "lo": None,
        "hi": None,
        "n_clusters": clusters,
        "ci_status": "ok",
    }
    if not n:
        result["ci_status"] = "empty"
    elif sel["site_id"].isna().any():
        result["ci_status"] = "missing_cluster_ids"
    elif clusters < MIN_CLUSTERS:
        result["ci_status"] = "insufficient_clusters"
    elif k in (0, n):
        result["ci_status"] = "single_outcome"
    else:
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        indices = rng.integers(0, clusters, size=(BOOTSTRAP_DRAWS, clusters))
        rates = sites["sum"].to_numpy()[indices].sum(axis=1) / sites["size"].to_numpy()[indices].sum(axis=1)
        result["lo"], result["hi"] = map(float, np.quantile(rates, [0.025, 0.975], method="linear"))
    return result


def signal_tables(X: pd.DataFrame) -> dict:
    v = X[X["label_valid"]]
    y = v["y30"]
    if not y.isin([0, 1]).all():
        raise ValueError("Label-valid rows require observed binary y30 outcomes")
    weak = v["tx_weak_score"] > 0
    judge = v["ck_overall"]
    good = judge == 0
    out: dict = {
        "n_rows": int(len(v)),
        "base_rate": float(y.mean()) if len(y) else None,
        "scope": "라벨 유효 점검 행 전체(학습·검증·테스트 합산) — 모델이 아니라 데이터의 기술통계",
        "uncertainty": {
            "method": "site_cluster_percentile_bootstrap",
            "cluster_column": "site_id",
            "confidence": 0.95,
            "seed": BOOTSTRAP_SEED,
            "draws": BOOTSTRAP_DRAWS,
            "minimum_clusters": MIN_CLUSTERS,
            "n_clusters": int(v["site_id"].nunique()),
            "estimand": "pooled_row_weighted_rate_within_each_cell",
            "resampling": "contributing_sites_with_replacement_preserving_all_within_site_rows",
            "quantile_method": "linear",
            "limitations": (
                "Descriptive synthetic-data intervals; five sites is a withholding floor, not a coverage guarantee. "
                "Assumes independent sites; cross-site inspector dependence is not covered. "
                "Pointwise intervals, not causal effects or simultaneous comparisons. "
                "No prespecified direction of change in interval width."
            ),
        },
    }
    out["by_judgement"] = {
        name: {"without_weak": cell(v, (judge == lvl) & ~weak), "with_weak": cell(v, (judge == lvl) & weak)}
        for name, lvl in (("good", 0), ("caution", 1), ("bad", 2))
    }
    cnt = v["tx_weak_on_good_sum6"].clip(upper=3).fillna(0).astype(int)
    out["good_by_weak_count"] = [
        {"label": lab, **cell(v, good & (cnt == c))}
        for c, lab in ((0, "0회"), (1, "1회"), (2, "2회"), (3, "3회 이상"))
    ]
    g = v[good & np.isfinite(v["q_inspector_lazy_rate"])]
    q = pd.qcut(g["q_inspector_lazy_rate"], 3, labels=False, duplicates="drop")
    labels = ["형식적 메모 적은 점검자", "중간", "형식적 메모 많은 점검자"]
    out["good_by_inspector"] = [
        {
            "label": labels[int(i)],
            "lazy_rate_median": float(g.loc[q == i, "q_inspector_lazy_rate"].median()),
            **cell(g, q == i),
        }
        for i in sorted(q.dropna().unique())
    ]
    short = v["q_dwell"] < 20
    out["good_by_dwell"] = {"short_under_20s": cell(v, good & short), "normal": cell(v, good & ~short)}
    return out
