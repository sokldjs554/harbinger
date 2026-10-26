"""Configure email monitoring on the already-authorized existing EC2 host only."""

import ipaddress
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

from deploy.aws.ec2 import deploy
from scripts.external_alerts import write_bundle


def running_owned_instance(instances):
    instance = deploy.select_instance(instances)
    if instance is None or instance["State"]["Name"] != "running":
        raise ValueError("One existing running owned instance is required; no creation/start allowed")
    return instance


def closed_ssh_group(groups):
    if len(groups) != 1:
        raise ValueError("One existing tagged security group required")
    group = groups[0]
    if any(
        r.get("IpProtocol") == "-1"
        or (r.get("IpProtocol") == "tcp" and r.get("FromPort", 65536) <= 22 <= r.get("ToPort", -1))
        for r in group["IpPermissions"]
    ):
        raise ValueError("Pre-existing SSH access must be reviewed first")
    return group["GroupId"]


def main():
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Reviewed main only")
    test_id = "mail-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
    out = Path(".monitoring-verification")
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hb-private-monitor-") as temporary:
        directory = Path(temporary)
        bundle = directory / "bundle"
        write_bundle(bundle, os.environ, test_id)  # Validate credentials before any AWS action.
        shutil.copyfile("deploy/monitoring/rules.yml", bundle / "config/rules.yml")
        shutil.copyfile("scripts/external_alerts.py", bundle / "external_alerts.py")
        archive = directory / "monitoring-bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(bundle, arcname=".")
        archive.chmod(0o600)
        identity = deploy.aws("sts", "get-caller-identity")
        if identity["Account"] != deploy.ACCOUNT or os.environ.get("AWS_REGION") != deploy.REGION:
            raise ValueError("AWS account/region mismatch")
        reservations = deploy.aws(
            "ec2",
            "describe-instances",
            "--filters",
            "Name=tag:Project,Values=harbinger",
            "Name=tag:Name,Values=harbinger-demo",
        )["Reservations"]
        instance = running_owned_instance([i for r in reservations for i in r["Instances"]])
        groups = deploy.aws(
            "ec2",
            "describe-security-groups",
            "--filters",
            "Name=tag:Project,Values=harbinger",
            "Name=group-name,Values=harbinger-web",
        )["SecurityGroups"]
        group_id = closed_ssh_group(groups)
        remote = deploy.Remote(instance, directory, wait_for_key=False)
        with urlopen("https://checkip.amazonaws.com/", timeout=15) as response:
            runner_ip = str(ipaddress.IPv4Address(response.read().decode().strip()))
        try:
            with deploy.temporary_ssh(deploy.aws, group_id, runner_ip):
                remote.run("mkdir -p -m 700 /home/ubuntu/harbinger-package")
                try:
                    remote.copy([archive, Path("deploy/monitoring/install_external.sh")])
                    remote.run(
                        "sudo bash /home/ubuntu/harbinger-package/install_external.sh " + test_id,
                        timeout=1000,
                    )
                finally:
                    remote.run("rm -f /home/ubuntu/harbinger-package/monitoring-bundle.tar.gz", timeout=30)
                    remote.authorize()
                    result = subprocess.run(
                        [
                            "ssh",
                            *remote.options,
                            f"ubuntu@{remote.ip}",
                            "sudo cat /opt/harbinger-monitoring/result.json",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=deploy.remote_environment(),
                    )
                    if result.returncode == 0:
                        record = json.loads(result.stdout)
                        if record.get("verification_id") == test_id:
                            (out / "result.json").write_text(json.dumps(record, indent=2) + "\n")
        finally:
            current = deploy.aws("ec2", "describe-security-groups", "--group-ids", group_id)["SecurityGroups"]
            assert closed_ssh_group(current) == group_id
            (out / "deployment.json").write_text(
                json.dumps(
                    {
                        "source_commit": os.environ["GITHUB_SHA"],
                        "verification_id": test_id,
                        "created_instance": False,
                        "ssh_closed": True,
                        "operator_receipt_confirmed": False,
                    },
                    indent=2,
                )
                + "\n"
            )
    print("Monitoring workflow finished; operator inbox receipt still requires actual confirmation.")


if __name__ == "__main__":
    main()
