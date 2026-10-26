"""Read-only audit: real loaded bundle, temporary in-process application only."""
import asyncio, json
import httpx
import pandas as pd
from fastapi import FastAPI
from harbinger.api.store import Store
from harbinger.api.deps import get_store
from harbinger.api.routers import report, sites, risk, replay, workbench
from harbinger.config import Settings

s = Store(Settings(demo_bootstrap=False)); s.load()
app = FastAPI()
for router in [report.router, sites.router, risk.router, replay.router, workbench.router]: app.include_router(router)
app.dependency_overrides[get_store] = lambda: s
sid = s.tables['sites'].site_id.iloc[0]
aid = s.tables['assets'].query('site_id == @sid').asset_id.iloc[0]
async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),base_url='http://audit') as c:
        for path in [f'/v1/sites/{sid}/report?as_of=2000-01-01&format=json',f'/v1/sites/{sid}/report?as_of=2000-01-01&format=md', '/v1/sites?as_of=2025-01-01T00:00:00Z','/v1/replay?site='+sid+'&from=NaT']:
            r=await c.get(path); print(json.dumps({'path':path,'status':r.status_code,'body':r.text[:180]},ensure_ascii=False),flush=True)
        presets=(await c.get(f'/v1/sites/{sid}/assets/{aid}/whatif/presets')).json()['scenarios']
        key = next(iter(presets[0]['items']))
        for value in [-1,128]:
            r=await c.post(f'/v1/sites/{sid}/assets/{aid}/whatif',json={'scenarios':[{'items':{key:value}}]})
            print(json.dumps({'whatif_item':key,'value':value,'status':r.status_code,'scenario':r.json()['scenarios'][0] if r.status_code==200 else r.text},ensure_ascii=False),flush=True)
        header='record_id,record_type,site_id,asset_id,category,archetype,installed,criticality,floor,zone,occurred_at,inspector_id,overall,memo,dwell_seconds,scheduled_at,method,photo_count\n'
        row='i1,inspection,client-a,pump-1,pump,office,2020-01-01,2,1,A,2025-08-01,person-1,1,noise,60,2025-08-01,nfc,0\n'
        r=await c.post('/v1/workbench/upload?observation_end=2025-08-02',content=(header+row).encode(),headers={'content-type':'text/csv'})
        p=r.json(); print(json.dumps({'upload_status':r.status_code,'default_as_of':p.get('default_as_of'),'uploaded_inspection_date':'2025-08-01'}),flush=True)
        r=await c.get('/v1/workbench/sessions/'+p['session_id']+'/analysis',params={'as_of':p['default_as_of']}); print(json.dumps({'default_analysis_status':r.status_code,'assets':len(r.json()['assets']),'reasons':r.json()['evaluation_reasons']},ensure_ascii=False),flush=True)
        r=await c.get('/v1/workbench/sessions/'+p['session_id']+'/analysis',params={'as_of':'2025-08-02'}); print(json.dumps({'latest_analysis_status':r.status_code,'assets':len(r.json()['assets'])}),flush=True)
asyncio.run(main())
