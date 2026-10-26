"""Recompute the packaged local comparison; no server, training or network needed."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quantile(values, q):
    values = sorted(values)
    index = (len(values) - 1) * q
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def close(a, b):
    assert math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10), (a, b)


def build(root):
    manifests = {m: read(root / m / "manifest.json") for m in ("before", "after")}
    before, after = manifests["before"], manifests["after"]
    equal_fields = (
        "kind",
        "platform",
        "python",
        "cpu_count_host_visible",
        "cpu_model",
        "host_mem_total",
        "container_cpu_max",
        "container_memory_max",
        "process_threads_env",
        "workers",
        "compute_slots",
        "requests_per_route_per_concurrency",
        "concurrency",
        "as_of",
        "site",
        "budget",
        "csv_bytes",
        "csv_rows",
        "csv_assets",
        "csv_sites",
        "csv_sha256",
        "example_summary",
        "version",
        "runtime_sha256",
        "measurement_sha256",
        "scope",
    )
    for field in equal_fields:
        assert before[field] == after[field], field
    assert set(before) == set(after)
    assert set(before) - set(equal_fields) == {
        "started_at_utc",
        "startup_seconds",
        "source_sha256",
        "compute_policy",
    }
    assert before["compute_policy"] == {"slots": 2, "waiting": 0, "timeout_seconds": 0}
    assert after["compute_policy"] == {"slots": 2, "waiting": 4, "timeout_seconds": 10.0}
    assert before["version"]["model_version"] == "v20261026-093937"
    changes = {
        p: {"before": before["source_sha256"].get(p), "after": after["source_sha256"].get(p)}
        for p in sorted(before["source_sha256"].keys() | after["source_sha256"].keys())
        if before["source_sha256"].get(p) != after["source_sha256"].get(p)
    }
    unchanged_hot_paths = (
        "src/harbinger/api/analysis.py",
        "src/harbinger/api/upload.py",
        "src/harbinger/models/classify.py",
        "src/harbinger/features/build.py",
        "src/harbinger/features/refresh.py",
        "src/harbinger/monitoring/metrics.py",
    )
    for p in unchanged_hot_paths:
        assert before["source_sha256"][p] == after["source_sha256"][p]
    output = {
        "evidence_root": str(root.relative_to(ROOT)) if root.is_relative_to(ROOT) else str(root),
        "scope": "One sequential before/after local synthetic run per condition; not AWS or a capacity guarantee.",
        "identical_manifest_fields": list(equal_fields),
        "shared_environment_workload": {
            k: before[k] for k in equal_fields if k not in ("runtime_sha256", "version", "scope")
        },
        "shared_runtime_sha256": before["runtime_sha256"],
        "shared_model_version": before["version"]["model_version"],
        "changed_source_files": changes,
        "unchanged_hot_path_files": list(unchanged_hot_paths),
        "policies": {m: manifests[m]["compute_policy"] for m in manifests},
        "runs": {},
        "resource_reconstruction_limit": "CPU endpoint deltas and wall durations are recorded in load-summary, not independently reconstructable from 100ms interior samples. CPU% is recalculated; RSS sampled maximum is cross-checked. Endpoint-inclusive RSS may exceed the interior sampled peak; each cell records that gap.",
    }
    required_alerts = {"HarbingerWorkbenchFailures", "HarbingerWorkbenchSlow"}
    for mode, manifest in manifests.items():
        folder = root / mode
        assert digest(folder / "workload.csv") == manifest["csv_sha256"]
        data = (folder / "workload.csv").read_bytes()
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        assert (
            len(data),
            len(rows),
            len({r["asset_id"] for r in rows}),
            len({r["site_id"] for r in rows}),
        ) == (1546864, 7352, 104, 1)
        execution = read(folder / "execution.json")
        assert execution["exit_code"] == 0
        raw, summaries = read(folder / "load-raw.json"), read(folder / "load-summary.json")
        assert len(raw) == 120 and len(summaries) == 6
        results = []
        for saved in summaries:
            op, concurrency = saved["operation"], saved["concurrency"]
            requests = [r for r in raw if r["operation"] == op and r["concurrency"] == concurrency]
            assert len(requests) == saved["requests"] == 20
            counts = dict(sorted(Counter(str(r["status"]) for r in requests).items()))
            assert counts == saved["status_counts"]
            assert counts == ({"200": 2, "429": 18} if mode == "before" and concurrency == 4 else {"200": 20})
            success = [r["seconds"] for r in requests if r["status"] == 200]
            latencies = {key: quantile(success, q) for key, q in (("p50", 0.5), ("p95", 0.95), ("max", 1))}
            for k, v in latencies.items():
                close(v, saved["success_latency_seconds"][k])
            failures = sum(
                r["status"] == "transport_error" or isinstance(r["status"], int) and r["status"] >= 500
                for r in requests
            )
            assert failures == 0 and saved["server_or_transport_failure_rate"] == 0
            close(counts.get("429", 0) / 20, saved["intentional_429_rate"])
            samples = read(folder / f"resources-{op}-{concurrency}.json")
            interior_peak = max(r["rss_bytes"] for r in samples)
            assert interior_peak <= saved["peak_sampled_rss_bytes"]
            assert samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"] <= saved["cpu_seconds"] + 1e-9
            cpu_percent = 100 * saved["cpu_seconds"] / saved["wall_seconds"]
            close(cpu_percent, saved["cpu_percent_one_core"])
            results.append(
                {
                    "operation": op,
                    "concurrency": concurrency,
                    "requests": 20,
                    "status_counts": counts,
                    "successes": len(success),
                    "successful_latency_seconds": latencies,
                    "server_or_transport_failures": failures,
                    "rate_429": counts.get("429", 0) / 20,
                    "wall_seconds": saved["wall_seconds"],
                    "cpu_seconds": saved["cpu_seconds"],
                    "cpu_percent_one_core": cpu_percent,
                    "peak_rss_mib": saved["peak_sampled_rss_bytes"] / 1024**2,
                    "interior_peak_rss_mib": interior_peak / 1024**2,
                    "resource_samples": len(samples),
                    "endpoint_peak_above_interior_bytes": saved["peak_sampled_rss_bytes"] - interior_peak,
                    "total_response_requests_per_second": 20 / saved["wall_seconds"],
                    "successful_requests_per_second": len(success) / saved["wall_seconds"],
                }
            )
        recovery = read(folder / "load-recovery.json")
        assert recovery["health"]["status"] == "ok"
        assert all(r["status"] == 200 for r in recovery["requests"])
        assert all(r["status"] == 200 for r in read(folder / "warmup.json"))
        capacity = read(folder / "capacity.json")
        assert (
            capacity["status"] == 429
            and "세션 한도 8개" in capacity["rejection"]
            and capacity["capacity_reason"] is None
        )
        overload = read(folder / "admission-overload.json")
        assert (
            overload["injected_hold_seconds"] == 15
            and overload["concurrency"] == 12
            and len(overload["requests"]) == 20
        )
        overload_counts = dict(Counter(str(r["status"]) for r in overload["requests"]))
        assert overload_counts == {"200": 2, "429": 18}
        rejection_reasons = dict(
            sorted(
                Counter(
                    r["capacity_reason"] or "legacy_immediate_rejection"
                    for r in overload["requests"]
                    if r["status"] == 429
                ).items()
            )
        )
        if mode == "after":
            assert rejection_reasons == {"queue_full": 14, "wait_timeout": 4}
            assert all(r["retry_after"] == "1" for r in overload["requests"] if r["status"] == 429)
            assert all(
                10 <= r["seconds"] < 11
                for r in overload["requests"]
                if r["capacity_reason"] == "wait_timeout"
            )
        assert all(r["status"] == 200 for r in read(folder / "admission-recovery.json"))
        notifications = read(folder / "notifications.json")
        events = [
            {"name": r["alert"]["labels"]["alertname"], "state": r["state"], "at": r["received_at"]}
            for r in notifications
        ]
        for state in ("firing", "resolved"):
            assert required_alerts <= {e["name"] for e in events if e["state"] == state}
        alert_result = read(folder / "alert-result.json")
        assert required_alerts <= set(alert_result["fired"]) and required_alerts <= set(
            alert_result["resolved"]
        )
        assert alert_result["recovery_request"]["status"] == 200
        recovered_rules = read(folder / "recovered-rules.json")
        final_states = {
            r["name"]: r["state"]
            for g in recovered_rules["data"]["groups"]
            for r in g["rules"]
            if "state" in r
        }
        latest_states = {}
        for event in sorted(events, key=lambda event: event["at"]):
            latest_states[event["name"]] = event["state"]
        all_alerts_settled = all(
            final_states.get(name) == "inactive" and latest_states.get(name) == "resolved"
            for name in required_alerts
        )
        if "currently_recovered" in alert_result:
            assert alert_result["currently_recovered"] == all_alerts_settled
        alert_requests = read(folder / "alert-requests.json")
        assert any(r["status"] == 500 for r in alert_requests)
        output["runs"][mode] = {
            "execution": execution,
            "load": results,
            "load_recovery": recovery,
            "session_capacity": capacity,
            "admission": {
                "hold_seconds": 15,
                "client_workers": 12,
                "requests": 20,
                "status_counts": overload_counts,
                "rejection_reasons": rejection_reasons,
                "recovery": read(folder / "admission-recovery.json"),
            },
            "alert_events": events,
            "last_recorded_alert_states": final_states,
            "alerts_both_fired_and_resolved_at_least_once": True,
            "latest_notification_states": latest_states,
            "all_required_alerts_currently_settled": all_alerts_settled,
            "alert_fault_injection_status_counts": dict(Counter(str(r["status"]) for r in alert_requests)),
            "alert_recovery": alert_result["recovery_request"],
        }
    output["evidence_sha256"] = {
        str(p.relative_to(root)): digest(p)
        for mode in manifests
        for p in sorted((root / mode).iterdir())
        if p.is_file()
    }
    output["raw_measurement_checks_passed"] = True
    output["overall_passed"] = all(
        run["all_required_alerts_currently_settled"] for run in output["runs"].values()
    )
    assert (root / "before/test-rules.yml").read_bytes() == (root / "after/test-rules.yml").read_bytes()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "strict",
        help="Folder containing before/ and after/; default is packaged strict retry.",
    )
    parser.add_argument(
        "--write", action="store_true", help="Write comparison.json; default verifies existing comparison."
    )
    args = parser.parse_args()
    comparison = build(args.root.resolve())
    path = ROOT / "comparison.json"
    if args.write:
        path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    elif path.exists() and read(path).get("evidence_root") == comparison["evidence_root"]:
        assert comparison == read(path), "comparison.json differs from recomputed evidence"
    print(
        json.dumps(
            {
                "raw_measurement_checks_passed": True,
                "overall_passed": comparison["overall_passed"],
                "evidence_root": comparison["evidence_root"],
                "alert_settlement": {
                    mode: run["all_required_alerts_currently_settled"]
                    for mode, run in comparison["runs"].items()
                },
            },
            indent=2,
        )
    )
    raise SystemExit(0 if comparison["overall_passed"] else 1)


if __name__ == "__main__":
    main()
