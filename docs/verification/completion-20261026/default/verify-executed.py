"""Recompute saved HGB scores and the frozen validation decision, without fitting."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.default_model_selection import snapshot_metrics, choose_default, verify_freeze

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
root = parser.parse_args().root
choice = verify_freeze(root)
runs = {'validation': [], 'test': []}
for phase in runs:
    for path in sorted(root.glob(f'*/model-*/{phase}/run.json')):
        saved = json.loads(path.read_text())
        rows = pd.read_csv(path.parent / 'rows.csv.gz', parse_dates=['decision_at', 'source_t'])
        arrays = np.load(path.parent / 'predictions.npz')
        for name in ('full', 'no_memo'):
            actual = snapshot_metrics(rows, arrays[name])
            for metric in ('auroc', 'pr_auc', 'brier', 'precision_at_k'):
                assert np.isclose(actual[metric], saved['models'][name][metric], rtol=1e-12, atol=1e-12)
            for site, value in actual['per_site_precision'].items():
                assert np.isclose(value, saved['models'][name]['per_site_precision'][site], atol=1e-12)
        runs[phase].append(saved)
    assert len(runs[phase]) == 6
assert choose_default(runs['validation']) == choice
summary = {'selected_before_test': choice['selected'], 'recomputed_all_scores': True,
           'selection_unchanged': True, 'runs': runs, 'means': {}, 'dispersion': {},
           'note': '3 synthetic worlds x 2 training seeds; descriptive variation, not six independent worlds. Classification scores use snapshot rows; P@10 is equal-site/equal-day. Validation reused for calibration.'}
for phase in runs:
    summary['means'][phase], summary['dispersion'][phase] = {}, {}
    for name in ('full', 'no_memo'):
        summary['means'][phase][name], summary['dispersion'][phase][name] = {}, {}
        for metric in ('auroc','pr_auc','brier','precision_at_k'):
            values = [r['models'][name][metric] for r in runs[phase]]
            summary['means'][phase][name][metric] = float(np.mean(values))
            summary['dispersion'][phase][name][metric] = {'sd': float(np.std(values, ddof=1)), 'min': min(values), 'max': max(values)}
(root / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
print(json.dumps({'means': summary['means'], 'selected': choice['selected']}, indent=2))
