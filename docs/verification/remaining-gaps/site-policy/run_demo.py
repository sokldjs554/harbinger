"""Synthetic operational demonstration, not a held-out performance experiment.

Run from repo root after `harbinger bootstrap` into /tmp/hb-gap-runtime.
Writes only its dedicated copy /tmp/hb-gap-policy-demo and this evidence directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from harbinger.api.analysis import analyze, markdown_report
from harbinger.api.store import Store
from harbinger.config import Settings

OUTPUT = Path(__file__).resolve().parent
RUNTIME = Path("/tmp/hb-gap-runtime")
DEMO = Path("/tmp/hb-gap-policy-demo")


def command(*arguments, expected=0):
    run = subprocess.run(
        [sys.executable, "scripts/site_policy.py", *arguments],
        text=True,
        capture_output=True,
        env={**os.environ, "OMP_NUM_THREADS": "1"},
    )
    if expected == 0:
        assert run.returncode == 0, run.stderr
        return json.loads(run.stdout)
    assert run.returncode != 0
    assert "prior revision mismatch" in run.stderr
    return {"rejected": True, "reason": "prior revision mismatch"}


def main():
    if DEMO.exists():
        shutil.rmtree(DEMO)
    shutil.copytree(RUNTIME / "models", DEMO / "models")
    model_args = ["--model-dir", str(DEMO / "models")]
    selection = command(
        "select",
        *model_args,
        "--data-dir",
        str(RUNTIME / "data"),
        "--validation-start",
        "2023-09-02",
        "--validation-end",
        "2023-11-30",
        "--test-start",
        "2027-01-01",
        "--outcomes-complete",
        "--output",
        str(DEMO / "proposal.json"),
    )
    activation = command(
        "activate", *model_args, "--proposal", str(DEMO / "proposal.json"), "--expected-revision", "none"
    )
    conflict = command(
        "activate",
        *model_args,
        "--proposal",
        str(DEMO / "proposal.json"),
        "--expected-revision",
        "none",
        expected=1,
    )
    store = Store(Settings(data_dir=RUNTIME / "data", model_dir=DEMO / "models", demo_bootstrap=False))
    store.load()
    past = store.latest_rows(None, store.data_end, max_age_days=36500)
    np.testing.assert_array_equal(past.p30, store.bundle["classifier"].predict_proba(past))
    assert set(past.policy_reason) == {"selection_not_available"}
    # This intentionally exercises routing after activation using old synthetic
    # records. It is not eligible for outcome/performance evaluation.
    as_of = pd.Timestamp(datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5))
    rows = store.latest_rows(None, as_of, max_age_days=36500)
    comparisons = []
    for site, group in rows.groupby("site_id"):
        model, trace = store.model_for(site, as_of)
        np.testing.assert_array_equal(group.p30, model.predict_proba(group))
        comparisons.append(
            {
                "site_id": site,
                "n": len(group),
                **trace,
                "max_absolute_prediction_error": float(np.max(abs(group.p30 - model.predict_proba(group)))),
            }
        )
    result = analyze(store, as_of)
    assert result["evaluation_status"] == "withheld"
    assert all(a["policy_revision"] == activation["revision"] for a in result["assets"])
    details = []
    for site, group in rows.groupby("site_id"):
        asset = store.asset_risk(site, group.iloc[0].asset_id, as_of)
        assert asset["selected_model"] == group.iloc[0].selected_model
        if asset["selected_model"] != "baseline":
            assert asset["explanation"]["contributions"] is None
            assert asset["explanation"]["status"] == "unavailable_for_selected_model"
        details.append(
            {k: asset[k] for k in ("site_id", "asset_id", "selected_model", "policy_revision", "explanation")}
        )
    baseline = command(
        "rollback", *model_args, "--to-revision", "none", "--expected-revision", activation["revision"]
    )
    restored_rows = store.latest_rows(None, as_of, max_age_days=36500)
    np.testing.assert_array_equal(restored_rows.p30, store.bundle["classifier"].predict_proba(restored_rows))
    restored = command(
        "rollback",
        *model_args,
        "--to-revision",
        activation["revision"],
        "--expected-revision",
        baseline["revision"],
    )
    replay_rows = store.latest_rows(None, as_of, max_age_days=36500)
    np.testing.assert_array_equal(rows.p30, replay_rows.p30)
    bad = DEMO / "models" / store.bundle["version"] / "classifier.joblib"
    original = bad.read_bytes()
    try:
        bad.write_bytes(original + b"corruption-test")
        invalid = store.latest_rows(None, as_of, max_age_days=36500)
        assert set(invalid.policy_reason) == {"invalid_policy"}
        np.testing.assert_array_equal(invalid.p30, store.bundle["classifier"].predict_proba(invalid))
    finally:
        bad.write_bytes(original)
    assert activation["revision"] in markdown_report(result)
    proposal = json.loads((DEMO / "proposal.json").read_text())
    summary = {
        "kind": "synthetic-operational-demonstration",
        "source_sha256": {
            name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in (
                "src/harbinger/models/site_policy.py",
                "src/harbinger/api/store.py",
                "src/harbinger/api/analysis.py",
                "src/harbinger/api/backtest.py",
                "src/harbinger/api/whatif.py",
                "scripts/site_policy.py",
                "docs/verification/remaining-gaps/site-policy/run_demo.py",
            )
        },
        "heldout_performance_evaluated": False,
        "runtime": {
            "seed": 20260101,
            "months": 12,
            "scale": 0.12,
            "assets": len(rows),
            "model_version": store.bundle["version"],
        },
        "selection": selection,
        "activation": activation,
        "cas_conflict": conflict,
        "baseline_rollback": baseline,
        "prior_revision_rollback": restored,
        "historical_baseline_parity": True,
        "corrupted_weights_fallback": True,
        "model_comparisons": comparisons,
        "analysis_evaluation_status": result["evaluation_status"],
        "explanation_checks": details,
        "as_of": as_of.isoformat(),
        "limitations": [
            "Synthetic data only; old records scored after activation only to check routing.",
            "Validation window reuses historical synthetic data; new held-out test not evaluated.",
            "Small-sample selection is not evidence of customer optimization.",
        ],
    }
    (OUTPUT / "demo-result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    (OUTPUT / "proposal.json").write_text(json.dumps(proposal, indent=2))
    (OUTPUT / "analysis.md").write_text(markdown_report(result))
    pd.DataFrame(result["assets"]).to_csv(OUTPUT / "asset-predictions.csv", index=False)
    evidence = DEMO / "models" / "site-policy-evidence" / (proposal["evidence_sha256"] + ".json")
    shutil.copyfile(evidence, OUTPUT / "validation-evidence.json")
    assert (
        hashlib.sha256((OUTPUT / "validation-evidence.json").read_bytes()).hexdigest()
        == proposal["evidence_sha256"]
    )
    if (OUTPUT / "history").exists():
        shutil.rmtree(OUTPUT / "history")
    shutil.copytree(DEMO / "models" / "site-policy-history", OUTPUT / "history")
    print(json.dumps({"assets": len(rows), "sites": comparisons, "checks": "passed"}, indent=2))


if __name__ == "__main__":
    main()
