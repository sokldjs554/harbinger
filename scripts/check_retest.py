"""Browser contract for recorder, using explicit tool-test data (no human claims)."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from scripts.retest_records import validate


def run(url, out):
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        page.locator("#export").click()
        expect(page.locator("#notice")).to_contain_text("필수")
        for key, value in {
            "participant": "TOOL-TEST",
            "observer": "automated",
            "version": "test-only",
            "scenario": "browser-contract",
        }.items():
            page.locator("#" + key).fill(value)
        page.locator("#kind").select_option("tool-test")
        page.locator("#phase").select_option("after")
        page.locator("#mode").select_option("local")
        page.locator("#consent").check()
        first = page.locator('[data-task="1"]')
        first.locator('[data-action="start"]').click()
        page.wait_for_timeout(80)
        # A second task must not run concurrently.
        expect(page.locator('[data-task="2"] [data-action="start"]')).to_be_disabled()
        first.locator('[data-action="waiting"]').click()
        page.wait_for_timeout(80)
        first.locator('[data-action="active"]').click()
        first.locator('[data-field="result"]').select_option("assisted")
        first.locator('[data-field="help"]').fill("자동 검사 입력: 필터 위치 안내")
        first.locator('[data-action="finish"]').click()
        page.locator('[data-task="2"] [data-field="help"]').fill("자동 검사: 설명 후 미실시")
        for index in range(2, 8):
            page.locator(f'[data-task="{index}"] [data-action="skip"]').click()
        with page.expect_download() as download:
            page.locator("#export").click()
        path = out / "tool-test-record.json"
        download.value.save_as(path)
        record = json.loads(path.read_text())
        assert record["record_kind"] == "tool-test"
        assert validate(record) == {
            "completed": 1,
            "unassisted": 0,
            "assisted": 1,
            "incomplete": 0,
            "not_attempted": 6,
        }
        assert record["tasks"][0]["waiting_ms"] >= 60
        assert record["tasks"][0]["active_ms"] > 0
        assert record["tasks"][1]["help"] == "자동 검사: 설명 후 미실시"
        page.screenshot(path=str(out / "recorder-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(out / "recorder-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
    checks = {
        "human_results": False,
        "checks": [
            "metadata guard",
            "single active task",
            "waiting separated",
            "assistance preserved",
            "skipped tasks excluded",
            "validated JSON export",
            "mobile no overflow",
        ],
        "page_errors": errors,
    }
    (out / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2))
    print("retest recorder browser checks passed; no human participant results")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8030/retest.html")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.url, args.out)
