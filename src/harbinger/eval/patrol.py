"""순찰 시뮬레이션 — 테스트 기간의 날마다 "오늘 상위 k 개 설비"를 고르면 그중 몇 개가 30일 안에 실제로 고장나는가.

비교군: 라운드로빈(가장 오래 안 본 설비부터 — 현장의 기본 규칙), 무작위, 연식순, 마지막 점검 판정순.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harbinger.config import HORIZON_DAYS


def latest_rows_asof(X: pd.DataFrame, day: pd.Timestamp, max_age_days: int = 120) -> pd.DataFrame:
    """설비별로 day 이하 가장 최근 행. 너무 오래된 행(max_age_days 초과)은 제외."""
    sub = X[(X["t"] <= day) & (X["t"] > day - pd.Timedelta(days=max_age_days))]
    if sub.empty:
        return sub
    idx = sub.groupby("asset_id")["t"].idxmax()
    return sub.loc[idx]


def simulate_patrol(
    X_test: pd.DataFrame,
    scores: dict[str, np.ndarray],
    breakdowns: pd.DataFrame,
    k: int = 10,
    step_days: int = 7,
    seed: int = 0,
) -> dict:
    """scores: 이름 → X_test 와 같은 길이의 점수 배열. 반환: 방법별 precision@k, 라운드로빈 대비 lift, 날 수."""
    rng = np.random.default_rng(seed)
    X = X_test.copy()
    for name, s in scores.items():
        X[f"score__{name}"] = s
    X["score__random"] = rng.random(len(X))
    bd = {k_: v["opened_at"].to_numpy() for k_, v in breakdowns.groupby("asset_id")}
    days = pd.date_range(
        X["t"].min().normalize() + pd.Timedelta(days=30),
        X["t"].max().normalize() - pd.Timedelta(days=HORIZON_DAYS),
        freq=f"{step_days}D",
    )
    rows = []
    for d in days:
        latest = latest_rows_asof(X, d)
        if latest.empty:
            continue
        latest = latest.copy()
        latest["score__round_robin"] = (d - latest["t"]).dt.total_seconds()
        latest["score__age"] = latest["st_age_years"]
        latest["score__last_inspection"] = (
            latest["ck_overall"] * 1000 + (d - latest["t"]).dt.total_seconds() / 86400
        )
        end = (d + pd.Timedelta(days=HORIZON_DAYS)).to_datetime64()
        d64 = d.to_datetime64()
        hit = np.array(
            [
                bool(
                    np.any(
                        (bd.get(a, np.array([], dtype="datetime64[ns]")) > d64)
                        & (bd.get(a, np.array([], dtype="datetime64[ns]")) <= end)
                    )
                )
                for a in latest["asset_id"]
            ]
        )
        latest["hit"] = hit
        for sid, g in latest.groupby("site_id"):
            kk = min(k, len(g))
            for col in [c for c in g.columns if c.startswith("score__")]:
                top = g.nlargest(kk, col)
                rows.append(
                    {
                        "day": d,
                        "site_id": sid,
                        "method": col[7:],
                        "precision": float(top["hit"].mean()),
                        "k": kk,
                        "base_rate": float(g["hit"].mean()),
                        "n_assets": int(len(g)),
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
    methods = {}
    for _, r in summary.iterrows():
        methods[r["method"]] = {
            "precision_at_k": float(r["mean"]),
            "std": float(r["std"]),
            "n_site_days": int(r["count"]),
            "lift_vs_round_robin": float(r["mean"] / rr) if rr and rr > 0 else float("nan"),
        }
    per_arch = None
    return {
        "k": k,
        "days": int(res["day"].nunique()),
        "base_rate": float(res["base_rate"].mean()),
        "methods": methods,
        "per_archetype": per_arch,
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
