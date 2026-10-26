"""The evaluated service sees the same historical inspections as online selection."""

import pandas as pd


def test_pipeline_evaluates_full_history_with_explicit_mature_dates(tiny, tmp_path, monkeypatch):
    import harbinger.eval.run as evaluation

    original = evaluation.simulate_patrol
    seen = {}

    def capture(features, *args, **kwargs):
        seen["earliest_history"] = features.t.min()
        seen["kwargs"] = kwargs
        return original(features, *args, **kwargs)

    monkeypatch.setattr(evaluation, "simulate_patrol", capture)
    result = evaluation.run(
        tiny["data"], tmp_path / "models", tmp_path / "artifacts", seed=1, quick=True, skip_loso=True
    )
    cutoff = pd.Timestamp(result["split"]["val"]["to"])
    assert seen["earliest_history"] < cutoff
    assert seen["kwargs"]["start"] == cutoff + pd.Timedelta(days=30)
    assert seen["kwargs"]["end"] == pd.Timestamp(result["observation"]["observation_end"]) - pd.Timedelta(
        days=30
    )
    assert set(seen["kwargs"]["assets"].asset_id) == set(tiny["tables"]["assets"].asset_id)
    assert "selection_hit_rate" in result["patrol"]["service_policy"]["methods"]["harbinger_hgb"]
