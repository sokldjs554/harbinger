# Signal intervals and operational rules — 2026-10-25

Task 1 changes site-level uncertainty and makes the existing exporter contract runnable in Prometheus. This is synthetic-data/statistical and local rule-engine verification; it is not a field validation, customer SLO calibration, or delivered notification drill.

## Signal calculation

- Input: `/tmp/hb-memo-full/data-202610251/data/features.parquet`.
- SHA256: `2d6ce147ee45a85f0e24dfae0bf9448ed988f217719ef9f22eb39d474f599e72` (19,670,470 bytes).
- 126,861 source rows; 123,415 label-valid rows; 25 sites. Source observation times span 2023-01-01 through 2025-12-31. Base descriptive failure rate: 0.0777863306729328.
- New output: [signals-ops-full.json](signals-ops-full.json). Original `artifacts/signals.json`, archived reports and deployed verification snapshots are preserved.
- 95% pointwise percentile site-cluster bootstrap: 2,000 draws, seed 20261025, NumPy default RNG; linear 2.5% / 97.5% quantiles. Sites are sorted before sampling. Within each fixed descriptive cell, contributing sites are drawn with replacement. Each selected site's complete row count and positive count travel together; their sum ratio estimates the pooled row-weighted rate. This preserves within-site repeated asset, inspector and time dependence without materializing duplicate rows.
- Every cell reports `n`, `k`, `rate`, `n_clusters` and `ci_status`. Empty cells return null rate and bounds; missing cluster IDs, fewer than 5 contributing sites, and a single observed outcome withhold bounds. Invalid mature labels raise an explicit binary-outcome error. JSON uses strict serialization without NaN.
- Five sites is an explicit minimum reporting floor, not evidence that 95% coverage is achieved with five sites. Site independence, fixed group definitions, cross-site inspector dependence, multiplicity, and generator uncertainty remain limitations. These are descriptive rates, not causal effects or model accuracy.

On the **same input**, all 15 cell sample counts, positive counts and rates match the legacy implementation at baseline commit `a66c0350b72fafcc9be900b61cd88cad3b5588b1`. See [signals-ops-comparison.json](signals-ops-comparison.json). Cluster / legacy-Wilson width ratios range from **0.9088 to 2.6872**: the bad-without-weak cell is narrower, while 14 others are wider. No width direction was assumed. The console explains the method supplied by the artifact, and labels old artifacts as historical Wilson calculations without claiming their intervals must be narrower.

Reproduce the new artifact from that source:

```bash
OMP_NUM_THREADS=1 PYTHONPATH=src:. python scripts/make_signals.py \
  --data /tmp/hb-memo-full/data-202610251/data \
  --out docs/verification/remaining-gaps-20261025/signals-ops-full.json
```

The temporary source path is provenance for this run, not a promise that the source is stored in Git. NumPy 2.5.4 and pandas 2.3.3 were used. Re-running against another source must record its own hash.

## Prometheus

[deploy/monitoring/rules.yml](../../../deploy/monitoring/rules.yml) supplies 4 recording and 11 alert rules. The p95 rule uses `rate(harbinger_request_seconds_bucket[5m])`, retaining `le`, and the exported route `/v1/sites/{site_id}/patrol/today`. A minimum 20 observations guards the latency alert. Histogram quantiles approximate values within buckets. Model loading checks handle a missing gauge as well as a zero gauge. Drift alerts distinguish success with changed features, insufficient data, computation errors, initialization, missing status metrics, and stale computations. Target down and an entirely missing scrape job are separate states. The p30 mean uses `_sum`/`_count`, and is suppressed when there are no observations; repeat online predictions are not population-level daily performance.

`deploy/monitoring/prometheus.yml` is a standalone local configuration. The runbook documents Compose mounting and `rule_files` integration. Alertmanager recipients and notification routing are intentionally not configured or exercised.

Official release archives were fetched over HTTPS from `github.com/prometheus/prometheus/releases/download` and their SHA256 values were matched to each release's `sha256sums.txt` before extraction/execution:

| Version | Archive SHA256 | Result |
|---|---|---|
| 2.54.1 (existing Compose pin) | `31715ef65e8a898d0f97c8c08c03b6b9afe485ac84e1698bcfec90fc6e62924f` | check rules, test rules, check config passed |
| 3.5.0 | `e811827af26d822afb09a4f28314f61b618b12cff5369835a67f674d8b46f39a` | check rules, test rules, check config passed |

[signals-ops-promtool.txt](signals-ops-promtool.txt) records versions, official download URLs, checksum verification and command output. The 12 test groups cover pending/firing/recovery, scrape absence/down, missing/zero model metrics, drift insufficient/error/initializing/missing/stale states, low-traffic withholding, real/incorrect route matching, server-error counters, and prediction means with no observations. A negative control changes `{site_id}` to the legacy `{id}` selector: the real-route and wrong-route tests fail as expected ([signals-ops-promtool-regression.txt](signals-ops-promtool-regression.txt)).

## Checks and limits

- Regression RED: 10 expected failures / 1 existing point-estimate pass before implementation, recorded in [signals-ops-red.txt](signals-ops-red.txt). The CLI provenance test separately failed on missing `source` before its fix.
- Focused GREEN: 12 tests pass, including repeated asset/inspector cluster preservation, row-order determinism, row-weighted rates, insufficient/missing/single-outcome handling, empty strict JSON, invalid labels and CLI source hash.
- Full repository suite: **180 passed, 1 skipped**, 45.17 seconds ([signals-ops-pytest.txt](signals-ops-pytest.txt)).
- Focused Ruff, `node --check src/harbinger/console/app.js`, and `git diff --check` passed.
- No production rollout, long-running monitoring observation, actual incident, notification delivery, or field/customer performance is claimed. Existing Nginx request/connection limits were not changed.
