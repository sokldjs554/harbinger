"""External alert configuration and receipt evidence safety contracts."""

import importlib.util
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/external_alerts.py"
    assert path.exists(), "external notification configuration is not implemented"
    spec = importlib.util.spec_from_file_location("external_alerts", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def settings():
    return {
        "HARBINGER_SMTP_HOST": "smtp.example.test",
        "HARBINGER_SMTP_PORT": "465",
        "HARBINGER_SMTP_USERNAME": "sender@example.test",
        "HARBINGER_SMTP_PASSWORD": "test-only-password-do-not-send",
        "HARBINGER_SMTP_FROM": "sender@example.test",
        "HARBINGER_ALERT_TO": "owner@example.test",
    }


def test_bundle_keeps_password_out_of_yaml_and_uses_tls_resolved_email(tmp_path):
    module().write_bundle(tmp_path, settings(), "check-123")
    config = yaml.safe_load((tmp_path / "config/alertmanager.yml").read_text())
    assert config["global"]["smtp_require_tls"] is True
    assert config["global"]["smtp_force_implicit_tls"] is True
    assert config["global"]["smtp_smarthost"].endswith(":465")
    assert config["global"]["smtp_auth_password_file"] == "/etc/hbmonitor/smtp-password"
    for receiver in config["receivers"]:
        assert receiver["email_configs"][0]["send_resolved"] is True
        assert receiver["email_configs"][0]["to"] == "owner@example.test"
    assert settings()["HARBINGER_SMTP_PASSWORD"] not in json.dumps(config)
    password = tmp_path / "config/smtp-password"
    assert password.read_text() == settings()["HARBINGER_SMTP_PASSWORD"]
    assert password.stat().st_mode & 0o777 == 0o600
    assert not yaml.safe_load((tmp_path / "config/prometheus-normal.yml").read_text())["rule_files"][
        -1
    ].endswith("test-rules.yml")


@pytest.mark.parametrize(
    "field,value",
    [
        ("HARBINGER_ALERT_TO", "first@example.test,second@example.test"),
        ("HARBINGER_SMTP_FROM", "a@example.test\nBcc:other@example.test"),
        ("HARBINGER_SMTP_HOST", "smtp.example.test/path"),
        ("HARBINGER_SMTP_PORT", "25"),
        ("HARBINGER_SMTP_PASSWORD", ""),
    ],
)
def test_invalid_mail_settings_fail_without_echoing_values(tmp_path, field, value):
    env = settings()
    env[field] = value
    with pytest.raises(ValueError) as error:
        module().write_bundle(tmp_path, env, "check-123")
    if value:
        assert value not in str(error.value)
    assert not (tmp_path / "config").exists()


def test_controlled_probe_is_separate_from_application_and_has_fixed_budget(tmp_path):
    module().write_bundle(tmp_path, settings(), "check-123")
    config = yaml.safe_load((tmp_path / "config/prometheus-test.yml").read_text())
    jobs = {j["job_name"]: j for j in config["scrape_configs"]}
    assert jobs["harbinger"]["static_configs"][0]["targets"] == ["127.0.0.1:8000"]
    assert jobs["harbinger-controlled-probe"]["static_configs"][0]["targets"] == ["127.0.0.1:19101"]
    rule = yaml.safe_load((tmp_path / "config/test-rules.yml").read_text())["groups"][0]["rules"][0]
    assert rule["expr"] == 'up{job="harbinger-controlled-probe"} == 0'
    assert rule["for"] == "30s"
    assert rule["labels"]["verification_id"] == "check-123"
    compose = yaml.safe_load((tmp_path / "compose.yml").read_text())
    assert set(compose["services"]) == {"prometheus", "alertmanager"}
    for service in compose["services"].values():
        assert service["mem_limit"] and service["cpus"] <= 0.25
        assert service["read_only"] and "127.0.0.1:" in " ".join(service["command"])


def test_success_log_parser_excludes_other_receivers_and_does_not_copy_secrets():
    rows = [
        {
            "ts": "2026-10-27T01:00:00Z",
            "msg": "Notify success",
            "receiver": "verification",
            "integration": "email[0]",
            "extra": "private@example.test",
        },
        {
            "ts": "2026-10-27T01:00:01Z",
            "msg": "Notify attempt failed",
            "receiver": "verification",
            "integration": "email[0]",
        },
        {
            "ts": "2026-10-27T01:00:02Z",
            "msg": "Notify success",
            "receiver": "operator",
            "integration": "email[0]",
        },
    ]
    result = module().email_successes("\n".join(json.dumps(r) for r in rows))
    assert result == [{"at": "2026-10-27T01:00:00Z", "receiver": "verification", "integration": "email[0]"}]
    assert "private" not in json.dumps(result)


def test_invalid_verification_id_is_rejected_before_file_write(tmp_path):
    with pytest.raises(ValueError):
        module().write_bundle(tmp_path, settings(), "../outside")
    assert not list(tmp_path.iterdir())


def test_scraper_container_cannot_read_email_credentials(tmp_path):
    module().write_bundle(tmp_path, settings(), "check-123")
    services = yaml.safe_load((tmp_path / "compose.yml").read_text())["services"]
    prom = " ".join(services["prometheus"]["volumes"])
    assert "./config:/" not in prom
    assert "smtp-password" not in prom and "alertmanager.yml" not in prom
    assert any("smtp-password" in volume for volume in services["alertmanager"]["volumes"])


def test_monitor_deployment_cannot_create_or_start_an_instance():
    from scripts.deploy_external_alerts import running_owned_instance

    with pytest.raises(ValueError):
        running_owned_instance([])
    stopped = {
        "InstanceId": "i-test",
        "State": {"Name": "stopped"},
        "Tags": [
            {"Key": "Project", "Value": "harbinger"},
            {"Key": "Name", "Value": "harbinger-demo"},
        ],
    }
    with pytest.raises(ValueError):
        running_owned_instance([stopped])


def test_existing_broad_ssh_permission_is_rejected():
    from scripts.deploy_external_alerts import closed_ssh_group

    with pytest.raises(ValueError):
        closed_ssh_group([{"GroupId": "sg-test", "IpPermissions": [{"IpProtocol": "-1"}]}])
    assert closed_ssh_group([{"GroupId": "sg-test", "IpPermissions": []}]) == "sg-test"


@pytest.mark.parametrize("has_previous", [False, True])
def test_failed_docker_rollback_still_deletes_new_credentials(tmp_path, has_previous):
    script = (Path(__file__).resolve().parents[1] / "deploy/monitoring/install_external.sh").read_text()
    handler = script[script.index("finish() {") : script.index("trap finish EXIT")]
    release = tmp_path / "new"
    (release / "config").mkdir(parents=True)
    credentials = [release / "config" / name for name in ("smtp-password", "alertmanager.yml")]
    for path in credentials:
        path.write_text("test fixture")
    (release / "compose.yml").touch()
    previous = tmp_path / "old"
    previous.mkdir()
    (previous / "compose.yml").touch()
    bundle = tmp_path / "bundle"
    bundle.touch()
    binary = tmp_path / "docker"
    binary.write_text("#!/bin/sh\nexit 23\n")
    binary.chmod(0o755)
    setup = "\n".join(
        f"{key}={shlex.quote(str(value))}"
        for key, value in {
            "bundle": bundle,
            "release": release,
            "previous": previous if has_previous else "",
            "complete": 0,
        }.items()
    )
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + setup + "\n" + handler + "\ntrap finish EXIT\nexit 7\n"],
        env={**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not bundle.exists()
    assert all(not path.exists() for path in credentials), "rollback failure bypassed credential deletion"


def test_notification_failures_expose_only_safe_categories_and_smtp_codes():
    rows = [
        {
            "time": "2026-10-26T17:00:00Z",
            "msg": "Notify attempt failed, will retry later",
            "receiver": "verification",
            "integration": "email[0]",
            "err": "*email.loginAuth: 535 5.7.1 authentication rejected private@example.test test-secret",
        },
        {
            "time": "2026-10-26T17:00:01Z",
            "msg": "Notify attempt failed",
            "receiver": "verification",
            "integration": "email[0]",
            "err": "dial tcp smtp.example.test:465: i/o timeout private@example.test",
        },
        {
            "time": "2026-10-26T17:00:02Z",
            "msg": "Notify attempt failed",
            "receiver": "verification",
            "integration": "email[0]",
            "err": "tls: x509 certificate private@example.test",
        },
        {
            "time": "2026-10-26T17:00:03Z",
            "msg": "Notify attempt failed",
            "receiver": "operator",
            "integration": "email[0]",
            "err": "535 private@example.test",
        },
    ]
    actual = module().email_failures("\n".join(json.dumps(row) for row in rows))
    assert [row["category"] for row in actual] == ["authentication", "network", "tls"]
    assert actual[0]["smtp_code"] == "535"
    assert "private" not in json.dumps(actual) and "test-secret" not in json.dumps(actual)
    assert all(set(row) == {"at", "receiver", "integration", "category", "smtp_code"} for row in actual)


def test_failure_json_in_hidden_output_directory_is_included_in_artifact():
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / ".github/workflows/external-alerts.yml").read_text()
    )
    step = next(
        s
        for s in workflow["jobs"]["verify"]["steps"]
        if s.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert step["if"] == "always()"
    assert step["with"]["path"] == ".monitoring-verification/*.json"
    assert step["with"].get("include-hidden-files") is True
    assert step["with"].get("if-no-files-found") == "error"


def test_capture_preserves_previous_trial_without_misattributing_current(tmp_path, monkeypatch):
    from scripts import deploy_external_alerts as runner

    class Remote:
        options = []
        ip = "127.0.0.1"

        def authorize(self):
            pass

    record = {"verification_id": "mail-123-1", "transport_verified": False, "error_type": "TimeoutError"}
    monkeypatch.setattr(
        runner.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(record), "")
    )
    runner.capture_result(Remote(), tmp_path / "previous.json")
    assert json.loads((tmp_path / "previous.json").read_text()) == record
    runner.capture_result(Remote(), tmp_path / "current.json", "mail-124-1")
    assert not (tmp_path / "current.json").exists()


@pytest.mark.parametrize("returncode", [1, 255])
def test_previous_evidence_read_failure_aborts_before_overwrite(tmp_path, monkeypatch, returncode):
    from scripts import deploy_external_alerts as runner

    class Remote:
        options = []
        ip = "127.0.0.1"

        def authorize(self):
            pass

    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, "", "private error"),
    )
    with pytest.raises(RuntimeError, match="retrieve") as error:
        runner.capture_result(Remote(), tmp_path / "previous.json")
    assert "private error" not in str(error.value)


def test_explicitly_absent_previous_evidence_allows_first_install(tmp_path, monkeypatch):
    from scripts import deploy_external_alerts as runner

    class Remote:
        options = []
        ip = "127.0.0.1"

        def authorize(self):
            pass

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 44, "", ""))
    runner.capture_result(Remote(), tmp_path / "previous.json")
    assert not (tmp_path / "previous.json").exists()


def test_first_success_after_failed_install_preserves_active_mail_config(tmp_path):
    script = (Path(__file__).resolve().parents[1] / "deploy/monitoring/install_external.sh").read_text()
    previous_assignment = next(line for line in script.splitlines() if line.startswith("previous="))
    finalization = script[script.index('ln -sfn "$release" "$root/current"') :].split("\npython3 ")[0]
    root = tmp_path / "monitoring"
    root.mkdir()  # Failed initial install created the directory but no current link.
    release = root / "releases" / "new"
    (release / "config").mkdir(parents=True)
    paths = [release / "config" / name for name in ("smtp-password", "alertmanager.yml")]
    for path in paths:
        path.write_text("test fixture")
    command = (
        f"set -euo pipefail\nroot={shlex.quote(str(root))}\nrelease={shlex.quote(str(release))}\n"
        + previous_assignment
        + "\n"
        + finalization
    )
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert all(path.is_file() for path in paths), "cleanup deleted the newly active mail configuration"


def test_persistence_check_refuses_recreation_when_files_are_missing(tmp_path, monkeypatch):
    mod = module()
    release = tmp_path / "releases" / "mail-123-1"
    release.mkdir(parents=True)
    (release / "verification-id").write_text("mail-123-1")
    out = tmp_path / "result.json"
    out.write_text(
        json.dumps({"verification_id": "mail-123-1", "version_before": "v-test", "transport_verified": True})
    )
    monkeypatch.setattr(
        mod.subprocess, "run", lambda *a, **k: pytest.fail("missing config must prevent container recreation")
    )
    with pytest.raises(AssertionError, match="persistent config missing"):
        mod.verify_persistence(release, out)
    record = json.loads(out.read_text())
    assert record["transport_verified"] is True
    assert record["persistence_verified"] is False
    assert record["release_config_before_restart"] == {
        "smtp_password_file_present": False,
        "alertmanager_config_file_present": False,
    }


@pytest.mark.parametrize("correct_target", [True, False])
def test_activation_requires_persistent_files_and_exact_current_target(tmp_path, correct_target):
    mod = module()
    release = tmp_path / "releases" / "mail-123-1"
    (release / "config").mkdir(parents=True)
    (release / "verification-id").write_text("mail-123-1")
    for name in ["smtp-password", "alertmanager.yml"]:
        (release / "config" / name).write_text("private-test-value")
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "current").symlink_to(release if correct_target else other)
    out = tmp_path / "result.json"
    out.write_text(
        json.dumps(
            {
                "verification_id": "mail-123-1",
                "persistence_verified": True,
                "operator_receipt_confirmed": False,
            }
        )
    )
    if correct_target:
        mod.record_activation(release, out)
    else:
        with pytest.raises(AssertionError, match="active persistent config missing"):
            mod.record_activation(release, out)
    record = json.loads(out.read_text())
    assert record["activation_verified"] is correct_target
    assert record["persistence_verified"] is correct_target
    assert record["operator_receipt_confirmed"] is False
    assert "private-test-value" not in out.read_text()
