# Corrected-source missing-memo rerun — 2026-10-26

This is a retrospective rerun of the already-known data seeds 202610251/202610252/202610253 and training seeds 17/29. It is not a new independent performance proof. The six runs are two training seeds nested within three synthetic worlds, not six independent customer populations. No production default was selected or changed by this experiment.

Corrected source: `5a7f947146dd24b43eb79a8e4744449615dabc17`, detached checkout `/tmp/harbinger-memo-5a`. Historical provenance records `20a79f7af445857f2949291ffc8fc3c2090498bd`; that historical commit object is unavailable in the local checkout, so comparisons use preserved per-file SHA256 provenance rather than a Git diff. Historical artifacts are preserved without overwrite.

The original experiment contract is unchanged: scale 1; 36 months; 24/6/6 chronological split; maximum 40 epochs, patience 6, learning rate .002, batch 1024; legacy/robust/no_memo; clean/25%/50%/100% missing memos; original validation-only selection and held-out adoption rule. The original design hash, model configuration, package versions, and split descriptions match. 100% missingness remains stress reporting only.

Feature semantics are version **3**, versus historical version **2**. Site-ID masking was corrected from an initial permanent 30% mask plus another 30% epoch mask (51% expected combined masking) to a single fresh **30%** epoch mask. This is separate from the robust model’s unchanged **35% memo dropout**. Consequently score differences reflect the corrected source as a whole, not an isolated causal estimate for site dropout.

## Execution and verification

All three worlds ran concurrently with one OpenMP/OpenBLAS thread each, using local CPU only. No paid resources, network calls, or API sockets were used. Exact commands, UTC times, exit codes and durations are in `logs/run-*.json`; full stdout/stderr in `logs/run-*.txt`. The orchestrator is `run.py`.

```bash
cd /tmp/harbinger-memo-5a
export PYTHONPATH=/tmp/harbinger-memo-5a/src OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLCONFIGDIR=/tmp/hb-completion-mpl
/tmp/hb-audit-venv/bin/python -m scripts.memo_robustness --data-seed 202610251 --work /tmp/hb-completion-memo/work --out /workspace/harbinger-runs/completion-20261026/memo/results
/tmp/hb-audit-venv/bin/python -m scripts.memo_robustness --data-seed 202610252 --work /tmp/hb-completion-memo/work --out /workspace/harbinger-runs/completion-20261026/memo/results
/tmp/hb-audit-venv/bin/python -m scripts.memo_robustness --data-seed 202610253 --work /tmp/hb-completion-memo/work --out /workspace/harbinger-runs/completion-20261026/memo/results
/tmp/hb-audit-venv/bin/python -m scripts.memo_summary /workspace/harbinger-runs/completion-20261026/memo/results
/tmp/hb-audit-venv/bin/python /workspace/harbinger-runs/completion-20261026/memo/compare.py
```

| Data seed | Exit | Duration (seconds) |
|---|---:|---:|
| 202610251 | 0 | 1354.1 |
| 202610252 | 0 | 1366.2 |
| 202610253 | 0 | 1391.0 |

Existing summary revalidation exited 0. It recomputed both validation and test metrics from saved arrays, all six selections, freeze and validation hashes, all paired site bootstrap intervals, finite/range checks, cohort uniqueness/maturity, gzip CRCs, artifact hashes, and exact no-memo prediction invariance across conditions. 118 historical files remain byte-identical in both the detached checkout and main working repository. No experimental run or summary failure occurred. Existing NumPy timedelta deprecation and PyTorch scalar-conversion warnings are retained in the logs; no source was changed to suppress them.

The runner also asserted all pre-training features/labels unchanged by damage, all four label/survival fields unchanged, memo-independent numerical features unchanged, and identical condition cohorts. Independent post-run checks match actual changed memo rows to recorded damage counts, confirm only eligible post-training memos were emptied, and confirm all historical/new validation and test rows and labels agree. All 21 generated raw-source table hashes (seven tables × three worlds) match history; generated `features.parquet` is audited separately because feature semantics changed.

## Mean held-out performance

Precision@10 below is the original sum-of-hits / sum-of-selected estimator. Its site-block bootstrap recomputes that same ratio. It is intentionally not rewritten as the separate equal-customer patrol estimator.

| Model | Condition | Historical P@10 | Corrected P@10 | Change (pp) | Historical AUROC | Corrected AUROC | Historical PR-AUC | Corrected PR-AUC | Historical Brier | Corrected Brier |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy | clean | 0.237000 | 0.237242 | +0.024 | 0.748122 | 0.748506 | 0.227353 | 0.226980 | 0.068506 | 0.068419 |
| legacy | missing_25 | 0.176364 | 0.179727 | +0.336 | 0.700421 | 0.702724 | 0.161395 | 0.163448 | 0.080471 | 0.079453 |
| legacy | missing_50 | 0.177061 | 0.179485 | +0.242 | 0.680301 | 0.683425 | 0.159400 | 0.161063 | 0.090541 | 0.088613 |
| legacy | missing_100 | 0.192818 | 0.193909 | +0.109 | 0.701734 | 0.703146 | 0.175899 | 0.176057 | 0.105619 | 0.102059 |
| robust | clean | 0.231970 | 0.232242 | +0.027 | 0.744828 | 0.746578 | 0.219111 | 0.221021 | 0.069195 | 0.068964 |
| robust | missing_25 | 0.228970 | 0.230515 | +0.155 | 0.740543 | 0.742061 | 0.214000 | 0.216902 | 0.069514 | 0.069310 |
| robust | missing_50 | 0.228788 | 0.229364 | +0.058 | 0.737220 | 0.739218 | 0.212073 | 0.215286 | 0.069770 | 0.069587 |
| robust | missing_100 | 0.225273 | 0.226970 | +0.170 | 0.733389 | 0.735577 | 0.207886 | 0.212009 | 0.070275 | 0.070142 |
| no_memo | clean | 0.237303 | 0.237515 | +0.021 | 0.740652 | 0.740941 | 0.226182 | 0.226038 | 0.069073 | 0.069206 |
| no_memo | missing_25 | 0.237303 | 0.237515 | +0.021 | 0.740652 | 0.740941 | 0.226182 | 0.226038 | 0.069073 | 0.069206 |
| no_memo | missing_50 | 0.237303 | 0.237515 | +0.021 | 0.740652 | 0.740941 | 0.226182 | 0.226038 | 0.069073 | 0.069206 |
| no_memo | missing_100 | 0.237303 | 0.237515 | +0.021 | 0.740652 | 0.740941 | 0.226182 | 0.226038 | 0.069073 | 0.069206 |

Full-precision means, including log loss, are in `mean-metrics-comparison.csv`. `dispersion-comparison.csv` reports all six-run means, sample standard deviations, minima and maxima; these are descriptive variation across nested runs, not independent-world uncertainty estimates. All 720 individual validation/test metric comparisons (six runs × two phases × three models × four conditions × five metrics) are in `all-runs-metrics-comparison.csv`.

## All six validation-selected outcomes

Each delta below compares that run’s validation-selected model with that same run’s legacy on held-out test. Historical and corrected selections can differ.

| World / training seed | Historical choice | Corrected choice | Historical clean delta (pp) | Corrected clean delta (pp) | Historical 25/50 mean gain (pp) | Corrected 25/50 mean gain (pp) |
|---|---|---|---:|---:|---:|---:|
| 202610251 / 17 | no_memo | no_memo | +0.091 | -0.018 | +6.318 | +6.064 |
| 202610251 / 29 | no_memo | no_memo | +0.255 | +0.945 | +7.755 | +8.273 |
| 202610252 / 17 | no_memo | robust | -0.182 | -0.036 | +5.473 | +5.518 |
| 202610252 / 29 | no_memo | no_memo | -0.545 | -0.455 | +4.982 | +4.836 |
| 202610253 / 17 | no_memo | robust | +1.400 | +0.400 | +7.255 | +5.909 |
| 202610253 / 29 | legacy | legacy | +0.000 | +0.000 | +0.000 | +0.000 |

The selected-policy mean 25/50-missing gain versus same-run legacy is 5.297 percentage points historically and 5.100 now. Mean clean delta is +0.170 and +0.139 percentage points, respectively. The current selected-policy mean clean Brier / legacy mean clean Brier is 1.004797. These comparisons use each version’s separately frozen validation choices.

Historical frozen adoption gate: **True**. Corrected rerun gate: **True**. Each criterion is recorded in `results/summary.json`; thresholds were not adjusted after seeing results.

| Gate criterion | Historical | Corrected |
|---|---|---|
| six_runs | True | True |
| finite | True | True |
| every_clean_drop_at_most_2pp | True | True |
| every_missing_mean_nondecreasing | True | True |
| mean_missing_gain_at_least_2pp | True | True |
| mean_clean_drop_at_most_1pp | True | True |
| mean_clean_brier_at_most_5pct_worse | True | True |

## Raw data, source and damage audit

`raw-source-hash-comparison.json` compares every raw-table/feature SHA256; `code-hash-comparison.json` compares every recorded source SHA256. Current code hashes were checked against the fixed checkout. `cohort-comparison.json` preserves every historical/new cohort comparison and compressed artifact hash. Gzip byte differences alone do not imply data differences; parsed rows and labels are compared.

| World | Condition | Eligible rows | Changed rows | Historical damage record identical |
|---|---|---:|---:|---|
| 202610251 | missing_25 | 42208 | 10490 | True |
| 202610251 | missing_50 | 42208 | 21036 | True |
| 202610251 | missing_100 | 42208 | 42208 | True |
| 202610252 | missing_25 | 41203 | 10135 | True |
| 202610252 | missing_50 | 41203 | 20360 | True |
| 202610252 | missing_100 | 41203 | 41203 | True |
| 202610253 | missing_25 | 42667 | 10719 | True |
| 202610253 | missing_50 | 42667 | 21357 | True |
| 202610253 | missing_100 | 42667 | 42667 | True |

`damage-comparison.json` contains complete damage records, including requested rate and deterministic seed. `verification.json` records final checks. Each run’s provenance and artifact hashes remain in `results/data-*/`. Training epoch counts and best clean-validation NLL for all 18 fits are compared in `training-comparison.json`; saved weight/metadata hashes were rechecked. Trained weights and full generated data are in `/tmp/hb-completion-memo/work`.

The retrospective results do not establish real-customer generalization, superiority over HGB, production suitability, or a new independent replication. The archived provenance’s inherited phrase “Synthetic new seeds” describes the original design and must not be read as fresh seeds in this rerun. No deployment, default replacement, test-driven retuning, or historical result rewrite was performed.
