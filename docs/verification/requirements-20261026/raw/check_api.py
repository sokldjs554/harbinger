"""Actual local API regression smoke; no public endpoint or load."""
import json
from pathlib import Path
import httpx

out = Path(__file__).parent
with httpx.Client(base_url='http://127.0.0.1:18021', timeout=120, trust_env=False) as c:
    results = {}
    for route in ['/health', '/ready', '/version', '/v1/workbench/info']:
        r = c.get(route)
        r.raise_for_status()
        results[route] = r.json()
    r = c.get('/v1/sites/S01/report', params={'as_of':'2022-12-31', 'format':'md'})
    r.raise_for_status()
    assert '산출 불가' in r.text or '계산 불가' in r.text or '계산할 수' in r.text, r.text
    results['empty_report'] = {'status': r.status_code, 'text': r.text}
    for date in ['NaT', '2025-01-01T00:00:00Z']:
        r = c.get('/v1/replay', params={'site':'S01', 'from':date})
        assert r.status_code == 422, r.text
        results['date_' + date] = {'status':r.status_code, 'detail':r.json()}
    r = c.post('/v1/sites/S01/assets/A-S01-0001/whatif', json={'scenarios':[{'items':{'noise':128}}]})
    assert r.status_code == 422, r.text
    results['checklist_range'] = {'status': r.status_code, 'detail': r.json()}
    for day in ['2023-01-02', '2022-12-31']:
        r=c.get('/v1/sites/S01/energy/anomalies',params={'as_of':day,'days':14})
        r.raise_for_status()
        data=r.json()
        assert data['n_anomaly_days'] is None and data['n_evaluable_days'] == 0
        results['energy_' + day]=data
    (out/'api-checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print('actual local API regressions passed')
