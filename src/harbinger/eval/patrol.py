"""순찰 시뮬레이션 — 테스트 기간의 날마다 "오늘 상위 k 개 설비"를 고르면 그중 몇 개가 30일 안에 실제로 고장나는가.

비교군: 라운드로빈(가장 오래 안 본 설비부터 — 현장의 기본 규칙), 무작위, 연식순, 마지막 점검 판정순.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from harbinger.config import HORIZON_DAYS
from harbinger.eval.patrol_summary import summarize_patrol_rows
from harbinger.features.refresh import Refresher
from harbinger.prescribe.priority import select_patrol


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
    *,
    assets: pd.DataFrame | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    evaluation_days=None,
    max_age_days: int = 120,
) -> dict:
    """Report raw top-K risk separately from actual mandatory/criticality selection.

    Pass full historical features plus inclusive start/end snapshot bounds to
    reproduce Store.latest_rows eligibility (source t > day - 120 days). The
    caller must end snapshots at least HORIZON_DAYS before observation ends.
    Without bounds, retain the historical test-frame date range. score_fns are
    learned probability scores; built-in rule priorities keep their own scales.
    """
    if k < 1 or step_days < 1 or max_age_days < 1:
        raise ValueError("k, step_days and max_age_days must be positive")
    if evaluation_days is not None and (start is not None or end is not None):
        raise ValueError("use evaluation_days or start/end, not both")
    rules = {"random", "round_robin", "age", "recent_repair", "last_inspection"}
    if rules.intersection(score_fns):
        raise ValueError("learned methods cannot replace built-in rule names")
    rng = np.random.default_rng(seed)
    bd = {a: v["opened_at"].to_numpy() for a, v in breakdowns.groupby("asset_id")}
    if X_test.empty:
        days = []
    elif evaluation_days is not None:
        days = sorted(set(pd.to_datetime(evaluation_days)))
    else:
        days = pd.date_range(
            pd.Timestamp(start)
            if start is not None
            else X_test["t"].min().normalize() + pd.Timedelta(days=30),
            pd.Timestamp(end)
            if end is not None
            else X_test["t"].max().normalize() - pd.Timedelta(days=HORIZON_DAYS),
            freq=f"{step_days}D",
        )
    rows, service_rows, snapshots = [], [], []
    for d in days:
        latest = latest_rows_asof(X_test, d, max_age_days=max_age_days)
        if latest.empty:
            continue
        if assets is not None:
            cols = [
                c
                for c in ("category", "name", "zone", "st_floor", "st_criticality")
                if c in assets and c not in latest
            ]
            latest = latest.merge(
                assets[["asset_id", *cols]], on="asset_id", how="left", validate="many_to_one"
            )
        latest = refresher.apply(latest, d).copy()
        for name, fn in score_fns.items():
            values = np.asarray(fn(latest), dtype=float)
            if (
                values.shape != (len(latest),)
                or not np.isfinite(values).all()
                or ((values < 0) | (values > 1)).any()
            ):
                raise ValueError(f"{name} must return one finite probability in [0, 1] per asset")
            latest[f"score__{name}"] = values
        latest["score__random"] = rng.random(len(latest))
        latest["score__round_robin"] = (d - latest["t"]).dt.total_seconds()
        latest["score__age"] = latest["st_age_years"]
        latest["score__recent_repair"] = -latest["wo_days_since_bd"].fillna(10000)
        latest["score__last_inspection"] = (
            latest["ck_overall"] * 1000 + (d - latest["t"]).dt.total_seconds() / 86400
        )
        end64 = (d + pd.Timedelta(days=HORIZON_DAYS)).to_datetime64()
        empty = np.array([], dtype="datetime64[ns]")
        latest["hit"] = [
            bool(np.any((bd.get(a, empty) > d.to_datetime64()) & (bd.get(a, empty) <= end64)))
            for a in latest["asset_id"]
        ]
        for sid, g in latest.groupby("site_id"):
            candidate_ids = sorted(g.asset_id.astype(str).tolist())
            # The production selector computes mandatory status once per score;
            # every comparator receives the same candidate rows and date.
            snapshot = dict(
                site_id=str(sid),
                day=d.isoformat(),
                candidate_asset_ids=candidate_ids,
                source_t={str(r.asset_id): r.t.isoformat() for r in g.itertuples()},
            )
            snapshots.append(snapshot)
            for col in [c for c in g.columns if c.startswith("score__")]:
                name = col[7:]
                raw = g.sort_values([col, "asset_id"], ascending=[False, True]).head(k)
                service = select_patrol(g, d, k, score_column=col, probability_score=name in score_fns)
                mandatory_ids = sorted(service.loc[service.mandatory, "asset_id"].astype(str).tolist())
                optional = g.loc[~g.asset_id.astype(str).isin(mandatory_ids)]
                random_hits = float(service.loc[service.mandatory, "hit"].sum())
                optional_slots = len(service) - len(mandatory_ids)
                if optional_slots:
                    random_hits += optional_slots * float(optional.hit.mean())
                for target, selected, kind in (
                    (rows, raw, "raw_risk"),
                    (service_rows, service, "service_policy"),
                ):
                    target.append(
                        dict(
                            day=d.isoformat(),
                            site_id=str(sid),
                            method=name,
                            hits=int(selected.hit.sum()),
                            positives=int(g.hit.sum()),
                            picks=len(selected),
                            precision=float(selected.hit.mean()),
                            base_rate=float(g.hit.mean()),
                            random_expected_precision=random_hits / len(service)
                            if kind == "service_policy"
                            else float(g.hit.mean()),
                            requested_k=k,
                            mandatory_count=len(mandatory_ids),
                            overflow=max(0, len(selected) - k),
                            candidate_asset_ids=candidate_ids,
                            mandatory_asset_ids=mandatory_ids,
                            selected_asset_ids=selected.asset_id.astype(str).tolist(),
                            score_kind="probability" if name in score_fns else "rule_priority",
                            selection=kind,
                        )
                    )
    result = summarize_patrol_rows(pd.DataFrame(rows), seed=seed)
    service_result = summarize_patrol_rows(pd.DataFrame(service_rows), seed=seed, service_policy=True)
    service_result.update(
        rows=service_rows,
        k=k,
        selection="all mandatory assets; remaining budget by probability × criticality or unchanged rule priority",
    )
    result.update(
        k=k,
        rows=rows,
        service_policy=service_result,
        snapshots=snapshots,
        per_archetype=None,
        scored_at="as_of(시간 의존 피처 갱신)",
        provenance=dict(
            max_age_days=max_age_days,
            source_timestamp="t",
            eligible="day-max_age_days < t <= day",
            start=days[0].isoformat() if len(days) else None,
            end=days[-1].isoformat() if len(days) else None,
            horizon_days=HORIZON_DAYS,
            bootstrap_seed=seed,
            bootstrap_replicates=2000,
            tie_break="asset_id ascending",
            selector="harbinger.prescribe.priority.select_patrol",
        ),
    )
    return result


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
        "recall": float(hits / total) if total else None,
    }
