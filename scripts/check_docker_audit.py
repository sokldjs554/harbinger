"""Actual API smoke against the audit Docker container on loopback port 18002."""

import argparse
import json
from pathlib import Path

import httpx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    c = httpx.Client(base_url="http://127.0.0.1:18002", trust_env=False, timeout=120)
    result = {}
    for route in ("/health", "/ready", "/version", "/v1/workbench/info"):
        response = c.get(route)
        response.raise_for_status()
        result[route] = response.json()
    ex = c.post("/v1/workbench/example")
    ex.raise_for_status()
    session = ex.json()
    token = session["session_id"]
    params = {"as_of": session["default_as_of"], "site": "S01", "k": 10}
    r = c.get(f"/v1/workbench/sessions/{token}/analysis", params=params)
    r.raise_for_status()
    analysis = r.json()
    result["analysis"] = {
        "assets": len(analysis["assets"]),
        "model_version": analysis["model_version"],
        "evaluation_status": analysis["evaluation_status"],
    }
    for fmt in ("json", "csv", "md"):
        r = c.get(f"/v1/workbench/sessions/{token}/download", params={**params, "format": fmt})
        r.raise_for_status()
        assert len(r.content) > 100
        result["download_" + fmt] = {"status": r.status_code, "bytes": len(r.content)}
    csv = c.get("/v1/workbench/example.csv?site=S01")
    csv.raise_for_status()
    upload = c.post(
        "/v1/workbench/upload",
        params={"observation_end": session["latest_as_of_date"], "observation_confirmed": True},
        headers={"Content-Type": "text/csv"},
        content=csv.content,
    )
    upload.raise_for_status()
    uploaded = upload.json()
    r = c.get("/v1/workbench/sessions/" + uploaded["session_id"] + "/analysis", params=params)
    r.raise_for_status()
    result["upload"] = {
        "status": upload.status_code,
        "analysis_status": r.status_code,
        "assets": len(r.json()["assets"]),
    }
    energy = c.get("/v1/sites/S01/energy/anomalies?as_of=2023-01-02&days=14")
    energy.raise_for_status()
    result["short_energy"] = energy.json()
    assert result["short_energy"]["n_anomaly_days"] is None
    assert result["short_energy"]["n_evaluable_days"] == 0
    for sid in (token, uploaded["session_id"]):
        c.delete("/v1/workbench/sessions/" + sid).raise_for_status()
    result["sessions_closed"] = True
    (a.out / "api.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print("Docker actual API analysis/upload/three downloads/short energy passed")


if __name__ == "__main__":
    main()
