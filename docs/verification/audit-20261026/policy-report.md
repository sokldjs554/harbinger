# Policy remediation

Implemented schema 2 fixed ranking selection in `models/site_policy.py` and `models/policy_evaluation.py`, CLI source-table snapshot construction, focused regression/lifecycle tests and updated `docs/site-model-policy.md`. No commits, activation of actual synthetic policies, network calls or existing archive changes were made. The synthetic run uses copied model files under `/tmp/audit-policy-models` and read-only original data.

## Behavior

Snapshots retain `inspection_t`, pass original inspection `t` through `Refresher.apply`, then stamp common snapshot dates. Outcomes are rebuilt from workorders strictly after the snapshot through day 30 inclusive. Historical workorder features preserve the refresher's existing strictly-before-as-of convention. Snapshots older than 120 days are removed. Full source-asset site/date counts include missing and stale assets, including sites with no eligible rows.

The immutable contract requires 30-day nonoverlapping schedules, four dates/90 days, 50 assets per date, three positives/negatives per date, budget 10, positive precision improvement, no per-date precision loss and Brier improvement >=0.001. CLI/API gate overrides may strengthen but cannot weaken floors. Equal-weight date metrics and deterministic ID ranking are shared by every candidate. Candidate family is fixed before predictions and recorded.

Paired asset bootstrap resamples whole histories with replacement, reranks deterministic clone IDs and shares draws across candidates. Date bootstrap separately retains complete dates. Both use 2,000 replicates, seed 20261026, linear percentile at .05/(candidate count*2), precision lower bound >=0 and Brier lower bound >0. Undersized asset replicates are counted and conservatively fail uncertainty, without retrying/dropping into a passing bound. Point/per-date scores, deltas, bounds and reasons are retained. Four calendar windows have low temporal power; these separate sensitivity checks do not provide simultaneous dependence coverage or customer generalization guarantees.

Validation rejects schema 1, fixed-contract/candidate-family/gate mismatches, malformed/nonfinite probabilities, duplicate/off-grid outcomes and stale/future inspection dates; it recomputes the complete decision and bounds from immutable evidence in addition to checking hashes. Existing activation time gates, CAS, history, rollback and mixed-site routing remain. Baseline rollback stays available for old policies. Direct Python callers must supply explicitly aligned snapshots with `inspection_t`; the production CLI builds them from verified sources. A caller-supplied data hash remains provenance supplied by an administrator, not a cryptographic guarantee of the truth of labels.

## Reproduction and validation

`policy-red.txt` preserves the initial test run, including fixture-discovery errors and the missing evaluation-module failure. `policy-old-code-red.txt` independently executes the original HEAD selector extracted to `/tmp` and demonstrates selection of a single-window candidate with precision@10 0 versus baseline 1 solely because Brier is better. Original production source was not replaced during this reproduction. Snapshot test initially expected as-of equality in historical features and was corrected to preserve the existing strictly-before-as-of refresher semantics.

Focused commands:

```
.venv/bin/pytest tests/test_policy_selection.py tests/test_site_policy.py -q
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/pytest tests/test_site_policy.py tests/test_policy_selection.py tests/test_policy_integration.py -q
.venv/bin/ruff check src/harbinger/models/site_policy.py src/harbinger/models/policy_evaluation.py scripts/site_policy.py tests/test_site_policy.py tests/test_policy_selection.py
```

The first focused run passed 20 tests (`policy-green.txt`); a subsequent six-selection-test run passed (`policy-selection-tests.txt`). The latest expanded focused/integration run passes all 28 tests; results are retained in `policy-final-tests.txt`. Lint passes in `policy-lint.txt`. The controller is running the full project suite, including concurrent energy/operations changes. The strong lifecycle fixture uses four legitimate aligned windows; the small real fixture now retains baseline under unchanged production floors while still verifying probabilities, time gates and trace propagation.

## Actual synthetic selection

```
cp -a /workspace/harbinger-runs/ci-smoke/models /tmp/audit-policy-models
.venv/bin/python scripts/site_policy.py select --model-dir /tmp/audit-policy-models --data-dir /workspace/harbinger-runs/ci-smoke/data --validation-start 2023-09-02 --validation-end 2023-12-01 --test-start 2099-01-01 --outcomes-complete --output /tmp/audit-policy-proposal.json
```

Exact proposal and immutable raw evidence are copied as `policy-proposal.json` and `policy-evidence.json`; `policy-selection-raw.json` records source hashes. Bundle `v20261021-115634`: SHA256 `1d018434fe58b84db36b9569352f9368063e6d1dbea7e0024f3016fba85e29e8`; composite data SHA256 `67d980a12ed881632c15a115284360382434110dd28eaa80a4d96a9ec30de89c`. Model observations end 2023-09-01; outcomes end 2024-01-01. The attempted August-start run correctly rejected temporal overlap; it was rerun after the model cutoff.

All five sites retain baseline. S01–S04 have 113/169/141/67 assets at all four dates, but every candidate fails at least one gate. S05 has 43 assets per date and fails eligibility. S01 without_text has mean precision improvement +0.075 and Brier improvement +0.00245767, but fails uncertainty. S02 without_text improves Brier +0.00435649 while worsening precision -0.025 and is rejected. This is synthetic selection data, not an independent test; future test remains unscored (`test_scored=false`). No field effectiveness claim follows.

The archived S01 original inspection-row evidence remains unchanged. `policy-archived-S01.txt` independently recomputes its pooled Brier: baseline .07602243765, without_text .07454679640 (improvement .00147564125); pooled old inspection-row precision@10 .6 versus .7. These old pooled, repeated inspection rows are not the new aligned per-date estimand and must not be interpreted as an independent test or equal comparison to the new +.075 result.

## Limitations

Selection recalculation performs 2,000 bootstrap replicates on a cold validation input. A bounded 16-entry cache now stores only deterministic decision recomputation, keyed by canonical immutable content of targets, grid, candidate family, sites, dates, gates and fixed contract. Cached results are immutable bytes; bundle/evidence hashing, policy/evidence equality, fixed gates and candidate checks, target validity and current chronology still run on every validation. A new regression (`policy-cache-red.txt` before implementation) warms the cache then verifies edited evidence, weights, contract and current-time failures still reject. On the actual synthetic evidence, cold validation took 4.402 seconds; three warm validations took .02111/.02105/.02156 seconds (`policy-cache-timing.json`), with 3 hits/1 miss and maximum size 16. These are local function timings, not HTTP/production latency claims. Hashes establish integrity/provenance within the existing administrator-controlled model directory, not signatures against privileged rewriting. Complete breakdown ascertainment is still an explicit operator assertion. Four dates and synthetic source data do not establish customer power, calibration or operational benefit. Existing historical schema1 candidates deliberately fail closed until reselected; audited baseline rollback is available.
