"""Exercise a running protected server using disposable fixture accounts; emits no credentials."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import httpx


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--credentials", type=Path, required=True)
    args = parser.parse_args()
    origin = args.base_url.rstrip("/")
    credentials = json.loads(args.credentials.read_text())
    first, second = [record for record in credentials if record["role"] == "operator"][:2]
    clients = []
    try:
        anonymous = httpx.Client(base_url=origin, timeout=120, trust_env=False)
        clients.append(anonymous)
        check(anonymous.get("/v1/sites").status_code == 401, "Anonymous data access")
        for record in (first, second):
            client = httpx.Client(base_url=origin, timeout=120, headers={"Origin": origin}, trust_env=False)
            clients.append(client)
            response = client.post("/auth/login", json={k: record[k] for k in ("username", "password")})
            check(response.status_code == 200, "Login failed")
            check("HttpOnly" in response.headers["set-cookie"], "Missing HttpOnly cookie")
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            sites = client.get("/v1/sites").json()["sites"]
            check({site["site_id"] for site in sites} == set(record["sites"]), "Site list leaked")
        alice, bob = clients[1:]
        other = second["sites"][0]
        check(alice.get(f"/v1/sites/{other}/report?format=md").status_code == 404, "Cross-site report")
        check(alice.get("/v1/artifacts/metrics").status_code == 403, "Global artifact access")
        check(alice.get("/metrics").status_code == 403, "Global monitoring access")
        check(
            alice.post("/v1/workbench/example", headers={"X-CSRF-Token": "bad"}).status_code == 403,
            "Missing CSRF enforcement",
        )
        response = alice.post("/v1/workbench/example")
        check(response.status_code == 200, "Example creation failed")
        session = response.json()
        route = "/v1/workbench/sessions/" + session["session_id"]
        params = {"as_of": session["default_as_of"]}
        for endpoint in ("analysis", "download"):
            check(
                bob.get(f"{route}/{endpoint}", params=params).status_code == 404, "Cross-user session access"
            )
        check(bob.delete(route).status_code == 404, "Cross-user session reset")
        check(alice.get(route + "/download", params=params).status_code == 200, "Same-site export failed")
        own_csv = alice.get("/v1/workbench/example.csv", params={"site": first["sites"][0]}).text
        other_csv = bob.get("/v1/workbench/example.csv", params={"site": other}).text
        own_rows, other_rows = (
            list(csv.DictReader(io.StringIO(own_csv))),
            list(csv.DictReader(io.StringIO(other_csv))),
        )
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(own_rows[0]))
        writer.writeheader()
        writer.writerows(own_rows + other_rows)
        end = alice.get("/v1/workbench/info").json()["observation_end"]
        check(
            alice.post(
                "/v1/workbench/upload",
                params={"observation_end": end},
                content=output.getvalue().encode(),
                headers={"Content-Type": "text/csv"},
            ).status_code
            == 403,
            "Mixed-site CSV accepted",
        )
        check(alice.delete(route).status_code == 200, "Owner reset failed")
        check(alice.get(route + "/analysis", params=params).status_code == 404, "Reset session retained")
        check(alice.post("/auth/logout").status_code == 200, "Logout failed")
        check(alice.get("/v1/sites").status_code == 401, "Logout did not revoke access")
        check(bob.post("/auth/logout").status_code == 200, "Second logout failed")
        print(
            "PASS: login, tenant scope, direct URL, cross-user session, export, mixed CSV, CSRF, reset, logout"
        )
    finally:
        for client in clients:
            client.close()


if __name__ == "__main__":
    main()
