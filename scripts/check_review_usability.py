"""Exercise review-driven behavior against real saved or API-backed pages."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def check_review_usability(page, static, out):
    def nav(view):
        page.locator(f'.app-bar [data-view="{view}"]').click()

    nav("list")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.click("#reset-filters")
    first = page.locator("#assets tr").first
    asset_id = first.locator("[data-asset]").get_attribute("data-asset")
    # Open the actual evidence to independently obtain this asset's registered floor.
    first.locator("[data-asset]").click()
    expect(page.locator("#asset-location")).to_contain_text("층", timeout=120000)
    location = page.locator("#asset-location").inner_text()
    import re

    floor = re.search(r"(?:지하 )?\d+층", location).group()
    expect(page.locator("#maintenance-status")).to_contain_text("확인되지 않음")
    expect(page.locator("#prediction-context")).to_contain_text("당시")
    page.click("#back-list")
    page.fill("#search", floor)
    expect(page.locator(f'[data-asset="{asset_id}"]')).to_be_visible()
    assert all(
        s.startswith(floor + " ·") or s.startswith(floor + " (")
        for s in page.locator(".asset-location").all_text_contents()
    )
    for width in (320, 390, 650):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(page.locator(".asset-location").first).to_be_visible()
        expect(page.locator(".asset-id").first).to_be_visible()
        page.screenshot(path=str(out / f"review-location-{width}.png"))
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.click("#reset-filters")
    applied = page.locator("#as-of").input_value()
    if static:
        page.select_option("#as-of", index=1)
    else:
        page.fill("#as-of", page.locator("#as-of").get_attribute("max"))
    expect(page.locator("#list-pending")).to_contain_text("미적용")
    expect(page.locator("#prediction-date")).to_contain_text(applied)
    if not static:
        failed = "**/workbench/sessions/*/analysis?*"
        before_ids = page.locator("[data-asset]").evaluate_all("els=>els.map(e=>e.dataset.asset)")
        page.route(
            failed,
            lambda route: route.fulfill(
                status=503, content_type="application/json", body='{"detail":"검증용 계산 실패"}'
            ),
        )
        page.click("#calculate")
        expect(page.locator("#list-error")).to_contain_text("이전에 적용한", timeout=120000)
        assert before_ids == page.locator("[data-asset]").evaluate_all("els=>els.map(e=>e.dataset.asset)")
        expect(page.locator("#prediction-date")).to_contain_text(applied)
        page.unroute(failed)
    if static:
        page.select_option("#as-of", applied)
    else:
        page.fill("#as-of", applied)
    expect(page.locator("#list-pending")).to_have_text("")
    nav("validation")
    expect(page.locator("#report-time-context")).to_contain_text("당시", timeout=120000)
    nav("data")
    if not static:
        # A user who cannot vouch for all failure records must still be able to explore.
        HEADER = "record_id,record_type,site_id,asset_id,category,archetype,installed,criticality,floor,zone,occurred_at,inspector_id,overall,memo,dwell_seconds,scheduled_at,method,photo_count\n"
        ROW = "i1,inspection,client-a,pump-1,pump,office,2020-01-01,2,1,A,2025-08-01,person-1,1,약간 소음,60,2025-08-01,nfc,0\n"

        page.set_input_files(
            "#csv-file", {"name": "review.csv", "mimeType": "text/csv", "buffer": (HEADER + ROW).encode()}
        )
        page.fill("#observation-end", "2025-10-01")
        page.uncheck("#observation-confirm")
        page.click("#upload-submit")
        expect(page.locator("#mode")).to_contain_text("업로드 기록", timeout=120000)
        nav("validation")
        expect(page.locator("#evaluation-note")).to_contain_text("완전성", timeout=120000)
        expect(page.locator("#outcome-rows")).to_contain_text("미확정")
        nav("downloads")
        with page.expect_download() as download:
            page.click('[data-format="json"]')
        path = out / "review-unconfirmed.json"
        download.value.save_as(str(path))
        response = json.loads(path.read_text())
        assert response["observation_confirmed"] is False
        assert all(a["failed_within_30d"] is None for a in response["assets"])
        nav("data")
        page.check("#observation-confirm")
        page.fill("#observation-end", "2025-10-02")
        expect(page.locator("#observation-confirm")).not_to_be_checked()
        page.check("#observation-confirm")
        page.set_input_files(
            "#csv-file", {"name": "another.csv", "mimeType": "text/csv", "buffer": (HEADER + ROW).encode()}
        )
        expect(page.locator("#observation-confirm")).not_to_be_checked()
        # Invalid numeric cell must preserve the active uploaded result and identify the row.
        broken = (HEADER + ROW.replace(",1,약간", ",9,약간")).encode()
        page.set_input_files("#csv-file", {"name": "broken.csv", "mimeType": "text/csv", "buffer": broken})
        page.click("#upload-submit")
        expect(page.locator("#data-error")).to_contain_text("점검 종합 판정(overall)", timeout=120000)
        expect(page.locator("#data-error")).to_contain_text("CSV 행 [2]")
        page.screenshot(path=str(out / "review-upload-error.png"), full_page=True)
        nav("list")
        expect(page.locator('[data-asset="pump-1"]')).to_be_visible()
        nav("data")
    if not static:
        page.set_input_files(
            "#csv-file", {"name": "review.csv", "mimeType": "text/csv", "buffer": (HEADER + ROW).encode()}
        )
        page.fill("#observation-end", "2025-10-01")
        page.check("#observation-confirm")
        page.click("#load-example")
        expect(page.locator("#mode")).to_contain_text("합성 예제", timeout=120000)
        nav("data")
        expect(page.locator("#observation-confirm")).not_to_be_checked()
    (out / "review-checks.json").write_text(
        json.dumps(
            {
                "static": static,
                "checks": [
                    "location search and visible IDs at 320/390/650px",
                    "historical prediction and unknown repair status",
                    "pending date keeps applied date",
                    "unconfirmed upload and exports withheld, confirmation reset, actionable error preserves data",
                ]
                if not static
                else [
                    "location search and visible IDs at 320/390/650px",
                    "historical prediction and unknown repair status",
                    "pending date keeps applied date",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8020/")
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("/tmp/review-browser"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(args.url)
        expect(page.locator("[data-asset]").first).to_be_visible(timeout=120000)
        check_review_usability(page, args.static, args.out)
        page.click("#close-session")
        browser.close()
    print("review usability checks passed")


if __name__ == "__main__":
    main()
