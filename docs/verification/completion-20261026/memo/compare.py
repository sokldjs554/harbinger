import csv, hashlib, json, pathlib, statistics
import numpy as np
import pandas as pd
ROOT=pathlib.Path('/workspace/harbinger-runs/completion-20261026/memo')
SOURCE=pathlib.Path('/tmp/harbinger-memo-5a')
OLD=SOURCE/'docs/verification/memo-20261025/results'
NEW=ROOT/'results'
MODELS=('legacy','robust','no_memo')
CONDITIONS=('clean','missing_25','missing_50','missing_100')
METRICS=('precision_at_k','auroc','pr_auc','brier','logloss')
def read(path): return json.loads(path.read_text())
def save(name,value): (ROOT/name).write_text(json.dumps(value,indent=2)+'\n')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def csvfile(name,rows):
    with (ROOT/name).open('w') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
old,new=read(OLD/'summary.json'),read(NEW/'summary.json')
raw,source,damage,cohorts,details,training=[],[],[],[],[],[]
for ds in (202610251,202610252,202610253):
    a,b=[read(base/f'data-{ds}'/'provenance.json') for base in (OLD,NEW)]
    assert b['source_commit']=='5a7f947146dd24b43eb79a8e4744449615dabc17'
    assert b['features']['feature_semantics_version']==3
    assert b['design_sha256']==a['design_sha256']
    assert b['model_config']==a['model_config']
    assert b['packages']==a['packages']
    assert b['split']==a['split']
    for name in sorted(a['raw_sha256'].keys()|b['raw_sha256'].keys()):
        actual=pathlib.Path('/tmp/hb-completion-memo/work')/f'data-{ds}'/'data'/name
        assert sha(actual)==b['raw_sha256'][name]
        raw.append({'data_seed':ds,'file':name,'historical':a['raw_sha256'].get(name),'current':b['raw_sha256'].get(name),'equal':a['raw_sha256'].get(name)==b['raw_sha256'].get(name),'generated_source_table':name!='features.parquet'})
    for name in sorted(a['source_sha256'].keys()|b['source_sha256'].keys()):
        source.append({'data_seed':ds,'file':name,'historical':a['source_sha256'].get(name),'current':b['source_sha256'].get(name),'equal':a['source_sha256'].get(name)==b['source_sha256'].get(name)})
    for name, expected in b['source_sha256'].items(): assert sha(SOURCE/name)==expected
    for cond in CONDITIONS[1:]:
        da,db=a['damage'][cond],b['damage'][cond]
        damage.append({'data_seed':ds,'condition':cond,'historical':da,'current':db,'equal':da==db})
        clean=pd.read_csv(NEW/f'data-{ds}'/'clean-memos.csv.gz',keep_default_na=False)
        altered=pd.read_csv(NEW/f'data-{ds}'/f'{cond}-memos.csv.gz',keep_default_na=False)
        pd.testing.assert_frame_equal(clean[['inspection_id','t']],altered[['inspection_id','t']])
        changed=clean.memo!=altered.memo
        assert int(changed.sum())==db['changed_rows']
        assert (altered.loc[changed,'memo']=='').all()
        assert not (changed & (pd.to_datetime(clean.t)<pd.Timestamp(b['split']['train']['to']))).any()
    for ms in (17,29):
        for m in MODELS:
            ta,tb=[read(base/f'data-{ds}'/f'model-{ms}'/f'{m}-training.json') for base in (OLD,NEW)]
            training.append({'data_seed':ds,'model_seed':ms,'model':m,'historical_epochs_run':ta['epochs_run'],'current_epochs_run':tb['epochs_run'],'historical_best_val_nll':ta['best_val_nll'],'current_best_val_nll':tb['best_val_nll']})
            for name,expected in tb['saved_model_sha256'].items():
                assert sha(pathlib.Path('/tmp/hb-completion-memo/work')/f'data-{ds}'/f'model-{ms}'/m/name)==expected
        for phase in ('validation','test'):
            pa,pb=[base/f'data-{ds}'/f'model-{ms}'/phase for base in (OLD,NEW)]
            ra,rb=[pd.read_csv(p/'rows.csv.gz') for p in (pa,pb)]
            same=ra.equals(rb)
            cohorts.append({'data_seed':ds,'model_seed':ms,'phase':phase,'same_rows_labels':same,'historical_rows':len(ra),'current_rows':len(rb),'historical_sha256':sha(pa/'rows.csv.gz'),'current_sha256':sha(pb/'rows.csv.gz')})
            ma,mb=[read(p/'metrics.json') for p in (pa,pb)]
            for m in MODELS:
                for c in CONDITIONS:
                    for metric in METRICS:
                        details.append({'data_seed':ds,'model_seed':ms,'phase':phase,'model':m,'condition':c,'metric':metric,'historical':ma[m][c][metric],'current':mb[m][c][metric],'delta':mb[m][c][metric]-ma[m][c][metric]})
means=[]
dispersion=[]
for m in MODELS:
    for c in CONDITIONS:
        for metric in METRICS:
            a,b=old['test_means'][m][c][metric],new['test_means'][m][c][metric]
            means.append({'model':m,'condition':c,'metric':metric,'historical':a,'current':b,'delta':b-a})
            matched=[r for r in details if r['phase']=='test' and r['model']==m and r['condition']==c and r['metric']==metric]
            dispersion.append({'model':m,'condition':c,'metric':metric,**{f'{period}_{stat}':float(fn([r[period] for r in matched])) for period in ('historical','current') for stat,fn in (('mean',np.mean),('sd',lambda x:np.std(x,ddof=1)),('min',min),('max',max))}})
assert all(x['equal'] for x in damage)
assert all(x['same_rows_labels'] for x in cohorts)
assert all(x['equal'] for x in raw if x['generated_source_table'])
original_hashes=read(ROOT/'historical-before-sha256.json')
assert all(sha(SOURCE/'docs/verification/memo-20261025'/p)==h for p,h in original_hashes.items())
assert all(sha(pathlib.Path('/workspace/harbinger/docs/verification/memo-20261025')/p)==h for p,h in original_hashes.items())
save('raw-source-hash-comparison.json',raw);save('code-hash-comparison.json',source);save('damage-comparison.json',damage);save('cohort-comparison.json',cohorts)
save('training-comparison.json',training)
csvfile('all-runs-metrics-comparison.csv',details);csvfile('mean-metrics-comparison.csv',means);csvfile('dispersion-comparison.csv',dispersion)
save('verification.json',{'historical_files_unchanged':len(original_hashes),'raw_source_tables_equal':all(x['equal'] for x in raw if x['generated_source_table']),'cohorts_and_labels_equal':all(x['same_rows_labels'] for x in cohorts),'damage_counts_equal':all(x['equal'] for x in damage),'feature_semantics_version':3,'existing_summary_exit_code':read(ROOT/'logs/summary-revalidation.json')['exit_code'],'failures':[]})
lines=['# Corrected-source missing-memo rerun — 2026-10-26','',
'This is a retrospective rerun of the already-known data seeds 202610251/202610252/202610253 and training seeds 17/29. It is not a new independent performance proof. The six runs are two training seeds nested within three synthetic worlds, not six independent customer populations. No production default was selected or changed by this experiment.','',
'Corrected source: `5a7f947146dd24b43eb79a8e4744449615dabc17`, detached checkout `/tmp/harbinger-memo-5a`. Historical provenance records `20a79f7af445857f2949291ffc8fc3c2090498bd`; that historical commit object is unavailable in the local checkout, so comparisons use preserved per-file SHA256 provenance rather than a Git diff. Historical artifacts are preserved without overwrite.','',
'The original experiment contract is unchanged: scale 1; 36 months; 24/6/6 chronological split; maximum 40 epochs, patience 6, learning rate .002, batch 1024; legacy/robust/no_memo; clean/25%/50%/100% missing memos; original validation-only selection and held-out adoption rule. The original design hash, model configuration, package versions, and split descriptions match. 100% missingness remains stress reporting only.','',
'Feature semantics are version **3**, versus historical version **2**. Site-ID masking was corrected from an initial permanent 30% mask plus another 30% epoch mask (51% expected combined masking) to a single fresh **30%** epoch mask. This is separate from the robust model’s unchanged **35% memo dropout**. Consequently score differences reflect the corrected source as a whole, not an isolated causal estimate for site dropout.','',
'## Execution and verification','',
'All three worlds ran concurrently with one OpenMP/OpenBLAS thread each, using local CPU only. No paid resources, network calls, or API sockets were used. Exact commands, UTC times, exit codes and durations are in `logs/run-*.json`; full stdout/stderr in `logs/run-*.txt`. The orchestrator is `run.py`.','',
'```bash','cd /tmp/harbinger-memo-5a','export PYTHONPATH=/tmp/harbinger-memo-5a/src OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLCONFIGDIR=/tmp/hb-completion-mpl']
for seed in (202610251,202610252,202610253):lines.append(f'/tmp/hb-audit-venv/bin/python -m scripts.memo_robustness --data-seed {seed} --work /tmp/hb-completion-memo/work --out {NEW}')
lines +=[f'/tmp/hb-audit-venv/bin/python -m scripts.memo_summary {NEW}',f'/tmp/hb-audit-venv/bin/python {ROOT}/compare.py','```','', '| Data seed | Exit | Duration (seconds) |','|---|---:|---:|']
for r in read(ROOT/'runs.json'):lines.append(f"| {r['data_seed']} | {r['exit_code']} | {r['duration_seconds']:.1f} |")
lines +=['',f"Existing summary revalidation exited {read(ROOT/'logs/summary-revalidation.json')['exit_code']}. It recomputed both validation and test metrics from saved arrays, all six selections, freeze and validation hashes, all paired site bootstrap intervals, finite/range checks, cohort uniqueness/maturity, gzip CRCs, artifact hashes, and exact no-memo prediction invariance across conditions. {len(original_hashes)} historical files remain byte-identical in both the detached checkout and main working repository. No experimental run or summary failure occurred. Existing NumPy timedelta deprecation and PyTorch scalar-conversion warnings are retained in the logs; no source was changed to suppress them.",'',
'The runner also asserted all pre-training features/labels unchanged by damage, all four label/survival fields unchanged, memo-independent numerical features unchanged, and identical condition cohorts. Independent post-run checks match actual changed memo rows to recorded damage counts, confirm only eligible post-training memos were emptied, and confirm all historical/new validation and test rows and labels agree. All 21 generated raw-source table hashes (seven tables × three worlds) match history; generated `features.parquet` is audited separately because feature semantics changed.','',
'## Mean held-out performance','',
'Precision@10 below is the original sum-of-hits / sum-of-selected estimator. Its site-block bootstrap recomputes that same ratio. It is intentionally not rewritten as the separate equal-customer patrol estimator.','',
'| Model | Condition | Historical P@10 | Corrected P@10 | Change (pp) | Historical AUROC | Corrected AUROC | Historical PR-AUC | Corrected PR-AUC | Historical Brier | Corrected Brier |','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for m in MODELS:
    for c in CONDITIONS:
        a,b=old['test_means'][m][c],new['test_means'][m][c]
        lines.append(f"| {m} | {c} | {a['precision_at_k']:.6f} | {b['precision_at_k']:.6f} | {100*(b['precision_at_k']-a['precision_at_k']):+.3f} | {a['auroc']:.6f} | {b['auroc']:.6f} | {a['pr_auc']:.6f} | {b['pr_auc']:.6f} | {a['brier']:.6f} | {b['brier']:.6f} |")
lines +=['','Full-precision means, including log loss, are in `mean-metrics-comparison.csv`. `dispersion-comparison.csv` reports all six-run means, sample standard deviations, minima and maxima; these are descriptive variation across nested runs, not independent-world uncertainty estimates. All 720 individual validation/test metric comparisons (six runs × two phases × three models × four conditions × five metrics) are in `all-runs-metrics-comparison.csv`.','',
'## All six validation-selected outcomes','',
'Each delta below compares that run’s validation-selected model with that same run’s legacy on held-out test. Historical and corrected selections can differ.','',
'| World / training seed | Historical choice | Corrected choice | Historical clean delta (pp) | Corrected clean delta (pp) | Historical 25/50 mean gain (pp) | Corrected 25/50 mean gain (pp) |','|---|---|---|---:|---:|---:|---:|']
for a,b in zip(old['runs'],new['runs'],strict=True):
    assert (a['data_seed'],a['model_seed'])==(b['data_seed'],b['model_seed'])
    lines.append(f"| {b['data_seed']} / {b['model_seed']} | {a['selected']} | {b['selected']} | {100*a['clean_delta']:+.3f} | {100*b['clean_delta']:+.3f} | {100*a['missing_mean_delta']:+.3f} | {100*b['missing_mean_delta']:+.3f} |")
aggregates={label:{'mean_clean_delta_pp':100*float(np.mean([r['clean_delta'] for r in data['runs']])), 'mean_missing_delta_pp':100*float(np.mean([r['missing_mean_delta'] for r in data['runs']])), 'mean_clean_brier_ratio':float(np.mean([r['clean_brier'] for r in data['runs']])/np.mean([r['legacy_clean_brier'] for r in data['runs']]))} for label,data in (('historical',old),('current',new))}
save('selected-policy-comparison.json',aggregates)
lines +=['',f"The selected-policy mean 25/50-missing gain versus same-run legacy is {aggregates['historical']['mean_missing_delta_pp']:.3f} percentage points historically and {aggregates['current']['mean_missing_delta_pp']:.3f} now. Mean clean delta is {aggregates['historical']['mean_clean_delta_pp']:+.3f} and {aggregates['current']['mean_clean_delta_pp']:+.3f} percentage points, respectively. The current selected-policy mean clean Brier / legacy mean clean Brier is {aggregates['current']['mean_clean_brier_ratio']:.6f}. These comparisons use each version’s separately frozen validation choices."]
lines +=['',f"Historical frozen adoption gate: **{old['adoption']['passed']}**. Corrected rerun gate: **{new['adoption']['passed']}**. Each criterion is recorded in `results/summary.json`; thresholds were not adjusted after seeing results.",'',
'| Gate criterion | Historical | Corrected |','|---|---|---|']
for k,v in new['adoption']['criteria'].items():lines.append(f"| {k} | {old['adoption']['criteria'].get(k)} | {v} |")
lines +=['','## Raw data, source and damage audit','',
'`raw-source-hash-comparison.json` compares every raw-table/feature SHA256; `code-hash-comparison.json` compares every recorded source SHA256. Current code hashes were checked against the fixed checkout. `cohort-comparison.json` preserves every historical/new cohort comparison and compressed artifact hash. Gzip byte differences alone do not imply data differences; parsed rows and labels are compared.','',
'| World | Condition | Eligible rows | Changed rows | Historical damage record identical |','|---|---|---:|---:|---|']
for x in damage:
    d=x['current'];lines.append(f"| {x['data_seed']} | {x['condition']} | {d.get('eligible_rows')} | {d['changed_rows']} | {x['equal']} |")
lines +=['','`damage-comparison.json` contains complete damage records, including requested rate and deterministic seed. `verification.json` records final checks. Each run’s provenance and artifact hashes remain in `results/data-*/`. Training epoch counts and best clean-validation NLL for all 18 fits are compared in `training-comparison.json`; saved weight/metadata hashes were rechecked. Trained weights and full generated data are in `/tmp/hb-completion-memo/work`.','',
'The retrospective results do not establish real-customer generalization, superiority over HGB, production suitability, or a new independent replication. The archived provenance’s inherited phrase “Synthetic new seeds” describes the original design and must not be read as fresh seeds in this rerun. No deployment, default replacement, test-driven retuning, or historical result rewrite was performed.']
(ROOT/'report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'adoption':new['adoption'],'selected':[r['selected'] for r in new['runs']],'report':str(ROOT/'report.md'),'verification':read(ROOT/'verification.json')},indent=2))
