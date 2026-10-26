"""Keep full selection evidence without sending it in every model-summary response."""

import gzip
import hashlib
import json


def test_publish_patrol_summary_preserves_full_hashed_observations(tmp_path):
    from harbinger.eval.run import save_patrol_evaluation

    full = {
        "methods": {"model": {"precision_at_k": 0.2}},
        "rows": [{"selected_ids": ["a"]}],
        "snapshots": [{"candidate_ids": ["a", "b"]}],
        "service_policy": {
            "methods": {"model": {"selection_hit_rate": 0.1}},
            "rows": [{"selected_ids": ["b"]}],
        },
    }
    before = json.dumps(full)
    summary = save_patrol_evaluation(full, tmp_path)
    assert "rows" not in summary and "snapshots" not in summary
    assert "rows" not in summary["service_policy"]
    assert summary["methods"] == full["methods"]
    path = tmp_path / summary["observations"]["file"]
    assert summary["observations"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with gzip.open(path, "rt") as stream:
        assert json.load(stream) == full
    assert json.dumps(full) == before
