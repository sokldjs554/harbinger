import json
from pathlib import Path
import joblib
import pandas as pd
from harbinger.models.common import split_by_time,labeled
from harbinger.eval.metrics import c_index_from_risk
root=Path('/workspace/harbinger')
X=pd.read_parquet(root/'data/features.parquet')
split=split_by_time(X)
model=joblib.load(root/'models/v20261021-103259/classifier.joblib')
p=model.predict_proba(split.test)
m=split.test.label_valid.to_numpy()
old=json.loads((root/'artifacts/survival.json').read_text())
print(json.dumps({'bundle':'v20261021-103259','features':'existing historical cache; no rebuild',
 'test_rows':len(split.test),'mature_test_rows':int(m.sum()),
 'stored_hgb_survival_c_index':old['lifelines']['hgb_constant_hazard']['c_index'],
 'recomputed_mature_only_c_index':c_index_from_risk(split.test.tte_days.to_numpy()[m],split.test.event.to_numpy()[m],p[m]),
 'recomputed_all_test_c_index':c_index_from_risk(split.test.tte_days.to_numpy(),split.test.event.to_numpy(),p)},indent=2))
