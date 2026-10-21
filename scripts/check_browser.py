"""Real Chromium clicks, uploads, downloads, and mobile layout checks."""

import argparse
import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/console/")
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("docs/verification/browser"))
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 1080},
            record_video_dir=str(out / "video") if args.record else None,
            record_video_size={"width": 1440, "height": 1080} if args.record else None,
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.url)
        page.wait_for_function("!document.getElementById('mode').textContent.includes('확인 중')")
        assert "오류" not in page.locator("#mode").inner_text()
        page.screenshot(path=str(out / "landing.png"), full_page=True)
        page.click("#example")
        page.wait_for_function("document.querySelectorAll('#assets tr').length > 0", timeout=120000)
        page.locator("[data-asset]").first.click()
        page.wait_for_function(
            "document.getElementById('evidence').innerText.includes('점검 원문')", timeout=120000
        )
        page.screenshot(path=str(out / "priority.png"), full_page=True)
        # Editing controls without submitting must not change evidence/export conditions.
        shown_date = page.locator("#static-date" if args.static else "#date").input_value()
        if args.static:
            page.select_option("#static-date", index=1)
        else:
            page.fill("#date", page.locator("#date").get_attribute("max"))
        page.locator("[data-asset]").first.click()
        page.wait_for_function("!document.getElementById('status').classList.contains('busy')")
        page.click('[data-tab="downloads"]')
        with page.expect_download() as unchanged:
            page.click('[data-format="json"]')
        unchanged.value.save_as(str(out / "unchanged-query.json"))
        assert json.loads((out / "unchanged-query.json").read_text())["as_of"].startswith(shown_date)
        if args.static:
            page.select_option("#static-date", shown_date)
        else:
            page.fill("#date", shown_date)
        for name in ["comparison", "customers", "downloads", "priority"]:
            page.click(f'[data-tab="{name}"]')
            assert page.locator("#" + name).is_visible()
        page.click('[data-tab="downloads"]')
        for fmt in ["json", "csv", "md"]:
            with page.expect_download() as d:
                page.click(f'[data-format="{fmt}"]')
            d.value.save_as(str(out / f"result.{fmt}"))
        page.click('[data-tab="priority"]')
        page.select_option("#site", index=1)
        page.locator("#analysis-form button").click()
        page.wait_for_function("!document.getElementById('status').classList.contains('busy')")
        if args.static:
            page.select_option("#static-date", index=1)
        else:
            end = page.locator("#date").get_attribute("max")
            page.fill("#date", end)
        page.locator("#analysis-form button").click()
        page.wait_for_function("!document.getElementById('status').classList.contains('busy')")
        assert "평가 보류" in page.locator("#stats").inner_text()
        page.click('[data-tab="comparison"]')
        assert "평가 보류" in page.locator("#evaluation-note").inner_text()
        page.screenshot(path=str(out / "withheld.png"), full_page=True)
        if not args.static:
            page.click('[data-tab="priority"]')
            page.fill("#date", "2000-01-01")
            page.locator("#analysis-form button").click()
            page.wait_for_selector("#empty:visible")
            page.click("#upload-toggle")
            page.set_input_files("#csv", {"name": "bad.csv", "mimeType": "text/csv", "buffer": b"wrong\n1"})
            page.locator("#upload-form button").click()
            page.wait_for_selector("#error:visible")
            assert "필수 열" in page.locator("#error").inner_text()
            page.screenshot(path=str(out / "upload-error.png"), full_page=True)
            response = page.request.get(urljoin(args.url, "/v1/workbench/example.csv"))
            assert response.ok
            page.set_input_files(
                "#csv", {"name": "example.csv", "mimeType": "text/csv", "buffer": response.body()}
            )
            page.locator("#upload-form button").click()
            page.wait_for_function(
                "document.getElementById('dataset').textContent.includes('업로드 기록')", timeout=120000
            )
            page.wait_for_function("!document.getElementById('status').classList.contains('busy')")
            assert not page.locator("#error").is_visible(), page.locator("#error").inner_text()
        page.set_viewport_size({"width": 390, "height": 844})
        page.click('[data-tab="priority"]')
        page.screenshot(path=str(out / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
            "Mobile horizontal overflow"
        )
        assert not errors, errors
        page.click("#close")
        page.wait_for_selector("#workspace", state="hidden")
        context.close()
        browser.close()
        (out / "checks.json").write_text(
            json.dumps(
                {
                    "url": args.url,
                    "static": args.static,
                    "page_errors": errors,
                    "checks": [
                        "load",
                        "evidence",
                        "all tabs",
                        "site selection",
                        "pending outcomes",
                        "downloads",
                        "mobile",
                        "session close",
                    ]
                    + ([] if args.static else ["empty", "invalid CSV", "valid CSV"]),
                },
                indent=2,
            )
        )
        print("browser checks passed")


if __name__ == "__main__":
    main()
