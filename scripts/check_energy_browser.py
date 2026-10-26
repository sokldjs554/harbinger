"""Actual API energy status, missing history, and desktop/mobile rendering."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:18001/console/advanced.html#energy")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(a.url)
        legend = page.locator("#energy-z .legend").first
        expect(legend).to_contain_text("계산 완료", timeout=120000)
        page.screenshot(path=str(a.out / "energy-desktop.png"), full_page=True)
        available = legend.inner_text()
        initial_date = page.locator("#asof").input_value()
        # ci-smoke synthetic energy starts Jan 1 2023. Two actual days cannot yield a 7-day statistic.
        page.fill("#asof", "2023-01-02")
        page.click("#apply")
        expect(legend).to_contain_text("관측 부족", timeout=120000)
        expect(legend).to_contain_text("관측 2일 · 판정 가능 0일 · 이상 여부 판정 보류")
        short = legend.inner_text()
        expect(page.locator("#energy-z")).to_contain_text("계산에 필요한 관측이 부족합니다")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#tab-energy").scroll_into_view_if_needed()
        page.screenshot(path=str(a.out / "energy-mobile-insufficient.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.fill("#asof", "2022-12-31")
        page.click("#apply")
        expect(legend).to_contain_text("자료 없음", timeout=120000)
        expect(legend).to_contain_text("관측 0일 · 판정 가능 0일 · 이상 여부 판정 보류")
        missing = legend.inner_text()
        page.screenshot(path=str(a.out / "energy-mobile-empty.png"), full_page=True)
        page.fill("#asof", initial_date)
        page.click("#apply")
        expect(legend).to_contain_text("계산 완료", timeout=120000)
        page.click('[data-tab="today"]')
        expect(page.locator("#today-head h2")).to_be_visible(timeout=120000)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(page.locator("#today-head")).to_contain_text("실제 선택")
        page.screenshot(path=str(a.out / "patrol-mobile.png"), full_page=True)
        page.fill("#asof", "2022-12-31")
        page.click("#apply")
        expect(page.locator("#today-head")).to_contain_text("순찰 비교를 보류합니다", timeout=120000)
        assert "undefined" not in page.locator("#today-head").inner_text()
        page.screenshot(path=str(a.out / "patrol-mobile-empty.png"), full_page=True)
        assert not errors, errors
        (a.out / "checks.json").write_text(
            json.dumps(
                {
                    "available": available,
                    "short": short,
                    "missing": missing,
                    "errors": errors,
                    "backend": "actual local API; no mocked responses",
                    "patrol_mobile": "actual selection counts, no horizontal overflow; empty comparison withheld",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        browser.close()


if __name__ == "__main__":
    main()
