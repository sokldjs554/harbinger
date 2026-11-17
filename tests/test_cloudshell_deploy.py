"""CloudShell deployment must stay bounded without exporting session credentials."""

import base64
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def mod(monkeypatch):
    folder = Path(__file__).resolve().parents[1] / "deploy/aws/ec2"
    monkeypatch.syspath_prepend(str(folder))
    spec = importlib.util.spec_from_file_location("cloudshell_deploy", folder / "cloudshell_deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake(m, calls, account=None, instances=None, deny=False):
    def call(*args):
        calls.append(args)
        key = args[:2]
        if key == ("sts", "get-caller-identity"):
            return {"Account": account or m.ACCOUNT}
        if key == ("ec2", "describe-vpcs"):
            return {"Vpcs": [{"State": "available", "IsDefault": True}]}
        if key == ("ec2", "describe-instances"):
            return {"Reservations": [{"Instances": instances or []}]}
        if key == ("ec2", "describe-security-groups"):
            if "--group-ids" in args:
                return {"SecurityGroups": [{"GroupId": "sg-test", "IpPermissions": []}]}
            return {"SecurityGroups": []}
        if key == ("ec2", "describe-instance-types"):
            return {"InstanceTypes": [{"InstanceType": m.INSTANCE_TYPE, "FreeTierEligible": True}]}
        if key == ("ec2", "describe-subnets"):
            return {"Subnets": [{"SubnetId": "subnet-test", "DefaultForAz": True, "State": "available"}]}
        if key == ("ec2", "describe-images"):
            return {
                "Images": [
                    {
                        "ImageId": "ami-test",
                        "RootDeviceName": "/dev/sda1",
                        "FreeTierEligible": True,
                        "CreationDate": "2026-11-01",
                    }
                ]
            }
        if key == ("ec2", "create-security-group"):
            return {"GroupId": "sg-test"}
        if key == ("ec2", "authorize-security-group-ingress"):
            return {}
        if key == ("ec2", "run-instances"):
            request = json.loads(args[-1])
            if request.get("DryRun"):
                raise RuntimeError("(UnauthorizedOperation)" if deny else "(DryRunOperation)")
            return {"Instances": [{"InstanceId": "i-test"}]}
        pytest.fail(f"Unexpected API call {key}")

    return call


def test_wrong_account_never_writes(mod):
    calls = []
    with pytest.raises(ValueError, match="Wrong AWS account"):
        mod.prepare(True, fake(mod, calls, account="000000000000"), lambda: None)
    assert len(calls) == 1


def test_existing_instance_never_creates_duplicate(mod):
    calls = []
    with pytest.raises(ValueError, match="already exists"):
        mod.prepare(
            True,
            fake(mod, calls, instances=[{"InstanceId": "i-owned", "State": {"Name": "running"}}]),
            lambda: None,
        )
    assert all(c[1].startswith(("get-", "describe-")) for c in calls)


def test_missing_ci_stops_before_writes(mod):
    calls = []

    def fail():
        raise ValueError("CI failed")

    with pytest.raises(ValueError, match="CI failed"):
        mod.prepare(True, fake(mod, calls), fail)
    assert all(c[1].startswith(("get-", "describe-")) for c in calls)


def test_plan_is_read_only(mod):
    calls = []
    assert mod.prepare(call=fake(mod, calls), ci_check=lambda: None) is None
    assert all(c[1].startswith(("get-", "describe-")) for c in calls)


def test_apply_has_one_bounded_launch_no_iam_no_ssh(mod, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    result = mod.prepare(True, fake(mod, calls), lambda: None)
    assert result["instance_id"] == "i-test"
    launches = [json.loads(c[-1]) for c in calls if c[:2] == ("ec2", "run-instances")]
    assert len(launches) == 2 and launches[0]["DryRun"] is True
    actual = launches[1]
    assert "DryRun" not in actual and actual["MinCount"] == actual["MaxCount"] == 1
    assert actual["InstanceInitiatedShutdownBehavior"] == "stop"
    assert actual["MetadataOptions"]["HttpTokens"] == "required"
    assert "IamInstanceProfile" not in actual
    assert not any(c[0] == "iam" for c in calls)
    rules = [json.loads(c[-1])[0] for c in calls if c[:2] == ("ec2", "authorize-security-group-ingress")]
    assert {r["FromPort"] for r in rules} == {80, 443}


def test_dry_run_denial_does_not_launch_or_open_ports(mod):
    calls = []
    with pytest.raises(RuntimeError, match="UnauthorizedOperation"):
        mod.prepare(True, fake(mod, calls, deny=True), lambda: None)
    assert not any(c[1] == "authorize-security-group-ingress" for c in calls)
    assert all(json.loads(c[-1]).get("DryRun") for c in calls if c[1] == "run-instances")


def test_rejects_existing_ssh_and_all_protocol_rules(mod):
    for rule in ({"IpProtocol": "-1"}, {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22}):
        with pytest.raises(ValueError, match="Unexpected inbound"):
            mod.check_group({"IpPermissions": [rule]})


def test_rendered_shell_is_valid_bounded_and_secret_free(mod):
    script = base64.b64decode(mod.user_data("2026-11-19 00:00:00 UTC")).decode()
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)
    assert "@@" not in script and len(script.encode()) < 16384
    assert "55m bash" in script and "Persistent=true" in script
    assert "2026-11-19 00:00:00 UTC" in script
    for forbidden in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "export-credentials",
    ):
        assert forbidden not in script


def test_monitor_error_requests_stop(mod, monkeypatch):
    calls = []

    def call(*args):
        calls.append(args)
        if args[1] == "describe-instances":
            raise RuntimeError("API unavailable")
        return {}

    monkeypatch.setattr(mod, "aws", call)
    with pytest.raises(RuntimeError, match="API unavailable"):
        mod.monitor({"instance_id": "i-owned"})
    assert calls[-1] == ("ec2", "stop-instances", "--instance-ids", "i-owned")
