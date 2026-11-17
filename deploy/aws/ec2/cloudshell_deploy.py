"""Launch once from CloudShell's native credential provider; never export credentials."""

import argparse
import base64
import datetime as dt
import json
import os
import time
import urllib.request
from pathlib import Path

from bootstrap_account import prepare_network
from deploy import ACCOUNT, INSTANCE_TYPE, REGION, VPC_ID, aws, launch_request, wait_https

# This application's full main CI passed before this deployment adapter was added.
SOURCE_SHA = "5afbeb2131f33802aa4fe075002650be90460a70"


def user_data(stop_at):
    template = Path(__file__).with_name("cloudshell_bootstrap.sh").read_text()
    rendered = template.replace("@@SOURCE_SHA@@", SOURCE_SHA).replace("@@STOP_AT@@", stop_at)
    if "@@" in rendered or len(rendered.encode()) > 16384:
        raise ValueError("Invalid EC2 bootstrap template")
    return base64.b64encode(rendered.encode()).decode()


def check_ci():
    url = f"https://api.github.com/repos/sokldjs554/harbinger/actions/runs?head_sha={SOURCE_SHA}&per_page=100"
    with urllib.request.urlopen(url, timeout=30) as response:
        runs = json.load(response)["workflow_runs"]
    matches = [
        r
        for r in runs
        if r["path"] == ".github/workflows/ci.yml"
        and r["event"] == "push"
        and r["head_branch"] == "main"
        and r["head_sha"] == SOURCE_SHA
    ]
    if not matches or max(matches, key=lambda r: r["id"])["conclusion"] != "success":
        raise ValueError("Full application CI has not passed; no AWS resources changed")


def check_group(group):
    for rule in group.get("IpPermissions", []):
        if (
            rule.get("IpProtocol") != "tcp"
            or rule.get("FromPort") not in (80, 443)
            or rule.get("ToPort") != rule.get("FromPort")
        ):
            raise ValueError("Unexpected inbound rule; existing group left unchanged")


def prepare(apply=False, call=aws, ci_check=check_ci):
    if call("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise ValueError("Wrong AWS account; nothing changed")
    # These functions use the native CloudShell provider, not copied environment keys.
    network = prepare_network(False, call)
    reservations = call("ec2", "describe-instances", "--filters", "Name=tag:Project,Values=harbinger")[
        "Reservations"
    ]
    active = [
        i
        for r in reservations
        for i in r["Instances"]
        if i["State"]["Name"] not in ("terminated", "shutting-down")
    ]
    if active:
        raise ValueError(
            "A Harbinger instance already exists; no duplicate created: "
            + ", ".join(i["InstanceId"] for i in active)
        )
    if network.get("security_group"):
        check_group(
            call("ec2", "describe-security-groups", "--group-ids", network["security_group"])[
                "SecurityGroups"
            ][0]
        )
    info = call("ec2", "describe-instance-types", "--instance-types", INSTANCE_TYPE)["InstanceTypes"][0]
    if info.get("InstanceType") != INSTANCE_TYPE or info.get("FreeTierEligible") is not True:
        raise ValueError("Reviewed Free Tier eligible instance type unavailable")
    subnets = call("ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={VPC_ID}")["Subnets"]
    subnets = sorted(
        (s for s in subnets if s.get("DefaultForAz") and s["State"] == "available"),
        key=lambda s: s["SubnetId"],
    )
    if not subnets:
        raise ValueError("No reviewed default subnet")
    images = call(
        "ec2",
        "describe-images",
        "--owners",
        "099720109477",
        "--filters",
        "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*",
        "Name=state,Values=available",
        "Name=architecture,Values=x86_64",
        "Name=free-tier-eligible,Values=true",
    )["Images"]
    if not images:
        raise ValueError("No reviewed Canonical Ubuntu image")
    image = max(images, key=lambda i: i["CreationDate"])
    ci_check()
    stop_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S UTC")  # noqa: UP017 -- CloudShell Python 3.9 compatibility
    bootstrap = user_data(stop_at)
    print(
        json.dumps(
            {
                "account": ACCOUNT,
                "region": REGION,
                "source": SOURCE_SHA,
                "instance_type": INSTANCE_TYPE,
                "disk_gib": 30,
                "auto_stop_at": stop_at,
                "ssh_open": False,
                "apply": apply,
            }
        ),
        flush=True,
    )
    if not apply:
        return None
    network = prepare_network(True, call)
    group_id = network["security_group"]
    group = call("ec2", "describe-security-groups", "--group-ids", group_id)["SecurityGroups"][0]
    check_group(group)
    request = launch_request(image, subnets[0]["SubnetId"], group_id, "hb-cloudshell-" + SOURCE_SHA[:24])
    request.update(UserData=bootstrap, InstanceInitiatedShutdownBehavior="stop", DryRun=True)
    try:
        call("ec2", "run-instances", "--cli-input-json", json.dumps(request))
    except RuntimeError as error:
        if "(DryRunOperation)" not in str(error):
            raise
    else:
        raise ValueError("Expected dry-run confirmation")
    for port in (80, 443):
        permission = [
            {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}
        ]
        try:
            call(
                "ec2",
                "authorize-security-group-ingress",
                "--group-id",
                group_id,
                "--ip-permissions",
                json.dumps(permission),
            )
        except RuntimeError as error:
            if "InvalidPermission.Duplicate" not in str(error):
                raise
    request.pop("DryRun")
    instance = call("ec2", "run-instances", "--cli-input-json", json.dumps(request))["Instances"][0]
    record = {"instance_id": instance["InstanceId"], "source": SOURCE_SHA, "auto_stop_at": stop_at}
    Path("harbinger-deployment.json").write_text(json.dumps(record, indent=2))
    print("INSTANCE_CREATED " + json.dumps(record), flush=True)
    return record


def monitor(record):
    instance_id = record["instance_id"]
    last_ip = None
    deadline = time.monotonic() + 3600
    try:
        while time.monotonic() < deadline:
            instance = aws("ec2", "describe-instances", "--instance-ids", instance_id)["Reservations"][0][
                "Instances"
            ][0]
            if instance["State"]["Name"] in ("stopped", "stopping", "terminated", "shutting-down"):
                raise RuntimeError(
                    "Server stopped before completion; inspect EC2 system log for HARBINGER_BOOTSTRAP_FAILED"
                )
            ip = instance.get("PublicIpAddress")
            if ip and ip != last_ip:
                print(f"DEMO_URL https://{ip}/console/ (building; not ready yet)", flush=True)
                last_ip = ip
            if ip:
                result = {}
                try:
                    with urllib.request.urlopen(f"https://{ip}/deployment.json", timeout=8) as response:
                        result = json.load(response)
                except (OSError, ValueError):
                    pass  # HTTPS must validate normally; never disable certificate checks.
                if result.get("commit") == SOURCE_SHA and result.get("bootstrap_completed") is True:
                    wait_https(ip, SOURCE_SHA)
                    aws("ec2", "reboot-instances", "--instance-ids", instance_id)
                    time.sleep(30)
                    wait_https(ip, SOURCE_SHA)
                    record.update(
                        url=f"https://{ip}/console/",
                        https_verified=True,
                        renewal_dry_run=result["renewal_dry_run"],
                        reboot_requested_and_health_recovered=True,
                        browser_verified=False,
                    )
                    Path("harbinger-deployment.json").write_text(json.dumps(record, indent=2))
                    print("DEPLOYMENT_READY " + json.dumps(record), flush=True)
                    return
            print("Building/checking server; native AWS credentials remain in CloudShell.", flush=True)
            time.sleep(30)
        raise TimeoutError("Bootstrap did not complete in 60 minutes")
    except BaseException:
        try:
            aws("ec2", "stop-instances", "--instance-ids", instance_id)
            print("Server stop requested after interrupted/failed deployment; disk is retained.", flush=True)
        finally:
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Create one server; automatic stop after 24 hours"
    )
    args = parser.parse_args()
    if any(
        os.environ.get(k)
        for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE")
    ):
        raise SystemExit(
            "Use a fresh native CloudShell session without manually exported keys/profile; do not paste credentials."
        )
    result = prepare(args.apply)
    if result:
        monitor(result)
