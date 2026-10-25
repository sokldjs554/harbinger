# Policy implementation task
Read the Selection contract and Task 2 of docs/superpowers/plans/2026-10-26-audit.md first; those are fixed requirements. Work only policy source/CLI/tests/docs and selection evidence. No unrelated edits, no subagents, no commits (controller integrates).

Builder clarifications before scoring:
- Preserve original inspection t through Refresher.apply, then stamp snapshot t; retain inspection_t. Recompute (t,t+30d] from workorders; test boundaries/intervening history.
- Full site/date grid must record zero/stale/undersized dates, including wholly missing sites.
- Asset bootstrap resamples whole histories with replacement, shared draws for all candidates, rerank clone IDs; if a resample has <10 at any date fail uncertainty conservatively, never silently drop/retry; record count.
- Separate asset/date bootstrap sensitivity is NOT simultaneous dependency coverage; four windows have low temporal power. Persist per-date deltas, counts, bounds, quantile method/seed.
- Fixed candidate family/count before outcomes; schema2 immutable contract, CLI cannot weaken fixed floors. Old schema1 policies fail closed, baseline rollback still works. validate must enforce contract/gates/finite decision evidence, not only hash equality.
- Use existing lifecycle and test intent; update old fixtures to legitimate strong multiwindow candidates, never weaken production thresholds to make tests pass. Existing small fixture integration can properly retain baseline and verify tracing separately.

Start with reproduction tests that fail old code, preserve red log in docs/verification/audit-20261026. Confirm archived S01 delta from old evidence without overwriting. Implement and test. New selection on actual synthetic data can use /workspace/harbinger-runs/ci-smoke (inspect) or dedicated tmp bootstrap; don't overwrite existing records/models. Record raw selection results and exact data/model hash, no independent-test claim.
Report full changes, commands/results/limitations in docs/verification/audit-20261026/policy-report.md; return concise status. Controller doing energy/operations independently; shared worktree /workspace/harbinger branch fix/audit-policy-energy-ops-20261026. No network/deployment required for your task.
