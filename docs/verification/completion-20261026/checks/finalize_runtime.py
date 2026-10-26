"""Package the completed run; fitting used def9c94's unchanged model/feature code."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from harbinger.eval.run import save_patrol_evaluation

runtime = Path('/tmp/hb-completion-final')
art = runtime/'artifacts'
metrics = json.loads((art/'metrics.json').read_text())
patrol = json.loads((art/'patrol.json').read_text())
if 'rows' in patrol:
    patrol = save_patrol_evaluation(patrol, art)
    metrics['patrol'] = patrol
    for name, value in [('patrol',patrol),('metrics',metrics)]:
        (art/f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
fit_commit = subprocess.check_output(['git','rev-parse','def9c94'],text=True).strip()
fit_paths = subprocess.check_output(['git','ls-tree','-r','--name-only',fit_commit,'src/harbinger/features','src/harbinger/models','src/harbinger/eval','src/harbinger/synth'],text=True).splitlines()
proof = {
 'model_version':metrics['bundle_version'], 'base_commit':fit_commit,
 'synthetic':True,'seed':20260101,'scale':1,'months':36,'quick':False,'skip_loso':False,
 'feature_semantics_version':metrics['observation']['feature_semantics_version'],
 'note':'Fit/evaluation source snapshot def9c94; pipeline started before that commit was recorded, with those source bytes. Membership packaging alone was applied after fitting with save_patrol_evaluation. No refit/reselection or metric changes in packaging. Current serving code is bound separately by release hashes.',
 'fit_source_sha256':{p:hashlib.sha256(subprocess.check_output(['git','show',f'{fit_commit}:{p}'])).hexdigest() for p in fit_paths if p.endswith('.py')},
 'artifact_packaging_source_sha256':hashlib.sha256(Path('src/harbinger/eval/run.py').read_bytes()).hexdigest(),
 'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((runtime/'data').glob('*.parquet'))},
 'model_sha256':{str(p.relative_to(runtime/'models')):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((runtime/'models').rglob('*')) if p.is_file()},
 'training_seconds':metrics['elapsed_seconds'],
 'command':'OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 harbinger eval --data /tmp/hb-completion-final/data --models /tmp/hb-completion-final/models --artifacts /tmp/hb-completion-final/artifacts --seed 20260101',
}
(art/'training-provenance.json').write_text(json.dumps(proof,indent=2)+'\n')
for path in art.iterdir():
    if path.is_file(): shutil.copy2(path,Path('artifacts')/path.name)
print(json.dumps({'model_version':metrics['bundle_version'],'seconds':metrics['elapsed_seconds'],'classifier':metrics['classifier']['hgb_full'],'patrol':patrol['methods']['harbinger_hgb'],'service':patrol['service_policy']['methods']['harbinger_hgb']},indent=2))
