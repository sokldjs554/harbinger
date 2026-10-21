from harbinger.api.routers.workbench import sessions
from tests.test_upload import HEADER, ROW


def test_upload_session_isolation_and_withheld_results(client):
    before = client.get("/v1/sites").json()
    r = client.post(
        "/v1/workbench/upload?observation_end=2025-10-01",
        content=(HEADER + ROW).encode(),
        headers={"Content-Type": "text/csv"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["session_id"]
    try:
        analysis = client.get(f"/v1/workbench/sessions/{token}/analysis?as_of=2025-08-01").json()
        assert len(analysis["assets"]) == 1
        assert 0 < analysis["assets"][0]["p30"] < 1
        assert analysis["evaluation_status"] == "withheld"
        assert all(m["precision_at_k"] is None for m in analysis["comparisons"])
        recent = client.get(f"/v1/workbench/sessions/{token}/analysis?as_of=2025-10-01").json()
        assert recent["assets"][0]["failed_within_30d"] is None
        for fmt in ["csv", "json", "md"]:
            response = client.get(f"/v1/workbench/sessions/{token}/download?as_of=2025-08-01&format={fmt}")
            assert response.status_code == 200, response.text
            assert "attachment" in response.headers["content-disposition"]
        empty = client.get(f"/v1/workbench/sessions/{token}/analysis?as_of=2020-01-01").json()
        assert empty["assets"] == [] and empty["evaluation_status"] == "withheld"
        assert client.get("/v1/sites").json() == before
        assert token not in client.get("/metrics").text
    finally:
        assert client.delete(f"/v1/workbench/sessions/{token}").status_code == 200
    assert token not in sessions
    assert client.get(f"/v1/workbench/sessions/{token}/analysis?as_of=2025-08-01").status_code == 404


def test_invalid_upload_is_atomic(client):
    count = len(sessions)
    r = client.post(
        "/v1/workbench/upload?observation_end=2025-10-01",
        content=b"bad",
        headers={"Content-Type": "text/csv"},
    )
    assert r.status_code == 422 and "필수 열" in r.json()["detail"]
    assert len(sessions) == count
    assert (
        client.post(
            "/v1/workbench/upload?observation_end=2025-10-01",
            content=b"bad",
            headers={"Content-Type": "application/zip"},
        ).status_code
        == 415
    )


def test_example_download_is_supported_csv(client):
    from harbinger.api.upload import parse_csv

    info = client.get("/v1/workbench/info").json()
    csv = client.get("/v1/workbench/example.csv")
    assert csv.status_code == 200
    tables, summary = parse_csv(csv.content, info["observation_end"])
    assert len(tables["inspections"]) > 10 and summary["assets"] > 1


def test_example_download_excludes_records_beyond_declared_end(client, monkeypatch):
    import pandas as pd

    from harbinger.api.upload import parse_csv

    info = client.get("/v1/workbench/info").json()
    store = client.app.state.store
    inspections = store.tables["inspections"]
    late = inspections.query("site_id == 'S01'").iloc[[0]].copy()
    late["inspection_id"] = "outside-observation"
    late["performed_at"] = pd.Timestamp(info["observation_end"]) + pd.Timedelta(days=1)
    monkeypatch.setitem(store.tables, "inspections", pd.concat([inspections, late], ignore_index=True))
    response = client.get("/v1/workbench/example.csv")
    assert response.status_code == 200
    tables, _ = parse_csv(response.content, info["latest_as_of_date"])
    assert "outside-observation" not in set(tables["inspections"].inspection_id)
    assert len(tables["inspections"]) > 10
