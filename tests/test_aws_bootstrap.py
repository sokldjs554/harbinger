"""Account migration must never provision compute from the CloudShell setup."""

import importlib.util
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "deploy/aws/ec2/bootstrap_account.py"
    spec = importlib.util.spec_from_file_location("bootstrap", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def fake(m, calls, *, account=None, role=None, groups=None, provider=None):
    def call(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("sts", "get-caller-identity"):
            return {"Account": account or m.ACCOUNT}
        if args[:2] == ("ec2", "describe-vpcs"):
            return {"Vpcs": [{"VpcId": m.VPC, "State": "available", "IsDefault": True}]}
        if args[:2] == ("iam", "get-open-id-connect-provider"):
            return provider
        if args[:2] == ("iam", "get-role"):
            return role
        if args[:2] == ("ec2", "describe-security-groups"):
            return {"SecurityGroups": groups or []}
        if args[:2] == ("ec2", "create-security-group"):
            return {"GroupId": "sg-test"}
        if args[:2] in {
            ("iam", "create-open-id-connect-provider"),
            ("iam", "create-role"),
            ("iam", "put-role-policy"),
        }:
            return {}
        pytest.fail(f"Unexpected AWS action: {args[:2]}")

    return call


def test_default_plan_is_read_only():
    m = module()
    calls = []
    result = m.prepare(call=fake(m, calls))
    assert result["applied"] is False
    assert all(args[1].startswith(("get-", "describe-")) for args in calls)


def test_wrong_account_stops_before_any_mutation():
    m = module()
    calls = []
    with pytest.raises(ValueError, match="Wrong AWS account"):
        m.prepare(True, fake(m, calls, account="577331852023"))
    assert len(calls) == 1


def test_apply_only_creates_identity_and_empty_group():
    m = module()
    calls = []
    result = m.prepare(True, fake(m, calls))
    assert result["compute_created"] is False
    assert result["security_group"] == "sg-test"
    writes = [args[:2] for args in calls if not args[1].startswith(("get-", "describe-"))]
    assert writes == [
        ("iam", "create-open-id-connect-provider"),
        ("iam", "create-role"),
        ("iam", "put-role-policy"),
        ("ec2", "create-security-group"),
    ]


def test_foreign_role_is_not_overwritten():
    m = module()
    calls = []
    with pytest.raises(ValueError, match="not owned"):
        m.prepare(True, fake(m, calls, role={"Role": {"Tags": []}}))
    assert all(args[1].startswith(("get-", "describe-")) for args in calls)


def test_foreign_group_stops_before_iam_creation():
    m = module()
    calls = []
    with pytest.raises(ValueError, match="not owned"):
        m.prepare(True, fake(m, calls, groups=[{"VpcId": m.VPC, "Tags": []}]))
    assert all(args[1].startswith(("get-", "describe-")) for args in calls)


def test_trust_is_exact_repo_and_main_without_wildcards():
    m = module()
    statement = m.trust_policy()["Statement"][0]
    conditions = statement["Condition"]["StringEquals"]
    subjects = conditions[f"{m.PROVIDER}:sub"]
    assert conditions[f"{m.PROVIDER}:aud"] == "sts.amazonaws.com"
    assert all(s.endswith(":ref:refs/heads/main") and "*" not in s for s in subjects)
    assert subjects == [
        "repo:sokldjs554/harbinger:ref:refs/heads/main",
        "repo:sokldjs554@97650034/harbinger@1407369165:ref:refs/heads/main",
    ]


def test_owned_setup_is_reusable_without_duplicate_resources():
    m = module()
    calls = []
    role = {
        "Role": {"Tags": m.TAGS, "AssumeRolePolicyDocument": m.trust_policy(), "MaxSessionDuration": 7200}
    }
    provider = {"Url": m.PROVIDER, "ClientIDList": ["sts.amazonaws.com"]}
    group = {"VpcId": m.VPC, "Tags": m.TAGS, "GroupId": "sg-owned"}
    result = m.prepare(True, fake(m, calls, role=role, provider=provider, groups=[group]))
    assert result["security_group"] == "sg-owned"
    assert not any(args[1].startswith("create-") for args in calls)


def test_workflow_cannot_auto_deploy_or_use_old_keys():
    import yaml

    path = Path(__file__).resolve().parents[1] / ".github/workflows/aws-ec2.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["allow_create"]["default"] == "false"
    assert "secrets.AWS_ACCESS_KEY_ID" not in path.read_text()
    assert "secrets.AWS_EC2_SSH_HOST_IDENTITY" not in path.read_text()
    auth = next(
        s
        for s in workflow["jobs"]["deploy"]["steps"]
        if s.get("name") == "Assume the new account deployment role"
    )
    assert auth["with"]["allowed-account-ids"] == "971966100387"
