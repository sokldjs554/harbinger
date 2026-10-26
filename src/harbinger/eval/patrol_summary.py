"""Site-equal patrol estimates and paired site-cluster uncertainty."""

from __future__ import annotations

import numpy as np
import pandas as pd


def summarize_patrol_rows(rows: pd.DataFrame, *, seed: int = 0, service_policy: bool = False) -> dict:
    """Average days within sites, then sites; bootstrap those same site means.

    Comparisons require the same site/day, candidate assets, mandatory assets and
    requested budget. Incomplete panels retain descriptive means but withhold
    uncertainty. Paired deltas use only complete, comparable site/day rows.
    """
    metric = "selection_hit_rate" if service_policy else "precision_at_k"
    info = {
        "estimand": "equal-site mean of within-site daily hit rates",
        "uncertainty": "2000 paired site-cluster bootstrap; all days/assets within a site kept together; synthetic sites only",
        "methods": {},
        "days": 0,
        "base_rate": None,
        "random_expected_precision": None,
    }
    if rows.empty:
        return info
    if rows.duplicated(["site_id", "day", "method"]).any():
        raise ValueError("duplicate method/site/day rows")
    names = sorted(rows.method.unique())
    valid_keys = []
    for key, group in rows.groupby(["site_id", "day"], sort=True):
        same_assets = group.candidate_asset_ids.map(lambda x: tuple(sorted(x))).nunique() == 1
        same_mandatory = group.mandatory_asset_ids.map(lambda x: tuple(sorted(x))).nunique() == 1
        if (
            set(group.method) == set(names)
            and same_assets
            and same_mandatory
            and group.requested_k.nunique() == 1
        ):
            valid_keys.append(key)
    keys = pd.MultiIndex.from_frame(rows[["site_id", "day"]])
    paired = rows.loc[keys.isin(valid_keys)]
    complete = len(paired) == len(rows)
    wide = paired.pivot(index=["site_id", "day"], columns="method", values="precision")
    paired_sites = wide.groupby(level="site_id").mean()
    n_sites = len(paired_sites)
    status = (
        "available"
        if complete and n_sites >= 2
        else ("incomplete_pairs" if not complete else "fewer_than_two_sites")
    )
    ix = (
        np.random.default_rng(seed).integers(0, n_sites, size=(2000, n_sites))
        if status == "available"
        else None
    )
    means = rows.groupby(["method", "site_id"]).precision.mean().groupby("method").mean()
    for name in names:
        subset = rows[rows.method == name]
        site_means = subset.groupby("site_id").precision.mean()
        estimate = float(site_means.mean())
        reference = "last_inspection"
        diff = (
            (paired_sites[name] - paired_sites[reference])
            if (name in paired_sites and reference in paired_sites and n_sites)
            else None
        )
        item = {
            metric: estimate,
            f"historical_date_weighted_{metric}": float(subset.precision.mean()),
            "std": float(site_means.std()) if len(site_means) > 1 else None,
            "n_site_days": len(subset),
            "n_sites": len(site_means),
            "n_paired_site_days": len(wide),
            "n_paired_sites": n_sites,
            "uncertainty_status": status,
            "site_cluster_ci95": np.quantile(
                paired_sites[name].to_numpy()[ix].mean(axis=1), [0.025, 0.975]
            ).tolist()
            if ix is not None
            else None,
            "delta_vs_last_inspection": float(diff.mean()) if diff is not None else None,
            "delta_vs_last_inspection_ci95": np.quantile(
                diff.to_numpy()[ix].mean(axis=1), [0.025, 0.975]
            ).tolist()
            if ix is not None and diff is not None
            else None,
            "hits": int(subset.hits.sum()),
            "picks": int(subset.picks.sum()),
            "positives": int(subset.positives.sum()),
            "historical_pooled_recall": float(subset.hits.sum() / subset.positives.sum())
            if subset.positives.sum()
            else None,
        }
        # Recall uses the same site/day weighting, omitting undefined zero-positive days.
        recalls = subset.assign(recall=subset.hits / subset.positives.replace(0, np.nan))
        recall = recalls.groupby("site_id").recall.mean().mean()
        item["selection_recall" if service_policy else "recall_at_k"] = (
            float(recall) if pd.notna(recall) else None
        )
        for baseline in ("round_robin", "random"):
            denominator = means.get(baseline, 0)
            item[f"lift_vs_{baseline}"] = estimate / denominator if denominator > 0 and complete else None
        if service_policy:
            item.update(
                mandatory_count=int(subset.mandatory_count.sum()),
                overflow=int(subset.overflow.sum()),
                overflow_site_days=int((subset.overflow > 0).sum()),
            )
        info["methods"][name] = item
    # One base-rate observation per site/day, independent of number of methods.
    base = rows.drop_duplicates(["site_id", "day"]).groupby("site_id").base_rate.mean().mean()
    expected = (
        rows.drop_duplicates(["site_id", "day"]).groupby("site_id").random_expected_precision.mean().mean()
        if "random_expected_precision" in rows
        else base
    )
    info.update(
        days=int(rows.day.nunique()),
        base_rate=float(base),
        random_expected_precision=float(expected),
        historical_date_weighted_base_rate=float(rows.drop_duplicates(["site_id", "day"]).base_rate.mean()),
        pairing=dict(
            complete=complete,
            n_common_site_days=len(wide),
            n_common_sites=n_sites,
            excluded_method_rows=len(rows) - len(paired),
        ),
    )
    return info
