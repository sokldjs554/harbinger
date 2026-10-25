"""Reject unsupported improvement claims, edited timings and mismatched retests."""

import copy

import pytest
from scripts.retest_records import compare, validate


def record(phase="before", kind="human"):
    return {
        "schema": "harbinger-retest-v1",
        "record_kind": kind,
        "participant": "B",
        "observer": "진행자",
        "phase": phase,
        "version": "v-test",
        "mode": "local",
        "scenario": "same-csv-2025-06",
        "date": "2026-10-25",
        "consent": True,
        "tasks": [
            {
                "id": i,
                "result": "unassisted",
                "help": "",
                "notes": "",
                "events": [
                    {"state": "active", "at_ms": 0},
                    {"state": "waiting", "at_ms": 3000},
                    {"state": "paused", "at_ms": 5000},
                    {"state": "active", "at_ms": 6000},
                    {"state": "finished", "at_ms": 10000},
                ],
                "active_ms": 7000,
                "waiting_ms": 2000,
                "paused_ms": 1000,
            }
            for i in range(1, 8)
        ],
    }


def test_measured_events_reject_forged_duration():
    r = record()
    assert validate(r)["unassisted"] == 7
    r["tasks"][0]["active_ms"] = 999
    with pytest.raises(ValueError, match="duration"):
        validate(r)


def test_incomplete_and_skipped_never_count_as_success():
    r = record()
    r["tasks"][0].update(result="incomplete", notes="막힘")
    r["tasks"][1].update(result="not_attempted", events=[], active_ms=0, waiting_ms=0, paused_ms=0)
    assert validate(r) == {
        "completed": 5,
        "unassisted": 5,
        "assisted": 0,
        "incomplete": 1,
        "not_attempted": 1,
    }


def test_help_cannot_be_hidden_as_unassisted():
    r = record()
    r["tasks"][0]["help"] = "필터 위치 안내"
    with pytest.raises(ValueError, match="help"):
        validate(r)
    r["tasks"][0]["result"] = "assisted"
    assert validate(r)["assisted"] == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(consent=False),
        lambda r: r.update(version=""),
        lambda r: r["tasks"].pop(),
        lambda r: r["tasks"][0]["events"].__setitem__(1, {"state": "waiting", "at_ms": -1}),
    ],
)
def test_incomplete_invalid_record_rejected(mutate):
    r = record()
    mutate(r)
    with pytest.raises(ValueError):
        validate(r)


def test_comparison_requires_matched_human_records():
    before, after = record(), record("after")
    after["tasks"][0]["events"][-1]["at_ms"] = 9000
    after["tasks"][0]["active_ms"] = 6000
    result = compare(before, after)
    assert result["tasks"][0]["active_delta_ms"] == -1000
    assert result["scope"] == "paired observations; not causal or population evidence"
    changed = copy.deepcopy(after)
    changed["participant"] = "A"
    with pytest.raises(ValueError, match="match"):
        compare(before, changed)
    changed = copy.deepcopy(after)
    changed["record_kind"] = "tool-test"
    with pytest.raises(ValueError, match="human"):
        compare(before, changed)


def test_skipped_task_has_no_time_comparison():
    before, after = record(), record("after")
    after["tasks"][0].update(result="not_attempted", events=[], active_ms=0, waiting_ms=0, paused_ms=0)
    assert compare(before, after)["tasks"][0]["active_delta_ms"] is None


def test_negative_duration_is_never_accepted_as_rounding_tolerance():
    r = record()
    r["tasks"][0].update(result="not_attempted", events=[], active_ms=-1, waiting_ms=0, paused_ms=0)
    with pytest.raises(ValueError, match="duration"):
        validate(r)
