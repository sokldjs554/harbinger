"""PyTorch 위험 네트와 Keras 구현이 같은 명세를 따르는지 — 별도 프로세스에서 돌린다. TensorFlow 가 없으면 건너뛴다."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harbinger.models.keras_parity import tf_available

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "keras_parity_check.py"


@pytest.mark.skipif(not tf_available(), reason="tensorflow 미설치 (선택 의존성)")
def test_torch_and_keras_reach_similar_quality(tiny):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--features", str(tiny["data"] / "features.parquet"), "--epochs", "12"],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["nll_gap"] < 0.25, out
    assert out["auroc_gap"] < 0.12, out
