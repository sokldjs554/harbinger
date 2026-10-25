# Execution ledger — 2026-10-25 missing memo

Plan: ../../superpowers/plans/2026-10-25-memo.md
Spec: ../../superpowers/specs/2026-10-25-memo-design.md

- Before implementation: isolated branch from e3d124c, base full suite152 passed/1skip. Frozen design committed7970592 before smoke or new full experiments.
- Task1 complete: legacy-compatible missing-aware model; nine new test cases RED→GREEN. Options default off; actual base-module equality independently verified.
- Task2 code complete: candidate selection/temporal cohort checks/final gate RED→GREEN; 14 focused cases; smoke2epochs completed. Full three-world experiments running with source55a150a, configuration unchanged after smoke. Source hashes are stored per world; subsequent20a79f7 only release source digest and verification records.
- Task3 verification: full suite166 passed/1skip; Ruff102 files; numeric contract passes. Release check first detected modified deep.py, then source digest regenerated without changing historic model/demo artifacts and check passed.
- Final review: independent reviewer found0 Critical/0 Important. Actual legacy training/state/load outputs match old source. Smoke raw predictions/selection/bootstrap independently recomputed.
- Final: Ruling: re-grade the missing direct-mask regression as important coverage because removing masking defeats the core mitigation while a counter-only test stays green. Added a real forward-input spy; an in-memory mask-removal mutation fails, unchanged correct implementation passes. Full suite167 passed/1skip. Experiment source was not altered and running models were not interrupted.
- Ruling: new experiments use previously unused generation seeds with the existing24/6/6 calendar windows, not a claim of later real-world observations. Generation/learning settings and thresholds fixed before seeing results. Generalization remains limited to this generator.
- Ruling: no second model tuning after final-test results. Report failed gate if it fails; retain public HGB/default legacy behavior. Cost of this conservative choice is that an improved candidate may remain opt-in.

- Task2 complete: all3 new worlds ×2 seeds finished; legacy/robust/no-memo models scored. Validation selected no_memo5/legacy1. Raw recomputation passed all gates. Mean selected missing25/50 gain5.30pp; no post-test tuning.
- Artifact recovery:2 completed-run gzip CSV streams were truncated; exact external cause unconfirmed. Raw Parquet hashes and all12 prediction ZIP CRCs matched. Reconstructed memo transformation and common cohort from unchanged sources; verified full surviving prefixes. Preserved original bytes/manifests and repair hashes. No predictions, selection, weights, or thresholds changed.
- Artifact hardening RED→GREEN: atomic complete CSV publication and full gzip verification; truncated trailer test fails. Updated smoke reproduces all24 original prediction vectors exactly and all gzip streams verify. Full suite168 passed/1skip.
- Final review scope: independent review covered model/evaluation logic; serialization-only recovery hardening was verified by regression tests, complete smoke, and raw-artifact revalidation by implementer. Final reporting and integration checks performed by implementer.
