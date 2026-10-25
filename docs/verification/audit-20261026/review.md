# Independent whole-branch review

Reviewed the uncommitted branch against `0c36ba0`, `/tmp/hb-audit-review.diff`, the fixed audit plan, policy evidence/report, execution ledger, regression tests, and local operations harness/evidence. No remote resources, AWS requests, or public deployment were used. The existing final test log reports **260 passed, 1 skipped**; I did not repeat the full suite. I ran two small local edge-case reproductions described below. This report records the reviewed state before any resulting fixes.

## Verdict

No Critical findings. **Two Important findings should be corrected before completion:** incomplete handling of missing energy values and loss of required eligibility evidence for empty snapshots. The controller confirmed the latter is Important because complete missing/stale counts are a user requirement, despite baseline fallback remaining safe.

## Important

### I1. Missing daily energy values can receive a verdict, and the no-model response can fail JSON serialization

Locations: `src/harbinger/models/energy.py:69`, `src/harbinger/api/store.py:357`, `src/harbinger/api/store.py:369`.

`anomalies()` treats a finite rolling z-score as sufficient for a current-day verdict. Pandas rolling means skip NaN current readings, so prior observations can produce a finite z-score on a day whose actual energy is missing. `Store.energy_anomalies()` counts this day as both observed and evaluable. Separately, the newly added no-model branch uses `float(r[target])` rather than the finite-to-null conversion used by the model branch, allowing NaN/Infinity into the response. The parquet loader does not enforce finite energy readings.

Reproduction using the existing small test helper:

```python
from tests.test_energy_availability import store
import numpy as np
import pandas as pd
import json

s = store(7)
s.tables['energy'].loc[6, 'electricity_kwh'] = np.nan
r = s.energy_anomalies('S', pd.Timestamp('2024-01-07'), 1)
# Actual observed result: actual=None, status='available', anomaly=True,
# n_observed_days=1, n_evaluable_days=1, n_anomaly_days=1.
# Making the preceding readings 100 instead yields a normal/False verdict.
s.bundle['energy'] = None
r = s.energy_anomalies('S', pd.Timestamp('2024-01-07'), 1)
json.dumps(r, allow_nan=False)
# ValueError: Out of range float values are not JSON compliant: nan
```

Require a finite current reading/residual as well as sufficient trailing history before emitting a daily verdict. Count genuinely observed days consistently, and apply nullable finite-number serialization in both model branches. Add a missing-current-reading regression and an API/report serialization regression with an unavailable model; include Infinity if supporting arbitrary parquet inputs.

### I2. An all-empty snapshot result loses stale/missing asset counts

Location: `src/harbinger/models/site_policy.py:164`.

After `snapshots()` attaches the complete site/date `grid`, `if rows.empty: rows = frame.iloc[:0].copy()` discards those attributes. An all-stale or all-future input still correctly retains baseline, but immutable evidence now reports zero missing/stale assets, contradicting the documented full-grid accounting.

Reproduction: use the existing `candidate.__wrapped__(temporary_path)` fixture, set all inspection `t` values to `2023-01-01`, supply its 80 distinct assets plus matching inspections and an empty typed workorders table, then select for `2024-02-01` through `2024-05-01`. Observed evidence has `grid=[]`; its first date has `assets=0, stale_assets=0, missing_assets=0`, although all 80 assets are stale. Preserve snapshot attributes when normalizing an empty frame and assert stale/missing counts in the all-empty case.

## Minor

No additional actionable Minor findings. The pending completion section and initial-state progress ledger need their normal final update before the PR is presented as complete.

## Confirmed strengths and scope

- The selector fixes budget 10, common nonoverlapping 30-day dates, per-date eligibility, equal date weighting, positive mean precision improvement, no individual-date precision regression, and minimum Brier improvement. Excellent Brier with harmful ranking is explicitly rejected. Duplicate assets per date are rejected; a repeated single asset cannot satisfy the production floor.
- Snapshot construction retains original inspection timestamps for refresh, uses historical workorders strictly before the snapshot for features, and relabels breakdowns strictly after the snapshot through day 30 inclusive.
- Asset bootstrap resamples complete histories and reranks clones; date bootstrap retains whole dates. Draws are paired between candidates, undersized draws fail conservatively, and multiplicity-adjusted bounds are fixed. Documentation appropriately states that these separate checks do not guarantee simultaneous coverage under arbitrary crossed dependence or establish field effectiveness.
- A strong synthetic candidate is actually selected, activated, and resolved to its candidate model. Lifecycle/CAS/rollback, chronology, loaded-bundle/evidence hashes, fixed-contract validation, and bounded content-based decision cache checks remain present. The real synthetic run honestly withholds all five sites and keeps the future test unscored.
- Ordinary missing-history, short-history, unseen-site, calendar-gap, overlap-window, and future-invariance cases are covered. JSON/Markdown/UI propagate nullable verdicts for those covered cases.
- Middleware records latency even when computation raises and separates successful requests, server failures, intentional 429s, and other client errors without token labels. Promtool checks all three main routes. The real local harness records actual API traffic and receives slow/failure firing and resolved notifications under explicitly accelerated rules. Capacity saturation is separately recorded; it is not represented as end-to-end capacity-alert notification coverage.
- Local load evidence distinguishes configuration limits from sampled process usage and explicitly reports the 90% rejection rate under concurrency 4. It does not claim AWS/customer capacity or a deployed external notification channel.

Final PR/CI/Docker completion and evidence-index updates were still being completed by the controller during this review; this review does not certify those pending steps or public deployment.

## Controller resolution

Both Important findings were reproduced by dedicated failing tests (`review-energy-red.txt`, `review-grid-red.txt`), fixed (`review-fixes-green.txt`), and followed by the whole suite: 262 passed, 1 optional TensorFlow test skipped. No further independent re-review is claimed.
