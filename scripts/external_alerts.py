"""Private SMTP configuration and a bounded, separate-target notification drill.

The on-host verifier uses only the standard library. Rendering requires PyYAML.
It never reads back SMTP configuration or treats operator receipt as automatic.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

PROM = "http://127.0.0.1:19090"
ALERT = "HarbingerControlledNotification"


def write_bundle(directory, env, verification_id):
    """Validate first; secrets go only to a private deployment bundle."""
    import yaml

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", verification_id):
        raise ValueError("invalid verification ID")
    names = ("HOST", "PORT", "USERNAME", "PASSWORD", "FROM")
    values = {}
    for name in names:
        key = "HARBINGER_SMTP_" + name
        value = env.get(key, "")
        if not value or any(c in value for c in "\r\n\x00"):
            raise ValueError("missing or invalid " + key)
        values[name] = value
    recipient = env.get("HARBINGER_ALERT_TO", "")
    address = r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+"
    for key, value in (("HARBINGER_SMTP_FROM", values["FROM"]), ("HARBINGER_ALERT_TO", recipient)):
        if not re.fullmatch(address, value):
            raise ValueError("invalid " + key)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9.-]+", values["HOST"]):
        raise ValueError("invalid HARBINGER_SMTP_HOST")
    if values["PORT"] != "465":
        raise ValueError("HARBINGER_SMTP_PORT must use the supported implicit TLS port")
    directory = Path(directory)
    config = directory / "config"
    config.mkdir(parents=True, mode=0o700)

    def save(name, data):
        path = config / name
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        path.chmod(0o600)

    email = {
        "to": recipient,
        "send_resolved": True,
        "headers": {
            "Subject": "[Harbinger {{ .Status | toUpper }}] {{ .CommonLabels.alertname }} {{ .CommonLabels.verification_id }}"
        },
    }
    save(
        "alertmanager.yml",
        {
            "global": {
                "smtp_smarthost": values["HOST"] + ":465",
                "smtp_from": values["FROM"],
                "smtp_auth_username": values["USERNAME"],
                "smtp_auth_password_file": "/etc/hbmonitor/smtp-password",
                "smtp_require_tls": True,
                "smtp_force_implicit_tls": True,
            },
            "route": {
                "receiver": "operator",
                "group_by": ["alertname", "instance", "verification_id"],
                "group_wait": "10s",
                "group_interval": "10s",
                "repeat_interval": "12h",
                "routes": [{"receiver": "verification", "matchers": ['alertname="' + ALERT + '"']}],
            },
            "receivers": [{"name": name, "email_configs": [email]} for name in ("operator", "verification")],
        },
    )
    password = config / "smtp-password"
    password.write_text(values["PASSWORD"])
    password.chmod(0o600)
    normal = {
        "global": {"scrape_interval": "15s", "evaluation_interval": "15s"},
        "rule_files": ["/etc/hbmonitor/rules.yml"],
        "alerting": {"alertmanagers": [{"static_configs": [{"targets": ["127.0.0.1:19093"]}]}]},
        "scrape_configs": [{"job_name": "harbinger", "static_configs": [{"targets": ["127.0.0.1:8000"]}]}],
    }
    save("prometheus-normal.yml", normal)
    save("prometheus.yml", normal)
    test = json.loads(json.dumps(normal))
    test["rule_files"].append("/etc/hbmonitor/test-rules.yml")
    test["scrape_configs"].append(
        {"job_name": "harbinger-controlled-probe", "static_configs": [{"targets": ["127.0.0.1:19101"]}]}
    )
    save("prometheus-test.yml", test)
    save(
        "test-rules.yml",
        {
            "groups": [
                {
                    "name": "controlled-notification",
                    "rules": [
                        {
                            "alert": ALERT,
                            "expr": 'up{job="harbinger-controlled-probe"} == 0',
                            "for": "30s",
                            "labels": {"severity": "test", "verification_id": verification_id},
                            "annotations": {
                                "summary": "Controlled email drill; public Harbinger remains available",
                                "description": "Separate loopback probe stopped/restored for notification verification. This is not a customer incident.",
                            },
                        }
                    ],
                }
            ]
        },
    )
    services = {}
    for name, image, port, memory, cpu, command in [
        (
            "prometheus",
            "prom/prometheus:v2.54.1",
            19090,
            "192m",
            0.25,
            [
                "--config.file=/etc/hbmonitor/prometheus.yml",
                "--storage.tsdb.path=/prometheus",
                "--storage.tsdb.retention.time=24h",
                "--storage.tsdb.retention.size=100MB",
                "--web.enable-lifecycle",
            ],
        ),
        (
            "alertmanager",
            "prom/alertmanager:v0.33.0",
            19093,
            "64m",
            0.1,
            [
                "--config.file=/etc/hbmonitor/alertmanager.yml",
                "--storage.path=/alertmanager",
                "--cluster.listen-address=",
                "--log.level=debug",
                "--log.format=json",
            ],
        ),
    ]:
        services[name] = {
            "image": image,
            "container_name": "harbinger-" + name,
            "restart": "unless-stopped",
            "network_mode": "host",
            "user": "65534:65534",
            "read_only": True,
            "mem_limit": memory,
            "cpus": cpu,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "command": command + [f"--web.listen-address=127.0.0.1:{port}"],
            "volumes": [
                *[
                    f"./config/{filename}:/etc/hbmonitor/{filename}:ro"
                    for filename in (
                        ("prometheus.yml", "rules.yml", "test-rules.yml")
                        if name == "prometheus"
                        else ("alertmanager.yml", "smtp-password")
                    )
                ],
                f"/opt/harbinger-monitoring/data/{name}:/{name}",
            ],
            "logging": {"driver": "json-file", "options": {"max-size": "2m", "max-file": "2"}},
        }
    (directory / "compose.yml").write_text(yaml.safe_dump({"services": services}, sort_keys=False))
    (directory / "verification-id").write_text(verification_id)


def email_successes(logs):
    """Project only safe transport-success metadata, never full debug logs."""
    events = []
    for line in logs.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (
            row.get("msg") == "Notify success"
            and row.get("receiver") == "verification"
            and str(row.get("integration", "")).startswith("email[")
        ):
            events.append(
                {
                    "at": row.get("ts") or row.get("time"),
                    "receiver": "verification",
                    "integration": row["integration"],
                }
            )
    return events


def now():
    return datetime.now(UTC).isoformat()


def email_failures(logs):
    """Keep failure classification, never provider messages or account values."""
    events = []
    for line in logs.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (
            row.get("receiver") != "verification"
            or not str(row.get("integration", "")).startswith("email[")
            or not str(row.get("msg", "")).startswith("Notify attempt failed")
        ):
            continue
        error = str(row.get("err", ""))
        code = re.search(r"\b([45][0-5][0-9])[ -]", error)
        lowered = error.lower()
        if "auth" in lowered or (code and code[1] in {"534", "535", "538"}):
            category = "authentication"
        elif any(s in lowered for s in ("x509", "tls", "certificate")):
            category = "tls"
        elif any(s in lowered for s in ("timeout", "dial tcp", "connection refused", "no such host")):
            category = "network"
        else:
            category = "smtp_rejection" if code else "unclassified"
        events.append(
            {
                "at": row.get("ts") or row.get("time"),
                "receiver": "verification",
                "integration": "email[0]",
                "category": category,
                "smtp_code": code[1] if code else None,
            }
        )
    return events


def request(url, post=False):
    with urlopen(Request(url, data=b"" if post else None), timeout=5) as response:
        data = response.read()
    return json.loads(data) if data else None


def wait_for(check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except OSError:
            pass
        time.sleep(2)
    raise TimeoutError("bounded monitoring condition did not settle")


def verify_on_host(release, out):
    """Real Prometheus/Alertmanager -> SMTP; human receipt stays unconfirmed."""
    release, out = Path(release), Path(out)
    test_id = (release / "verification-id").read_text().strip()
    started = now()
    report = {
        "verification_id": test_id,
        "started_at": started,
        "operator_receipt_confirmed": False,
        "scope": "existing host; real email route; isolated probe fault; no public load",
        "events": {},
    }
    server = None

    class Probe(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"harbinger_controlled_probe 1\n")

        def log_message(self, *args):
            pass

    def start_probe():
        probe = ThreadingHTTPServer(("127.0.0.1", 19101), Probe)
        threading.Thread(target=probe.serve_forever, daemon=True).start()
        return probe

    def rule_state():
        return next(
            (
                r
                for g in request(PROM + "/api/v1/rules")["data"]["groups"]
                for r in g["rules"]
                if r["name"] == ALERT
            ),
            None,
        )

    def notification_logs():
        result = subprocess.run(
            ["docker", "logs", "--since", started, "harbinger-alertmanager"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout + "\n" + result.stderr

    def successes():
        return email_successes(notification_logs())

    try:
        report["health_before"] = request("http://127.0.0.1:8000/health")
        report["version_before"] = request("http://127.0.0.1:8000/version")["model_version"]
        assert report["health_before"]["status"] == "ok"
        server = start_probe()
        shutil.copyfile(release / "config/prometheus-test.yml", release / "config/prometheus.yml")
        request(PROM + "/-/reload", post=True)
        from urllib.parse import urlencode

        query = PROM + "/api/v1/query?" + urlencode({"query": 'up{job="harbinger-controlled-probe"}'})
        wait_for(lambda: any(r["value"][1] == "1" for r in request(query)["data"]["result"]))
        report["events"]["fault_injected_at"] = now()
        server.shutdown()
        server.server_close()
        server = None
        rule = wait_for(lambda: (r := rule_state()) and r["state"] == "firing" and r)
        report["events"]["firing_observed_at"] = now()
        report["prometheus_alerts"] = rule["alerts"]
        firing = wait_for(lambda: (e := successes()) and e, timeout=240)
        report["firing_email_transport_success"] = firing[-1]
        server = start_probe()
        report["events"]["probe_restored_at"] = now()
        wait_for(lambda: (r := rule_state()) and r["state"] == "inactive")
        report["events"]["inactive_observed_at"] = now()
        resolved = wait_for(lambda: (e := successes()) and len(e) > len(firing) and e, timeout=240)
        report["resolved_email_transport_success"] = resolved[-1]
        report["transport_verified"] = True
    except Exception as error:
        report["transport_verified"] = False
        report["error_type"] = type(error).__name__
        try:
            report["email_transport_failures"] = email_failures(notification_logs())
        except Exception as diagnostic_error:
            report["diagnostic_error_type"] = type(diagnostic_error).__name__
        raise
    finally:
        try:
            shutil.copyfile(release / "config/prometheus-normal.yml", release / "config/prometheus.yml")
            request(PROM + "/-/reload", post=True)
            assert rule_state() is None
            report["test_rule_removed"] = True
            report["health_after"] = request("http://127.0.0.1:8000/health")
            report["version_after"] = request("http://127.0.0.1:8000/version")["model_version"]
            assert report["health_after"]["status"] == "ok"
            assert report["version_after"] == report["version_before"]
            report["remaining_firing_alerts"] = [
                a["labels"]["alertname"]
                for a in request(PROM + "/api/v1/alerts")["data"]["alerts"]
                if a["state"] == "firing"
            ]
            report["normal_after_test"] = not report["remaining_firing_alerts"]
        finally:
            if server:
                server.shutdown()
                server.server_close()
            report["finished_at"] = now()
            out.write_text(json.dumps(report, indent=2) + "\n")
    assert report["normal_after_test"], "remaining real alerts require operator attention"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    verify_on_host(args.release, args.out)
