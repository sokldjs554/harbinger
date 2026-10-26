"""External alert configuration and receipt evidence safety contracts."""

import importlib.util
import json
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
