# Final whole-branch integration review

Initial reviewed HEAD: `9527c05`, base `e82b696d0c68fa3834f93a32742705d970f7dc1a`. Read-only review of repository/runtime artifacts; no credentials read and no repository/runtime files edited. Synthetic in-memory table copies were used for current-date integration cases. This report is the only reviewer-created file.

## Critical

None found in the reviewed scope.

## Important findings found and resolved

1. **Pooled replay certifies selected-model observations before their reserved test boundary depending on site iteration order.** `src/harbinger/api/backtest.py`, `replay`, merged-week construction and aggregation (initial HEAD around lines 185–206).
   - `replay_site` correctly computes each site's model/selection holdout. The pooled branch initializes `held_out` from the first site and never combines later sites' flags.
   - Concrete reproduction: two sites, six assets each, decision 2025-09-01, model observed until 2025-07-01, observation end 2025-12-01, k=5. S1 uses an unlisted-site baseline with no selection gate; S2 uses logistic with reserved `policy_test_start=2025-10-01`. Real `replay_site`/`replay` execution returns S1 `held_out=True`, available, 5 certified picks; S2 false, withheld, 0; pooled S1-first true, available, **10** certified picks. Reversing only the sites table makes pooled false, withheld, 0.
   - Fix: combine all contributing site holdout flags (logical AND), or explicitly aggregate only eligible sites while documenting excluded contributions. Add both-order mixed-site regression and a date after all test boundaries.

2. **Legacy report export loses actual model provenance and associates baseline headline metrics with selected-model scores.** `src/harbinger/api/routers/report.py`, `build_report` and `to_markdown` (initial HEAD around lines 22–72 and 81–136).
   - With the actual copied model directory `/tmp/hb-gap-policy-demo/models`, S01 routes to `without_text`. On an in-memory synthetic calendar shift to exercise recent-report inputs, report `patrol.selected_model` is `without_text`, while top-risk records omit model/revision/reason, report `model` contains only version/headline, and Markdown contains neither `without_text` nor the active revision.
   - Admin/public report `model.headline` comes from the baseline bundle's original evaluation, without identifying it as a historical baseline reference; scoped user reports correctly redact that aggregate metadata, but still omit selected-model provenance in Markdown.
   - Fix: carry actual route into report model/top records and Markdown, and separate any historical baseline reference metrics from active selected-model evaluation. A selected model has no newly established held-out performance merely because bundle metrics exist.

Both findings were promptly sent to the parent and implementation agent and are now fixed. Independent final remediation verification is recorded below.

## Minor

No additional minor findings raised. The prior core-review recorder findings have fixes: skipped-task help is preserved and negative stated durations are rejected. Avoided treating pre-existing empty legacy-report behavior or administrator-rewritten signed-by-hash policy content as new issues in this change.

## Independent verification

- Read remaining-gaps design/plan and extended-stress preregistration, site-policy design/CLI/implementation/tests, Store/analysis/backtest/what-if/report/dependency seams, scoped authentication boundary, CI/Pages/static builders and recorder integration.
- Ran `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src:. /tmp/harbinger-review-venv/bin/python -m pytest -q tests/test_site_policy.py tests/test_extended_stress.py tests/test_retest_records.py`: **38 passed**.
- Actual policy runtime: all 466 row scores matched direct per-site selected candidate predictions exactly (S01 without_text 104, S02 baseline 198, S03 baseline 83, S04 baseline 81).
- Scoped dependency copy for S01 matched the full Store's S01 predictions exactly. Original Store kept all four sites; scoped tables/results exposed only S01. data_meta and aggregate model metrics were removed, while observation provenance stayed sufficient for time eligibility.
- Active selected-policy analysis before reserved 2027-01-01 heldout boundary remained withheld and reported the boundary. Empty 2000-01-01 snapshot returned no assets and withheld evaluation without error.
- Custom-model what-if, using a synthetic in-memory calendar shift only, used without_text for both baseline/scenario and exposed unavailable SHAP rather than baseline HGB attribution. Its baseline probability exactly matched a separately rebuilt feature row and direct without_text prediction.
- Policy tests cover mature outcomes, training/calibration chronology, wall-clock future outcomes rejection, default fallback for malformed policy/hash mismatch/missing candidate, evidence integrity, CAS conflicts, rollback, loaded-weight fingerprint, and historical baseline parity.
- Extended-stress code uses frozen verified model files, raw memo transformations independent of outcome labels, reconstructed memo-dependent features, nonmemo-input invariance, exact original ordered mature target cohort, delayed inspection availability, and bitwise clean/no-memo parity checks. Summary recomputes metrics and paired site intervals from saved arrays. No new model selection/adoption occurs in that path.
- CI uses the new monitoring, protected-stack and recorder checks; static builders strip auth bootstrap for public saved output and copy recorder assets. Parent is separately fixing/retesting browser-generated CSV/Markdown route propagation.

## Scope and limitations

This is integration review, not a repeat of the independent 163-case auth review or exact full signal artifact recomputation already completed by other reviewers. Actual six-run new stress artifacts were still being produced in another worktree and are not certified by this review yet. No real customer data, human remeasurement, production SLO calibration, or newly collected held-out selected-policy performance is established. No external deployment, push, live service mutation or credential access occurred.

## Remediation verification

Final reviewed root HEAD: `67eb715`; backend fixes from `6393ac63a75704586c137aa250ca442e7ec9dbb3` integrated as `dd80d72`, browser fixes from `048d6f5`.

- Inspected the exact backend fix diff. Pooled replay now ANDs every contributing site's eligibility and explains both model and policy holdout boundaries. Legacy reports attach actual row routing to model/top records and Markdown, with nonbaseline headline withheld and the historical baseline metrics explicitly scoped as a separate reference.
- Independently ran integration+policy tests on the fix worktree: **20 passed**. Re-ran the four new integration cases on final root `67eb715`: **4 passed**. These test both site orders, pre-boundary withholding, later eligibility, custom-model report trace, and baseline-reference scope.
- Re-ran the actual without_text runtime report on in-memory shifted synthetic inputs: report/patrol/top-record selected identities and revision agree; Markdown contains model/revision; selected-model headline is null and the stored original headline appears only as an explicit baseline reference. Pass.
- Inspected parent browser fixes and verified source/static reports.js and workbench.js are byte-identical. Independently exercised actual Chromium with a clearly synthetic injected saved-response fixture carrying custom `without_text`, exact revision, reason and reserved test-start values. Visible asset detail showed without_text; downloaded CSV preserved all four fields on every row; downloaded Markdown preserved all values; no page errors. This is a tool test, not human evidence or a performance evaluation.
- Parent's separate real protected browser verification reports no page errors and passes two-account scoped export/logout flows; I did not read its credentials or repeat the broad authentication campaign.

**Review disposition: approved for the reviewed integration scope. No unresolved Critical, Important or Minor findings from this review.** The new stress six-run result artifacts remain subject to their separate final verification/adoption; this approval does not certify not-yet-reviewed results, deployment, customer performance or human usability measurements.
