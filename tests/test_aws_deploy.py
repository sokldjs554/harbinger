"""Safety contracts for the external AWS/SSH deployment boundary."""

import base64
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "deploy/aws/ec2/deploy.py"
    assert path.exists(), "AWS deployment orchestrator is not implemented"
    spec = importlib.util.spec_from_file_location("aws_ec2_deploy", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def owned(instance_id="i-1"):
    return {
        "InstanceId": instance_id,
        "State": {"Name": "running"},
        "Tags": [{"Key": "Project", "Value": "harbinger"}, {"Key": "Name", "Value": "harbinger-demo"}],
    }


def test_refuses_duplicate_or_foreign_servers():
    deploy = module()
    with pytest.raises(ValueError):
        deploy.select_instance([owned(), owned("i-2")])
    foreign = owned()
    foreign["Tags"][0]["Value"] = "another-project"
    with pytest.raises(ValueError):
        deploy.select_instance([foreign])
    assert deploy.select_instance([]) is None
    assert deploy.select_instance([owned()])["InstanceId"] == "i-1"


def test_launch_contract_bounds_billable_resources():
    deploy = module()
    request = deploy.launch_request(
        {"ImageId": "ami-123", "RootDeviceName": "/dev/sda1"}, "subnet-123", "sg-123", "test"
    )
    assert request["MinCount"] == request["MaxCount"] == 1
    assert request["InstanceType"] == "t3.medium"
    assert request["MetadataOptions"]["HttpTokens"] == "required"
    assert request["CreditSpecification"]["CpuCredits"] == "standard"
    assert request["BlockDeviceMappings"][0]["Ebs"] == {
        "VolumeSize": 30,
        "VolumeType": "gp3",
        "Encrypted": True,
        "DeleteOnTermination": True,
    }
    for resource in ("instance", "volume"):
        tags = next(t["Tags"] for t in request["TagSpecifications"] if t["ResourceType"] == resource)
        assert {t["Key"]: t["Value"] for t in tags}["Project"] == "harbinger"
    assert "IamInstanceProfile" not in request and "KeyName" not in request


def test_host_key_comes_from_console_and_fails_closed():
    deploy = module()
    key = "AAAAC3NzaC1lZDI1NTE5AAAAIKtestkey"
    text = f"boot output\r\nssh-ed25519 {key} root@host\r\n"
    assert deploy.console_host_key(text) == f"ssh-ed25519 {key}"
    assert deploy.console_host_key(base64.b64encode(text.encode()).decode()) == f"ssh-ed25519 {key}"
    with pytest.raises(ValueError):
        deploy.console_host_key("boot has not printed an SSH host key")


def test_ssh_rule_is_removed_after_failure():
    deploy = module()
    calls = []

    def aws(*args):
        calls.append(args)
        return {}

    with pytest.raises(RuntimeError):
        with deploy.temporary_ssh(aws, "sg-123", "8.8.8.8"):
            raise RuntimeError("remote install failed")
    assert [c[1] for c in calls] == ["authorize-security-group-ingress", "revoke-security-group-ingress"]
    for call in calls:
        permission = json.loads(call[call.index("--ip-permissions") + 1])[0]
        assert permission["FromPort"] == permission["ToPort"] == 22
        assert permission["IpRanges"][0]["CidrIp"] == "8.8.8.8/32"


def test_invalid_runner_ip_cannot_open_ssh():
    deploy = module()
    with pytest.raises(ValueError):
        with deploy.temporary_ssh(lambda *args: pytest.fail("AWS must not be called"), "sg-123", "0.0.0.0/0"):
            pass


def test_remote_tools_do_not_inherit_cloud_credentials(monkeypatch):
    deploy = module()
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-stay-local")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-stay-local")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "must-stay-local")
    monkeypatch.setenv("GITHUB_TOKEN", "must-stay-local")
    env = deploy.remote_environment()
    assert "PATH" in env
    assert not any(name.startswith("AWS_") or name == "GITHUB_TOKEN" for name in env)


@pytest.mark.parametrize(
    ("created", "started", "expected"), [(True, False, True), (False, True, True), (False, False, False)]
)
def test_failed_deployment_restores_compute_state(created, started, expected):
    deploy = module()
    calls = []
    deploy.stop_failed_deployment(lambda *args: calls.append(args), "i-1", created, started)
    assert bool(calls) == expected
    if expected:
        assert calls == [("ec2", "stop-instances", "--instance-ids", "i-1")]


def test_release_remains_rollbackable_until_browser_check_finishes():
    deploy = module()

    class Remote:
        def __init__(self):
            self.commands = []

        def run(self, command):
            self.commands.append(command)

    remote = Remote()
    with pytest.raises(RuntimeError, match="browser failed"):
        with deploy.release_transaction(remote):
            raise RuntimeError("browser failed")
    assert remote.commands == ["sudo bash /opt/harbinger/pending-deployment/rollback.sh"]
    remote = Remote()
    with deploy.release_transaction(remote):
        remote.commands.append("browser passed")
    assert remote.commands == ["browser passed", "sudo rm -rf /opt/harbinger/pending-deployment"]
