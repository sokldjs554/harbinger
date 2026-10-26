"""PyTorch 위험 네트와 Keras 구현이 같은 명세를 따르는지 — 별도 프로세스에서 돌린다. TensorFlow 가 없으면 건너뛴다."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from harbinger.models.keras_parity import tf_available


@pytest.mark.parametrize(
    "day,event,expected",
    [
        (0, 1, [1, 0, 0, 0]),
        (30, 1, [1, 0, 0, 0]),
        (30.1, 1, [0, 1, 1, 0]),
        (60, 1, [0, 1, 1, 0]),
        (60.1, 1, [0, 0, 1, 1]),
        (29.9, 0, [0, 0, 0, 0]),
        (30, 0, [0, 0, 1, 0]),
        (60, 0, [0, 0, 1, 1]),
    ],
)
def test_keras_target_bins_include_events_at_right_edge(day, event, expected):
    from harbinger.models.keras_parity import _targets

    actual = _targets(np.array([day]), np.array([event]), n_bins=2, bin_days=30)
    np.testing.assert_array_equal(actual[0], expected)


@pytest.mark.skipif(not tf_available(), reason="TensorFlow optional dependency absent")
def test_keras_training_handles_all_missing_feature():
    code = """
import json
import numpy as np
import pandas as pd
from harbinger.models.keras_parity import train_keras_hazard
train=pd.DataFrame({'st_age_years': [1.,2.,3.,4.]*8, 'en_missing': [np.nan]*32,
 'st_category': ['pump']*32, 'st_archetype': ['office']*32,
 'tte_days': [30.,60.,90.,120.]*8, 'event': [1,0,1,0]*8})
r=train_keras_hazard(train,train.iloc[:8],['st_age_years','en_missing'],epochs=3)
assert np.isfinite(r['val_nll']), r
assert np.isfinite(r['p30_val']).all(), r
np.testing.assert_allclose(r['learning_rates'],[0.002,0.0015,0.0005],rtol=1e-6)
print(json.dumps({'nll':r['val_nll']}))
"""
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]


@pytest.mark.skipif(not tf_available(), reason="TensorFlow optional dependency absent")
def test_tensorflow_loss_matches_hand_calculation_and_torch_gradient():
    code = """
import numpy as np
import torch
from harbinger.models.deep import discrete_nll
from harbinger.models.keras_parity import _targets, discrete_hazard_nll
import tensorflow as tf
days=np.array([30.,60.,30.,60.])
event=np.array([1,1,0,0])
targets=_targets(days,event,n_bins=2)
# h=.5: event30 ->1 term, event60 ->2, censor30 ->1, censor60 ->2.
tv=torch.zeros((4,2),requires_grad=True)
pt=discrete_nll(tv,torch.tensor(days),torch.tensor(event));pt.backward()
kv=tf.Variable(np.zeros((4,2),dtype=np.float32))
with tf.GradientTape() as tape:
 loss=discrete_hazard_nll(tf.constant(targets),kv)
grad=tape.gradient(loss,kv).numpy()
np.testing.assert_allclose(float(loss),1.5*np.log(2),rtol=1e-6)
np.testing.assert_allclose(float(loss),float(pt.detach()),rtol=1e-6)
np.testing.assert_allclose(grad,tv.grad.numpy(),atol=1e-7)
"""
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]


@pytest.mark.skipif(not tf_available(), reason="TensorFlow optional dependency absent")
def test_shared_weights_match_network_logits_and_parameter_gradients():
    code = """
import numpy as np
import torch
from harbinger.models.deep import HazardNet, discrete_nll
from harbinger.models.keras_parity import build_keras_hazard, _targets, discrete_hazard_nll
import tensorflow as tf
torch.manual_seed(19)
pt=HazardNet(2,1,2,use_text=False,use_site=False);pt.eval()
weights={'category':pt.cat_emb.weight.detach().numpy(), 'archetype':pt.arch_emb.weight.detach().numpy()}
for name, layer in [('hidden1',pt.trunk[0]),('hidden2',pt.trunk[3]),('hazard',pt.trunk[6])]:
 weights[name]=[layer.weight.detach().numpy().T,layer.bias.detach().numpy()]
tfm=build_keras_hazard(2,initial_weights=weights)
num=np.array([[.1,1.],[-2.,.3],[.5,-.7],[2.,3.]],dtype=np.float32)
cat=np.array([0,1,2,0]);arch=np.array([0,1,2,3])
day=np.array([30.,60.,5.,120.],dtype=np.float32);event=np.array([1,1,0,0])
tl=pt(torch.tensor(num),torch.tensor(cat),torch.tensor(arch),torch.zeros(4,dtype=torch.long),torch.zeros((4,64),dtype=torch.long))
loss=discrete_nll(tl,torch.tensor(day),torch.tensor(event));loss.backward()
with tf.GradientTape() as tape:
 kl=tfm([num,cat,arch],training=False)
 kloss=discrete_hazard_nll(tf.constant(_targets(day,event)),kl)
kg=tape.gradient(kloss,tfm.get_layer('hazard').kernel)
np.testing.assert_allclose(kl.numpy(),tl.detach().numpy(),rtol=2e-5,atol=2e-6)
np.testing.assert_allclose(float(kloss),float(loss.detach()),rtol=2e-6)
np.testing.assert_allclose(kg.numpy(),pt.trunk[6].weight.grad.numpy().T,rtol=2e-5,atol=2e-6)
"""
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "keras_parity_check.py"


@pytest.mark.skipif(not tf_available(), reason="tensorflow 미설치 (선택 의존성)")
def test_shared_initialization_training_meets_original_gap_limits(tiny):
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--features",
            str(tiny["data"] / "features.parquet"),
            "--epochs",
            "12",
            "--shared-initialization",
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["initialization"] == "shared_pretraining_weights"
    assert out["torch"]["active_params"] == out["keras"]["n_params"]
    assert out["evaluation_role"] == "validation_reused_for_early_stopping"
    assert out["independent_test"] is False
    assert len(out["feature_sha256"]) == 64
    assert out["versions"]["tensorflow"]
    assert out["versions"]["torch"]
    assert out["seed"] == 0
    assert out["nll_gap"] < 0.25, out
    assert out["auroc_gap"] < 0.12, out
