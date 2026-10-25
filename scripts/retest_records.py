"""Validate locally exported observations; never infer missing human results."""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

STATES = {"active", "waiting", "paused", "finished"}
RESULTS = {"unassisted", "assisted", "incomplete", "not_attempted"}


def durations(events):
    totals = {"active_ms": 0, "waiting_ms": 0, "paused_ms": 0}
    if not events:
        return totals
    if events[0].get("state") != "active" or events[0].get("at_ms") != 0:
        raise ValueError("events must start active at zero")
    if events[-1].get("state") != "finished":
        raise ValueError("task is still running")
    previous = None
    for index, event in enumerate(events):
        at, state = event.get("at_ms"), event.get("state")
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or at < 0:
            raise ValueError("invalid event timestamp")
        if state not in STATES or (state == "finished" and index != len(events) - 1):
            raise ValueError("invalid event state")
        if previous is not None:
            if at < previous["at_ms"]:
                raise ValueError("nonmonotonic event time")
            totals[previous["state"] + "_ms"] += at - previous["at_ms"]
        previous = event
    return totals


def validate(record):
    if not isinstance(record, dict) or record.get("schema") != "harbinger-retest-v1":
        raise ValueError("unsupported record schema")
    for name in ("participant", "observer", "version", "mode", "scenario", "date"):
        if not isinstance(record.get(name), str) or not record[name].strip():
            raise ValueError(f"missing {name}")
    date.fromisoformat(record["date"])
    if record.get("consent") is not True:
        raise ValueError("recording consent required")
    if record.get("record_kind") not in {"human", "tool-test"} or record.get("phase") not in {
        "before",
        "after",
    }:
        raise ValueError("invalid kind or phase")
    tasks = record.get("tasks", [])
    if len(tasks) != 7 or [t.get("id") for t in tasks] != list(range(1, 8)):
        raise ValueError("seven ordered tasks required")
    counts = dict.fromkeys(["completed", "unassisted", "assisted", "incomplete", "not_attempted"], 0)
    for task in tasks:
        result = task.get("result")
        if result not in RESULTS:
            raise ValueError("task result missing")
        for field in ("help", "notes"):
            if not isinstance(task.get(field), str):
                raise ValueError(f"invalid {field}")
        if result == "unassisted" and task["help"].strip():
            raise ValueError("help cannot be recorded as unassisted")
        if result == "assisted" and not task["help"].strip():
            raise ValueError("assisted result needs help description")
        if result == "incomplete" and not task["notes"].strip():
            raise ValueError("incomplete result needs reason")
        events = task.get("events")
        if not isinstance(events, list):
            raise ValueError("events required")
        if (result == "not_attempted") != (len(events) == 0):
            raise ValueError("unattempted task must have no recorded attempt")
        for key, value in durations(events).items():
            stated = task.get(key)
            if isinstance(stated, bool) or not isinstance(stated, (int, float)) or not math.isfinite(stated):
                raise ValueError("invalid duration")
            if stated < 0 or abs(stated - value) > 2:
                raise ValueError("duration disagrees with events")
        counts[result] += 1
        counts["completed"] += int(result in {"unassisted", "assisted"})
    return counts


def compare(before, after):
    a, b = validate(before), validate(after)
    if before["record_kind"] != "human" or after["record_kind"] != "human":
        raise ValueError("human observations required; tool tests are not participants")
    if before["phase"] != "before" or after["phase"] != "after":
        raise ValueError("before/after pair required")
    for key in ("participant", "mode", "scenario"):
        if before[key] != after[key]:
            raise ValueError(f"records must match {key}")
    if date.fromisoformat(after["date"]) < date.fromisoformat(before["date"]):
        raise ValueError("after date precedes before")
    tasks = []
    for left, right in zip(before["tasks"], after["tasks"], strict=True):
        comparable = left["result"] in {"unassisted", "assisted"} and right["result"] in {
            "unassisted",
            "assisted",
        }
        tasks.append(
            {
                "id": left["id"],
                "before_result": left["result"],
                "after_result": right["result"],
                "active_delta_ms": right["active_ms"] - left["active_ms"] if comparable else None,
                "waiting_delta_ms": right["waiting_ms"] - left["waiting_ms"] if comparable else None,
            }
        )
    return {
        "before": a,
        "after": b,
        "tasks": tasks,
        "scope": "paired observations; not causal or population evidence",
        "limitations": "Self-reported observation record; practice/order effects and assistance differences remain.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--after", type=Path)
    args = parser.parse_args()
    record = json.loads(args.record.read_text())
    result = compare(record, json.loads(args.after.read_text())) if args.after else validate(record)
    print(json.dumps(result, ensure_ascii=False, indent=2))
