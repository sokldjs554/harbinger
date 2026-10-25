# Site policy verification — 2026-10-25

This directory records a **synthetic operational check**, not customer optimization or a new held-out performance claim. The frozen default gates selected `without_text` for S01 and retained the baseline for S02–S04. The demonstration scored all 466 assets through `Store.latest_rows`; each site's output matched its selected real classifier exactly (maximum absolute error 0.0).

## Evidence

- `proposal.json`, `validation-evidence.json`: model/data/evidence hashes, fixed chronology and gates, same-target validation predictions, outcomes and site scores. The evidence file's byte SHA-256 equals `proposal.evidence_sha256`.
- `history/`: activation, original-baseline rollback, and prior-revision rollback records with chained prior revision references. Each filename and record revision equals the canonical record content hash.
- `demo-result.json`: source code hashes, data file hashes, real model version, selected models, exact-probability checks, conflict rejection, rollback checks, historical-date baseline parity, corrupted-weight fallback, and explanation status.
- `asset-predictions.csv`, `analysis.md`: actual routed output and exported model/policy identities. Outcome evaluation is explicitly withheld.
- `*-red.txt`: observed failures for missing serving trace, malformed active JSON, baseline rollback, reserved test evaluation boundary, future outcome maturity, and misleading evaluation reason before each corresponding fix.
- `full-pytest.txt`: final whole-repository test run: 184 passed, 1 skipped in 45.61 seconds; TensorFlow parity is the optional skipped test.
- `monitoring-policy-green.txt`: 39 focused tests after repairing optional-policy compatibility with mocked in-memory baseline stores.

The first full suite exposed 12 monitoring regressions: `Store.load` initially required on-disk policy hashes even for mocked, policy-free models. The fix preserves ordinary baseline loading but marks unverifiable bundles ineligible for any policy. The final full suite includes the fix. No previously red test was omitted.

## Reproduce

Run from the repository root with the project environment:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src:. python -m harbinger.cli bootstrap \
  --data /tmp/hb-gap-runtime/data --models /tmp/hb-gap-runtime/models \
  --artifacts /tmp/hb-gap-runtime/artifacts --scale 0.12 --months 12

OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src:. \
  python docs/verification/remaining-gaps/site-policy/run_demo.py

OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src:. python -m pytest -rs
```

The generator uses seed 20260101, four synthetic sites, 466 assets and 8,953 inspections across 12 months. The demo copies the model directory into `/tmp/hb-gap-policy-demo`; it does not activate a policy in the shared runtime. It exercises the public offline CLI for selection, activation, stale-revision rejection, and both rollback forms. A new execution creates fresh timestamps, revision hashes and evidence hashes.

Model training/calibration observations stop at 2023-09-01. Policy validation uses 2023-09-02 through 2023-11-30, with certified synthetic observation end 2024-01-01. This historic period was previously in the base model's test window and is now **selection validation**, not untouched policy test data. The separate policy test boundary is 2027-01-01 and is not evaluated. Postactivation scoring of old synthetic records only demonstrates routing, with outcome evaluation withheld; it is not a prospective accuracy result.

Serving historical dates before today's selection/activation remains baseline. Nonbaseline SHAP is explicitly unavailable. Hashes are integrity/provenance checks inside an administrator-controlled model directory, not signatures against an administrator rewriting evidence and hashes together. See `docs/site-model-policy.md` for operational details and limitations.
