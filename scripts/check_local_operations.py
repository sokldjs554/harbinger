"""Fixed, loopback-only workload and real Prometheus -> local receiver exercise.

Uses existing local synthetic data/models; creates no remote resources. Run with
--runtime DIR (data/models/artifacts) --prometheus PATH --out DIR.
Raw timings exclude session cleanup; workload setup/warmup is recorded separately.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv as csv_module
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import numpy as np
import yaml

BASE = "http://127.0.0.1:18000"
PROM = "http://127.0.0.1:19090"
ROUTES = {
    "analysis": "/v1/workbench/sessions/{token}/analysis",
    "upload": "/v1/workbench/upload",
    "download": "/v1/workbench/sessions/{token}/download",
}


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def wait_http(url, timeout=90):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if httpx.get(url, timeout=2, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Local service did not become ready: {url}")


def read_limit(name):
    path = Path("/sys/fs/cgroup") / name
    return path.read_text().strip() if path.exists() else None


def proc_usage(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()
    return {
        "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
        "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
    }


def alert_recovery_complete(required, notifications, rules):
    latest = {n["alert"]["labels"]["alertname"]: n["state"] for n in notifications}
    states = {
        r["name"]: r.get("state")
        for group in rules.get("data", {}).get("groups", [])
        for r in group.get("rules", [])
    }
    return all(latest.get(name) == "resolved" and states.get(name) == "inactive" for name in required)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--prometheus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fault = out / "inject-failure"
    hold = out / "hold-computation"
    fault.unlink(missing_ok=True)
    hold.unlink(missing_ok=True)
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "HARBINGER_DEMO_BOOTSTRAP": "0",
        "HARBINGER_AUTH_MODE": "demo",
        "HARBINGER_AUDIT_FAULT_FILE": str(fault),
    }
    for kind in ("data", "model", "artifact"):
        env[f"HARBINGER_{kind.upper()}_DIR"] = str(
            args.runtime.resolve() / (kind + "s" if kind != "data" else kind)
        )
    processes = []
    receiver = None
    try:
        startup = time.perf_counter()
        server = subprocess.Popen(
            [sys.executable, "-m", "scripts.audit_fault_server"],
            env=env,
            stdout=(out / "api.log").open("w"),
            stderr=subprocess.STDOUT,
        )
        processes.append(server)
        wait_http(BASE + "/health")
        startup = time.perf_counter() - startup
        client = httpx.Client(base_url=BASE, timeout=120, trust_env=False)
        example = client.post("/v1/workbench/example")
        example.raise_for_status()
        ex = example.json()
        token = ex["session_id"]
        params = {"as_of": ex["default_as_of"], "site": "S01", "k": 10}
        csv = client.get("/v1/workbench/example.csv?site=S01").content
        csv_rows = list(csv_module.DictReader(io.StringIO(csv.decode("utf-8-sig"))))
        (out / "workload.csv").write_bytes(csv)
        version = client.get("/version").json()
        manifest = {
            "kind": "local-synthetic-fixed-workload",
            "started_at_utc": datetime.now(UTC).isoformat(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count_host_visible": os.cpu_count(),
            "cpu_model": next(
                (
                    s.split(":", 1)[1].strip()
                    for s in Path("/proc/cpuinfo").read_text().splitlines()
                    if s.startswith("model name")
                ),
                None,
            ),
            "host_mem_total": Path("/proc/meminfo").read_text().splitlines()[0],
            "container_cpu_max": read_limit("cpu.max"),
            "container_memory_max": read_limit("memory.max"),
            "process_threads_env": {k: env[k] for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")},
            "workers": 1,
            "compute_slots": 2,
            "compute_policy": client.get("/v1/workbench/info")
            .json()
            .get("compute_policy", {"slots": 2, "waiting": 0, "timeout_seconds": 0}),
            "requests_per_route_per_concurrency": 20,
            "concurrency": [1, 4],
            "as_of": params["as_of"],
            "site": "S01",
            "budget": 10,
            "csv_bytes": len(csv),
            "csv_rows": len(csv_rows),
            "csv_assets": len({r["asset_id"] for r in csv_rows}),
            "csv_sites": len({r["site_id"] for r in csv_rows}),
            "csv_sha256": hashlib.sha256(csv).hexdigest(),
            "example_summary": ex["summary"],
            "version": version,
            "startup_seconds": startup,
            "source_sha256": {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path("src").rglob("*.py"))
            },
            "measurement_sha256": {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path("scripts/check_local_operations.py"), Path("scripts/audit_fault_server.py")]
            },
            "runtime_sha256": {
                str(p.relative_to(args.runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in ("data", "models")
                for p in sorted((args.runtime / folder).rglob("*"))
                if p.is_file()
            },
            "scope": "Local process measurements; not AWS throughput or customer capacity. Startup includes interpreter/model loading, excludes bootstrap/build.",
        }
        dump(out / "manifest.json", manifest)
        raw = []
        summaries = []

        def request(operation):
            began = time.perf_counter()
            try:
                if operation == "upload":
                    r = client.post(
                        ROUTES[operation],
                        params={"observation_end": ex["latest_as_of_date"], "observation_confirmed": True},
                        content=csv,
                        headers={"Content-Type": "text/csv"},
                    )
                else:
                    r = client.get(
                        ROUTES[operation].format(token=token),
                        params={**params, **({"format": "json"} if operation == "download" else {})},
                    )
                duration = time.perf_counter() - began
                code = r.status_code
                rejection = r.json().get("detail") if code == 429 else None
                if operation == "upload" and code == 200:
                    client.delete("/v1/workbench/sessions/" + r.json()["session_id"])
                return {
                    "operation": operation,
                    "status": code,
                    "seconds": duration,
                    "bytes": len(r.content),
                    "rejection": rejection,
                    "retry_after": r.headers.get("Retry-After"),
                    "capacity_reason": r.headers.get("X-Harbinger-Capacity"),
                }
            except httpx.HTTPError as exc:
                return {
                    "operation": operation,
                    "status": "transport_error",
                    "seconds": time.perf_counter() - began,
                    "error": type(exc).__name__,
                }

        warm = [request(op) for op in ROUTES]
        dump(out / "warmup.json", warm)
        assert all(r["status"] == 200 for r in warm), warm
        for concurrency in (1, 4):
            for operation in ROUTES:
                samples = []
                stop = threading.Event()

                def sample(stop=stop, samples=samples):
                    while not stop.wait(0.1):
                        samples.append({"monotonic_seconds": time.monotonic(), **proc_usage(server.pid)})

                thread = threading.Thread(target=sample)
                thread.start()
                usage0 = proc_usage(server.pid)
                began = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                    records = list(pool.map(lambda _, operation=operation: request(operation), range(20)))
                elapsed = time.perf_counter() - began
                usage1 = proc_usage(server.pid)
                stop.set()
                thread.join()
                dump(out / f"resources-{operation}-{concurrency}.json", samples)
                for r in records:
                    r["concurrency"] = concurrency
                raw.extend(records)
                success = [r["seconds"] for r in records if r["status"] == 200]
                summaries.append(
                    {
                        "operation": operation,
                        "concurrency": concurrency,
                        "requests": 20,
                        "status_counts": dict(Counter(str(r["status"]) for r in records)),
                        "success_latency_seconds": dict(
                            zip(["p50", "p95", "max"], map(float, np.quantile(success, [0.5, 0.95, 1])))
                        )
                        if success
                        else None,
                        "server_or_transport_failure_rate": sum(
                            r["status"] == "transport_error"
                            or isinstance(r["status"], int)
                            and r["status"] >= 500
                            for r in records
                        )
                        / 20,
                        "intentional_429_rate": sum(r["status"] == 429 for r in records) / 20,
                        "wall_seconds": elapsed,
                        "cpu_seconds": usage1["cpu_seconds"] - usage0["cpu_seconds"],
                        "cpu_percent_one_core": 100
                        * (usage1["cpu_seconds"] - usage0["cpu_seconds"])
                        / elapsed,
                        "peak_sampled_rss_bytes": max(
                            [usage0["rss_bytes"], usage1["rss_bytes"]] + [s["rss_bytes"] for s in samples]
                        ),
                    }
                )
                dump(out / "load-raw.json", raw)
                dump(out / "load-summary.json", summaries)
        recovery = [request(op) for op in ROUTES]
        dump(
            out / "load-recovery.json",
            {"requests": recovery, "health": client.get("/health").json(), "usage": proc_usage(server.pid)},
        )
        assert all(r["status"] == 200 for r in recovery)
        assert not any(s["server_or_transport_failure_rate"] for s in summaries)
        # Explicit saturation: fill session slots; an intended 429 is not a 5xx failure.
        extra = []
        for _ in range(8):
            response = client.post("/v1/workbench/example")
            if response.status_code == 200:
                extra.append(response.json()["session_id"])
            else:
                assert response.status_code == 429
        capacity = request("upload")
        for sid in extra:
            client.delete("/v1/workbench/sessions/" + sid)
        dump(out / "capacity.json", capacity)
        assert capacity["status"] == 429
        # Deliberate local hold is separate from throughput/latency claims above.
        # Same 20 requests/12 workers before and after the admission-policy change.
        hold.write_text("local 15s computation hold\n")
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                overload = list(pool.map(lambda _: request("analysis"), range(20)))
        finally:
            hold.unlink(missing_ok=True)
        dump(
            out / "admission-overload.json",
            {"injected_hold_seconds": 15, "concurrency": 12, "requests": overload},
        )
        assert all(r["status"] in (200, 429) for r in overload)
        assert any(r["status"] == 429 for r in overload)
        if manifest["compute_policy"]["waiting"]:
            reasons = {r["capacity_reason"] for r in overload}
            assert {"queue_full", "wait_timeout"} <= reasons, reasons
        overload_recovery = [request(op) for op in ROUTES]
        dump(out / "admission-recovery.json", overload_recovery)
        assert all(r["status"] == 200 for r in overload_recovery)
        # Prometheus sends Alertmanager v2 messages directly to a local protocol receiver.
        notifications = []

        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received = datetime.now(UTC)
                for alert in body:
                    ends = datetime.fromisoformat(alert["endsAt"].replace("Z", "+00:00"))
                    notifications.append(
                        {
                            "received_at": received.isoformat(),
                            "state": "resolved" if ends <= received else "firing",
                            "alert": alert,
                        }
                    )
                dump(out / "notifications.json", notifications)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        receiver = ThreadingHTTPServer(("127.0.0.1", 19093), Receiver)
        threading.Thread(target=receiver.serve_forever, daemon=True).start()
        rules = yaml.safe_load(Path("deploy/monitoring/rules.yml").read_text())
        group = next(g for g in rules["groups"] if g["name"] == "harbinger-workbench")
        group["interval"] = "1s"
        for rule in group["rules"]:
            rule["expr"] = (
                rule["expr"].replace("[5m]", "[10s]").replace("> 2)", "> 0.001)").replace(">= 20)", ">= 1)")
            )
            if "for" in rule:
                rule["for"] = "2s"
        (out / "test-rules.yml").write_text(yaml.safe_dump({"groups": [group]}, sort_keys=False))
        config = {
            "global": {"scrape_interval": "1s", "evaluation_interval": "1s"},
            "rule_files": [str(out / "test-rules.yml")],
            "scrape_configs": [
                {"job_name": "harbinger", "static_configs": [{"targets": ["127.0.0.1:18000"]}]}
            ],
            "alerting": {"alertmanagers": [{"static_configs": [{"targets": ["127.0.0.1:19093"]}]}]},
        }
        (out / "prometheus.yml").write_text(yaml.safe_dump(config))
        prom = subprocess.Popen(
            [
                str(args.prometheus.resolve()),
                "--config.file=" + str(out / "prometheus.yml"),
                "--storage.tsdb.path=" + str(out / "tsdb"),
                "--web.listen-address=127.0.0.1:19090",
            ],
            stdout=(out / "prometheus.log").open("w"),
            stderr=subprocess.STDOUT,
        )
        processes.append(prom)
        wait_http(PROM + "/-/ready")
        # Keep successful traffic through the real analysis path until local slow alert fires.
        alert_requests = []
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            alert_requests.append(request("analysis"))
            time.sleep(0.4)
        fault.write_text("local injected computation exception\n")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            alert_requests.append(request("analysis"))
            time.sleep(0.4)
        fault.unlink()
        (out / "metrics.txt").write_text(client.get("/metrics").text)
        dump(out / "firing-rules.json", httpx.get(PROM + "/api/v1/rules", trust_env=False).json())
        recovery_request = request("analysis")
        assert recovery_request["status"] == 200
        # Stop requests so the 10s observation window expires; await real resolved notifications.
        deadline = time.monotonic() + 45
        required = {"HarbingerWorkbenchSlow", "HarbingerWorkbenchFailures"}
        final_rules = {}
        while time.monotonic() < deadline:
            final_rules = httpx.get(PROM + "/api/v1/rules", trust_env=False).json()
            if alert_recovery_complete(required, notifications, final_rules):
                break
            time.sleep(1)
        dump(out / "alert-requests.json", alert_requests)
        dump(out / "recovered-rules.json", final_rules)
        fired = {n["alert"]["labels"]["alertname"] for n in notifications if n["state"] == "firing"}
        resolved = {n["alert"]["labels"]["alertname"] for n in notifications if n["state"] == "resolved"}
        dump(
            out / "alert-result.json",
            {
                "fired": sorted(fired),
                "resolved": sorted(resolved),
                "currently_recovered": alert_recovery_complete(required, notifications, final_rules),
                "recovery_request": recovery_request,
                "receiver": "local Alertmanager v2 protocol receiver; no external messaging",
                "test_thresholds": "1s scrape/eval, 10s rate, 2s for, p95 >1ms and >=1 successful request; production thresholds unchanged",
            },
        )
        assert required <= fired and required <= resolved
        assert alert_recovery_complete(required, notifications, final_rules), "Alerts have not settled"
        print(
            json.dumps(
                {
                    "status": "passed",
                    "load_requests": len(raw),
                    "alert_fired": sorted(fired),
                    "alert_resolved": sorted(resolved),
                }
            )
        )
    finally:
        fault.unlink(missing_ok=True)
        hold.unlink(missing_ok=True)
        if receiver:
            receiver.shutdown()
            receiver.server_close()
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
