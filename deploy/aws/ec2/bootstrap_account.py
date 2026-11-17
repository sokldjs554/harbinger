"""Prepare OIDC, a scoped deploy role and an empty security group; never launch EC2."""

import argparse
import json
import subprocess
from pathlib import Path

ACCOUNT = "971966100387"
REGION = "ap-southeast-2"
VPC = "vpc-08b683218cb924bfd"
ROLE = "harbinger-github-deploy"
PROVIDER = "token.actions.githubusercontent.com"
TAGS = [{"Key": "Project", "Value": "harbinger"}, {"Key": "Setup", "Value": "20261117"}]


def aws(*args, missing=False):
    result = subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "json", "--no-cli-pager"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        if missing and "(NoSuchEntity)" in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else {}


def trust_policy():
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": f"arn:aws:iam::{ACCOUNT}:oidc-provider/{PROVIDER}"},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"{PROVIDER}:aud": "sts.amazonaws.com",
                        f"{PROVIDER}:sub": [
                            "repo:sokldjs554/harbinger:ref:refs/heads/main",
                            "repo:sokldjs554@97650034/harbinger@1407369165:ref:refs/heads/main",
                        ],
                    }
                },
            }
        ],
    }


def prepare(apply=False, call=aws):
    if call("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise ValueError("Wrong AWS account; nothing changed")
    vpcs = call("ec2", "describe-vpcs", "--vpc-ids", VPC)["Vpcs"]
    if len(vpcs) != 1 or vpcs[0].get("State") != "available" or not vpcs[0].get("IsDefault"):
        raise ValueError("Reviewed default VPC is unavailable")
    provider_arn = f"arn:aws:iam::{ACCOUNT}:oidc-provider/{PROVIDER}"
    provider = call(
        "iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", provider_arn, missing=True
    )
    if provider and (
        provider.get("Url", "").removeprefix("https://") != PROVIDER
        or "sts.amazonaws.com" not in provider.get("ClientIDList", [])
    ):
        raise ValueError("Existing OIDC provider differs; refusing to change it")
    role_response = call("iam", "get-role", "--role-name", ROLE, missing=True)
    trust = trust_policy()
    if role_response:
        role = role_response["Role"]
        tags = {t["Key"]: t["Value"] for t in role.get("Tags", [])}
        if tags.get("Project") != "harbinger" or tags.get("Setup") != "20261117":
            raise ValueError("Existing role is not owned by this setup")
        if role.get("AssumeRolePolicyDocument") != trust or role.get("MaxSessionDuration") != 7200:
            raise ValueError("Existing role differs; refusing to expand trust")
    groups = call(
        "ec2",
        "describe-security-groups",
        "--filters",
        f"Name=vpc-id,Values={VPC}",
        "Name=group-name,Values=harbinger-web",
    )["SecurityGroups"]
    if len(groups) > 1:
        raise ValueError("Multiple deployment groups")
    if groups:
        tags = {t["Key"]: t["Value"] for t in groups[0].get("Tags", [])}
        if tags.get("Project") != "harbinger" or groups[0]["VpcId"] != VPC:
            raise ValueError("Existing security group is not owned by this setup")
    policy = json.loads((Path(__file__).resolve().parents[1] / "ec2-deploy-policy.json").read_text())
    policy_text = json.dumps(policy)
    if "577331852023" in policy_text or ACCOUNT not in policy_text:
        raise ValueError("Deployment policy points to the wrong account")
    summary = {
        "account": ACCOUNT,
        "region": REGION,
        "vpc": VPC,
        "role_arn": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}",
        "compute_created": False,
        "applied": apply,
    }
    if not apply:
        return summary
    # All ownership checks above run before the first mutation.
    if not provider:
        call(
            "iam",
            "create-open-id-connect-provider",
            "--url",
            f"https://{PROVIDER}",
            "--client-id-list",
            "sts.amazonaws.com",
            "--tags",
            json.dumps(TAGS),
        )
    if not role_response:
        call(
            "iam",
            "create-role",
            "--role-name",
            ROLE,
            "--assume-role-policy-document",
            json.dumps(trust),
            "--max-session-duration",
            "7200",
            "--tags",
            json.dumps(TAGS),
        )
    call(
        "iam",
        "put-role-policy",
        "--role-name",
        ROLE,
        "--policy-name",
        "HarbingerDeployment",
        "--policy-document",
        policy_text,
    )
    if not groups:
        group = call(
            "ec2",
            "create-security-group",
            "--group-name",
            "harbinger-web",
            "--description",
            "Harbinger HTTPS; temporary runner-only SSH during deployment",
            "--vpc-id",
            VPC,
            "--tag-specifications",
            json.dumps([{"ResourceType": "security-group", "Tags": TAGS}]),
        )
        summary["security_group"] = group["GroupId"]
    else:
        summary["security_group"] = groups[0]["GroupId"]
    summary["message"] = "SETUP_OK; no EC2 instance or disk created"
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create IAM connection and empty security group")
    args = parser.parse_args()
    print(json.dumps(prepare(args.apply), indent=2))
