"""Boundary regressions found by the service requirements audit; no network needed."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from harbinger.api import backtest
from harbinger.api.deps import parse_as_of
from harbinger.api.routers import workbench
from harbinger.api.routers.replay import _ts
from harbinger.api.routers.report import to_markdown
from harbinger.api.routers.risk import ScenarioIn
from harbinger.api.store import Store
from harbinger.config import Settings


def test_empty_history_report_preserves_unknown_risk():
    report = {
        "site": {
            "name": "Empty",
            "n_assets": 1,
            "n_inspectors": 1,
            "breakdowns_90d": 0,
            "downtime_hours_90d": 0,
            "mean_p30": None,
            "n_high_risk(p30>=0.15)": 0,
        },
        "as_of": "2020-01-01",
        "model": {
            "version": "test",
            "selected_model": "baseline",
            "policy_revision": None,
            "policy_reason": "no_policy",
            "policy_test_start": None,
        },
        "patrol": {"items": [], "note": "No inspections"},
        "top_risk_assets": [],
        "schedule_changes": {"n_shorten": 0, "n_lengthen": 0, "urgent": []},
        "energy": {
            "n_observed_days_90d": 0,
            "n_evaluable_days_90d": 0,
            "n_anomaly_days_90d": None,
            "status": "no_data",
            "anomalies": [],
        },
        "quality": {"site_average": None, "least_reliable": []},
        "caveats": [],
    }
    text = to_markdown(report)
    assert "계산 불가" in text
    assert "0.0%" not in text


@pytest.mark.parametrize("value", [-1, 3, 128])
def test_whatif_rejects_invalid_checklist_value(value):
    with pytest.raises(ValidationError):
        ScenarioIn(items={"noise": value})


def test_upload_default_has_existing_records():
    store = SimpleNamespace(
        data_end=pd.Timestamp("2025-08-02T23:59:59"),
        X=pd.DataFrame({"t": [pd.Timestamp("2025-08-01")]}),
        tables={"sites": pd.DataFrame({"site_id": ["S01"], "name": ["Site"]})},
        bundle={"version": "test"},
    )
    response = workbench.register(store, "uploaded-csv", {})
    try:
        assert pd.Timestamp(response["default_as_of"]) >= store.X.t.min().normalize()
    finally:
        workbench.sessions.pop(response["session_id"], None)


def test_ingestion_invalidates_replay_cache(tmp_path, monkeypatch):
    store = Store(Settings(model_dir=tmp_path))
    t = pd.Timestamp("2025-08-01")
    store._observation_end = t + pd.Timedelta(days=40)
    from harbinger.features.build import FEATURE_SEMANTICS_VERSION

    store.bundle = {"entry": {"feature_semantics_version": FEATURE_SEMANTICS_VERSION}}
    store.X = pd.DataFrame({"site_id": ["S01"], "asset_id": ["A01"], "t": [t]})
    store.tables = {
        "sites": pd.DataFrame({"site_id": ["S01"]}),
        "assets": pd.DataFrame({"site_id": ["S01"], "asset_id": ["A01"]}),
        "inspections": pd.DataFrame(
            {"site_id": ["S01"], "asset_id": ["A01"], "scheduled_at": [t], "performed_at": [t]}
        ),
    }
    calls = []

    def replay_site(*args, **kwargs):
        calls.append(1)
        return {"weeks": []}

    monkeypatch.setattr(backtest, "replay_site", replay_site)
    monkeypatch.setattr("harbinger.api.store.build_features", lambda *a, **kw: store.X.copy())
    monkeypatch.setattr(store, "_refresh_monitoring", lambda: None)
    monkeypatch.setattr(store, "latest_rows", lambda *a, **kw: pd.DataFrame(columns=["asset_id"]))
    store.replay("S01", t, t)
    store.ingest_inspections("S01", [{"asset_id": "A01", "performed_at": t, "scheduled_at": t}])
    store.replay("S01", t, t)
    assert len(calls) == 2


def test_same_commit_deploy_keeps_previous_release_intact(tmp_path):
    """Run the actual installer prefix with harmless local replacements for host tools."""
    installer = Path("deploy/aws/ec2/install.sh").read_text().split("docker load -i")[0]
    root = tmp_path / "host"
    sha = "a" * 40
    previous = root / "releases" / sha
    previous.mkdir(parents=True)
    (previous / "marker").write_text("previous runtime")
    (root / "current").symlink_to(previous)
    installer = installer.replace("/opt/harbinger", str(root))
    installer = installer.replace("/var/log/harbinger-deploy.log", str(tmp_path / "deploy.log"))
    installer = installer.replace("/var/www/harbinger-acme", str(tmp_path / "acme"))
    installer = installer.replace("/etc/nginx/sites-available/harbinger", str(tmp_path / "nginx-site"))
    installer += '\nprintf "RELEASE=%s\\nPREVIOUS=%s\\n" "$release" "$previous"\n'
    image_id = "sha256:" + "b" * 64
    stubs = (
        f"apt-get() {{ :; }}; systemctl() {{ :; }}; python3() {{ :; }}; docker() {{ echo {image_id}; }};\n"
    )
    result = subprocess.run(
        ["bash", "-c", stubs + installer, "audit", sha, "8.8.8.8"], text=True, capture_output=True, check=True
    )
    release = next(
        line.removeprefix("RELEASE=") for line in result.stdout.splitlines() if line.startswith("RELEASE=")
    )
    assert Path(release) != previous
    assert (previous / "marker").read_text() == "previous runtime"
    image_snapshot = root / "pending-deployment" / "previous-image"
    assert image_snapshot.read_text().strip() == image_id
    (previous / ".env").write_text(f"HARBINGER_RELEASE={sha}\n")
    rollback = root / "pending-deployment" / "rollback.sh"
    commands = tmp_path / "docker-rollback-commands"
    subprocess.run(
        [
            "bash",
            "-c",
            'docker() { printf "%s\\n" "$*" >> "$AUDIT_COMMANDS"; }; export -f docker; bash "$1"',
            "audit",
            str(rollback),
        ],
        env={"PATH": "/usr/bin:/bin", "AUDIT_COMMANDS": str(commands)},
        check=True,
        text=True,
        capture_output=True,
    )
    assert commands.read_text().splitlines()[0] == f"tag {image_id} harbinger:{sha}"
    assert (root / "current").resolve() == previous


@pytest.mark.parametrize("value", ["NaT", "2025-08-01T00:00:00Z", "2025-08-01T09:00:00+09:00"])
@pytest.mark.parametrize("parser", ["as_of", "replay"])
def test_query_dates_reject_missing_or_timezone_aware_values(value, parser):
    with pytest.raises(HTTPException) as error:
        if parser == "as_of":
            parse_as_of(Store(Settings()), value)
        else:
            _ts(value)
    assert error.value.status_code == 422
