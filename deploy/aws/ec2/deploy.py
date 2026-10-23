"""Deploy one tagged EC2 host through AWS CLI and short-lived SSH access."""

from __future__ import annotations

import base64
import contextlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REGION = "ap-southeast-2"
ACCOUNT = "577331852023"


def aws(*args):
    result = subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else {}


def select_instance(instances):
    active = []
    for instance in instances:
        if instance["State"]["Name"] in {"terminated", "shutting-down"}:
            continue
        tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
        if tags.get("Project") != "harbinger" or tags.get("Name") != "harbinger-demo":
            raise ValueError("Refusing to change an instance outside this deployment")
        active.append(instance)
    if len(active) > 1:
        raise ValueError("Multiple harbinger instances found; no instance was changed")
    return active[0] if active else None


def launch_request(image, subnet_id, group_id, token):
    tags = [{"Key": "Project", "Value": "harbinger"}, {"Key": "Name", "Value": "harbinger-demo"}]
    return {
        "ImageId": image["ImageId"],
        "InstanceType": "t3.medium",
        "MinCount": 1,
        "MaxCount": 1,
        "ClientToken": token,
        "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"},
        "CreditSpecification": {"CpuCredits": "standard"},
        "NetworkInterfaces": [
            {"DeviceIndex": 0, "SubnetId": subnet_id, "AssociatePublicIpAddress": True, "Groups": [group_id]}
        ],
        "BlockDeviceMappings": [
            {
                "DeviceName": image["RootDeviceName"],
                "Ebs": {
                    "VolumeSize": 30,
                    "VolumeType": "gp3",
                    "Encrypted": True,
                    "DeleteOnTermination": True,
                },
            }
        ],
        "TagSpecifications": [{"ResourceType": kind, "Tags": tags} for kind in ("instance", "volume")],
    }


def console_host_key(output):
    candidates = [output]
    try:
        candidates.append(base64.b64decode(output, validate=True).decode())
    except (ValueError, UnicodeDecodeError):
        pass
    for text in candidates:
        match = re.search(r"(?m)^ssh-ed25519 ([A-Za-z0-9+/=]+)(?:[ \t].*)?$", text.replace("\r", ""))
        if match:
            return "ssh-ed25519 " + match[1]
    raise ValueError("No verified SSH host key in EC2 console output")


def remote_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR"}
    }


@contextlib.contextmanager
def temporary_ssh(call_aws, group_id, runner_ip):
    address = ipaddress.IPv4Address(runner_ip)
    if not address.is_global:
        raise ValueError("Runner IP must be one global IPv4 address")
    permission = json.dumps(
        [{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": f"{address}/32"}]}]
    )
    added = False
    try:
        call_aws(
            "ec2", "authorize-security-group-ingress", "--group-id", group_id, "--ip-permissions", permission
        )
        added = True
        yield
    finally:
        if added:
            call_aws(
                "ec2", "revoke-security-group-ingress", "--group-id", group_id, "--ip-permissions", permission
            )


def stop_failed_deployment(call_aws, instance_id, created, started):
    if instance_id and (created or started):
        print(f"Deployment failed; restoring stopped state for {instance_id}.")
        call_aws("ec2", "stop-instances", "--instance-ids", instance_id)


@contextlib.contextmanager
def release_transaction(remote):
    try:
        yield
    except BaseException:
        try:
            remote.run("sudo bash /opt/harbinger/pending-deployment/rollback.sh")
        except Exception as error:
            print(f"Release rollback also failed: {error}")
        raise
    else:
        remote.run("sudo rm -rf /opt/harbinger/pending-deployment")


def describe(instance_id):
    return aws("ec2", "describe-instances", "--instance-ids", instance_id)["Reservations"][0]["Instances"][0]


def wait_running(instance_id):
    for _ in range(90):
        instance = describe(instance_id)
        if instance["State"]["Name"] == "running" and instance.get("PublicIpAddress"):
            return instance
        if instance["State"]["Name"] in {"terminated", "shutting-down"}:
            raise RuntimeError("Instance terminated while waiting")
        time.sleep(10)
    raise TimeoutError("Instance did not become running within 15 minutes")


def wait_https(ip, sha):
    for _ in range(90):
        try:
            with urllib.request.urlopen(f"https://{ip}/health", timeout=8) as response:
                assert response.status == 200
            with urllib.request.urlopen(f"https://{ip}/deployment.json", timeout=8) as response:
                assert json.load(response)["commit"] == sha
            with urllib.request.urlopen(f"https://{ip}/v1/workbench/info", timeout=8) as response:
                assert json.load(response)["mode"] == "live"
            return
        except (OSError, urllib.error.URLError, AssertionError, ValueError):
            time.sleep(5)
    raise TimeoutError("Trusted HTTPS health, version and live API did not recover")


class Remote:
    def __init__(self, instance, directory):
        self.instance = instance
        self.ip = str(ipaddress.IPv4Address(instance["PublicIpAddress"]))
        self.key = directory / "key"
        self.hosts = directory / "known_hosts"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-f", str(self.key), "-N", ""], check=True)
        for _ in range(60):
            console = aws("ec2", "get-console-output", "--instance-id", instance["InstanceId"], "--latest")
            try:
                host_key = console_host_key(console.get("Output", ""))
                self.hosts.write_text(f"{self.ip} {host_key}\n")
                break
            except ValueError:
                time.sleep(10)
        else:
            raise RuntimeError("SSH host key unavailable; refusing insecure host-key bypass")
        self.options = [
            "-i",
            str(self.key),
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"UserKnownHostsFile={self.hosts}",
            "-o",
            "HostKeyAlgorithms=ssh-ed25519",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=15",
        ]

    def authorize(self):
        result = aws(
            "ec2-instance-connect",
            "send-ssh-public-key",
            "--instance-id",
            self.instance["InstanceId"],
            "--availability-zone",
            self.instance["Placement"]["AvailabilityZone"],
            "--instance-os-user",
            "ubuntu",
            "--ssh-public-key",
            self.key.with_suffix(".pub").read_text().strip(),
        )
        if not result.get("Success"):
            raise RuntimeError("EC2 Instance Connect did not authorize temporary SSH key")

    def run(self, command, timeout=1200):
        self.authorize()
        subprocess.run(
            ["ssh", *self.options, f"ubuntu@{self.ip}", command],
            check=True,
            timeout=timeout,
            env=remote_environment(),
        )

    def copy(self, paths):
        self.authorize()
        subprocess.run(
            [
                "scp",
                *self.options,
                *[str(path) for path in paths],
                f"ubuntu@{self.ip}:/home/ubuntu/harbinger-package/",
            ],
            check=True,
            timeout=1200,
            env=remote_environment(),
        )


def main():
    sha = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected immutable Git commit SHA")
    identity = aws("sts", "get-caller-identity")
    if identity["Account"] != ACCOUNT or os.environ.get("AWS_REGION") != REGION:
        raise ValueError("AWS account or project region does not match reviewed policy")
    package = Path(".aws-package")
    required = [
        package / name
        for name in ("image.tar.gz", "runtime.tar.gz", "install.sh", "compose.yml", "deployment.json")
    ]
    if not all(path.is_file() for path in required):
        raise ValueError("Build image and train runtime bundle before provisioning")
    reservations = aws(
        "ec2",
        "describe-instances",
        "--filters",
        "Name=tag:Project,Values=harbinger",
        "Name=tag:Name,Values=harbinger-demo",
    )["Reservations"]
    instance = select_instance([i for r in reservations for i in r["Instances"]])
    groups = aws(
        "ec2",
        "describe-security-groups",
        "--filters",
        "Name=tag:Project,Values=harbinger",
        "Name=group-name,Values=harbinger-web",
    )["SecurityGroups"]
    if len(groups) != 1:
        raise ValueError("Run AWS connection check to prepare one tagged security group first")
    group = groups[0]
    group_id = group["GroupId"]
    if any(
        rule.get("IpProtocol") == "-1"
        or (rule.get("IpProtocol") == "tcp" and rule.get("FromPort", 65536) <= 22 <= rule.get("ToPort", -1))
        for rule in group["IpPermissions"]
    ):
        raise ValueError("Unexpected pre-existing SSH rule; no broad SSH access will be reused")
    created = instance is None
    instance_id = None
    started = False
    try:
        if created:
            subnets = aws("ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={group['VpcId']}")[
                "Subnets"
            ]
            subnets = sorted(
                [s for s in subnets if s.get("DefaultForAz") and s["State"] == "available"],
                key=lambda s: s["SubnetId"],
            )
            if not subnets:
                raise ValueError("No available default subnet")
            images = aws(
                "ec2",
                "describe-images",
                "--owners",
                "099720109477",
                "--filters",
                "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*",
                "Name=state,Values=available",
                "Name=architecture,Values=x86_64",
            )["Images"]
            image = max(images, key=lambda i: i["CreationDate"])
            token = f"hb-{sha[:20]}-{os.environ['GITHUB_RUN_ID']}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
            request = launch_request(image, subnets[0]["SubnetId"], group_id, token)
            request["DryRun"] = True
            try:
                aws("ec2", "run-instances", "--cli-input-json", json.dumps(request))
            except RuntimeError as error:
                if "(DryRunOperation)" not in str(error):
                    raise
            else:
                raise RuntimeError("AWS did not return the expected dry-run result")
            request.pop("DryRun")
            user_data = "#!/bin/bash\nset -eu\nexport DEBIAN_FRONTEND=noninteractive\napt-get update\napt-get install -y ec2-instance-connect\n"
            request["UserData"] = base64.b64encode(user_data.encode()).decode()
            instance = aws("ec2", "run-instances", "--cli-input-json", json.dumps(request))["Instances"][0]
        instance_id = instance["InstanceId"]
        if instance["State"]["Name"] == "stopping":
            aws("ec2", "wait", "instance-stopped", "--instance-ids", instance_id)
            instance = describe(instance_id)
        if instance["State"]["Name"] == "stopped":
            started = True
            aws("ec2", "start-instances", "--instance-ids", instance_id)
        instance = wait_running(instance_id)
        if {g["GroupId"] for g in instance["SecurityGroups"]} != {group_id}:
            raise ValueError("Existing instance security group does not match this deployment")
        for port in (80, 443):
            permission = json.dumps(
                [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": port,
                        "ToPort": port,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    }
                ]
            )
            try:
                aws(
                    "ec2",
                    "authorize-security-group-ingress",
                    "--group-id",
                    group_id,
                    "--ip-permissions",
                    permission,
                )
            except RuntimeError as error:
                if "InvalidPermission.Duplicate" not in str(error):
                    raise
        with urllib.request.urlopen("https://checkip.amazonaws.com/", timeout=15) as response:
            runner_ip = response.read().decode().strip()
        with temporary_ssh(aws, group_id, runner_ip), tempfile.TemporaryDirectory() as temp:
            remote = Remote(instance, Path(temp))
            # The cloud image may start SSH before package initialization has finished.
            for attempt in range(30):
                try:
                    remote.run("sudo cloud-init status --wait", timeout=900)
                    break
                except subprocess.CalledProcessError:
                    if attempt == 29:
                        raise
                    time.sleep(10)
            remote.run("mkdir -p /home/ubuntu/harbinger-package")
            remote.copy(required)
            with release_transaction(remote):
                remote.run(f"sudo bash /home/ubuntu/harbinger-package/install.sh {sha} {remote.ip}")
                wait_https(remote.ip, sha)
                remote.run(
                    "sudo /opt/harbinger/certbot/bin/certbot renew --dry-run --run-deploy-hooks --deploy-hook /usr/local/sbin/harbinger-reload-nginx",
                    timeout=600,
                )
                remote.run(
                    "sudo systemctl is-active docker harbinger harbinger-cert-renew.timer && sudo docker inspect -f '{{.Config.User}}' harbinger-api"
                )
                aws("ec2", "reboot-instances", "--instance-ids", instance_id)
                time.sleep(30)
                wait_https(remote.ip, sha)
                subprocess.run(
                    [
                        sys.executable,
                        "scripts/check_browser.py",
                        "--url",
                        f"https://{remote.ip}/console/",
                        "--out",
                        str(package / "browser"),
                        "--record",
                    ],
                    check=True,
                    timeout=900,
                    env=remote_environment(),
                )
            result = {
                "commit": sha,
                "region": REGION,
                "instance_id": instance_id,
                "created": created,
                "started_from_stopped": started,
                "browser_verified": True,
                "ip": remote.ip,
                "url": f"https://{remote.ip}/console/",
                "reboot_verified": True,
                "renewal_dry_run": True,
                "data": "synthetic; full scale=1 months=36 seed=20260101",
            }
        current = aws("ec2", "describe-security-groups", "--group-ids", group_id)["SecurityGroups"][0]
        assert not any(
            rule.get("IpProtocol") == "-1"
            or (
                rule.get("IpProtocol") == "tcp"
                and rule.get("FromPort", 65536) <= 22 <= rule.get("ToPort", -1)
            )
            for rule in current["IpPermissions"]
        )
        result["ssh_closed"] = True
        (package / "deployment-result.json").write_text(json.dumps(result, indent=2) + "\n")
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"url={result['url']}\n")
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(
                f"### AWS live analysis demo\n{result['url']}\n\n```json\n{json.dumps(result, indent=2)}\n```\n"
            )
        print(json.dumps(result, indent=2))
    except BaseException:
        try:
            stop_failed_deployment(aws, instance_id, created, started)
        except Exception as error:
            print(f"Instance stop cleanup also failed: {error}")
        raise


if __name__ == "__main__":
    main()
