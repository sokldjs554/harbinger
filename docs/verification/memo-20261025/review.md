# Independent missing-memo branch review

Reviewed base `e3d124cdfb59a7a47e9fef6770fb46e04b922838` through implementation HEAD `55a150a087bf4cb8889ad2f0b2cb6f9a3461ac55` and the small follow-on diff through `20a79f7af445857f2949291ffc8fc3c2090498bd` on 2026-10-25. Final local Git tree: `e36b216bed30aa24ce7b5205c19aad72547b4ed1`. Read the design and plan, all branch changes, and relevant existing feature, time-split, snapshot, perturbation, and bootstrap code. Follow-on changes only add verification logs and update the deep.py release source digest; that digest was independently checked against the source. No working-tree/index/HEAD edits and no experiment interruption were performed.

## Findings

**Critical: none found.**

**Important: none found.**

**Minor — dropout regression test observes a counter rather than the actual training input.** `tests/test_deep_missing.py:65-75` checks `memo_rows_dropped` at dropout=1 and separately checks missing-input inference. Deleting `chars[mask] = 0` at `src/harbinger/models/deep.py:281` would leave that test's central assertions satisfied, despite breaking the mitigation. The implementation is correct as written. An optional stronger regression test should spy on training forward inputs, asserting every training char tensor is zero at rate=1 while clean validation remains unmodified, or equivalently demonstrate zero gradients in the text path under full dropout. This is a coverage improvement, not a merge-blocking present defect.

## Review conclusions

- Backward compatibility is sound: constructor defaults preserve old dimensions and execution, and `load_deep` defaults absent metadata to legacy at `deep.py:353`. Independently executing the actual base revision's model module and HEAD with the same 96 training rows, 32 validation rows, two epochs and seed 17 produced exactly equal state dictionaries and predictions on 50 test rows. Base and HEAD loaders also gave exactly equal predictions on 200 smoke-world rows including empty, None and whitespace memos.
- New-mode missing inputs are normalized to empty; unknown Unicode characters still encode as non-padding. The gate removes CNN bias as well as activations, and the presence bit is zero under dropout. Numeric memo derivatives in the current feature builder are all excluded and explicitly rejected in the new training path. No production default or HGB behavior changes.
- The current dropout code clones batch chars before masking and uses a dedicated deterministic RNG. Inference is deterministic and has no dropout mutation. Existing repeated-training and serialization tests passed.
- Survival train/validation labels are censored at the appropriate boundaries by the existing `split_by_time`/`observe_until`. Weekly validation decisions mature by `val_end`; test decisions start at or after it. Test cohorts are constructed early, but their outcomes/predictions do not feed selection. The executable sequence at `memo_robustness.py:209-217` writes and hashes the validation selection before test scoring.
- Missingness is applied to raw inspections after the train boundary, followed by feature rebuilding. Original outcomes are asserted equal by the existing contract; all safe numeric inputs are asserted equal at `memo_robustness.py:138`; condition-specific snapshots assert matching asset/site/decision/outcome rows. The no-memo arm supplies an additional invariant over saved predictions.
- Candidate thresholds, tie order, exclusion of 100% missingness from selection, and the six-run adoption gate match the frozen design. Bootstrap resamples whole sites and correctly retains repeated decisions within each site. The six runs are explicitly described as nested within three synthetic worlds, not independent real-customer evidence.
- The summary recomputes metrics, selection and bootstrap intervals from saved prediction arrays, verifies hashes and temporal maturity, and checks no-memo invariance. Source/config/model hashes and fresh-output refusal support auditable evidence. A hash alone is not independent proof of chronology; the reviewed control flow supplies the chronology here.

## Validation executed

1. `OMP_NUM_THREADS=1 PYTHONPATH=src:. /tmp/harbinger-review-venv/bin/python -m pytest tests/test_deep_missing.py tests/test_memo_experiment.py tests/test_observation_boundary.py tests/test_robustness.py -q` — passed (35 tests).
2. Actual base-vs-HEAD module compatibility checks described above — exact equality passed.
3. Independent read-only smoke artifact audit under `/tmp/hb-memo-smoke-results/data-202610251` — all manifest hashes, 24 prediction vectors (12 each validation/test), scalar metrics, per-site counts, temporal maturity, selection hashes/recomputed choice, no-memo invariance, and paired bootstrap intervals passed. Each phase had 768 cohort rows; smoke selected no_memo. Smoke is only pipeline evidence.

## Declined to judge / merge verdict

The full three-world/two-model-seed experiment was still running when this review finished. I do not judge its adoption result, all six final artifacts, final reporting text, CI, or any later commits. No claim of real-customer generalization or superiority over HGB is supported by this synthetic experiment.

**Code verdict: approve with one optional test-coverage nit.** For the complete measurement/reporting task, finish all six runs, run the raw-artifact summary successfully, faithfully report the predeclared gate even if it fails, and complete the planned integration checks before claiming the task complete or merging its final result report. No current implementation defect was found that requires restarting the frozen runs.

## Implementer follow-up

The optional dropout-coverage finding was treated as important regression coverage for the central mitigation. Added `test_full_dropout_masks_actual_training_input_only`: observes real training inputs, verifies all chars are masked at rate1 while validation remains present, and delegates to the real forward computation. A deliberately mask-removed module executed only in a separate test process failed ([mutation evidence](dropout-mutation-red.txt)); the correct source passed the full167-test suite ([log](tests.txt),1optional TensorFlow skip). No model or experiment source changed for this fix, so the frozen runs remain valid. No reviewer finding remains deferred.
