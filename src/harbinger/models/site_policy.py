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
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from harbinger.models.policy_evaluation import CONTRACT, evaluate, snapshots

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
    tables=None,
    min_rows=50,
    min_class=3,
    min_improvement=0.001,
    max_brier_regression=0.0,
):
    """Freeze paired top-10/Brier selection on mature snapshots and fixed gates.

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
    if min_rows < 50 or min_class < 3 or min_improvement < 0.001 or max_brier_regression != 0:
        raise ValueError("fixed selection gates cannot be weakened")
    required = {"site_id", "asset_id", "t", "y30", "label_valid"}
    if not required <= set(frame):
        raise ValueError("missing outcomes or row metadata")
    dates = pd.date_range(start, end, freq="30D")
    all_sites = sorted(frame.site_id.astype(str).unique())
    if tables is not None:
        rows, all_sites, dates = snapshots(frame, tables, start, end)
    else:
        rows = frame.loc[frame.t.isin(dates)].copy()
        # Direct callers must supply already aligned, explicitly labelled snapshots.
        if not rows.empty and "inspection_t" not in rows:
            rows = rows.iloc[:0]
    if rows[list(required)].isna().any().any() or not rows.label_valid.eq(True).all():
        raise ValueError("missing or immature validation outcomes")
    if not rows.y30.isin([0, 1]).all() or rows.duplicated(["site_id", "asset_id", "t"]).any():
        raise ValueError("invalid outcomes or duplicate target rows")
    if len(rows):
        inspection = pd.to_datetime(rows.inspection_t)
        if (
            inspection.isna().any()
            or (inspection > rows.t).any()
            or (inspection < rows.t - pd.Timedelta(days=120)).any()
        ):
            raise ValueError("invalid snapshot inspection age")
    models = candidates(bundle)
    predictions = {}
    for name, model in models.items():
        p = np.asarray(model.predict_proba(rows), dtype=float) if len(rows) else np.array([])
        if p.shape != (len(rows),) or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
            raise ValueError("invalid candidate probabilities")
        predictions[name] = p
    evaluation = evaluate(rows, predictions, all_sites, dates, min_rows, min_class, min_improvement)
    sites, scores = evaluation["sites"], evaluation["scores"]
    policy = {
        "schema": 2,
        "contract": CONTRACT.copy(),
        "candidate_family": sorted(models),
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
                "inspection_t": r.inspection_t.isoformat(),
                "probabilities": {name: float(p[i]) for name, p in predictions.items()},
            }
            for i, r in enumerate(rows.itertuples())
        ],
        "grid": [
            {"site_id": site, "t": t, **counts} for (site, t), counts in rows.attrs.get("grid", {}).items()
        ],
        "test_scored": False,
    }
    digest = hashlib.sha256(_json(evidence)).hexdigest()
    directory = _bounded(model_dir, "site-policy-evidence")
    _atomic(_bounded(directory, digest + ".json"), evidence)
    return {**policy, "evidence_sha256": digest}


@lru_cache(maxsize=16)
def _cached_decision(canonical_inputs: bytes) -> bytes:
    """Cache only deterministic computation by immutable content, never trust checks.

    Return immutable bytes so callers cannot poison cached results by mutation.
    """
    value = json.loads(canonical_inputs)
    rows = pd.DataFrame(
        value["targets"], columns=["site_id", "asset_id", "t", "y30", "inspection_t", "probabilities"]
    )
    rows["t"] = pd.to_datetime(rows.t)
    rows.attrs["grid"] = {
        (r["site_id"], r["t"]): {k: v for k, v in r.items() if k not in {"site_id", "t"}}
        for r in value["grid"]
    }
    predictions = {n: np.array([r["probabilities"][n] for r in value["targets"]]) for n in value["family"]}
    dates = pd.date_range(value["start"], value["end"], freq="30D")
    gates = value["gates"]
    return _json(
        evaluate(
            rows,
            predictions,
            value["sites"],
            dates,
            gates["min_rows"],
            gates["min_class"],
            gates["min_improvement"],
        )
    )


def validate(model_dir, bundle, policy):
    if policy.get("schema") != 2 or policy["bundle_version"] != bundle["version"]:
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
    if policy.get("contract") != CONTRACT or policy.get("candidate_family") != sorted(candidates(bundle)):
        raise ValueError("fixed contract or candidate family mismatch")
    gates = policy["gates"]
    if (
        gates["min_rows"] < 50
        or gates["min_class"] < 3
        or gates["min_improvement"] < 0.001
        or gates["max_brier_regression"] != 0
        or not all(np.isfinite(v) for v in gates.values())
    ):
        raise ValueError("invalid fixed gates")
    targets = evidence["targets"]
    rows = pd.DataFrame(targets, columns=["site_id", "asset_id", "t", "y30", "inspection_t", "probabilities"])
    rows["t"] = pd.to_datetime(rows.t)
    dates = pd.date_range(_time(policy["validation_start"]), _time(policy["validation_end"]), freq="30D")
    if len(rows) and (
        rows.duplicated(["site_id", "asset_id", "t"]).any()
        or not rows.t.isin(dates).all()
        or not rows.y30.isin([0, 1]).all()
    ):
        raise ValueError("invalid decision targets")
    if len(rows):
        inspection = pd.to_datetime(rows.inspection_t)
        if (
            inspection.isna().any()
            or (inspection > rows.t).any()
            or (inspection < rows.t - pd.Timedelta(days=120)).any()
        ):
            raise ValueError("invalid snapshot inspection age")
    rows.attrs["grid"] = {
        (r["site_id"], r["t"]): {k: v for k, v in r.items() if k not in {"site_id", "t"}}
        for r in evidence.get("grid", [])
    }
    predictions = {n: np.array([r["probabilities"][n] for r in targets]) for n in policy["candidate_family"]}
    if any(not np.isfinite(p).all() or ((p < 0) | (p > 1)).any() for p in predictions.values()):
        raise ValueError("invalid decision probabilities")
    recalculated = json.loads(
        _cached_decision(
            _json(
                {
                    "targets": targets,
                    "grid": evidence.get("grid", []),
                    "family": policy["candidate_family"],
                    "contract": policy["contract"],
                    "sites": sorted(policy["sites"]),
                    "start": policy["validation_start"],
                    "end": policy["validation_end"],
                    "gates": gates,
                }
            )
        )
    )
    if recalculated["sites"] != policy["sites"] or recalculated["scores"] != evidence["scores"]:
        raise ValueError("decision evidence/gates mismatch")
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
