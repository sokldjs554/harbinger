"""Validation-only site routing. JSON policy files never deserialize model weights.

The model directory is an administrator-controlled trust boundary. Content hashes
provide integrity/provenance, not a signature against an administrator rewriting
both a policy and its evidence. Candidates always come from the loaded bundle.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASELINE = "baseline"
WEIGHTS = (
    "bundle.json",
    "classifier.joblib",
    "comparators.joblib",
    "hazardnet.pt",
    "deep_meta.json",
    "energy.joblib",
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _time(value):
    t = pd.Timestamp(value)
    if pd.isna(t):
        raise ValueError("missing timestamp")
    return t.tz_localize(None) if t.tz is None else t.tz_convert("UTC").tz_localize(None)


def _now():
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def _bounded(root, name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in {".", ".."}:
        raise ValueError("unsafe path")
    root = Path(root).resolve()
    target = root / name
    if target.resolve().parent != root:
        raise ValueError("unsafe path")
    return target


def bundle_hash(model_dir, bundle):
    directory = _bounded(model_dir, bundle["version"])
    hashes = {}
    for name in WEIGHTS:
        path = _bounded(directory, name)
        if path.exists():
            hashes[name] = sha256(path)
    if not {"bundle.json", "classifier.joblib"} <= hashes.keys():
        raise ValueError("missing bundle weights")
    return hashlib.sha256(_json(hashes)).hexdigest()


def candidates(bundle):
    return {
        BASELINE: bundle["classifier"],
        **{
            k: v
            for k, v in bundle.get("comparators", {}).items()
            if k in {"logistic", "without_text", "without_history"}
        },
    }


def _atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".policy-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def select_policy(
    model_dir,
    bundle,
    frame,
    *,
    validation_start,
    validation_end,
    test_start,
    observation_end,
    outcomes_complete,
    data_hash,
    min_rows=50,
    min_class=3,
    min_improvement=0.001,
    max_brier_regression=0.0,
):
    """Freeze selection using only mature validation rows, Brier score, fixed gates.

    test_start is a reserved future test boundary; this function never scores it.
    Training *and calibration* must finish before validation starts. created_at is
    wall time, so a policy cannot be backdated to historical validation snapshots.
    """
    start, end, test, observed = map(_time, (validation_start, validation_end, test_start, observation_end))
    provenance = bundle.get("entry", {}).get("metrics", {}).get("observation", {})
    if provenance.get("boundary_version") != 2 or not provenance.get("max_observed_at"):
        raise ValueError("missing model observation metadata")
    cutoff = _time(provenance["max_observed_at"])
    created = _time(_now())
    available = max(end + pd.Timedelta(days=30), created)
    if not outcomes_complete:
        raise ValueError("complete outcomes required")
    if (
        not cutoff < start <= end
        or end + pd.Timedelta(days=30) > min(observed, created)
        or not available < test
    ):
        raise ValueError("invalid temporal boundaries: mature validation and future held-out test required")
    if not re.fullmatch("[0-9a-f]{64}", data_hash):
        raise ValueError("data hash required")
    if min_rows < 2 or min_class < 1 or min_improvement < 0 or max_brier_regression < 0:
        raise ValueError("invalid selection gates")
    required = {"site_id", "asset_id", "t", "y30", "label_valid"}
    if not required <= set(frame):
        raise ValueError("missing outcomes or row metadata")
    rows = frame.loc[(frame.t >= start) & (frame.t <= end)].copy()
    if rows.empty or rows[list(required)].isna().any().any() or not rows.label_valid.eq(True).all():
        raise ValueError("missing or immature validation outcomes")
    if not rows.y30.isin([0, 1]).all() or rows.duplicated(["site_id", "asset_id", "t"]).any():
        raise ValueError("invalid outcomes or duplicate target rows")
    models = candidates(bundle)
    predictions = {}
    for name, model in models.items():
        p = np.asarray(model.predict_proba(rows), dtype=float)
        if p.shape != (len(rows),) or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
            raise ValueError("invalid candidate probabilities")
        predictions[name] = p
    sites, scores = {}, {}
    for site, positions in rows.groupby("site_id").indices.items():
        y = rows.iloc[positions].y30.to_numpy()
        score = {name: float(np.mean((p[positions] - y) ** 2)) for name, p in predictions.items()}
        scores[str(site)] = {"rows": len(y), "positives": int(y.sum()), "brier": score}
        if len(y) < min_rows or min(y.sum(), len(y) - y.sum()) < min_class:
            sites[str(site)] = {"model": BASELINE, "reason": "insufficient_sample"}
            continue
        best = min(score, key=lambda name: (score[name], name != BASELINE, name))
        improves = score[BASELINE] - score[best] >= min_improvement
        within_error = score[best] <= score[BASELINE] + max_brier_regression
        chosen = best if improves and within_error else BASELINE
        sites[str(site)] = {
            "model": chosen,
            "reason": "validation_brier" if chosen != BASELINE else "baseline_not_improved",
        }
    policy = {
        "schema": 1,
        "bundle_version": bundle["version"],
        "bundle_sha256": bundle_hash(model_dir, bundle),
        "data_sha256": data_hash,
        "created_at": created.isoformat(),
        "train_observed_until": cutoff.isoformat(),
        "validation_start": start.isoformat(),
        "validation_end": end.isoformat(),
        "observation_end": observed.isoformat(),
        "effective_from": available.isoformat(),
        "test_start": test.isoformat(),
        "outcomes_complete": True,
        "sites": sites,
        "gates": {
            "min_rows": min_rows,
            "min_class": min_class,
            "min_improvement": min_improvement,
            "max_brier_regression": max_brier_regression,
        },
    }
    evidence = {
        "policy": policy,
        "scores": scores,
        "targets": [
            {
                "site_id": str(r.site_id),
                "asset_id": str(r.asset_id),
                "t": r.t.isoformat(),
                "y30": int(r.y30),
                "probabilities": {name: float(p[i]) for name, p in predictions.items()},
            }
            for i, r in enumerate(rows.itertuples())
        ],
        "test_scored": False,
    }
    digest = hashlib.sha256(_json(evidence)).hexdigest()
    directory = _bounded(model_dir, "site-policy-evidence")
    _atomic(_bounded(directory, digest + ".json"), evidence)
    return {**policy, "evidence_sha256": digest}


def validate(model_dir, bundle, policy):
    if policy.get("schema") != 1 or policy["bundle_version"] != bundle["version"]:
        raise ValueError("bundle version mismatch")
    actual = bundle_hash(model_dir, bundle)
    if policy["bundle_sha256"] != actual or bundle.get("_policy_bundle_hash", actual) != actual:
        raise ValueError("bundle hash mismatch")
    digest = policy["evidence_sha256"]
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("invalid evidence hash")
    path = _bounded(_bounded(model_dir, "site-policy-evidence"), digest + ".json")
    if sha256(path) != digest:
        raise ValueError("evidence hash mismatch")
    evidence = json.loads(path.read_text())
    if (
        evidence["policy"] != {k: v for k, v in policy.items() if k != "evidence_sha256"}
        or evidence["test_scored"]
    ):
        raise ValueError("policy/evidence mismatch")
    cutoff, start, end, effective, test, created, observed = map(
        _time,
        (
            policy["train_observed_until"],
            policy["validation_start"],
            policy["validation_end"],
            policy["effective_from"],
            policy["test_start"],
            policy["created_at"],
            policy["observation_end"],
        ),
    )
    if not (
        cutoff < start <= end
        and end + pd.Timedelta(days=30) <= min(created, observed)
        and created <= _time(_now())
        and created <= effective < test
        and policy["outcomes_complete"] is True
    ):
        raise ValueError("invalid policy chronology")
    if any(v["model"] not in candidates(bundle) for v in policy["sites"].values()):
        raise ValueError("missing candidate")


def _read_active(model_dir):
    path = _bounded(model_dir, "site-policy.json")
    if not path.exists():
        return None
    active = json.loads(path.read_text())
    if not isinstance(active, dict):
        raise ValueError("invalid policy record")
    _time(active["recorded_at"])
    content = {k: v for k, v in active.items() if k != "revision"}
    if active["revision"] != hashlib.sha256(_json(content)).hexdigest():
        raise ValueError("revision hash mismatch")
    return active


@contextmanager
def _lock(model_dir):
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    with _bounded(model_dir, "site-policy.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _transition(model_dir, bundle, proposal, expected_revision, operation, target=None):
    if proposal is not None:
        validate(model_dir, bundle, proposal)
    elif operation != "rollback":
        raise ValueError("empty policy only allowed for baseline rollback")
    if operation == "activate" and _time(_now()) >= _time(proposal["test_start"]):
        raise ValueError("selection must be activated before held-out test")
    with _lock(model_dir):
        active = _read_active(model_dir)
        previous = active["revision"] if active else None
        if previous != expected_revision:
            raise ValueError("prior revision mismatch")
        payload = {
            "policy": proposal,
            "previous_revision": previous,
            "operation": operation,
            "recorded_at": _now(),
            "rollback_target": target,
        }
        revision = hashlib.sha256(_json(payload)).hexdigest()
        record = {**payload, "revision": revision}
        _atomic(_bounded(_bounded(model_dir, "site-policy-history"), revision + ".json"), record)
        _atomic(_bounded(model_dir, "site-policy.json"), record)
        return revision


def activate(model_dir, bundle, proposal, *, expected_revision):
    return _transition(model_dir, bundle, proposal, expected_revision, "activate")


def rollback(model_dir, bundle, revision, *, expected_revision):
    if revision is None:
        return _transition(model_dir, bundle, None, expected_revision, "rollback")
    if not re.fullmatch("[0-9a-f]{64}", revision):
        raise ValueError("unsafe revision")
    record = json.loads(_bounded(_bounded(model_dir, "site-policy-history"), revision + ".json").read_text())
    content = {k: v for k, v in record.items() if k != "revision"}
    if record["revision"] != revision or hashlib.sha256(_json(content)).hexdigest() != revision:
        raise ValueError("history revision mismatch")
    return _transition(model_dir, bundle, record["policy"], expected_revision, "rollback", revision)


def resolve_many(model_dir, bundle, site_ids, as_of):
    # One immutable snapshot per scoring call, including mixed-site requests.
    routes = {}
    active, invalid = None, False
    try:
        active = _read_active(model_dir)
        if active is not None and active["policy"] is not None:
            validate(model_dir, bundle, active["policy"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        invalid = True
    for site_id in site_ids:
        trace = {
            "selected_model": BASELINE,
            "policy_revision": active.get("revision") if active else None,
            "policy_reason": "no_policy",
        }
        model = bundle["classifier"]
        if invalid:
            trace["policy_reason"] = "invalid_policy"
        elif active is not None and active["policy"] is None:
            trace["policy_reason"] = "baseline_restored"
        elif active is not None:
            policy = active["policy"]
            if _time(as_of) < max(_time(policy["effective_from"]), _time(active["recorded_at"])):
                trace["policy_reason"] = "selection_not_available"
            else:
                choice = policy["sites"].get(str(site_id), {"model": BASELINE, "reason": "unlisted_site"})
                trace.update(selected_model=choice["model"], policy_reason=choice["reason"])
                if str(site_id) in policy["sites"]:
                    trace["policy_test_start"] = policy["test_start"]
                model = candidates(bundle)[choice["model"]]
        routes[str(site_id)] = model, trace
    return routes


def resolve(model_dir, bundle, site_id, as_of):
    return resolve_many(model_dir, bundle, [site_id], as_of)[str(site_id)]
