from tests.conftest import first_site


def test_health_and_version(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["assets"] > 0
    v = client.get("/version").json()
    assert v["synthetic_data"] is True and v["n_features"] > 50


def test_sites_and_summary(client):
    r = client.get("/v1/sites")
    assert r.status_code == 200
    sites = r.json()["sites"]
    assert len(sites) >= 1 and all("n_assets" in s for s in sites)
    sid = sites[0]["site_id"]
    s = client.get(f"/v1/sites/{sid}").json()
    assert s["n_assets"] > 0 and "mean_p30" in s
    assert client.get("/v1/sites/NOPE").status_code == 404


def test_patrol_and_risk_and_schedule(client):
    sid = first_site(client)
    p = client.get(f"/v1/sites/{sid}/patrol/today?k=5").json()
    assert 1 <= len(p["items"]) <= max(5, sum(i["mandatory"] for i in p["items"]))
    assert p["expected_breakdowns_in_list"] >= 0
    aid = p["items"][0]["asset_id"]
    r = client.get(f"/v1/sites/{sid}/assets/{aid}/risk").json()
    assert 0 < r["p30"] < 1 and r["recommendation"]["recommended_interval_days"] >= 7
    assert r["explanation"]["evidence"]["recent_inspections"]
    sc = client.get(f"/v1/sites/{sid}/schedule").json()
    assert sc["n_assets"] == len(sc["items"]) > 0
    assert client.get(f"/v1/sites/{sid}/assets/NOPE/risk").status_code == 404


def test_energy_quality_report(client):
    sid = first_site(client)
    e = client.get(f"/v1/sites/{sid}/energy/anomalies?days=60").json()
    assert len(e["days"]) > 30 and "n_anomaly_days" in e
    q = client.get(f"/v1/sites/{sid}/quality").json()
    assert q["inspectors"] and all(0 <= i["reliability_score"] <= 1 for i in q["inspectors"])
    r = client.get(f"/v1/sites/{sid}/report")
    assert r.status_code == 200 and r.json()["top_risk_assets"]
    md = client.get(f"/v1/sites/{sid}/report?format=md")
    assert md.status_code == 200 and "실증 리포트" in md.text


def test_admin_and_metrics(client):
    m = client.get("/v1/models").json()
    assert m["active"] and m["versions"]
    d = client.get("/v1/monitoring/drift?window_days=30").json()
    assert "features" in d and "predictions" in d
    a = client.get("/v1/artifacts/ablation")
    assert a.status_code == 200
    assert client.get("/v1/artifacts/secret").status_code == 404
    text = client.get("/metrics").text
    assert "harbinger_requests_total" in text and "harbinger_model_loaded" in text


def test_ingest_updates_risk(client):
    sid = first_site(client)
    assets = client.get(f"/v1/sites/{sid}/assets?limit=3").json()["assets"]
    aid = assets[0]["asset_id"]
    before = client.get(f"/v1/sites/{sid}/assets/{aid}/risk?explain=false").json()
    last = before["last_inspection_at"]
    import pandas as pd

    t = (pd.Timestamp(last) + pd.Timedelta(days=3)).isoformat()
    payload = [
        {
            "inspection_id": "N-TEST-1",
            "asset_id": aid,
            "inspector_id": "I-TEST",
            "scheduled_at": t,
            "performed_at": t,
            "method": "nfc",
            "dwell_seconds": 120,
            "overall": 2,
            "items": {"noise": 2, "vibration": 1},
            "memo": "소음 심함, 진동 증가, 즉시 수리 필요",
            "photo_count": 2,
        }
    ]
    r = client.post(f"/v1/sites/{sid}/inspections", json=payload)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["ingested"] == 1 and body["updated"][0]["asset_id"] == aid
    after = client.get(f"/v1/sites/{sid}/assets/{aid}/risk?explain=false").json()
    assert after["last_inspection_at"].startswith(t[:10])
    bad = client.post(f"/v1/sites/{sid}/inspections", json=[dict(payload[0], asset_id="NOPE")])
    assert bad.status_code == 422
