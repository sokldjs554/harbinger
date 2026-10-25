"""Real protected HTTP and browser verification with disposable local-only credentials."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
from playwright.sync_api import expect, sync_playwright


def browser_check(base, credentials, out):
    operators = [x for x in credentials if x["role"] == "operator"]
    errors, contexts = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        sessions = []
        for i, user in enumerate(operators):
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            contexts.append(context)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))

            def captured(response):
                if response.ok and response.url.endswith("/v1/workbench/example"):
                    sessions.append(response.json()["session_id"])

            page.on("response", captured)
            page.goto(base + "/console/")
            expect(page).to_have_url(base + "/console/login.html")
            page.locator('[name="username"]').fill(user["username"])
            page.locator('[name="password"]').fill(user["password"])
            page.locator('button[type="submit"]').click()
            expect(page.locator("[data-asset]").first).to_be_visible(timeout=120000)
            page.locator('.app-bar [data-view="downloads"]').click()
            expect(page.locator("#report-site option")).to_have_count(len(user["sites"]) + 1)
            options = page.locator("#report-site option").evaluate_all(
                "els=>els.map(e=>e.value).filter(Boolean)"
            )
            assert set(options) == set(user["sites"]), "Browser tenant selection leaked"
            other = operators[1 - i]["sites"][0]
            assert context.request.get(base + f"/v1/sites/{other}/assets").status == 404
            page.locator('.app-bar [data-view="downloads"]').click()
            with page.expect_download() as download:
                page.locator('[data-format="json"]').click()
            path = out / f"scoped-export-{i}.json"
            download.value.save_as(path)
            result = json.loads(path.read_text())
            assert {row["site_id"] for row in result["assets"]} == set(user["sites"])
            for fmt in ("csv", "md"):
                with page.expect_download() as exported:
                    page.locator(f'[data-format="{fmt}"]').click()
                exported_path = out / f"scoped-export-{i}.{fmt}"
                exported.value.save_as(exported_path)
                content = exported_path.read_text(encoding="utf-8-sig")
                if fmt == "csv":
                    values = list(csv.DictReader(io.StringIO(content)))
                    assert {r["selected_model"] for r in values} == {
                        r["selected_model"] for r in result["assets"]
                    }
                    assert {r["policy_reason"] for r in values} == {
                        r["policy_reason"] for r in result["assets"]
                    }
                else:
                    assert "사용 모델" in content
                    assert all(r["selected_model"] in content for r in result["model_routing"])
                exported_path.unlink()
            path.unlink()  # Verification result summary suffices; no stored session identifiers.
            page.locator('.app-bar [data-view="list"]').click()
            if i == 0:
                page.screenshot(path=str(out / "protected-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(out / "protected-mobile.png"), full_page=True)
        assert len(sessions) == 2
        assert (
            contexts[1]
            .request.get(base + f"/v1/workbench/sessions/{sessions[0]}/analysis?as_of=2023-10-01")
            .status
            == 404
        )
        for context in contexts:
            page = context.pages[0]
            page.get_by_role("button", name="로그아웃", exact=True).click()
            expect(page).to_have_url(base + "/console/login.html")
            assert context.request.get(base + "/v1/sites").status == 401
            context.close()
        browser.close()
    assert not errors, errors
    return {
        "human_results": False,
        "page_errors": errors,
        "checks": [
            "anonymous login redirect",
            "two separate browser accounts",
            "site-limited selection and JSON export",
            "direct cross-site denial",
            "cross-user analysis token denial",
            "logout revocation",
            "desktop/mobile no overflow",
        ],
    }


def run(args):
    args.out.mkdir(parents=True, exist_ok=True)
    sites = pd.read_parquet(args.data / "sites.parquet").site_id.astype(str).tolist()[:2]
    if len(sites) != 2:
        raise ValueError("At least two synthetic sites are needed")
    meta = json.loads((args.data / "meta.json").read_text())
    if meta.get("synthetic") is not True:
        raise ValueError("Only synthetic fixtures may be used")
    command = [sys.executable, "scripts/protected_fixture.py", "--site", sites[0], "--site", sites[1]]
    directory = Path(subprocess.check_output(command, text=True).strip())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = os.environ | {
        "HARBINGER_DATA_DIR": str(args.data.resolve()),
        "HARBINGER_MODEL_DIR": str(args.models.resolve()),
        "HARBINGER_ARTIFACT_DIR": str(args.artifacts.resolve()),
        "HARBINGER_DEMO_BOOTSTRAP": "0",
        "HARBINGER_PROTECTED_MODE": "1",
        "HARBINGER_AUTH_USERS_FILE": str(directory / "users.json"),
        "HARBINGER_AUTH_ORIGIN": base,
        "HARBINGER_AUTH_COOKIE_SECURE": "false",
        "OMP_NUM_THREADS": "1",
    }
    process = None
    try:
        with (args.out / "server.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "harbinger.api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--workers",
                    "1",
                    "--no-access-log",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            with httpx.Client(trust_env=False) as client:
                for _ in range(300):
                    if process.poll() is not None:
                        raise RuntimeError("Protected service exited; inspect server.log")
                    try:
                        if client.get(base + "/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("Protected service did not start")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_protected.py",
                    base,
                    "--credentials",
                    str(directory / "credentials.json"),
                ],
                text=True,
                capture_output=True,
            )
            (args.out / "api-checks.txt").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError("Protected API checks failed; inspect api-checks.txt")
            checks = browser_check(base, json.loads((directory / "credentials.json").read_text()), args.out)
            (args.out / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2))
            print("Protected API and actual browser checks passed; disposable accounts only")
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        shutil.rmtree(directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "models", "artifacts", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    run(parser.parse_args())
