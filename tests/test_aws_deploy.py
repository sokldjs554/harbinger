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
        {"ImageId": "ami-123", "RootDeviceName": "/dev/sda1", "FreeTierEligible": True},
        "subnet-123",
        "sg-123",
        "test",
    )
    assert request["MinCount"] == request["MaxCount"] == 1
    assert request["InstanceType"] == "c7i-flex.large"
    assert request["MetadataOptions"]["HttpTokens"] == "required"
    assert "CreditSpecification" not in request  # Flex types do not accept T-family CPU-credit settings.
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
    key = host_key().split()[1]
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


@pytest.mark.parametrize("eligible", [False, None])
def test_unverified_free_plan_image_cannot_be_launched(eligible):
    deploy = module()
    image = {"ImageId": "ami-123", "RootDeviceName": "/dev/sda1", "FreeTierEligible": eligible}
    with pytest.raises(ValueError, match="Free Tier"):
        deploy.launch_request(image, "subnet-123", "sg-123", "test")


def test_noneligible_instance_type_is_rejected_before_provisioning():
    deploy = module()
    with pytest.raises(ValueError, match="Free Tier"):
        deploy.validate_instance_type({"InstanceType": "c7i-flex.large", "FreeTierEligible": False})
    deploy.validate_instance_type({"InstanceType": "c7i-flex.large", "FreeTierEligible": True})


def host_key(byte=1):
    blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes([byte]) * 32
    return "ssh-ed25519 " + base64.b64encode(blob).decode()


def identity(instance_id="i-0123456789abcdef0", key=None):
    return json.dumps({"instance_id": instance_id, "host_key": key or host_key()})


def console_reader(output):
    def read(*args):
        assert args[:2] == ("ec2", "get-console-output")
        return {"InstanceId": "i-0123456789abcdef0", "Output": output}

    return read


def test_explicit_identity_can_verify_existing_host_after_console_rollover():
    deploy = module()
    assert (
        deploy.verified_host_key("i-0123456789abcdef0", identity(), console_reader("reboot log"))
        == host_key()
    )


def test_identity_cannot_be_reused_for_another_instance():
    deploy = module()
    with pytest.raises(ValueError, match="instance"):
        deploy.verified_host_key(
            "i-1123456789abcdef0", identity(), lambda *args: pytest.fail("must reject before AWS")
        )


@pytest.mark.parametrize(
    "pin",
    [
        "not json",
        "[]",
        json.dumps({"instance_id": "i-0123456789abcdef0", "host_key": host_key(), "extra": "ignored?"}),
        identity(key="ssh-ed25519 not-base64"),
        identity(key="ssh-ed25519 " + base64.b64encode(b"wrong wire structure").decode()),
        identity(key=host_key() + "\nmalicious-host " + host_key(2)),
        identity(key="ssh-rsa " + host_key().split()[1]),
        identity(
            key="ssh-ed25519 "
            + base64.b64encode(base64.b64decode(host_key().split()[1]) + b"trailing").decode()
        ),
    ],
)
def test_invalid_pin_never_falls_back_to_console(pin):
    deploy = module()
    with pytest.raises(ValueError):
        deploy.verified_host_key(
            "i-0123456789abcdef0", pin, lambda *args: pytest.fail("reject malformed pin first")
        )


def test_pin_must_agree_with_authenticated_console_key():
    deploy = module()
    with pytest.raises(ValueError, match="mismatch"):
        deploy.verified_host_key("i-0123456789abcdef0", identity(), console_reader(host_key(2)))


def test_console_identity_still_works_without_a_pin():
    deploy = module()
    assert deploy.verified_host_key("i-0123456789abcdef0", None, console_reader(host_key())) == host_key()


def test_missing_identity_fails_closed_with_actionable_input():
    deploy = module()
    with pytest.raises(deploy.HostKeyUnavailable, match="AWS_EC2_SSH_HOST_IDENTITY"):
        deploy.verified_host_key("i-0123456789abcdef0", None, console_reader("reboot log"))


def test_console_response_must_belong_to_requested_instance():
    deploy = module()
    with pytest.raises(ValueError, match="instance"):
        deploy.verified_host_key(
            "i-0123456789abcdef0", identity(), lambda *args: {"InstanceId": "i-other", "Output": host_key()}
        )


def test_remote_uses_only_the_verified_key_and_no_user_ssh_config(tmp_path, monkeypatch):
    deploy = module()
    monkeypatch.setenv("AWS_EC2_SSH_HOST_IDENTITY", identity())
    monkeypatch.setattr(deploy, "aws", console_reader("reboot log"))
    calls = []
    monkeypatch.setattr(
        deploy.time,
        "sleep",
        lambda seconds: pytest.fail("an explicit pin must not wait for missing console output"),
    )
    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs: calls.append(args[0]))
    instance = owned("i-0123456789abcdef0")
    instance["PublicIpAddress"] = "8.8.8.8"
    remote = deploy.Remote(instance, tmp_path)
    assert remote.hosts.read_text() == "8.8.8.8 " + host_key() + "\n"
    assert remote.options[:2] == ["-F", "/dev/null"]
    assert "StrictHostKeyChecking=yes" in remote.options
    assert "GlobalKnownHostsFile=/dev/null" in remote.options
    assert all(call[0] == "ssh-keygen" for call in calls)


@pytest.mark.parametrize("pin", [None, identity()])
def test_existing_host_preflight_only_reads_aws(monkeypatch, pin):
    deploy = module()
    monkeypatch.setenv("AWS_REGION", deploy.REGION)
    if pin:
        monkeypatch.setenv("AWS_EC2_SSH_HOST_IDENTITY", pin)
    else:
        monkeypatch.delenv("AWS_EC2_SSH_HOST_IDENTITY", raising=False)
    calls = []

    def read(*args):
        calls.append(args[:2])
        if args[:2] == ("sts", "get-caller-identity"):
            return {"Account": deploy.ACCOUNT}
        if args[:2] == ("ec2", "describe-instances"):
            return {"Reservations": [{"Instances": [owned("i-0123456789abcdef0")]}]}
        if args[:2] == ("ec2", "get-console-output"):
            return {"InstanceId": "i-0123456789abcdef0", "Output": "key no longer retained"}
        pytest.fail("Preflight must not mutate AWS")

    monkeypatch.setattr(deploy, "aws", read)
    if pin:
        deploy.preflight_host_identity()
    else:
        with pytest.raises(deploy.HostKeyUnavailable):
            deploy.preflight_host_identity()
    assert set(calls) == {
        ("sts", "get-caller-identity"),
        ("ec2", "describe-instances"),
        ("ec2", "get-console-output"),
    }


def test_conflicting_console_histories_fail_without_a_pin():
    deploy = module()

    def read(*args):
        return {"InstanceId": "i-0123456789abcdef0", "Output": host_key(1 if "--latest" in args else 2)}

    with pytest.raises(ValueError, match="conflicting"):
        deploy.verified_host_key("i-0123456789abcdef0", None, read)


def test_duplicate_identity_json_fields_are_rejected():
    deploy = module()
    pin = identity()[:-1] + ', "instance_id": "i-0123456789abcdef0"}'
    with pytest.raises(ValueError, match="Duplicate"):
        deploy.verified_host_key(
            "i-0123456789abcdef0", pin, lambda *args: pytest.fail("reject duplicate fields first")
        )
