from datetime import date
from unittest.mock import patch
import json
import numpy as np
import pandas as pd
import torch
from harbinger.synth.generate import GenConfig, generate
from harbinger.models.deep import train_deep, HazardNet
from harbinger.eval.metrics import censoring_km, ipcw_brier
from harbinger.prescribe.schedule import recommend_interval

results={}
for d,m in [(date(2024,11,1),3),(date(2024,1,31),1)]:
    try:
        generate(GenConfig(start=d, months=m, scale=.01),verbose=False)
        results[f'calendar_{d}_{m}']='unexpected success'
    except Exception as exc:
        results[f'calendar_{d}_{m}']={'type':type(exc).__name__,'error':str(exc)}
# Record actual sites received by the first training forward call; no tensor approximation.
n=1024
frame=pd.DataFrame({'st_category':['pump']*n,'st_archetype':['office']*n,
    'site_id':['S']*n,'memo':['']*n,'feature':np.linspace(-1,1,n),
    'tte_days':np.full(n,60.),'event':np.zeros(n,dtype=int)})
seen=[]
original=HazardNet.forward
def record(self,num,cat,arch,site,chars):
    if self.training: seen.append(site.detach().clone().numpy())
    return original(self,num,cat,arch,site,chars)
with patch.object(HazardNet,'forward',record):
    train_deep(frame,frame.iloc[:0],['feature'],use_text=False,site_dropout=.3,
               epochs=1,batch=n,seed=42,verbose=False)
rng=np.random.default_rng(42)
initial=rng.random(n)<.3
nextdraw=rng.random(n)<.3
results['double_site_dropout']={'configured':.3,'training_zero_sites':int((seen[0]==0).sum()),
 'n':n,'initial_only_count':int(initial.sum()),'epoch_only_count':int(nextdraw.sum()),
 'union_count':int((initial|nextdraw).sum()),'theoretical_effective_probability':1-(1-.3)**2}
# One censoring and one observed event at the same time. G(1-) = 1, G(1)=2/3.
km=censoring_km(np.array([1.,1.,2.,3.]),np.array([0,1,1,1]))
results['ipcw_tied_event_censor']={'actual':ipcw_brier(np.array([.5]),np.array([1.]),np.array([1]),1.,km),
 'event_left_limit_expected':.25,'G_at_1':float(km.predict(1.)),'G_before_1':float(km.predict(.999))}
r=recommend_interval('pump',.4)
results['interval_clipped_budget']={**r,'failure_probability_at_recommended_interval':1-(1-.4)**(r['recommended_interval_days']/30)}
print(json.dumps(results,indent=2))
