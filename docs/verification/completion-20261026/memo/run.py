import concurrent.futures, datetime, hashlib, json, os, pathlib, subprocess, time
ROOT = pathlib.Path('/workspace/harbinger-runs/completion-20261026/memo')
SOURCE = pathlib.Path('/tmp/harbinger-memo-5a')
PYTHON = '/tmp/hb-audit-venv/bin/python'
env = dict(os.environ, PYTHONPATH=str(SOURCE / 'src'), OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MPLCONFIGDIR='/tmp/hb-completion-mpl')
def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
def write(name, value):
    (ROOT/name).write_text(json.dumps(value,indent=2)+'\n')
write('historical-before-sha256.json', hashes(SOURCE/'docs/verification/memo-20261025'))
write('execution.json', {'source_commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=SOURCE,text=True).strip(), 'cwd':str(SOURCE),'environment':{k:env[k] for k in ('PYTHONPATH','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MPLCONFIGDIR')},'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'parallel_worlds':3})
def run(seed):
    cmd=[PYTHON,'-m','scripts.memo_robustness','--data-seed',str(seed),'--work','/tmp/hb-completion-memo/work','--out',str(ROOT/'results')]
    info={'data_seed':seed,'command':cmd,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    start=time.monotonic()
    with (ROOT/'logs'/f'run-{seed}.txt').open('x') as output:
        result=subprocess.run(cmd, cwd=SOURCE, env=env, stdout=output, stderr=subprocess.STDOUT)
    info.update(exit_code=result.returncode,duration_seconds=time.monotonic()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write(f'logs/run-{seed}.json',info)
    print(json.dumps(info),flush=True)
    return info
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results=list(pool.map(run, (202610251,202610252,202610253)))
write('runs.json', results)
assert all(r['exit_code']==0 for r in results), results
cmd=[PYTHON,'-m','scripts.memo_summary',str(ROOT/'results')]
start=time.monotonic()
with (ROOT/'logs'/'summary-revalidation.txt').open('x') as output:
    result=subprocess.run(cmd,cwd=SOURCE,env=env,stdout=output,stderr=subprocess.STDOUT)
write('logs/summary-revalidation.json', {'command':cmd,'exit_code':result.returncode,'duration_seconds':time.monotonic()-start})
assert result.returncode==0
assert hashes(SOURCE/'docs/verification/memo-20261025')==json.loads((ROOT/'historical-before-sha256.json').read_text())
print('ALL RUNS AND SUMMARY PASSED; HISTORICAL FILES UNCHANGED',flush=True)
