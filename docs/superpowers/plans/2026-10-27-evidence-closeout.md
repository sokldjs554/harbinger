# Evidence and submission closeout implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore reproducible published evidence, reconcile final submission documents, prepare honest participant retesting and verify external notifications when an actual recipient is supplied.

**Architecture:** Preserve the PR #16 source/model/evaluation and all historical evidence. Restore original missing files with their existing SHA-256, and run the unchanged verifier from a fresh checkout. Keep human observations and external receipt evidence separate from automated checks.

**Tech Stack:** Python standard library, Git/GitHub Actions, existing FastAPI/Prometheus workflow and existing browser retest recorder.

**Spec:** User's four closeout requirements on 2026-10-27 (Asia/Seoul), reproduced in the tasks below.

## Global Constraints

- No fabricated logs, participant results, personal credentials or notification receipts.
- No removal of evidence checks or favorable revision of performance numbers.
- No new paid resources or public load testing; never commit secrets.
- Source baseline: `e33072bc88652dc8e4bc50f9e3c68b9d44966379`; preserve the previous worktree and its original logs.
- User selected their Naver inbox and registered six GitHub Secrets, explicitly requiring smtp.naver.com:465 SSL. Use Alertmanager 0.33.0 implicit TLS; do not read/output secrets or substitute local acceptance for operator receipt.

## Review Focus

- Ignored but locally present evidence must fail in a clean checkout and succeed after original recovery.
- Missing or altered logs must continue to fail verification.
- Historical experiments and videos must not be presented as the final deployment version.
- Participant A/B's unmeasured or unperformed tasks must remain unknown, not success or zero seconds.
- HTTP delivery acceptance and an actual operator receipt must be recorded separately; normal recovery is required.

### Task 1: Recover original evidence

**Files:** `.gitignore`, six `docs/verification/completion-20261026/operations/strict/{before,after}/{api,prometheus,run}.log`, `.github/workflows/ci.yml`, `docs/verification/closeout-20261027/`.

- [x] Reproduce unchanged `verify_comparison.py` failure in a fresh tracked checkout.
- [ ] Scan original logs for credentials and compare their bytes to the existing six manifest hashes; restore byte-identical originals with narrowly scoped ignore exceptions.
- [ ] Add unchanged offline verifier to CI. Run it successfully, then confirm deletion and byte mutation still fail in disposable copies.
- [ ] Commit and clone the committed repository into a new directory; run the public reproduction command and preserve output.

### Task 2: Final documents and submission drafts

**Files:** `README.md`, `docs/{submission,application-update,submission-evidence-20261026,job-requirements-audit}.md`, current verification summaries and final release evidence.

- [ ] Recheck PR #16 merge and three final workflow results; archive small final deployment/version/check files with hashes and origin metadata.
- [ ] Replace current progress wording with verified final status; preserve dated historical records.
- [ ] Update self-introduction and portfolio with corrected memo experiment, frozen HGB selection and service-selection metrics. Distinguish synthetic evaluation, qualitative reviews, user's role and Codex implementation support.
- [ ] Check document numbers/links and source/model versions; label historical video and deployment-only LOSO omission explicitly.

### Task 3: Human retest handoff

**Files:** `docs/user-reviews/retest-guide.md`, two blank participant-specific forms and `docs/user-reviews/README.md`.

- [ ] Bind instructions to the deployed source/model and actual/saved modes; keep the same seven tasks and neutral guidance.
- [ ] Prepare A/B forms with date/timezone, version/mode, outcome, help, active/elapsed/system-wait times, unperformed option and consent. Leave all observations empty.
- [ ] Run existing retest validator and recorder checks; preserve their status as tool tests. Incorporate human records only after actual replies arrive.

### Task 4: External alert receipt

**Files:** `docs/ops/runbook.md`, controlled-test protocol/blank receipt record; routing files depend on the actual channel supplied.

- [ ] Obtain recipient/channel and securely configured credentials; check the chosen existing route.
- [ ] Prepare bounded test identification, firing/recovery and receipt timestamps, current alert state and teardown proof. Keep public service available.
- [ ] Execute with actual receiver only when configured, obtain real operator receipt, check resolved/inactive and restore normal state. Until then mark this task pending, with no fabricated receipt.

### Final verification

- [ ] Run applicable regression tests/full suite, fresh-clone evidence check and document manifest checks.
- [ ] Fresh whole-branch review; fix material findings and create a follow-up PR with explicit completed/pending items.

**Ruling:** The user has already requested execution and preservation; routine recovery, documentation and test preparation proceed inline without another design approval. Missing actual recipient and human observations are data dependencies, not permission gates for the independent tasks.

**Implementation choice:** Existing EC2 hosts a separate resource-limited Prometheus/Alertmanager Compose project. The test stops only a loopback probe; production API and models remain running. Normal monitoring remains installed after cleanup. Same-host failure detection is a documented limitation. Local Docker pull failed for disk capacity; own new unused image was removed, and checksum-verified native binaries passed the SSL protocol check.
