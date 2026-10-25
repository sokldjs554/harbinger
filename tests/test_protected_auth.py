"""Negative authorization tests run through the real application middleware and model store."""

import io
import json
import stat
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from harbinger.api.auth import COOKIE, AuthManager, password_hash, verify_password
from harbinger.config import Settings

PASSWORD = "ephemeral-test-password"
ORIGIN = "http://testserver"


@pytest.fixture
def protected(client, tmp_path):
    from harbinger.api import main
    from harbinger.api.routers import workbench

    store = main.app.state.store
    sites = list(store.tables["sites"].site_id)[:2]
    users = [
        {"username": name, "role": role, "sites": allowed, "password_hash": password_hash(PASSWORD)}
        for name, role, allowed in [
            ("alice", "operator", sites[:1]),
            ("bob", "operator", sites[1:]),
            ("reader", "viewer", sites[:1]),
            ("admin", "admin", []),
        ]
    ]
    path = tmp_path / "users.json"
    path.write_text(json.dumps(users))
    path.chmod(0o600)
    config = Settings(protected_mode=True, auth_users_file=path, auth_origin=ORIGIN, auth_cookie_secure=False)
    old_settings, old_auth = main.app.state.auth_settings, main.app.state.auth
    main.app.state.auth_settings = config
    main.app.state.auth = AuthManager(config)
    with workbench.lock:
        workbench.sessions.clear()
    yield main.app, sites
    with workbench.lock:
        workbench.sessions.clear()
    main.app.state.auth_settings, main.app.state.auth = old_settings, old_auth


def login(app, name):
    c = TestClient(app)
    result = c.post("/auth/login", headers={"Origin": ORIGIN}, json={"username": name, "password": PASSWORD})
    assert result.status_code == 200, result.text
    c.headers.update({"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]})
    return c


def test_fail_closed_and_hash_bounds(tmp_path):
    with pytest.raises(RuntimeError):
        AuthManager(Settings(protected_mode=True))
    path = tmp_path / "empty.json"
    path.write_text("[]")
    path.chmod(0o600)
    with pytest.raises(RuntimeError):
        AuthManager(Settings(protected_mode=True, auth_users_file=path, auth_origin="https://example.test"))
    hashed = password_hash(PASSWORD)
    assert verify_password(PASSWORD, hashed)
    assert not verify_password(PASSWORD, hashed.replace("16384", "1073741824"))
    assert not verify_password("wrong-password", hashed)
    assert not verify_password("x" * 257, hashed)


def test_all_direct_api_surfaces_require_auth(protected):
    app, sites = protected
    c = TestClient(app)
    for path in [
        "/v1/sites",
        f"/v1/sites/{sites[1]}",
        "/v1/workbench/info",
        "/v1/workbench/example.csv",
        "/v1/models",
        "/v1/monitoring/drift",
        "/v1/artifacts/metrics",
        "/v1/text/lexicon",
        "/v1/replay",
        "/metrics",
        "/version",
        "/ready",
        "/openapi.json",
        "/auth/me",
    ]:
        assert c.get(path).status_code == 401, path
    assert c.get("/health").status_code == 200
    assert c.get("/console/", follow_redirects=False).headers["location"] == "/console/login.html"
    assert c.get("/console/login.html").status_code == 200
    assert c.post("/v1/text/analyze", json={"memo": "test"}).status_code == 401


def test_sites_direct_export_and_global_admin_boundary(protected):
    app, sites = protected
    c = login(app, "alice")
    rows = c.get("/v1/sites").json()["sites"]
    assert [r["site_id"] for r in rows] == sites[:1]
    assert c.get(f"/v1/sites/{sites[0]}").status_code == 200
    assert c.get(f"/v1/sites/{sites[1]}").status_code == 404
    for suffix in ["/assets", "/report?format=md", "/schedule", "/quality"]:
        assert c.get(f"/v1/sites/{sites[1]}{suffix}").status_code == 404
    assert c.get(f"/v1/workbench/example.csv?site={sites[1]}").status_code == 404
    assert c.get(f"/v1/workbench/example.csv?site={sites[0]}").status_code == 200
    assert c.get(f"/v1/replay?site={sites[1]}").status_code == 404
    for path in [
        "/v1/models",
        "/v1/monitoring/drift",
        "/v1/artifacts/metrics",
        "/metrics",
        "/version",
        "/ready",
        "/openapi.json",
    ]:
        assert c.get(path).status_code == 403, path
    assert c.post(f"/v1/sites/{sites[0]}/inspections", json={"records": []}).status_code == 403
    assert c.post("/v1/text/analyze", json={"memo": "진동"}).status_code == 200
    # Scoping does not alter shared state or metadata.
    assert len(app.state.store.tables["sites"]) > 1
    admin = login(app, "admin")
    assert len(admin.get("/v1/sites").json()["sites"]) > 1
    assert admin.get("/v1/models").status_code == 200


def test_session_owner_cross_user_export_evidence_and_reset(protected):
    app, sites = protected
    alice, bob = login(app, "alice"), login(app, "bob")
    payload = alice.post("/v1/workbench/example").json()
    assert [s["site_id"] for s in payload["sites"]] == sites[:1]
    prefix = "/v1/workbench/sessions/" + payload["session_id"]
    query = "?as_of=" + payload["default_as_of"]
    for path in [
        prefix + "/analysis" + query,
        prefix + "/download" + query,
        prefix + "/assets/anything" + query,
    ]:
        assert bob.get(path).status_code == 404, path
    assert bob.delete(prefix).status_code == 404
    assert alice.get(prefix + "/analysis" + query + "&site=" + sites[1]).status_code == 404
    result = alice.get(prefix + "/analysis" + query)
    assert result.status_code == 200, result.text
    assert {a["site_id"] for a in result.json()["assets"]} <= {sites[0]}
    assert alice.get(prefix + "/download" + query + "&format=csv").status_code == 200
    assert alice.delete(prefix).status_code == 200
    assert alice.get(prefix + "/analysis" + query).status_code == 404


def test_csv_allowed_mixed_and_viewer(protected):
    app, sites = protected
    alice, admin = login(app, "alice"), login(app, "admin")
    frames = [
        pd.read_csv(io.StringIO(admin.get("/v1/workbench/example.csv", params={"site": site}).text))
        for site in sites
    ]
    info = alice.get("/v1/workbench/info").json()
    endpoint = "/v1/workbench/upload?observation_end=" + info["observation_end"]
    headers = {"Content-Type": "text/csv"}
    for df in [frames[1], pd.concat(frames)]:
        response = alice.post(endpoint, content=df.to_csv(index=False).encode(), headers=headers)
        assert response.status_code == 403, response.text
    response = alice.post(endpoint, content=frames[0].to_csv(index=False).encode(), headers=headers)
    assert response.status_code == 200, response.text
    assert [s["site_id"] for s in response.json()["sites"]] == sites[:1]
    reader = login(app, "reader")
    assert (
        reader.post(endpoint, content=frames[0].to_csv(index=False).encode(), headers=headers).status_code
        == 403
    )


def test_csrf_logout_expiry_cookie_and_rate_limit(protected):
    app, _ = protected
    c = TestClient(app)
    body = {"username": "alice", "password": PASSWORD}
    assert c.post("/auth/login", json=body).status_code == 403
    assert c.post("/auth/login", headers={"Origin": "https://evil.test"}, json=body).status_code == 403
    response = c.post("/auth/login", headers={"Origin": ORIGIN}, json=body)
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    csrf = response.json()["csrf_token"]
    assert c.post("/v1/workbench/example", headers={"Origin": ORIGIN}).status_code == 403
    assert (
        c.post(
            "/v1/workbench/example", headers={"Origin": "https://evil.test", "X-CSRF-Token": csrf}
        ).status_code
        == 403
    )
    c.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
    session = c.post("/v1/workbench/example").json()["session_id"]
    old = c.cookies.get(COOKIE)
    assert c.post("/auth/logout").status_code == 200
    c.cookies.set(COOKIE, old)
    assert c.get("/v1/sites").status_code == 401
    from harbinger.api.routers import workbench

    assert session not in workbench.sessions
    c = login(app, "alice")
    token = c.cookies.get(COOKIE)
    expired_workbench = c.post("/v1/workbench/example").json()["session_id"]
    app.state.auth.sessions[token].expires = time.monotonic() - 1
    assert c.get("/v1/sites").status_code == 401
    assert token not in app.state.auth.sessions
    assert expired_workbench not in workbench.sessions
    c = TestClient(app)
    for _ in range(10):
        response = c.post(
            "/auth/login", headers={"Origin": ORIGIN}, json={"username": "missing", "password": PASSWORD}
        )
    assert response.status_code == 429
    # Validation errors must not echo password material.
    response = c.post(
        "/auth/login", headers={"Origin": ORIGIN}, json={"username": "alice", "password": "secret" * 100}
    )
    assert "secret" not in response.text


def test_secure_cookie_default_and_permissions(protected):
    app, _ = protected
    app.state.auth.settings.auth_cookie_secure = True
    response = TestClient(app).post(
        "/auth/login", headers={"Origin": ORIGIN}, json={"username": "alice", "password": PASSWORD}
    )
    assert "Secure" in response.headers["set-cookie"]
    path = app.state.auth.settings.auth_users_file
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o644)
    with pytest.raises(RuntimeError):
        AuthManager(Settings(protected_mode=True, auth_users_file=path, auth_origin="https://testserver"))


def test_warmed_global_replay_cache_is_not_reused(protected):
    app, sites = protected
    admin, alice = login(app, "admin"), login(app, "alice")
    params = {"site": "all", "from": "2024-06-01", "to": "2024-06-08"}
    global_result = admin.get("/v1/replay", params=params)
    assert global_result.status_code == 200
    assert global_result.json()["n_sites"] > 1
    local_result = alice.get("/v1/replay", params=params)
    assert local_result.status_code == 200
    assert local_result.json()["n_sites"] == 1
    assert app.state.store._replay_cache
    assert alice.get(f"/v1/sites/{sites[0]}/report").json()["model"]["headline"] is None


def test_metrics_bearer_is_narrow_and_optional(protected):
    from pydantic import SecretStr, ValidationError

    app, _ = protected
    token = "disposable-metrics-token-" + "x" * 32
    c = TestClient(app, headers={"Authorization": "Bearer " + token})
    assert c.get("/metrics").status_code == 401
    app.state.auth_settings.auth_metrics_token = SecretStr(token)
    assert c.get("/metrics").status_code == 200
    for path in [
        "/v1/sites",
        "/v1/artifacts/metrics",
        "/v1/models",
        "/v1/monitoring/drift",
        "/version",
        "/ready",
        "/auth/me",
    ]:
        assert c.get(path).status_code == 401
    assert c.post("/metrics").status_code == 401
    assert c.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert Settings(auth_metrics_token="").auth_metrics_token is None
    with pytest.raises(ValidationError):
        Settings(auth_metrics_token="short")
    with pytest.raises(ValidationError):
        Settings(auth_metrics_token="x" * 257)
    assert token not in repr(Settings(auth_metrics_token=token))


def test_offline_provisioning_writes_only_hashes(tmp_path, monkeypatch):
    import sys

    from harbinger import auth_users

    path = tmp_path / "accounts.json"
    monkeypatch.setattr(
        sys, "argv", ["auth_users", str(path), "local-user", "--role", "operator", "--site", "S01"]
    )
    monkeypatch.setattr(auth_users.getpass, "getpass", lambda _: PASSWORD)
    auth_users.main()
    assert PASSWORD not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    records = json.loads(path.read_text())
    assert len(records) == 1
    assert verify_password(PASSWORD, records[0]["password_hash"])
    auth_users.main()
    assert len(json.loads(path.read_text())) == 1
