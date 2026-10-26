# Corrected-source memo rerun evidence

[Full report](report.md) · [Summary](results/summary.json) · [All 720 comparisons](all-runs-metrics-comparison.csv) · [Mean comparisons](mean-metrics-comparison.csv) · [Descriptive variation](dispersion-comparison.csv)

The original fixed gate passed again. Validation-selected 25/50% missingness improvement over the same-run legacy model averaged **5.100 percentage points** (historically 5.297); clean change averaged **+0.139 points** (historically +0.170). This reruns known synthetic seeds and is not new independent performance proof or a production-default selection.

Source is `5a7f947146dd24b43eb79a8e4744449615dabc17`, feature semantics v3. Corrected site masking is one fresh 30% mask per epoch, versus the historical combined expectation of 51%; robust memo dropout remains 35%. The original experiment settings, selection criteria and six-run adoption gate were unchanged.

## Complete verification package

The complete approximately 47 MB result folder is retained, following the earlier memo evidence convention: twelve raw prediction archives, twelve cohort/label CSVs, twelve transformed memo snapshots, per-condition metrics, selection/freezing records, bootstrap intervals, all eighteen training-history/weight-hash JSON files, provenance, complete comparison JSON/CSV files, execution commands/logs, and historical preservation evidence. These files are copied byte-for-byte from the verified run.

Every original root/world `sha256.json` is preserved **unchanged**, including all memo-snapshot entries. The separate `package-sha256.json` covers every packaged file except itself, including this README and additional packaging verification records. No manifest entry was removed to accommodate exclusions. No file from the original 47 MB evidence folder is excluded.

Generated source Parquet tables and binary trained weights were already outside that evidence folder and are not copied into the repository. Their hashes, training histories and exact reproduction commands are retained. [packaging.json](packaging.json) records paths and package scope. Packaging changes no source, predictions, cohort rows, outcome labels, metrics, model histories, selection decisions or historical evidence.

## Revalidate without training

From the repository root, with its documented Python environment:

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
PYTHONPATH=src python -m scripts.memo_summary docs/verification/completion-20261026/memo/results
```

This recomputes validation/test metrics, all frozen choices, adoption gates and paired site bootstrap intervals from saved arrays, and checks every original world-manifest entry, gzip integrity, probability ranges, timing boundaries and no-memo prediction invariance. The exact source checkout above was used for the stored [package verification log](logs/package-summary-revalidation.txt). No training is required or performed.

## Full reproduction

The original complete output remains at `/workspace/harbinger-runs/completion-20261026/memo`; generated source tables and trained weights remain at `/tmp/hb-completion-memo/work`. These local temporary paths are not durable substitutes for the committed evidence. [run.py](run.py) and [compare.py](compare.py) preserve the original workspace-specific orchestration/comparison commands; [the report](report.md) records the exact executed commands and durations.

To regenerate raw data, trained weights or all model results elsewhere, check out the exact source commit, install the recorded package versions from the world provenance, and use **fresh** work/output paths (the runner refuses overwrites):

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
for seed in 202610251 202610252 202610253; do
  PYTHONPATH=src python -m scripts.memo_robustness --data-seed "$seed" --work /tmp/memo-reproduction-work --out /tmp/memo-reproduction-results
done
PYTHONPATH=src python -m scripts.memo_summary /tmp/memo-reproduction-results
```

These commands document reproduction only; packaging did not launch new training. All historical files under `docs/verification/memo-20261025` were preserved.
