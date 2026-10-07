"""순찰 시뮬레이션 — 테스트 기간의 날마다 "오늘 상위 k 개 설비"를 고르면 그중 몇 개가 30일 안에 실제로 고장나는가.

비교군: 라운드로빈(가장 오래 안 본 설비부터 — 현장의 기본 규칙), 무작위, 연식순, 마지막 점검 판정순.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from harbinger.config import HORIZON_DAYS
from harbinger.features.refresh import Refresher


def latest_rows_asof(X: pd.DataFrame, day: pd.Timestamp, max_age_days: int = 120) -> pd.DataFrame:
    """설비별로 day 이하 가장 최근 행. 너무 오래된 행(max_age_days 초과)은 제외."""
    sub = X[(X["t"] <= day) & (X["t"] > day - pd.Timedelta(days=max_age_days))]
    if sub.empty:
        return sub
    idx = sub.groupby("asset_id")["t"].idxmax()
    return sub.loc[idx]


def simulate_patrol(
    X_test: pd.DataFrame,
    score_fns: dict[str, Callable[[pd.DataFrame], np.ndarray]],
    breakdowns: pd.DataFrame,
    refresher: Refresher,
    k: int = 10,
    step_days: int = 7,
    seed: int = 0,
) -> dict:
    """매주 사이트마다 방법별 상위 k 를 뽑아 이후 30일의 실제 고장 비율을 센다.

    score_fns: 이름 → (행 DataFrame → 확률). 점수는 **그날(as_of)에 맞춰 시간 의존 피처를 갱신한 행**으로 매기므로,
    점검 뒤에 고장나 수리된 설비가 계속 고위험으로 남지 않는다. 운영 경로(Store.latest_rows)와 같은 갱신을 쓴다.
    """
    rng = np.random.default_rng(seed)
    bd = {k_: v["opened_at"].to_numpy() for k_, v in breakdowns.groupby("asset_id")}
    days = pd.date_range(
        X_test["t"].min().normalize() + pd.Timedelta(days=30),
        X_test["t"].max().normalize() - pd.Timedelta(days=HORIZON_DAYS),
        freq=f"{step_days}D",
    )
    rows = []
    for d in days:
        latest = latest_rows_asof(X_test, d)
        if latest.empty:
            continue
        latest = refresher.apply(latest, d).copy()
        for name, fn in score_fns.items():
            latest[f"score__{name}"] = fn(latest)
        latest["score__random"] = rng.random(len(latest))
        latest["score__round_robin"] = (d - latest["t"]).dt.total_seconds()
        latest["score__age"] = latest["st_age_years"]
        latest["score__last_inspection"] = (
            latest["ck_overall"] * 1000 + (d - latest["t"]).dt.total_seconds() / 86400
        )
        end = (d + pd.Timedelta(days=HORIZON_DAYS)).to_datetime64()
        d64 = d.to_datetime64()
        empty = np.array([], dtype="datetime64[ns]")
        latest["hit"] = [
            bool(np.any((bd.get(a, empty) > d64) & (bd.get(a, empty) <= end))) for a in latest["asset_id"]
        ]
        for _sid, g in latest.groupby("site_id"):
            kk = min(k, len(g))
            for col in [c for c in g.columns if c.startswith("score__")]:
                top = g.nlargest(kk, col)
                rows.append(
                    {
                        "day": d,
                        "method": col[7:],
                        "precision": float(top["hit"].mean()),
                        "base_rate": float(g["hit"].mean()),
                    }
                )
    res = pd.DataFrame(rows)
    if res.empty:
        return {"methods": {}, "days": 0}
    summary = res.groupby("method")["precision"].agg(["mean", "std", "count"]).reset_index()
    rr = (
        float(summary.loc[summary["method"] == "round_robin", "mean"].iloc[0])
        if (summary["method"] == "round_robin").any()
        else float("nan")
    )
    rnd = (
        float(summary.loc[summary["method"] == "random", "mean"].iloc[0])
        if (summary["method"] == "random").any()
        else float("nan")
    )
    methods = {}
    for _, r in summary.iterrows():
        methods[r["method"]] = {
            "precision_at_k": float(r["mean"]),
            "std": float(r["std"]),
            "n_site_days": int(r["count"]),
            "lift_vs_round_robin": float(r["mean"] / rr) if rr and rr > 0 else float("nan"),
            "lift_vs_random": float(r["mean"] / rnd) if rnd and rnd > 0 else float("nan"),
        }
    return {
        "k": k,
        "days": int(res["day"].nunique()),
        "base_rate": float(res["base_rate"].mean()),
        "methods": methods,
        "per_archetype": None,
        "scored_at": "as_of(시간 의존 피처 갱신)",
    }


def breakdown_recall_at_top(
    X_test: pd.DataFrame, p: np.ndarray, breakdowns: pd.DataFrame, top_frac: float = 0.2
) -> dict:
    """테스트 기간 고장 각각에 대해, 고장 직전 마지막 점검 때 그 설비가 사이트 상위 top_frac 위험 목록에 있었는가."""
    X = X_test[["asset_id", "site_id", "t"]].copy()
    X["p"] = p
    X = X.sort_values("t")
    hits, total = 0, 0
    for _, b in breakdowns.iterrows():
        prior = X[
            (X["asset_id"] == b["asset_id"])
            & (X["t"] < b["opened_at"])
            & (X["t"] >= b["opened_at"] - pd.Timedelta(days=60))
        ]
        if prior.empty:
            continue
        last = prior.iloc[-1]
        # 같은 사이트, 같은 시점 기준 최근 행들과 비교
        peers = latest_rows_asof(X[X["site_id"] == b["site_id"]], last["t"])
        if len(peers) < 5:
            continue
        thr = peers["p"].quantile(1 - top_frac)
        total += 1
        hits += int(last["p"] >= thr)
    return {
        "top_frac": top_frac,
        "breakdowns_evaluated": total,
        "recall": float(hits / total) if total else float("nan"),
    }
