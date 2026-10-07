import numpy as np
import pandas as pd
import torch

from harbinger.config import SURVIVAL_BINS
from harbinger.models.calibration import PlattCalibrator, choose_calibrator, ece, fit_isotonic
from harbinger.models.coldstart import apply_offset, site_offset
from harbinger.models.common import model_columns, split_by_time, to_matrix
from harbinger.models.deep import discrete_nll
from harbinger.monitoring.drift import psi
from harbinger.prescribe.schedule import interval_from_p30, interval_from_survival, recommend_interval


def test_discrete_nll_matches_closed_form():
    logits = torch.zeros(3, SURVIVAL_BINS)  # h = 0.5 모든 구간
    tte = torch.tensor([10.0, 45.0, 400.0])
    event = torch.tensor([1, 0, 0])
    nll = discrete_nll(logits, tte, event)
    # 행1: 구간0 사건 → -log 0.5 ; 행2: 구간1 중도절단 → 구간0 생존 -log 0.5 ; 행3: 전 구간 생존 → 12·(-log 0.5)
    expected = (np.log(2) + np.log(2) + SURVIVAL_BINS * np.log(2)) / 3
    assert abs(float(nll) - expected) < 1e-5


def test_schedule_monotone_and_legal_cap():
    assert interval_from_p30(0.01) > interval_from_p30(0.10) > interval_from_p30(0.30)
    surv_low = np.cumprod([0.99] * SURVIVAL_BINS)
    surv_high = np.cumprod([0.8] * SURVIVAL_BINS)
    assert interval_from_survival(surv_low) > interval_from_survival(surv_high)
    r = recommend_interval("elevator", 0.001)
    assert r["recommended_interval_days"] <= 31 and r["legal_max_days"] == 31
    r2 = recommend_interval("pump", 0.4)
    assert r2["urgent"] and r2["recommended_interval_days"] == 7


def test_coldstart_offset_shrinks_to_zero():
    p = np.full(200, 0.05)
    assert site_offset(p, np.zeros(0)) == 0.0
    y_few = np.array([1, 0, 0, 0, 0])
    y_many = np.array([1] * 60 + [0] * 140)
    d_few, d_many = site_offset(p[:5], y_few), site_offset(p, y_many)
    assert 0 <= d_few < d_many  # 관측이 많을수록 더 크게 보정
    assert np.all(apply_offset(p, d_many) > p)


def test_calibration_helpers():
    rng = np.random.default_rng(0)
    p = rng.random(2000)
    y = (rng.random(2000) < p).astype(int)
    assert ece(p, y) < 0.05
    iso = fit_isotonic(p, y)
    assert np.all(np.diff(iso.predict(np.linspace(0, 1, 50))) >= -1e-12)


def test_psi():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 5000)
    assert psi(a, rng.normal(0, 1, 5000)) < 0.05
    assert psi(a, rng.normal(1.0, 1, 5000)) > 0.25


def test_classifier_beats_baselines_on_tiny(trained):
    r = trained["results"]
    hgb = r["classifier"]["hgb_full"]
    assert hgb["auroc"] > 0.55
    assert hgb["auroc"] > r["baselines"]["constant_prior"]["auroc"]
    assert r["baselines"]["oracle_latent_state"]["auroc"] >= hgb["auroc"] - 0.05, (
        "오라클이 모델보다 못하면 생성 모델/라벨에 문제가 있다"
    )
    assert "harbinger_hgb" in r["patrol"]["methods"]
    assert (trained["models"] / "manifest.json").exists()


def test_matrix_and_split(tiny):
    X = tiny["X"]
    cols = model_columns(X)
    M = to_matrix(X.head(50), cols)
    assert M.shape == (50, len(cols)) and M.dtypes.map(lambda d: d.kind == "f").all()
    assert M.filter(like="st_category__").sum(axis=1).eq(1).all()
    sp = split_by_time(X, 5, 2)
    assert sp.train["t"].max() < sp.val["t"].min() <= sp.val["t"].max() < sp.test["t"].min()
    assert len(sp.train) + len(sp.val) + len(sp.test) == len(X)


def test_registry_roundtrip(trained):
    from harbinger.models.registry import list_versions, load_bundle

    b = load_bundle(trained["models"])
    X = trained["X"].head(20)
    p = b["classifier"].predict_proba(X)
    assert p.shape == (20,) and np.all((p > 0) & (p < 1))
    if b["deep"] is not None:
        S = b["deep"].survival_curve(X)
        assert S.shape == (20, SURVIVAL_BINS) and np.all(np.diff(S, axis=1) <= 1e-9)
    assert list_versions(trained["models"])[0]["version"] == b["version"]
    assert isinstance(pd.Timestamp(b["entry"]["created_at"]), pd.Timestamp)


def test_calibrator_selection_keeps_good_probabilities_and_fixes_bad_ones():
    rng = np.random.default_rng(0)
    p = rng.beta(1, 12, 20000)
    y = (rng.random(20000) < p).astype(int)
    cal, info = choose_calibrator(p, y)
    assert info["method"] == "raw" and cal is None and not info["adopted"], (
        "이미 맞는 확률에는 보정을 씌우지 않는다"
    )
    over = np.clip(p * 1.6, 0, 1)
    cal2, info2 = choose_calibrator(over, y)
    assert info2["method"] == "platt" and isinstance(cal2, PlattCalibrator)
    fixed = cal2.predict(over)
    assert abs(fixed.mean() - y.mean()) < abs(over.mean() - y.mean()), (
        "과신된 확률은 보정 뒤 평균이 실제에 가까워져야 한다"
    )
    assert len(np.unique(np.round(fixed, 6))) > 1000, "Platt 은 계단(동점 구간)을 만들지 않는다"
