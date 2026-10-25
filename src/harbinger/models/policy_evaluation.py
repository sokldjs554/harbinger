"""Fixed paired ranking contract. Bootstrap bounds are sensitivity checks, not joint coverage."""

from __future__ import annotations

import numpy as np
import pandas as pd

CONTRACT = dict(
    budget=10,
    max_age_days=120,
    step_days=30,
    min_dates=4,
    min_span_days=90,
    min_assets=50,
    min_class=3,
    min_brier_improvement=0.001,
    replicates=2000,
    seed=20261026,
    alpha=0.05,
    quantile_method="linear",
)


def snapshots(frame, tables, start, end):
    from harbinger.features.refresh import Refresher

    dates = pd.date_range(start, end, freq="30D")
    refresher = Refresher(tables)
    parts = []
    grid = {}
    for date in dates:
        latest = (
            frame.loc[frame.t <= date].sort_values("t").drop_duplicates(["site_id", "asset_id"], keep="last")
        )
        for site in tables["assets"].site_id.astype(str).unique():
            previous = latest.loc[latest.site_id.astype(str).eq(site)]
            grid[(site, date.isoformat())] = dict(
                stale_assets=int((previous.t < date - pd.Timedelta(days=120)).sum()),
                missing_assets=int(tables["assets"].site_id.astype(str).eq(site).sum() - len(previous)),
            )
        latest = latest.loc[latest.t >= date - pd.Timedelta(days=120)].copy()
        latest["inspection_t"] = latest.t
        latest = refresher.apply(latest, date)
        latest["t"] = date
        wo = tables["workorders"]
        ids = wo.loc[
            (wo.type == "breakdown") & (wo.opened_at > date) & (wo.opened_at <= date + pd.Timedelta(days=30)),
            "asset_id",
        ]
        latest["y30"] = latest.asset_id.isin(ids).astype(int)
        latest["label_valid"] = True
        parts.append(latest)
    rows = pd.concat(parts, ignore_index=True)
    rows.attrs["grid"] = grid
    return rows, list(map(str, tables["assets"].site_id.unique())), dates


def _score(y, p, ids):
    order = np.lexsort((np.asarray(ids, dtype=str), -p))[:10]
    return np.array([y[order].mean(), ((p - y) ** 2).mean()])


def evaluate(rows, predictions, sites, dates, min_rows=50, min_class=3, min_improvement=0.001):
    names = sorted(n for n in predictions if n != "baseline")
    scores, choices = {}, {}
    q = 0.05 / max(1, len(names)) / 2
    for site in sites:
        positions = np.flatnonzero(rows.site_id.astype(str).eq(str(site)))
        sub = rows.iloc[positions]
        groups = [np.flatnonzero(sub.t.eq(d)) for d in dates]
        y = sub.y30.to_numpy(float)
        ids = sub.asset_id.astype(str).to_numpy()
        p = {n: np.asarray(v)[positions] for n, v in predictions.items()}
        counts = [
            dict(
                t=d.isoformat(), assets=len(g), positives=int(y[g].sum()), negatives=int(len(g) - y[g].sum())
            )
            for d, g in zip(dates, groups)
        ]
        eligibility = []
        if len(dates) < 4 or (dates[-1] - dates[0]).days < 90:
            eligibility.append("insufficient_dates")
        if any(len(g) < min_rows for g in groups):
            eligibility.append("insufficient_sample")
        if any(min(y[g].sum(), len(g) - y[g].sum()) < min_class for g in groups):
            eligibility.append("insufficient_classes")
        for count in counts:
            count.update(
                rows.attrs.get("grid", {}).get(
                    (str(site), count["t"]), dict(stale_assets=0, missing_assets=0)
                )
            )
        record = dict(dates=counts, candidates={}, reasons=eligibility)
        qualified = []
        if not eligibility:
            base = np.array([_score(y[g], p["baseline"][g], ids[g]) for g in groups])
            # Shared, paired asset draws across every candidate; histories retained together.
            rng = np.random.default_rng(CONTRACT["seed"])
            assets = np.unique(ids)
            asset_samples = {n: [] for n in names}
            invalid = 0
            # An asset appears at most once per date; lookup keeps clone histories paired.
            lookups = [{a: int(i) for i, a in zip(g, ids[g])} for g in groups]
            draws = rng.choice(assets, (CONTRACT["replicates"], len(assets)), replace=True)
            for draw in draws:
                gs = []
                for lookup in lookups:
                    sample = np.array([lookup.get(a, -1) for a in draw])
                    valid = sample >= 0
                    gs.append((sample[valid], np.flatnonzero(valid).astype(str)))
                if any(len(g) < 10 for g, _ in gs):
                    invalid += 1
                    continue
                for n in names:
                    diffs = []
                    for g, clone in gs:
                        b = _score(y[g], p["baseline"][g], clone)
                        c = _score(y[g], p[n][g], clone)
                        diffs.append([c[0] - b[0], b[1] - c[1]])
                    asset_samples[n].append(np.mean(diffs, axis=0))
            date_draws = rng.integers(0, len(groups), size=(CONTRACT["replicates"], len(groups)))
            for n in names:
                candidate = np.array([_score(y[g], p[n][g], ids[g]) for g in groups])
                delta = np.column_stack((candidate[:, 0] - base[:, 0], base[:, 1] - candidate[:, 1]))
                point = delta.mean(axis=0)
                date_bound = np.quantile(delta[date_draws].mean(axis=1), q, axis=0, method="linear")
                asset_bound = (
                    None if invalid else np.quantile(asset_samples[n], q, axis=0, method="linear").tolist()
                )
                reasons = []
                if point[0] <= 0:
                    reasons.append("precision_not_improved")
                if point[1] < min_improvement:
                    reasons.append("brier_not_improved")
                if (delta[:, 0] < 0).any():
                    reasons.append("date_precision_regression")
                if invalid:
                    reasons.append("undersized_asset_bootstrap")
                if (
                    asset_bound is None
                    or asset_bound[0] < 0
                    or asset_bound[1] <= 0
                    or date_bound[0] < 0
                    or date_bound[1] <= 0
                ):
                    reasons.append("uncertainty_failed")
                record["candidates"][n] = dict(
                    precision_delta=float(point[0]),
                    brier_improvement=float(point[1]),
                    per_date_delta=delta.tolist(),
                    baseline_scores=base.tolist(),
                    candidate_scores=candidate.tolist(),
                    asset_lower=asset_bound,
                    date_lower=date_bound.tolist(),
                    invalid_asset_replicates=invalid,
                    quantile=q,
                    quantile_method="linear",
                    seed=CONTRACT["seed"],
                    replicates=2000,
                    reasons=reasons,
                )
                if not reasons:
                    qualified.append((n, point))
        chosen = sorted(qualified, key=lambda item: (-item[1][0], -item[1][1], item[0]))
        choices[str(site)] = dict(
            model=chosen[0][0] if chosen else "baseline",
            reason="paired_ranking"
            if chosen
            else ("insufficient_sample" if eligibility else "candidate_gates_failed"),
        )
        scores[str(site)] = record
    return dict(sites=choices, scores=scores)
