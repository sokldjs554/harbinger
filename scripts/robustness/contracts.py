"""Offline evaluation contracts. No production model or endpoint is changed."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, KFold

from harbinger.models.calibration import fit_isotonic, fit_platt, logloss

SCHEMES = ("row_random", "asset_group", "purged_time", "purged_time_asset")


def stable_seed(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


def perturb_memos(inspections, start, kind, rate, seed):
    if kind not in ("missing", "typo") or not np.isfinite(rate) or not 0 <= rate <= 1:
        raise ValueError("Expected missing/typo and finite rate in [0,1]")
    out = inspections.copy(deep=True)
    eligible = out.performed_at >= pd.Timestamp(start)
    counts = {
        "eligible_rows": int(eligible.sum()),
        "changed_rows": 0,
        "eligible_characters": 0,
        "deleted_characters": 0,
    }
    for idx, row in out.loc[eligible].iterrows():
        rng = np.random.default_rng(stable_seed(f"{seed}:{kind}:{row.inspection_id}"))
        text = str(row.memo) if pd.notna(row.memo) else ""
        if kind == "missing":
            new = "" if rng.random() < rate else text
        else:
            chars = []
            for char in text:
                if char.isspace():
                    chars.append(char)
                    continue
                counts["eligible_characters"] += 1
                if rng.random() < rate:
                    counts["deleted_characters"] += 1
                else:
                    chars.append(char)
            new = "".join(chars)
        counts["changed_rows"] += int(new != text)
        out.at[idx, "memo"] = new
    return out, counts | {"kind": kind, "requested_rate": rate, "seed": seed}


def calibration_splits(frame, scheme, seed):
    if scheme not in SCHEMES:
        raise ValueError("Unknown calibration scheme")
    n = len(frame)
    groups = pd.MultiIndex.from_frame(frame[["site_id", "asset_id"]]).factorize()[0]
    if scheme == "row_random":
        return list(KFold(5, shuffle=True, random_state=seed).split(frame)) if n >= 5 else []
    if scheme == "asset_group":
        return list(GroupKFold(5).split(frame, groups=groups)) if len(set(groups)) >= 5 else []
    if not n:
        return []
    times = pd.to_datetime(frame.t).reset_index(drop=True)
    start, end = times.min().normalize(), times.max().normalize() + pd.Timedelta(days=1)
    edges = pd.date_range(start, end, periods=5)
    buckets = np.array(
        [stable_seed(f"{s}:{a}") % 3 for s, a in zip(frame.site_id, frame.asset_id, strict=True)]
    )
    result = []
    for lo, hi in zip(edges[1:-1], edges[2:], strict=True):
        available = (times + pd.Timedelta(days=30) < lo).to_numpy()
        held = ((times >= lo) & (times < hi)).to_numpy()
        for group in range(3) if scheme == "purged_time_asset" else [None]:
            tr = available if group is None else available & (buckets != group)
            va = held if group is None else held & (buckets == group)
            if tr.any() and va.any():
                result.append((np.flatnonzero(tr), np.flatnonzero(va)))
    return result


def oof_predictions(p, y, splits):
    p, y = np.asarray(p), np.asarray(y)
    oof = {k: np.full(len(p), np.nan) for k in ("platt", "isotonic")}
    audit = []
    seen = set()
    for fold, (tr, va) in enumerate(splits):
        if set(tr) & set(va) or seen & set(va):
            raise ValueError("Calibration membership overlaps")
        seen.update(va)
        row = {"fold": fold, "fit_n": len(tr), "held_n": len(va)}
        if not len(tr) or not len(va) or len(np.unique(y[tr])) < 2:
            audit.append(row | {"status": "withheld", "reason": "empty fold or single-class fit"})
            continue
        for name, fn in (("platt", fit_platt), ("isotonic", fit_isotonic)):
            oof[name][va] = fn(p[tr], y[tr]).predict(p[va])
        audit.append(row | {"status": "evaluated"})
    return oof, audit


def select_calibration(p, y, oof, mask, min_gain=0.005):
    p, y, mask = np.asarray(p), np.asarray(y), np.asarray(mask, dtype=bool)
    valid = mask & np.isfinite(p)
    for v in oof.values():
        valid &= np.isfinite(v)
    info = {"method": "raw", "selection_n": int(valid.sum()), "min_gain": min_gain}
    if not valid.any() or len(np.unique(y[valid])) < 2:
        return None, info | {"status": "withheld", "scores": {}}
    scores = {}
    for name, v in {"raw": p, **oof}.items():
        scores[name] = {
            "logloss": logloss(v[valid], y[valid]),
            "brier": float(np.mean((v[valid] - y[valid]) ** 2)),
        }
    best = min(("platt", "isotonic"), key=lambda k: scores[k]["logloss"])
    method = best if scores[best]["logloss"] < scores["raw"]["logloss"] * (1 - min_gain) else "raw"
    cal = {"platt": fit_platt, "isotonic": fit_isotonic}[method](p, y) if method != "raw" else None
    return cal, info | {"method": method, "status": "evaluated", "scores": scores}


def latest_available(features, decision_at, delay_days):
    if delay_days < 0:
        raise ValueError("Negative delay")
    visible = features.loc[features.t <= pd.Timestamp(decision_at) - pd.Timedelta(days=delay_days)]
    return visible.sort_values(["t", "asset_id"]).groupby(["site_id", "asset_id"], sort=False).tail(1).copy()


def weekly_metrics(frame, k=10):
    if frame.empty or k < 1:
        raise ValueError("Empty decision set or invalid budget")
    selected = (
        frame.sort_values(["p", "asset_id"], ascending=[False, True])
        .groupby(["site_id", "decision_at"], sort=True)
        .head(k)
    )
    by = selected.groupby("site_id").y30.agg(["sum", "count"])
    return {
        "precision_at_k": float(selected.y30.mean()),
        "selected": len(selected),
        "decisions": selected.groupby(["site_id", "decision_at"]).ngroups,
        "per_site": {str(s): {"hits": int(r["sum"]), "selected": int(r["count"])} for s, r in by.iterrows()},
    }


def paired_site_interval(candidate, reference, seed=20260101, repeats=2000):
    sites = sorted(candidate["per_site"])
    if sites != sorted(reference["per_site"]):
        raise ValueError("Paired sites differ")

    def values(result):
        return np.array([[result["per_site"][s]["hits"], result["per_site"][s]["selected"]] for s in sites])

    c, r = values(candidate), values(reference)
    if not np.array_equal(c[:, 1], r[:, 1]):
        raise ValueError("Paired budgets differ")
    picks = np.random.default_rng(seed).integers(0, len(sites), size=(repeats, len(sites)))
    cs, rs = c[picks].sum(axis=1), r[picks].sum(axis=1)
    delta = cs[:, 0] / cs[:, 1] - rs[:, 0] / rs[:, 1]
    return {
        "difference": candidate["precision_at_k"] - reference["precision_at_k"],
        "ci95": np.quantile(delta, [0.025, 0.975]).tolist(),
        "site_clusters": len(sites),
        "bootstrap_repeats": repeats,
        "note": "conditional on this synthetic world; not real-world confidence",
    }


def rebuild_memos(base, tables, start, kind, rate, seed, fit_until, observation_end):
    from harbinger.features.build import build_features

    copied = dict(tables)
    copied["inspections"], damage = perturb_memos(tables["inspections"], start, kind, rate, seed)
    # Energy source is unchanged. Avoid re-fitting its expensive regression for memo-only perturbations.
    copied["energy"] = tables["energy"].iloc[:0].copy()
    altered = build_features(copied, fit_until=fit_until, data_end=observation_end, verbose=False)
    original = base.set_index("inspection_id", verify_integrity=True)
    assert set(altered.inspection_id) == set(original.index)
    for col in [c for c in base if c.startswith("en_")]:
        altered[col] = altered.inspection_id.map(original[col])
    past = base[base.t < start].set_index("inspection_id").sort_index()
    check = altered.set_index("inspection_id").loc[past.index]
    pd.testing.assert_frame_equal(past, check)
    pd.testing.assert_frame_equal(
        original[["y30", "event", "tte_days", "label_valid"]].sort_index(),
        altered.set_index("inspection_id")[["y30", "event", "tte_days", "label_valid"]].sort_index(),
    )
    return altered, damage


def decision_snapshot(features, tables, decision_at, delay_days, observation_end):
    from harbinger.features.build import _next_event
    from harbinger.features.refresh import Refresher

    decision_at = pd.Timestamp(decision_at)
    if decision_at + pd.Timedelta(days=30) > pd.Timestamp(observation_end):
        raise ValueError("Decision outcome is not mature")
    rows = latest_available(features, decision_at, delay_days)
    source_t = rows.t.copy()
    rows = Refresher(tables).apply(rows, decision_at)
    rows["source_t"] = source_t
    rows["decision_at"] = decision_at
    bd = tables["workorders"].loc[tables["workorders"]["type"] == "breakdown"].sort_values("opened_at")
    events = {a: g.opened_at.to_numpy() for a, g in bd.groupby("asset_id")}
    ts = np.full(len(rows), np.datetime64(decision_at.to_datetime64(), "ns"))
    days = _next_event(events, rows.asset_id.to_numpy(), ts)
    rows["y30"] = (days <= 30).astype(int)
    rows["label_valid"] = True
    return rows.set_index(["site_id", "asset_id"], drop=False).sort_index()
