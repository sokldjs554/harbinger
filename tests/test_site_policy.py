"""Policy safety: deleting any gate here permits a concrete unsafe serving transition."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from harbinger.models import site_policy as policy
from harbinger.models.classify import train_logistic


@pytest.fixture
def candidate(tmp_path):
    frame = pd.DataFrame(
        {
            "x": np.tile([0.0, 1.0], 40),
            "y30": np.tile([0, 1], 40),
            "st_category": "pump",
            "st_archetype": "office",
        }
    )
    base = train_logistic(frame, frame.iloc[:0], ["x"])
    alternative = train_logistic(frame.assign(x=1 - frame.x), frame.iloc[:0], ["x"])
    root = tmp_path / "models"
    version = root / "v1"
    version.mkdir(parents=True)
    for name in ("classifier.joblib", "comparators.joblib", "bundle.json"):
        (version / name).write_text(name)
    bundle = {
        "version": "v1",
        "classifier": alternative,
        "comparators": {"logistic": base},
        "entry": {"metrics": {"observation": {"boundary_version": 2, "max_observed_at": "2024-01-01"}}},
    }
    frame = frame.assign(
        site_id="S1", asset_id=[f"a{i}" for i in range(80)], t=pd.Timestamp("2024-03-01"), label_valid=True
    )
    return root, bundle, frame


def propose(candidate, **kwargs):
    root, bundle, frame = candidate
    return policy.select_policy(
        root,
        bundle,
        frame,
        validation_start="2024-02-01",
        validation_end="2024-03-01",
        test_start="2099-01-01",
        observation_end="2024-06-01",
        outcomes_complete=True,
        data_hash="a" * 64,
        **kwargs,
    )


def test_real_candidate_selected_and_policy_is_time_gated(candidate):
    root, bundle, frame = candidate
    proposal = propose(candidate)
    assert proposal["sites"]["S1"]["model"] == "logistic"
    revision = policy.activate(root, bundle, proposal, expected_revision=None)
    model, trace = policy.resolve(root, bundle, "S1", pd.Timestamp("2099-02-01"))
    np.testing.assert_array_equal(
        model.predict_proba(frame), bundle["comparators"]["logistic"].predict_proba(frame)
    )
    assert trace["policy_revision"] == revision
    model, trace = policy.resolve(root, bundle, "S1", pd.Timestamp("2024-04-01"))
    assert model is bundle["classifier"]
    assert trace["policy_reason"] == "selection_not_available"


def test_hash_and_missing_candidate_fail_closed(candidate):
    root, bundle, _ = candidate
    proposal = propose(candidate)
    policy.activate(root, bundle, proposal, expected_revision=None)
    removed = copy.copy(bundle)
    removed["comparators"] = {}
    assert (
        policy.resolve(root, removed, "S1", pd.Timestamp("2099-02-01"))[1]["policy_reason"]
        == "invalid_policy"
    )
    (root / "v1" / "classifier.joblib").write_text("stale")
    assert (
        policy.resolve(root, bundle, "S1", pd.Timestamp("2099-02-01"))[1]["policy_reason"] == "invalid_policy"
    )


def test_insufficient_sample_keeps_baseline(candidate):
    proposal = propose(candidate, min_rows=100)
    assert proposal["sites"]["S1"] == {"model": "baseline", "reason": "insufficient_sample"}


def test_metadata_and_maturity_rejected(candidate):
    root, bundle, frame = candidate
    with pytest.raises(ValueError, match="outcomes"):
        policy.select_policy(
            root,
            bundle,
            frame,
            validation_start="2024-02-01",
            validation_end="2024-03-01",
            test_start="2099-01-01",
            observation_end="2024-03-10",
            outcomes_complete=False,
            data_hash="a" * 64,
        )
    bundle["entry"]["metrics"]["observation"] = {}
    with pytest.raises(ValueError, match="metadata"):
        propose(candidate)


def test_activation_cas_rollback_and_evidence_integrity(candidate):
    root, bundle, _ = candidate
    proposal = propose(candidate)
    r1 = policy.activate(root, bundle, proposal, expected_revision=None)
    with pytest.raises(ValueError, match="revision"):
        policy.activate(root, bundle, proposal, expected_revision=None)
    p2 = propose(candidate, min_rows=100)
    r2 = policy.activate(root, bundle, p2, expected_revision=r1)
    r3 = policy.rollback(root, bundle, r1, expected_revision=r2)
    assert r3 not in {r1, r2}
    assert policy.resolve(root, bundle, "S1", pd.Timestamp("2099-02-01"))[1]["selected_model"] == "logistic"
    evidence = root / "site-policy-evidence" / (proposal["evidence_sha256"] + ".json")
    evidence.write_text("{}")
    assert (
        policy.resolve(root, bundle, "S1", pd.Timestamp("2099-02-01"))[1]["policy_reason"] == "invalid_policy"
    )
    with pytest.raises(ValueError):
        policy.rollback(root, bundle, "../escape", expected_revision=r3)


def test_forged_selection_and_future_validation_rejected(candidate):
    root, bundle, _ = candidate
    p = propose(candidate)
    p["sites"]["S1"]["model"] = "baseline"
    with pytest.raises(ValueError, match="evidence"):
        policy.activate(root, bundle, p, expected_revision=None)
    root, bundle, frame = candidate
    with pytest.raises(ValueError):
        policy.select_policy(
            root,
            bundle,
            frame,
            validation_start="2023-01-01",
            validation_end="2024-03-01",
            test_start="2024-03-15",
            observation_end="2024-06-01",
            outcomes_complete=True,
            data_hash="a" * 64,
        )


def test_store_mixed_sites_selected_probabilities_and_explanations(trained, tmp_path):
    import shutil

    from harbinger.api.analysis import analyze, markdown_report
    from harbinger.api.store import Store
    from harbinger.config import Settings

    model_dir = tmp_path / "real-models"
    shutil.copytree(trained["models"], model_dir)
    store = Store(Settings(data_dir=trained["data"], model_dir=model_dir, demo_bootstrap=False))
    store.load()
    cutoff = pd.Timestamp(store.bundle["entry"]["metrics"]["observation"]["max_observed_at"])
    end = store.data_end - pd.Timedelta(days=30)
    proposal = policy.select_policy(
        model_dir,
        store.bundle,
        store.X,
        validation_start=cutoff + pd.Timedelta(seconds=1),
        validation_end=end,
        test_start="2099-01-01",
        observation_end=store.data_end,
        outcomes_complete=True,
        data_hash=policy.sha256(trained["data"] / "features.parquet"),
        min_rows=2,
        min_class=1,
        min_improvement=0,
    )
    revision = policy.activate(model_dir, store.bundle, proposal, expected_revision=None)
    as_of = pd.Timestamp("2099-02-01")
    rows = store.latest_rows(None, as_of, max_age_days=36500)
    assert len(rows.site_id.unique()) > 1
    assert set(rows.policy_revision) == {revision}
    for _, group in rows.groupby("site_id"):
        model, trace = store.model_for(str(group.iloc[0].site_id), as_of)
        np.testing.assert_allclose(group.p30, model.predict_proba(group), rtol=0, atol=0)
        if trace["selected_model"] != "baseline":
            assert store.explainer_for(trace["selected_model"]) is None
    result = analyze(store, as_of)
    assert {r["policy_revision"] for r in result["assets"]} == {revision}
    assert revision in markdown_report(result)
    past = store.latest_rows(None, store.data_end, max_age_days=36500)
    np.testing.assert_allclose(past.p30, store.bundle["classifier"].predict_proba(past), rtol=0, atol=0)


@pytest.mark.parametrize("invalid", ["[]", "null", '{"schema": 99}', "not-json"])
def test_malformed_active_policy_falls_back(candidate, invalid):
    root, bundle, _ = candidate
    (root / "site-policy.json").write_text(invalid)
    model, trace = policy.resolve(root, bundle, "S1", pd.Timestamp("2099-02-01"))
    assert model is bundle["classifier"]
    assert trace["policy_reason"] == "invalid_policy"


def test_loaded_weights_fingerprint_and_symlink_path_rejected(candidate, tmp_path):
    root, bundle, _ = candidate
    proposal = propose(candidate)
    policy.activate(root, bundle, proposal, expected_revision=None)
    bundle["_policy_bundle_hash"] = "0" * 64
    assert (
        policy.resolve(root, bundle, "S1", pd.Timestamp("2099-02-01"))[1]["policy_reason"] == "invalid_policy"
    )
    external = tmp_path / "outside"
    external.mkdir()
    (root / "escape").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe"):
        policy.bundle_hash(root, {"version": "escape"})


def test_unknown_site_and_missing_validation_outcome(candidate):
    root, bundle, frame = candidate
    proposal = propose(candidate)
    policy.activate(root, bundle, proposal, expected_revision=None)
    assert (
        policy.resolve(root, bundle, "unknown", pd.Timestamp("2099-02-01"))[1]["policy_reason"]
        == "unlisted_site"
    )
    frame.loc[0, "y30"] = np.nan
    with pytest.raises(ValueError, match="outcomes"):
        propose(candidate)


def test_rollback_to_original_default_is_audited(candidate):
    root, bundle, _ = candidate
    first = policy.activate(root, bundle, propose(candidate), expected_revision=None)
    restored = policy.rollback(root, bundle, None, expected_revision=first)
    assert restored != first
    model, trace = policy.resolve(root, bundle, "S1", pd.Timestamp("2099-02-01"))
    assert model is bundle["classifier"]
    assert trace == {
        "selected_model": "baseline",
        "policy_revision": restored,
        "policy_reason": "baseline_restored",
    }
    active = json.loads((root / "site-policy.json").read_text())
    assert active["previous_revision"] == first
    assert active["operation"] == "rollback"


def test_selected_policy_is_not_evaluated_before_reserved_test_boundary():
    from types import SimpleNamespace

    from harbinger.api.analysis import analyze

    rows = pd.DataFrame(
        [
            {
                "asset_id": "a",
                "site_id": "S1",
                "t": pd.Timestamp("2025-08-01"),
                "p30": 0.1,
                "name": "a",
                "category": "pump",
                "memo": "",
                "ck_overall": 0,
                "st_age_years": 5,
                "wo_days_since_bd": 100.0,
                "wo_bd_90d": 0,
                "policy_test_start": "2025-10-01",
                "selected_model": "logistic",
            }
        ]
    )
    store = SimpleNamespace(
        latest_rows=lambda *a, **kw: rows.copy(),
        data_end=pd.Timestamp("2025-12-01"),
        tables={"workorders": pd.DataFrame(columns=["asset_id", "type", "opened_at"])},
        bundle={
            "version": "test",
            "comparators": {},
            "entry": {"metrics": {"observation": {"boundary_version": 2, "max_observed_at": "2025-07-01"}}},
        },
    )
    result = analyze(store, pd.Timestamp("2025-09-01"))
    assert result["time_held_out"] is False
    assert not any("메타데이터가 없습니다" in reason for reason in result["evaluation_reasons"])


def test_future_validation_outcomes_cannot_be_certified_today(candidate):
    root, bundle, frame = candidate
    frame["t"] = pd.Timestamp("2098-02-01")
    with pytest.raises(ValueError, match="temporal"):
        policy.select_policy(
            root,
            bundle,
            frame,
            validation_start="2098-01-01",
            validation_end="2098-03-01",
            test_start="2099-01-01",
            observation_end="2098-06-01",
            outcomes_complete=True,
            data_hash="a" * 64,
        )
