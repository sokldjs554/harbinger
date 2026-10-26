import json
import numpy as np
import pandas as pd
from harbinger.features.energy import energy_residuals, _design
from harbinger.models.energy import train_energy

# Nonnegative observations with a heating relationship that extrapolates below zero in summer.
n=100
energy=pd.DataFrame(dict(site_id='S',day=pd.date_range('2024-01-01',periods=n),
 temp_mean_c=np.r_[np.linspace(1,8,60),np.full(n-60,18.)],occupancy_index=1.))
energy['electricity_kwh']=np.r_[10*(18-np.linspace(1,8,60))-50,np.full(n-60,30.)]
energy['gas_m3']=energy.electricity_kwh
r=energy_residuals(energy,pd.Timestamp('2024-03-01'))
x=_design(energy)
fit=energy.day<'2024-03-01'
coef=np.linalg.lstsq(x[fit],energy.electricity_kwh[fit],rcond=None)[0]
print(json.dumps({'ols':{'actual_min':float(energy.electricity_kwh.min()),'unsupported_forecast':float(x[-1]@coef),'ratio':float(r.en_resid_ratio.iloc[-1])}},indent=2))
# Actual HGB fit on spaced daily readings. Seven observations cover 43 calendar days.
n=40
weekly=pd.DataFrame(dict(site_id='S',day=pd.date_range('2024-01-01',periods=n,freq='7D'),
 temp_mean_c=20.,occupancy_index=1.,electricity_kwh=100+10*np.sin(np.arange(n))))
b=train_energy(weekly,seed=1)
rr=pd.Series((weekly.electricity_kwh.to_numpy()-b.predict(weekly))/b.predict(weekly),index=weekly.day)
print(json.dumps({'sparse_energy_sigma':{'stored_sigma':b.resid_sigma['S'],
'calendar_7d_evaluable_training_windows':int(rr.rolling('7D',min_periods=3).mean().notna().sum()),
'inference_evaluable_days':int(b.anomalies(weekly).z.notna().sum())}},indent=2))
