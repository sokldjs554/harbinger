"""Check long selected-model provenance on mobile with explicit synthetic fixtures."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run(url, out):
    fixture = json.loads(Path("docs/demo/workbench-data.json").read_text())
    trace = dict(
        selected_model="without_text",
        policy_revision="abcdef0123456789" * 4,
        policy_reason="validation_brier",
        policy_test_start="2027-01-01",
    )
    for result in fixture["snapshots"].values():
        result["model_routing"] = [dict(site_id="S01", **trace)]
        for asset in result["assets"]:
            asset.update(trace)
    for evidence in fixture["evidence"].values():
        evidence.update(trace)
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/workbench-data.json", lambda route: route.fulfill(json=fixture))
        for width in (320, 390, 650):
            page.set_viewport_size(dict(width=width, height=844))
            page.goto(url)
            expect(page.locator("[data-asset]").first).to_be_visible()
            page.locator("[data-asset]").first.click()
            page.locator("#model-details summary").click()
            expect(page.locator("#model-values")).to_contain_text(trace["policy_revision"])
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator('.app-bar [data-view="downloads"]').click()
            expect(page.locator('[data-format="csv"]')).to_be_enabled()
            page.locator(".provenance-details summary").click()
            expect(page.locator("#report-provenance")).to_contain_text(trace["policy_revision"])
            actual = page.evaluate("document.documentElement.scrollWidth")
            assert actual <= width, f"policy provenance overflow: viewport={width}, scroll={actual}"
            page.screenshot(path=str(out / f"policy-{width}.png"), full_page=True)
        assert not errors, errors
        browser.close()
    (out / "checks.json").write_text(
        json.dumps(
            dict(
                human_results=False,
                synthetic_injected_trace=True,
                widths=[320, 390, 650],
                exact_revision_preserved=True,
                page_errors=errors,
            ),
            indent=2,
        )
    )
    print("Long model policy provenance checks passed at 320/390/650px; synthetic fixture only")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8020/")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.url, args.out)
