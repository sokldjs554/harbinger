# Read-only core review

Reviewed implementation commit: `afc5bde2dbc52e2b1c1ae3b92f1ff9ec14d55eea` relative to `e82b696d0c68fa3834f93a32742705d970f7dc1a`, plus uncommitted CI/Pages monitoring and recorder wiring and `scripts/check_monitoring.sh`. HEAD moved to `5d0c5e46391490ce7c14c90818adf2bd37465136` during review; unrelated authentication/routing integration is excluded. No repository edits or commits performed.

## Critical

None found in reviewed scope.

## Important

None found in reviewed scope.

## Minor

1. **Skipped-task help is silently discarded despite remaining visible.** `src/harbinger/console/retest.js:46` and generated `docs/demo/retest.js`.
   - Chromium reproduction: on an unstarted task enter `TOOL-TEST pre-attempt help` in the help field and a note; click “미실시로 기록”; finish/skip the other tasks and export. The disabled help input still displays the text, but the exported task has `help: ""`. The skip branch snapshots notes only. This can lose facilitator context supplied before deciding not to attempt the task.
   - Fix: copy the help field into `task.help` when skipping (keeping result not_attempted), or explicitly disallow and visibly clear this input for skipped tasks. Prefer preserving supplied observations. Add a browser export assertion covering this case.

2. **Negative stated durations pass validation within the 2ms tolerance.** `scripts/retest_records.py:74-79`.
   - Reproduction: load a valid recorder export with a not_attempted task, set that task's `active_ms=-2`, call `validate(record)`. Validation succeeds because the derived duration is zero and `abs(-2 - 0) > 2` is false. Similarly a zero-duration field on an attempted task can be negative. This is a small inconsistency in the integrity validator, not a browser timing bug or material fabricated improvement.
   - Fix: reject `stated < 0` before comparing against event-derived duration; add a negative-duration rejection case. Browser exports are integer milliseconds and currently need no negative tolerance.

## Verification performed

- Read design spec, signal implementation/CLI/tests, rules/config/tests, exporter metric definitions and route matching, retest UI/validator/comparison/browser contract, static builder changes, CI/Pages wiring, runbook and retest guide.
- Ran `OMP_NUM_THREADS=1 PYTHONPATH=src:. /tmp/harbinger-review-venv/bin/python -m pytest -q tests/test_signals.py tests/test_retest_records.py`: 21 passed.
- Ran actual Prometheus 2.54.1 `promtool check config deploy/monitoring/prometheus.yml`: valid config and one real rule file found, 15 rules validated. Ran `promtool test rules deploy/monitoring/rules.test.yml`: SUCCESS. Compose rule path corresponds to its new mounted directory. Route and metric labels match the actual exporter/API.
- Independently loaded the saved full signal artifact's exact source parquet, verified its SHA256, and reran `signal_tables`: exact full artifact equality (excluding separately stored provenance object).
- Site bootstrap is pooled row-weighted: site sum/count travel together; within-site repeated rows remain intact. Counts/outcomes are preserved; empty/few/missing clusters and single outcomes withhold intervals; deterministic sorted-site sampling is sensible. Documentation explicitly limits independence across sites, coverage with few clusters, and pointwise descriptive interpretation. No fixed widening claim.
- Inspected `/tmp/hb-retest-browser` and `/tmp/hb-retest-static` tool outputs. Independently reran the actual Chromium recorder contract against both source and generated static HTML (file URLs), writing tool-only results under `/tmp/gap-core-browser`.
- Independently exercised pause/resume, help-vs-unassisted rejection, incomplete reason, skip notes/help, actual downloaded JSON, and paired incomplete/skipped record behavior. Pause interval was positive and separate; incomplete/skipped tasks produced no success count or time deltas. All browser records remained `record_kind=tool-test`. In-memory comparison fixtures temporarily used human kind solely to exercise validation logic; these are synthetic tests and were not saved or represented as human observations.
- Blank metadata/consent guard, one running task at a time, waiting intervals, assistance, JSON validation, and mobile overflow checks pass. Existing guides accurately leave real human remeasurement pending and distinguish manual waiting marks from API latency.

The two minor issues do not invalidate the site bootstrap or monitoring behavior. Actual human observations, customer SLO calibration, and live alert delivery remain outside the evidence and must remain pending.

## Integration resolution

Both minor findings were reproduced with failing checks and fixed in `9527c05`. Final source and saved-page Playwright runs preserved help for a skipped task, validated JSON, and detected no page errors or mobile overflow. Negative durations are rejected before tolerance comparison. The tool-test record is not human evidence.
