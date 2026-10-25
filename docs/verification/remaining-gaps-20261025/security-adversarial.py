import json,tempfile,os,time,logging
from pathlib import Path
from fastapi.testclient import TestClient
os.environ.update(HARBINGER_DATA_DIR='/tmp/hb-gap-runtime/data',HARBINGER_MODEL_DIR='/tmp/hb-gap-runtime/models',HARBINGER_ARTIFACT_DIR='/tmp/hb-gap-runtime/artifacts',HARBINGER_DEMO_BOOTSTRAP='0')
from harbinger.api import main
from harbinger.api.auth import AuthManager,password_hash,COOKIE
from harbinger.config import Settings
from harbinger.api.routers import workbench
logging.disable(logging.CRITICAL)
checks=[]
def ck(name,result):
 assert result,name
 checks.append(name)
with tempfile.TemporaryDirectory() as td,TestClient(main.app):
 store=main.app.state.store
 sites=list(store.tables['sites'].site_id)[:2]
 assets=[store.tables['assets'].query('site_id == @s').asset_id.iloc[0] for s in sites]
 p=Path(td)/'users.json'; pw='review-only-test-password'; origin='http://testserver'
 p.write_text(json.dumps([dict(username=n,role=r,sites=ss,password_hash=password_hash(pw)) for n,r,ss in [('alice','operator',sites[:1]),('bob','operator',sites[1:]),('reader','viewer',sites[:1]),('admin','admin',[])]]));p.chmod(0o600)
 cfg=Settings(protected_mode=True,auth_users_file=p,auth_origin=origin,auth_cookie_secure=False,auth_metrics_token='x'*48)
 main.app.state.auth_settings=cfg;main.app.state.auth=AuthManager(cfg)
 def login(n):
  c=TestClient(main.app);r=c.post('/auth/login',headers={'Origin':origin},json={'username':n,'password':pw});ck('login '+n,r.status_code==200);c.headers.update({'Origin':origin,'X-CSRF-Token':r.json()['csrf_token']});return c
 alice,bob,reader,admin=[login(n) for n in ['alice','bob','reader','admin']]
 anon=TestClient(main.app)
 def flatten(routes):
  for route in routes:
   if hasattr(route,'original_router'):yield from flatten(route.original_router.routes)
   elif getattr(route,'methods',None):yield route
 routes=list(flatten(main.app.routes))
 for route in routes:
  path=route.path.replace('{site_id}',sites[1]).replace('{asset_id}',assets[1]).replace('{name}','metrics').replace('{token}','stolen')
  if path in ['/health','/','/console','/auth/login']:continue
  for method in route.methods:ck('anonymous '+method+' '+path,anon.request(method,path).status_code==401)
 for path in ['/v1/models','/v1/artifacts/metrics','/metrics','/version','/ready','/docs','/docs/oauth2-redirect','/redoc','/openapi.json','/v1/monitoring/drift']:
  for variation in [path,path+'/',path.replace('/','/%2f',1),path.replace('/v1/','/v1/%2e/'),path.replace('metrics','%6detri%63s')]:
   r=alice.get(variation);ck('admin path '+variation,r.status_code in [403,404])
 for route in routes:
  if '{site_id}' not in route.path:continue
  path=route.path.replace('{site_id}',sites[1]).replace('{asset_id}',assets[1])
  for method in route.methods:
   r=alice.request(method,path,json={'scenarios':[{'memo':'x'}]} if method=='POST' else None)
   ck('tenant denial '+method+' '+path,r.status_code in [403,404])
 for payload in [b'{"username":"alice","password":"top-secret",',b'[]',b'null',b'{}',b'{"username":[],"password":"secret"}',b'x'*4097,b'username=alice&password=top-secret']:
  r=anon.post('/auth/login',headers={'Origin':origin,'Content-Type':'application/x-www-form-urlencoded'},content=payload)
  ck('invalid credential input '+str(len(payload)),r.status_code in [422,413] and 'secret' not in r.text)
 for value in ['',origin+'/',origin+'.evil','null','https://evil.test']:
  r=alice.post('/v1/workbench/example',headers={'Origin':value});ck('origin rejected '+value,r.status_code==403)
 ck('viewer upload reject',reader.post('/v1/workbench/upload?observation_end=2024-10-01',content=b'x',headers={'Content-Type':'text/csv'}).status_code==403)
 state=alice.post('/v1/workbench/example').json(); sid=state['session_id'];prefix='/v1/workbench/sessions/'+sid;query='?as_of='+state['default_as_of']
 for c in [bob,reader,admin]:
  for path in [prefix+'/analysis'+query,prefix+'/download'+query,prefix+'/assets/'+assets[0]+query]:ck('stolen session '+path,c.get(path).status_code==404)
  ck('stolen delete',c.delete(prefix).status_code==404)
 ck('own session analysis',alice.get(prefix+'/analysis'+query).status_code==200)
 old=alice.cookies.get(COOKIE)
 r=alice.post('/auth/login',json={'username':'alice','password':pw});ck('relogin',r.status_code==200);ck('relogin invalidates owned analysis',sid not in workbench.sessions)
 stolen=TestClient(main.app);stolen.cookies.set(COOKIE,old);ck('old login token',stolen.get('/auth/me').status_code==401)
 alice.headers['X-CSRF-Token']=r.json()['csrf_token']
 sid=alice.post('/v1/workbench/example').json()['session_id'];alice.post('/auth/logout');ck('logout removes analysis',sid not in workbench.sessions);ck('logout auth denial',alice.get('/v1/sites').status_code==401)
 token=bob.cookies.get(COOKIE);sid=bob.post('/v1/workbench/example').json()['session_id'];main.app.state.auth.sessions[token].expires=time.monotonic()-1;ck('expiry denial',bob.get('/v1/sites').status_code==401);ck('expiry cleanup',sid not in workbench.sessions)
 metrics=TestClient(main.app,headers={'Authorization':'Bearer '+'x'*48});ck('metrics bearer',metrics.get('/metrics').status_code==200)
 for path in ['/auth/me','/v1/models','/v1/sites','/version','/ready']:ck('narrow metrics '+path,metrics.get(path).status_code==401)
 params={'site':'all','from':'2024-06-01','to':'2024-06-08'}
 global_replay=admin.get('/v1/replay',params=params); local_replay=reader.get('/v1/replay',params=params)
 ck('warm global replay status',global_replay.status_code==200)
 ck('scoped replay excludes other sites',local_replay.status_code==200 and local_replay.json()['n_sites']==1 and global_replay.json()['n_sites']>1)
 ck('global headline stripped',reader.get('/v1/sites/'+sites[0]+'/report').json()['model']['headline'] is None)
 ck('shared state intact',len(store.tables['sites'])==4 and bool(store._replay_cache))
 manager=main.app.state.auth
 manager.attempts.clear()
 for i in range(10):
  r=anon.post('/auth/login',headers={'Origin':origin},json={'username':'unknown','password':pw})
  ck('wrong login '+str(i),r.status_code==401)
 ck('attempt 11 throttled',anon.post('/auth/login',headers={'Origin':origin},json={'username':'unknown','password':pw}).status_code==429)
 manager.attempts={'user:slot'+str(i):[time.monotonic()] for i in range(2048)}
 ck('rate tracker bounded',anon.post('/auth/login',headers={'Origin':origin},json={'username':'unknown-new','password':pw}).status_code==429 and len(manager.attempts)==2048)
 manager.attempts.clear();cfg.auth_max_sessions=len(manager.sessions)
 ck('sessions bounded',anon.post('/auth/login',headers={'Origin':origin},json={'username':'alice','password':pw}).status_code==429)
 from harbinger import auth_users
 import sys,unittest.mock as mock,stat
 provisioned=Path(td)/'provisioned.json'
 with mock.patch.object(sys,'argv',['auth_users',str(provisioned),'test','--role','viewer','--site',sites[0]]),mock.patch.object(auth_users.getpass,'getpass',return_value=pw):auth_users.main()
 ck('offline provision permissions',stat.S_IMODE(provisioned.stat().st_mode)==0o600)
 ck('offline provision hashes only',pw not in provisioned.read_text() and 'scrypt$16384$8$1$' in provisioned.read_text())
 p.chmod(0o644)
 try:AuthManager(cfg)
 except RuntimeError:ck('world readable config refused',True)
 else:ck('world readable config refused',False)
 print('PASSED',len(checks),'adversarial checks')
 print('sites',sites,'routes',len(routes),'shared sites',len(store.tables['sites']))
