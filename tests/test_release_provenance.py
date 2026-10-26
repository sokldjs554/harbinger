"""Published source hashes must not silently assert historical model provenance."""

import json

import pytest


def test_unrecorded_training_does_not_invent_a_commit(tmp_path):
    from scripts.release_manifest import training_context

    result = training_context({"bundle_version": "old-model"}, tmp_path / "missing.json")
    assert result["base_commit"] is None
    assert result["training_provenance"] is None


def test_training_record_must_match_the_published_model(tmp_path):
    from scripts.release_manifest import training_context

    path = tmp_path / "training.json"
    path.write_text(json.dumps({"model_version": "new", "base_commit": "abc"}))
    with pytest.raises(ValueError, match="model"):
        training_context({"bundle_version": "old"}, path)
    result = training_context({"bundle_version": "new"}, path)
    assert result["base_commit"] == "abc"
    assert result["training_provenance"]["model_version"] == "new"


def test_published_patrol_archive_hash_is_verified(tmp_path):
    import hashlib

    from scripts.release_manifest import verify_observations

    raw = tmp_path / "patrol-observations.json.gz"
    raw.write_bytes(b"original evidence")
    (tmp_path / "patrol.json").write_text(
        json.dumps(
            {
                "observations": {
                    "file": raw.name,
                    "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                }
            }
        )
    )
    verify_observations(tmp_path)
    raw.write_bytes(b"changed")
    with pytest.raises(AssertionError, match="observations"):
        verify_observations(tmp_path)
