"""Reproductions from the requirements audit; no historical artifacts are rewritten."""

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from harbinger.eval import run as evaluation
from harbinger.eval.metrics import censoring_km
from harbinger.models.deep import HazardNet, train_deep
from harbinger.synth.generate import GenConfig, generate


def test_site_dropout_resamples_once_per_epoch_without_permanent_mask(monkeypatch):
    n, seed, rate = 128, 42, 0.3
    frame = pd.DataFrame(
        dict(
            st_category="pump",
            st_archetype="office",
            site_id="S",
            memo="",
            feature=np.arange(n, dtype=float),
            tte_days=60.0,
            event=0,
        )
    )
    seen = []
    original = HazardNet.forward

    def record(self, num, cat, arch, site, chars):
        if self.training:
            # Recover each row identity despite minibatch shuffling.
            seen.append(dict(zip(num[:, 0].tolist(), site.tolist())))
        return original(self, num, cat, arch, site, chars)

    monkeypatch.setattr(HazardNet, "forward", record)
    bundle = train_deep(
        frame,
        frame.iloc[:0],
        ["feature"],
        use_text=False,
        epochs=2,
        batch=n,
        site_dropout=rate,
        seed=seed,
        verbose=False,
    )
    identities = bundle.tensors(frame)[0][:, 0].tolist()
    rng = np.random.default_rng(seed)
    assert len(seen) == 2
    for epoch in seen:
        expected = np.where(rng.random(n) < rate, 0, 1)
        np.testing.assert_array_equal([epoch[key] for key in identities], expected)


@pytest.mark.parametrize(
    "start,months,last",
    [
        (date(2024, 11, 1), 3, "2025-01-31"),
        (date(2024, 1, 31), 1, "2024-02-28"),
    ],
)
def test_synthetic_calendar_uses_elapsed_calendar_months(start, months, last):
    tables = generate(GenConfig(start=start, months=months, scale=0.01), verbose=False)
    days = tables["energy"].day
    assert days.min() == pd.Timestamp(start)
    assert days.max() == pd.Timestamp(last)
    assert days.nunique() == (pd.Timestamp(last) - pd.Timestamp(start)).days + 1


@pytest.mark.parametrize("months", [0, -1, 1.5, True])
def test_synthetic_month_count_rejects_invalid_duration(months):
    with pytest.raises(ValueError, match="months must be a positive integer"):
        generate(GenConfig(months=months), verbose=False)


def test_constant_hazard_survival_comparison_includes_immature_censored_rows():
    # The first two mature rows alone have C-index 1; the full cohort has 1/3.
    frame = pd.DataFrame(
        dict(
            tte_days=[10.0, 20.0, 5.0],
            event=[1, 0, 1],
            label_valid=[True, True, False],
            probability=[0.8, 0.2, 0.1],
        )
    )
    model = SimpleNamespace(predict_proba=lambda rows: rows.probability.to_numpy())
    km = censoring_km(np.array([100.0, 200.0]), np.array([1, 0]))
    score = getattr(evaluation, "constant_hazard_metrics", None)
    assert callable(score), "Provide one common all-row cohort for HGB survival metrics"
    result = score(model, frame, [2.0, 4.0], km)
    assert result["c_index"] == pytest.approx(1 / 3)
    assert result["rows"] == 3
    assert result["cohort"] == "all_test_rows_including_censored"
    assert set(result["brier_at"]) == {"2", "4"}


@pytest.mark.parametrize("check", ["horizon", "encoder"])
def test_survival_figure_labels_actual_horizons_and_removed_encoder(tmp_path, monkeypatch, check):
    spec = importlib.util.spec_from_file_location("audit_figures", Path("scripts/make_figures.py"))
    figures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(figures)
    artifact = dict(
        lifelines={"cox": dict(c_index=0.7, ibs=0.1, brier_at={"30": 0.1, "180": 0.1})},
        deep={"notext+site": dict(c_index=0.65, ibs=0.12, brier_at={"30": 0.1, "180": 0.14})},
    )
    (tmp_path / "survival.json").write_text(json.dumps(artifact))
    monkeypatch.setattr(figures.plt, "close", lambda *_: None)
    figures.fig_survival(tmp_path, tmp_path)
    figure = figures.plt.gcf()
    if check == "horizon":
        assert "30~180" in figure.axes[1].get_title(loc="left")
        assert "360" not in figure.axes[1].get_title(loc="left")
    else:
        labels = " ".join(t.get_text() for t in figure.axes[0].get_yticklabels())
        assert "CNN" in labels and "메모 없음" not in labels
    assert (tmp_path / "survival.png").is_file()


def test_energy_residuals_withhold_nonpositive_extrapolated_expectation():
    from harbinger.features.energy import energy_residuals

    n = 100
    temperature = np.r_[np.linspace(1, 8, 60), np.full(n - 60, 18.0)]
    actual = np.r_[10 * (18 - temperature[:60]) - 50, np.full(n - 60, 30.0)]
    energy = pd.DataFrame(
        dict(
            site_id="S",
            day=pd.date_range("2024-01-01", periods=n),
            temp_mean_c=temperature,
            occupancy_index=1.0,
            electricity_kwh=actual,
            gas_m3=actual,
        )
    )
    residual = energy_residuals(energy, pd.Timestamp("2024-03-01"))
    # All observations are positive, but the winter linear relationship predicts
    # -50 at the later temperature. This is unavailable evidence, not a huge anomaly.
    assert (actual > 0).all()
    assert residual.loc[energy.day >= "2024-03-01", "en_resid_ratio"].isna().all()
    assert residual.loc[energy.day >= "2024-03-01", "en_gas_resid_ratio"].isna().all()


def test_energy_sigma_uses_calendar_window_and_withholds_sparse_sites():
    from harbinger.models.energy import train_energy

    n = 40
    frames = []
    for site, frequency in [("daily", "D"), ("weekly", "7D")]:
        frames.append(
            pd.DataFrame(
                dict(
                    site_id=site,
                    day=pd.date_range("2024-01-01", periods=n, freq=frequency),
                    temp_mean_c=20.0,
                    occupancy_index=1.0,
                    electricity_kwh=100 + 10 * np.sin(np.arange(n)),
                )
            )
        )
    energy = pd.concat(frames, ignore_index=True)
    bundle = train_energy(energy, seed=1)
    daily = energy[energy.site_id == "daily"]
    ratios = bundle.residual_ratio(daily)
    ratios.index = daily.day
    expected = ratios.rolling("7D", min_periods=3).mean().std()
    assert bundle.resid_sigma["daily"] == pytest.approx(expected)
    assert "weekly" not in bundle.resid_sigma
    # A new dense week must not acquire false calibration from sparse training.
    incoming = daily.assign(site_id="weekly")
    assert bundle.anomalies(incoming).status.eq("no_model").all()
