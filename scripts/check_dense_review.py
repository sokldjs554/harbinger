"""Exercise the two review screens against a running API, not a mocked model."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765/console/review.html")
    ap.add_argument("--out", type=Path, default=Path("docs/verification/dense-review"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        errors = []
        explanations = []
        created_sessions = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def capture_explanation(response):
            if response.url.endswith("/v1/workbench/example") and response.ok:
                created_sessions.append(response.json()["session_id"])
            if "/assets/" in response.url and "as_of=" in response.url and response.ok:
                explanations.append(response.json())

        page.on("response", capture_explanation)
        page.goto(args.url)
        expect(page.locator("[data-asset]").first).to_be_visible(timeout=120000)
        page.screenshot(path=str(args.out / "desktop-list.png"))
        assert page.locator("#asset-table").bounding_box()["width"] > 1300
        assert page.locator("#asset-table tbody tr").first.bounding_box()["height"] <= 62
        # Search, customer, category and sort persist through both return methods.
        page.select_option("#customer", "S01")
        page.fill("#search", "냉")
        page.select_option("#category", "chiller")
        page.select_option("#sort", "inspection")
        assert all("냉동기" in name for name in page.locator("[data-asset]").all_text_contents())
        assert all("S01" in name for name in page.locator(".asset-id").all_text_contents())
        dates = page.locator(".date-cell").all_text_contents()
        assert dates == sorted(dates)
        expected = {
            key: page.locator("#" + key).input_value() for key in ["customer", "search", "category", "sort"]
        }
        first = page.locator("[data-asset]").first
        asset_id = first.get_attribute("data-asset")
        first.click()
        expect(page.locator("#detail-screen")).to_be_visible()
        expect(page.locator("#list-screen")).to_be_hidden()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        expect(page.locator("#detail-screen")).not_to_have_attribute("role", "dialog")
        if page.locator("[data-inspection]").count() > 1:
            page.locator("[data-inspection]").nth(1).click()
            expect(page.locator("[data-inspection]").nth(1)).to_have_attribute("aria-pressed", "true")
        # Evidence links must return to the correct source record, not just change decoration.
        source = page.locator('[data-source="latest"]').first
        if source.count():
            source.click()
            expect(page.locator("[data-inspection]").first).to_have_attribute("aria-pressed", "true")
        page.click("#back-list")
        expect(page.locator("#list-screen")).to_be_visible()
        for key, value in expected.items():
            assert page.locator("#" + key).input_value() == value
        assert page.evaluate("document.activeElement.dataset.asset") == asset_id
        page.locator("[data-asset]").first.click()
        expect(page.locator("#record-memo")).to_be_visible()
        page.go_back()
        expect(page.locator("#list-screen")).to_be_visible()
        page.go_forward()
        expect(page.locator("#record-memo")).to_be_visible()
        page.click("#back-list")
        page.click("#reset-filters")
        page.click("#next-page")
        expect(page.locator("#page-number")).to_contain_text("2 /")
        page.locator("[data-asset]").first.click()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        page.click("#back-list")
        expect(page.locator("#page-number")).to_contain_text("2 /")
        page.click("#previous-page")
        page.evaluate("window.scrollTo(0, 1100)")
        page.wait_for_timeout(200)
        # Choose a visible row so Playwright itself does not scroll before clicking.
        visible = page.locator("[data-asset]").evaluate_all(
            "els => els.find(e => {const r=e.getBoundingClientRect();return r.top>100 && r.bottom<innerHeight-50}).dataset.asset"
        )
        before_y = page.evaluate("scrollY")
        page.locator(f'[data-asset="{visible}"]').click()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        page.click("#back-list")
        expect(page.locator("#list-screen")).to_be_visible()
        page.wait_for_function("y => Math.abs(scrollY-y)<3", arg=before_y)
        page.fill("#search", "없는설비이름000")
        expect(page.locator("#empty")).to_be_visible()
        page.screenshot(path=str(args.out / "empty.png"))
        page.click("#reset-filters")
        page.evaluate("scrollTo(0,0)")
        # Capture a real asset and record, and preserve this scene on mobile.
        target = page.locator("[data-asset]").first.get_attribute("data-asset")
        page.locator("[data-asset]").first.click()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        page.screenshot(path=str(args.out / "desktop-detail.png"), full_page=True)
        detail_url = page.url
        page.reload()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        assert page.url == detail_url
        # The displayed text must be the backend original, including punctuation.
        record = page.locator("#record-memo").inner_text()
        original = next(r for r in reversed(explanations) if r["asset_id"] == target)
        latest = max(
            original["explanation"]["evidence"]["recent_inspections"], key=lambda m: m["performed_at"]
        )
        assert record == latest["memo"]
        page.locator("[data-inspection]").nth(1).click()
        expect(page.locator("[data-inspection]").nth(1)).to_have_attribute("aria-pressed", "true")
        selected_date = page.locator("#record-date").inner_text()
        page.reload()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        assert page.locator("#record-date").inner_text() == selected_date
        assert len(created_sessions) == 1, "Reload must reuse the same example session"
        page.locator("[data-inspection]").first.click()
        assert page.locator("#record-memo").inner_text() == record
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(args.out / "mobile-detail.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.click("#back-list")
        expect(page.locator("#list-screen")).to_be_visible()
        page.screenshot(path=str(args.out / "mobile-list.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator(f'[data-asset="{target}"]').click()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        page.go_back()
        expect(page.locator("#list-screen")).to_be_visible()
        page.evaluate("scrollTo(0,800)")
        page.wait_for_timeout(100)
        mobile_asset = page.locator("[data-asset]").evaluate_all(
            "els => els.find(e => {const r=e.getBoundingClientRect();return r.top>100 && r.bottom<innerHeight-50}).dataset.asset"
        )
        mobile_y = page.evaluate("scrollY")
        page.locator(f'[data-asset="{mobile_asset}"]').click()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        page.go_back()
        expect(page.locator("#list-screen")).to_be_visible()
        page.wait_for_function("y => Math.abs(scrollY-y)<3", arg=mobile_y)
        # A failed detail request must leave the way back usable and offer retry.
        page.route(
            "**/assets/*?as_of=*",
            lambda route: route.fulfill(status=503, json={"detail": "검증용 일시 오류"}),
        )
        page.locator("[data-asset]").nth(1).click()
        expect(page.locator("#detail-error")).to_be_visible(timeout=120000)
        expect(page.locator("#back-list")).to_be_enabled()
        page.unroute("**/assets/*?as_of=*")
        page.click("#retry-detail")
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        # Server restart/expiry: an absent cached session is renewed once.
        from urllib.parse import urlsplit

        base = urlsplit(args.url)
        origin = f"{base.scheme}://{base.netloc}"
        page.request.delete(f"{origin}/v1/workbench/sessions/{created_sessions[0]}")
        page.reload()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        assert len(created_sessions) == 2
        assert not errors, errors
        (args.out / "checks.json").write_text(
            json.dumps(
                {
                    "asset": target,
                    "page_errors": errors,
                    "checks": [
                        "real API analysis and explanation",
                        "dense full width list",
                        "separate detail route",
                        "filter and sort restore",
                        "scroll and focus restore",
                        "browser back and forward",
                        "inspection selection",
                        "evidence source links",
                        "deep link reload",
                        "empty result",
                        "desktop and mobile",
                        "detail error and retry",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        for token in created_sessions:
            page.request.delete(f"{origin}/v1/workbench/sessions/{token}")
        browser.close()
        print("dense review browser checks passed")


if __name__ == "__main__":
    main()
