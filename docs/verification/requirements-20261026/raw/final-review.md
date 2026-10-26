# Whole-branch review — requirements audit

Review basis: base `27051f07bd7597bd53442c98c281f9240f942e4f`, working tree on `audit/dwi-requirements-20261026`, 2026-10-26. Read-only code review; only this requested report was written. The parent was still updating documentation and running full verification, so this report is a snapshot, not certification of the eventual commit.

## Verdict

**Not ready to merge until Important I1 is fixed and integration verification finishes.** No Critical finding. One Important correctness issue; two nonblocking precision notes. The reviewed fixes otherwise have appropriate scope and meaningful regression coverage. FastAPI/AWS retention and an optional-but-CI-required TensorFlow comparison fit the stated scope; duplicating Flask/GCP is unnecessary.

## Important I1 — accepted historical models can silently score newly rebuilt, incompatible features

Locations: `src/harbinger/api/store.py:88` (matched historical semantics accepted), `src/harbinger/api/store.py:556` (ingestion), `src/harbinger/api/whatif.py:49` and `:83` (baseline/scenario rebuild), `src/harbinger/api/routers/workbench.py:154` (upload reuses base model).

`Store.load` correctly rejects a v3 cache paired with a v2 model, while allowing a matched historical v2 cache/model. After that successful load, ingestion and what-if call the current v3 `build_features` and still use the v2 model. Ingestion also replaces only one site's feature rows, leaving a mixture of v2 and v3 under the unchanged v2 bundle. Upload similarly bypasses `Store.load` by assigning `base.bundle` and building current features. Upload currently has no energy observations, so its practical numerical impact is narrower, but the semantic invariant is absent there too. Unversioned legacy pairs have the same rebuild problem.

Concrete local reproduction used the parent's completed BEFORE artifacts, without editing them:

1. Construct `Store(Settings(data_dir=Path('/tmp/hb-requirements-before/data'), model_dir=Path('/tmp/hb-requirements-before/models'), demo_bootstrap=False))`; suppress only monitoring in this isolated process and call `load()`.
2. Select `site_tables(store.tables, 'S01')` and rebuild with current `build_features`, explicitly preserving the bundle's original `metrics.observation.fit_until` and `store.data_end`.
3. Align old/new rows by `inspection_id`; compare `en_*` and the same classifier's predicted probabilities.

Observed output:

```json
{
  "loaded_model_semantics": 2,
  "rebuilder_semantics": 3,
  "site": "S01",
  "rows": 6508,
  "energy_changed_rows": 206,
  "probability_changed_rows": 184,
  "max_absolute_probability_change": 0.05429301664042313
}
```

Thus identical inspections/history can move P30 by 5.43 percentage points purely through an unannounced feature-definition change. This can change ranking and contradicts the new compatibility guard's purpose.

Suggested fix: preserve read-only historical cached predictions, but require current compatible model semantics before any operation that constructs features. Put the guard before ingestion mutates tables, before what-if rebuilds, and before upload builds/registers a session. Return an actionable non-500 response requiring a jointly rebuilt cache and retrained model. Alternatively, a genuinely versioned historical feature builder could preserve semantics, but that is materially larger scope. Add regressions that historical read-only use still works, all three rebuild paths refuse mismatches, refusal leaves tables/caches/sessions unchanged, and current-version operations still work.

## Minor / precision notes

**M1 — CLI exit status does not reflect its new comparison result.** `scripts/keras_parity_check.py:126` emits `comparison_passed=false` when either original gap limit fails, but line 132 returns success whenever AUROCs are finite. The pytest comparison does assert both limits, so the mandatory CI test is protected. A standalone caller relying on the process exit code can nevertheless treat a failed comparison as success. Consider returning nonzero for a failed comparison, or documenting the command as an evidence collector whose boolean field must be inspected (a separate explicit check flag also works). Do not silently reinterpret this as a successful independent-initialization experiment.

**M2 — sparse energy calibration status is broad, but safely withholds a result.** `src/harbinger/models/energy.py:97` omits sigma where there are too few calendar-window residual means; `:69` then calls the result `no_model` even when the fitted regression exists. The regression has no calibrated anomaly threshold, so this is not false normality and is not a blocking scientific bug. If changing wording, distinguish missing anomaly calibration from missing regression; preserve null anomaly/z values. Do not add an arbitrary fallback sigma to make the status green.

## Verification performed by this reviewer

- Read every initial diff hunk across TensorFlow model/script/tests/constraints/CI, PyTorch dropout, energy feature/model, feature semantic version, generator calendar, evaluation cohorts, figure labels, API/report/date/what-if/upload/replay changes, and AWS installer rollback. Read surrounding loaders, refresher, feature cache, what-if and upload paths, focused tests, and the requirements mapping/plan/ledger. Read README/modeling changes available during the pass; documentation was still in progress.
- Ran `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/pytest tests/test_model_audit_regressions.py tests/test_service_audit_regressions.py -q`: **25 passed**, exit 0. These cover exact epoch masks, synthetic month boundaries/rejection, common-cohort survival metrics, labels, negative OLS expectations, sparse calendar calibration, empty report rendering, checklist bounds, short uploads, replay invalidation, same-SHA directory/image rollback via harmless host stubs, and date rejection.
- Independently compared target-mask NLL with PyTorch `discrete_nll` for 1,026 cases including integer boundaries, event/censor states, random times through 500 days, and random logits: both `6.340570449829102`, absolute difference `0.0` after consistent float32 input conversion.
- Executed the historical-v2/current-v3 numerical reproduction above. This is a controlled same-data/same-fit-cutoff/same-model comparison, not a performance measurement.
- Inspected the mandatory TensorFlow job and actual-training test. The tests require TensorFlow availability in that job, verify finite all-missing-feature training, same-weight network logits, exact loss/logit gradients, the final hazard-layer kernel gradient, and shared-initialization training gaps. I did not rerun the expensive TensorFlow/full suite that the parent was already running.

## Required precision in final documentation/evidence

- Preserve independent-initialization NLL gap `0.269611` as a failure of the unchanged `<0.25` limit. A separate shared-pretraining-initialization result around `0.0040378` does not repair or replace that failed experiment. Record exact artifact values, inputs, versions, and source hashes from the final run.
- Both reported validation scores participate in early stopping; neither is an independent test estimate. Shared initialization does not synchronize batch shuffling/dropout. Same-weight numerical equivalence is a different claim from similar training outcomes or customer performance.
- The gradient regression checks the hazard output kernel, plus a separate direct loss/logit-gradient test; avoid claiming that every parameter gradient was compared unless coverage is extended.
- Historical site dropout has marginal expected masking `1-(1-0.3)^2=0.51`, with one permanent component; the revised training uses a fresh 0.3 mask once per epoch. Historical trained models/results remain historical.
- No-CNN ablation retains numeric memo-derived inputs. Use wording such as “character CNN removed; numeric memo features retained,” including the remaining `메모 없음` label in modeling prose while the parent finishes edits.
- HGB survival C-index now uses the full survival test cohort; do not directly replace a historical mature-only figure without labeling cohort change. IBS labels must use actual evaluated horizons.
- Model performance improvement requires the completed before/after experiment. Passing regressions alone proves the repaired contracts, not improved generalization.

## Declined to judge / limits

- Final full-suite, browser, full before/after training, container build, GitHub CI and final manifest/commit consistency: still running or not yet provided when dispatched. No completion claim is made.
- Actual EC2 replacement/rollback under Docker and systemd: inspected logic and ran the harmless stub regression; no live deployment, sockets, cloud changes, paid resources or public load were used. New unique release directories and restoring the exact previous image tag address the identified same-SHA overwrite mechanism, but the stub is not a live operational test.
- Exact job-ad transcription and current recruiting status: the authoritative screenshot was not in this reviewer's task payload; reviewed the mapping's claimed scope and its explicit unknowns, not the external listing.
- Personal credentials, customer pilots, production SLA, GCP execution and real customer predictive performance cannot be established by this patch. The mapping appropriately withholds these claims.
- This is one focused whole-diff pass with surrounding-path tracing, not a claim that every unchanged repository line or every historical artifact has been exhaustively revalidated.
